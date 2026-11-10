import io
from datetime import UTC, datetime, timedelta

import pytest
from docx import Document
from pptx import Presentation
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from insight.adapters.sources.local import LocalFileProvider
from insight.adapters.transforms.text import DocumentExtractor
from insight.bootstrap import Application, initialize_workspace
from insight.domain.contracts import Limits, PlatformError
from tests.helpers import analyze_case, start_case


class Clock:
    def __init__(self):
        self.value = datetime(2026, 10, 26, tzinfo=UTC)

    def __call__(self):
        return self.value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    def later(self, seconds):
        self.value += timedelta(seconds=seconds)


def test_enrichment_calls_share_the_frozen_model_budget_without_granting_review(tmp_path):
    root = tmp_path / "capability-workspace"
    initialize_workspace(root)
    app = Application(root)
    try:
        run_id = start_case(app, tmp_path, limits=Limits(model_calls=1))
        app.research.record_execution(
            run_id,
            "capability_requested",
            {"execution_ref": "cap-one", "capability": "entities", "messages": []},
        )
        app.research.record_execution(
            run_id,
            "capability_completed",
            {"execution_ref": "cap-one", "output": '{"entities": []}'},
        )
        status = app.queries.inspect_run(run_id)
        assert status["budget_usage"]["model_calls"] == 1
        with pytest.raises(PlatformError, match="model_calls budget exhausted"):
            app.research.record_execution(
                run_id, "review_requested", {"execution_ref": "review-after-capability"}
            )
        with app.db.transaction(None) as repo:
            assert repo.verification(run_id) is None
            assert repo.review(run_id) is None
    finally:
        app.close()


def test_expired_worker_is_fenced_and_new_lease_recovers(tmp_path):
    root = tmp_path / "lease-workspace"
    initialize_workspace(root)
    clock = Clock()
    app = Application(root, clock=clock)
    try:
        start_case(app, tmp_path)
        queued = app.projects.start_run("plan_sample")
        first = app.db.claim("first", clock(), "2026-10-26T00:01:00.000000Z")
        assert first.run_id == queued["run_id"]
        clock.later(61)
        assert app.db.recover(clock()) == 1
        second = app.db.claim("second", clock(), "2026-10-26T00:04:00.000000Z")
        assert second.token > first.token
        with pytest.raises(PlatformError, match="Expired"):
            with app.db.transaction(first) as repo:
                repo.event(first.run_id, "should_not_commit", {}, clock())
        with app.db.transaction(second) as repo:
            repo.event(second.run_id, "new_lease_committed", {}, clock())
        assert not any(
            e["kind"] == "should_not_commit"
            for e in app.queries.inspect_run(first.run_id)["events"]
        )
    finally:
        app.close()


def test_process_death_resumes_committed_source_without_duplicate_read(tmp_path):
    root = tmp_path / "recovery"
    initialize_workspace(root)
    clock = Clock()
    app = Application(root, clock=clock)
    try:
        first_run = start_case(app, tmp_path)
        path = tmp_path / "second.txt"
        path.write_text(
            "Second synthetic source for checkpoint recovery. Not a real-world assertion."
        )
        app.projects.import_local("second", str(path), "fixture", "synthetic fixture")
        with app.db.transaction(None) as repo:
            old = repo.frozen_input(first_run).plan
        new_item = old.items[0].model_copy(update={"source_ref": "second"})
        plan = old.model_copy(
            update={"plan_id": "recovery_plan", "items": (old.items[0], new_item)}
        )
        app.projects.freeze_source_plan(plan)
        local = LocalFileProvider(app.blobs, 50_000_000)
        calls = []

        class CrashOnce(LocalFileProvider):
            def acquire(self, source, item, budget, checkpoint):
                calls.append(source.source_id)
                if source.source_id == "second" and calls.count("second") == 1:
                    raise SystemExit("Injected worker process death")
                return local.acquire(source, item, budget, checkpoint)

        app.worker.providers["local"] = CrashOnce(app.blobs, 50_000_000)
        run = app.projects.start_run(plan.plan_id)["run_id"]
        with pytest.raises(SystemExit):
            app.worker.run_once()
        assert app.queries.inspect_run(run)["run"]["execution_state"] == "running"
        clock.later(121)
        app.worker.run_once()
        assert calls.count("source_sample") == 1
        assert calls.count("second") == 2
        with app.db.transaction(None) as repo:
            assert len(repo.versions(run)) == 2
        assert app.queries.inspect_run(run)["run"]["stage"] == "W5"
    finally:
        app.close()


def test_A08_reextracting_same_original_keeps_old_citations(app, tmp_path):
    run = start_case(app, tmp_path)
    analyze_case(app, run)
    old = app.delivery.assemble_delivery(run, allow_draft=True)
    before = (app.output_root / old.relative_path / "citations.json").read_bytes()
    with app.db.transaction(None) as repo:
        original = repo.versions(run)[0]
    app.worker.extractor = DocumentExtractor(revision="future-test-revision")
    rerun = app.projects.start_run("plan_sample")["run_id"]
    app.worker.run_once()
    with app.db.transaction(None) as repo:
        changed = repo.versions(rerun)[0]
    assert original.raw_artifact_id == changed.raw_artifact_id
    assert original.extracted_artifact_id != changed.extracted_artifact_id
    assert (app.output_root / old.relative_path / "citations.json").read_bytes() == before
    assert app.publisher.verify(old.relative_path)["portable"]


def test_pdf_pptx_docx_extractors_produce_real_located_text():
    extractor = DocumentExtractor()
    # Minimal PDF fixture generated through pypdf objects; no handwritten PDF parser.
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 200 Td (Synthetic PDF baseline 32) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    pdf = io.BytesIO()
    writer.write(pdf)
    result = extractor.extract(pdf.getvalue(), "application/pdf", "raw_document")
    assert "baseline 32" in result.units[0].text and result.units[0].kind == "page"
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[1])
    slide.shapes.title.text = "Synthetic slide"
    buffer = io.BytesIO()
    deck.save(buffer)
    result = extractor.extract(buffer.getvalue(), "application/octet-stream", "original_slides")
    assert result.units[0].text.startswith("Synthetic slide") and result.units[0].kind == "slide"
    doc = Document()
    doc.add_paragraph("Synthetic document baseline")
    buffer = io.BytesIO()
    doc.save(buffer)
    result = extractor.extract(buffer.getvalue(), "application/octet-stream", "raw_document")
    assert "document baseline" in result.units[0].text


def test_empty_scanned_pdf_is_a_gap_not_a_success():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    data = io.BytesIO()
    writer.write(data)
    with pytest.raises(PlatformError, match="No text"):
        DocumentExtractor().extract(data.getvalue(), "application/pdf", "raw_document")


def test_queries_do_not_change_audit_events_or_start_work(app, tmp_path):
    run = start_case(app, tmp_path)
    before = app.queries.inspect_run(run)
    app.queries.list_runs()
    app.doctor()
    app.queries.inspect_run(run)
    assert app.queries.inspect_run(run) == before


def test_context_budget_rejects_without_truncating(app, tmp_path):
    run = start_case(app, tmp_path, limits=Limits(context_characters=100))
    with pytest.raises(PlatformError, match="character budget"):
        analyze_case(app, run)
    with app.db.transaction(None) as repo:
        assert repo.context(run) is None


def test_cancelled_execution_is_terminal(app, tmp_path):
    start_case(app, tmp_path)
    run = app.projects.start_run("plan_sample")["run_id"]
    app.projects.cancel_run(run)
    assert app.queries.inspect_run(run)["run"]["execution_state"] == "cancelled"
    assert app.worker.run_once() is None
    with pytest.raises(PlatformError, match="Terminal"):
        app.projects.cancel_run(run)
    with pytest.raises(PlatformError, match="terminal"):
        app.projects.resume_run(run)


def test_long_workspace_paths_use_native_filesystem_support(tmp_path):
    root = tmp_path / ("deep" * 25) / ("工作区" * 20)
    initialize_workspace(root)
    app = Application(root)
    try:
        run = start_case(app, tmp_path)
        analyze_case(app, run)
        delivery = app.delivery.assemble_delivery(run, allow_draft=True)
        assert app.publisher.verify(delivery.relative_path)["portable"]
    finally:
        app.close()
