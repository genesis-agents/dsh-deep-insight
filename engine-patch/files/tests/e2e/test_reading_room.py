import hashlib
import json
import shutil
from urllib.parse import unquote, urlparse

import pytest
from bs4 import BeautifulSoup

from insight.adapters.persistence import objects
from insight.adapters.persistence.objects import native_path
from insight.domain.contracts import PlatformError
from tests.helpers import analyze_case, start_case


def edition_path(app, result):
    return native_path(app.output_root / "reading-room" / "editions" / result["edition"][:16])


def assert_local_links(root):
    root = native_path(root)
    for path in root.rglob("*.html"):
        soup = BeautifulSoup(path.read_bytes(), "html.parser")
        for anchor in soup.find_all("a", href=True):
            uri = urlparse(anchor["href"])
            if uri.scheme:
                continue
            target = (path.parent / unquote(uri.path)).resolve() if uri.path else path
            if target.is_dir():
                target = target / "index.html"
            assert target.is_file(), (path, target)
            if uri.fragment and target.suffix == ".html":
                assert BeautifulSoup(target.read_bytes(), "html.parser").find(id=uri.fragment)


def test_reading_classifies_and_connects_process_without_changing_research(app, tmp_path):
    first = start_case(
        app,
        tmp_path,
        project_id="first",
        content="<script>alert(1)</script> Test fixture condition.",
    )
    analyze_case(app, first)
    delivery = app.delivery.assemble_delivery(first, allow_draft=True)
    second = start_case(app, tmp_path, project_id="second", profile="industry")
    before = app.queries.inspect_run(first)
    report = app.output_root / delivery.relative_path / "report.html"
    report_hash = hashlib.sha256(report.read_bytes()).hexdigest()
    result = app.reading.publish()
    assert result["projects"] == 2 and result["materials"] == 2
    assert app.queries.inspect_run(first) == before
    assert hashlib.sha256(report.read_bytes()).hexdigest() == report_hash
    root = edition_path(app, result)
    assert (root / "资料库" / "用户提供资料").is_dir()
    home = (root / "index.html").read_text(encoding="utf-8")
    assert all(
        f'data-field="{key}"' in home for key in ("category", "publisher", "role", "project")
    )
    run = root / "研究项目" / "first" / "批次" / first
    evidence = (run / "04-证据摘录.html").read_text(encoding="utf-8")
    assert "&lt;script&gt;" in evidence and "<script>alert" not in evidence
    review = (run / "07-人工审阅.html").read_text(encoding="utf-8")
    assert "尚未记录人工审阅" in review
    pending = root / "研究项目" / "second" / "批次" / second / "05-分析判断.html"
    assert "尚未提交分析" in pending.read_text(encoding="utf-8")
    assert_local_links(root)
    assert_local_links(app.root / "01-研究项目")
    assert_local_links(app.root / "02-共享资料索引")
    assert (app.root / "00-开始阅读.html").is_file()
    for category in (
        "01-研究任务",
        "02-原始资料",
        "03-证据与摘录",
        "04-分析与核验",
        "05-成果交付",
        "06-更新记录",
    ):
        assert (app.root / "01-研究项目" / "first" / category / "index.html").is_file()
    assert app.reading.publish()["edition"] == result["edition"]
    moved = tmp_path / "迁移后的 工作区"
    shutil.copytree(native_path(app.output_root), native_path(moved))
    assert_local_links(moved / root.relative_to(native_path(app.output_root)))


def test_revised_analysis_preserves_edition_and_marks_verification_stale(app, tmp_path):
    from insight.domain.contracts import Attribution, SemanticCheck, VerificationSubmission
    from insight.domain.rules import fingerprint

    run_id = start_case(app, tmp_path)
    analysis, _ = analyze_case(app, run_id)
    app.research.submit_verification(
        VerificationSubmission(
            run_id=run_id,
            analysis_fingerprint=fingerprint(analysis),
            verifier=Attribution(mode="human", name="Fixture verifier", notes="Synthetic fixture"),
            checks=(
                SemanticCheck(claim_id="claim_1", verdict="supported", rationale="Fixture only"),
            ),
        )
    )
    first = app.reading.publish()
    root = edition_path(app, first)
    old_hash = hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()
    app.research.submit_analysis(
        analysis.model_copy(update={"synthesis": "Revised fixture interpretation."})
    )
    second = app.reading.publish()
    assert second["edition"] != first["edition"]
    assert hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest() == old_hash
    text = next(edition_path(app, second).rglob("06-核验记录.html")).read_text(encoding="utf-8")
    assert "对应旧分析" in text


def test_failed_or_corrupt_reading_preserves_previous_entrance(app, tmp_path, monkeypatch):
    run_id = start_case(app, tmp_path)
    result = app.reading.publish()
    pointer = app.output_root / "reading-room" / "index.html"
    before = pointer.read_bytes()
    analyze_case(app, run_id)
    from insight.adapters.export import reading

    original = objects.atomic_write

    def fail(path, data):
        if path.name == "manifest.json":
            raise OSError("Injected disk failure")
        original(path, data)

    with monkeypatch.context() as context:
        context.setattr(reading, "atomic_write", fail)
        with pytest.raises(OSError):
            app.reading.publish()
    assert pointer.read_bytes() == before
    current = app.reading.publish()
    assert current["edition"] != result["edition"]
    target = edition_path(app, current) / "index.html"
    target.write_text("tampered", encoding="utf-8")
    before = pointer.read_bytes()
    with pytest.raises(PlatformError, match="verification"):
        app.reading.publish()
    assert pointer.read_bytes() == before


def test_empty_reading_does_not_invent_projects(app):
    result = app.reading.publish()
    assert result["runs"] == result["projects"] == result["materials"] == 0
    manifest = json.loads((edition_path(app, result) / "manifest.json").read_bytes())
    assert manifest["kind"] == "readable_workspace_projection"


def test_defined_project_is_visible_before_any_run_and_latest_task_is_readable(app):
    from insight.domain.contracts import ChannelRequirement, ProjectSpec, Scope

    spec = ProjectSpec(
        collection_requirements=(
            ChannelRequirement(
                channel="local", disposition="required", rationale="Synthetic fixture, no network"
            ),
        ),
        project_id="not-started",
        question="Which evidence is still needed?",
        decision="Define a research task before collecting material",
        scope=Scope(regions=("North America",), as_of="2026-10-27"),
        profile_ref="technical@1",
        subquestions=("Which claims need evidence?",),
    )
    app.projects.define_project(spec, 0)
    result = app.reading.publish()
    assert result["projects"] == 1 and result["runs"] == result["materials"] == 0
    overview = app.root / "01-研究项目/not-started/00-项目概览.html"
    assert "尚未启动研究" in overview.read_text(encoding="utf-8")
    assert "Define a research task" in (
        overview.parent / "01-研究任务/01-已登记任务.html"
    ).read_text(encoding="utf-8")
    assert_local_links(overview.parent)
    app.projects.define_project(spec.model_copy(update={"question": "Revised research task"}), 1)
    updated = app.reading.publish()
    assert updated["edition"] != result["edition"]
    assert "Revised research task" in overview.read_text(encoding="utf-8")


def test_platform_data_can_live_below_management_directory(tmp_path):
    from insight.bootstrap import Application, initialize_workspace

    root = tmp_path / "用户工作区"
    root.mkdir()
    (root / "workspace.toml").write_text(
        'schema_version = 1\ndata_directory = "90-平台运行"\noutput_directory = "90-平台运行/outputs"\n',
        encoding="utf-8",
    )
    initialize_workspace(root)
    application = Application(root)
    try:
        assert application.data_root == root / "90-平台运行"
        run_id = start_case(application, tmp_path)
        analyze_case(application, run_id)
        application.delivery.assemble_delivery(run_id, allow_draft=True)
        application.reading.publish()
        assert (root / "90-平台运行" / "state" / "insight.db").is_file()
        assert not (root / "state").exists()
        assert_local_links(root / "01-研究项目")
    finally:
        application.close()


def test_html_original_bytes_survive_classification_and_user_edits_are_preserved(app, tmp_path):
    original = (
        "<!DOCTYPE HTML><html><head><title>index</title></head><body><article>"
        + "<p>Synthetic HTML fixture: the reported throughput applies only to a fixed batch of 32 and needs independent validation.</p>"
        * 12
        + "</article></body></html>"
    )
    start_case(app, tmp_path, content=original, suffix=".html")
    app.reading.publish()
    raw = next((app.root / "01-研究项目").rglob("原件-index.html"))
    assert raw.read_bytes() == original.encode()
    assert raw.with_name("index.html").read_bytes() != raw.read_bytes()
    before = (app.root / "00-开始阅读.html").read_bytes()
    raw.write_bytes(b"User annotations must not be overwritten")
    with pytest.raises(PlatformError, match="copy was edited"):
        app.reading.publish()
    assert raw.read_bytes() == b"User annotations must not be overwritten"
    assert (app.root / "00-开始阅读.html").read_bytes() == before


def test_portable_presentation_survives_move_without_original_workspace(app, tmp_path):
    from pptx import Presentation

    from insight.adapters.persistence.objects import native_path
    from insight.bootstrap import Application

    run = start_case(app, tmp_path)
    analyze_case(app, run)
    folder = app.output_root / "projects/sample/presentations/revision-1"
    folder.mkdir(parents=True)
    ppt = folder / "synthetic-fixture.pptx"
    deck = Presentation()
    deck.slides.add_slide(deck.slide_layouts[6])
    deck.save(str(ppt))
    artifact = dict(
        path=ppt.name,
        sha256=hashlib.sha256(ppt.read_bytes()).hexdigest(),
        bytes=ppt.stat().st_size,
        slides=1,
    )
    descriptor = folder / "delivery.json"
    descriptor.write_text(
        json.dumps(
            dict(schema="insight-presentation-delivery.v1", asOf="2026-10-27", artifact=artifact)
        ),
        encoding="utf-8",
    )
    pointer = folder.parent / "latest.json"
    pointer.write_text(
        json.dumps(
            dict(
                schema="insight-presentation-latest.v1",
                delivery="revision-1/delivery.json",
                userAcceptance="pending",
            )
        ),
        encoding="utf-8",
    )
    assert (
        not __import__("pathlib").Path(json.loads(pointer.read_bytes())["delivery"]).is_absolute()
    )
    # Legacy file pointers are compatibility data, never an implicit research registration.
    app.reading.publish()
    assert not list((app.root / "01-研究项目").rglob("registration.json"))
    from insight.domain.publications import PublicationRequest
    from insight.domain.rules import fingerprint

    with app.db.transaction(None) as repo:
        current_analysis = repo.analysis(run)
    evaluation = app.research.evaluate(run)
    request = PublicationRequest.model_validate_json(
        json.dumps(
            dict(
                run_id=run,
                basis_fingerprint=evaluation["basis_fingerprint"],
                analysis_fingerprint=fingerprint(current_analysis),
                title="Synthetic fixture",
                producer=current_analysis.producer.model_dump(mode="json"),
                presentation=dict(name=ppt.name, native_path=str(ppt), sha256=artifact["sha256"]),
                slides=[dict(slide=1, claim_ids=["claim_1"], note="Synthetic fixture claim")],
                limitations=["Synthetic test; no business or visual acceptance"],
            )
        )
    )
    app.publications.register(request)
    app.reading.publish()
    old_root = app.root
    app.close()
    moved_root = tmp_path / "New machine without original paths"
    shutil.copytree(native_path(old_root), native_path(moved_root))
    old_root.rename(old_root.with_name("original-workspace-unavailable"))
    moved = Application(moved_root)
    try:
        result = moved.reading.publish()
        assert result["projects"] == 1
        record = next((moved_root / "01-研究项目").rglob("registration.json"))
        data = json.loads(record.read_bytes())
        assert (record.parent / data["presentation"]["name"]).is_file()
        assert data["registration_mode"] == "research_bound"
        assert moved.publications.verify(data["publication_id"])["files_verified"] == 1
        assert_local_links(moved_root / "01-研究项目")
    finally:
        moved.close()


@pytest.mark.parametrize("value", ["D:/old-machine/data", "/old-machine/data", "../outside"])
def test_workspace_settings_reject_machine_bound_directories(value):
    from pydantic import ValidationError

    from insight.bootstrap import WorkspaceSettings

    with pytest.raises(ValidationError, match="relative paths"):
        WorkspaceSettings(data_directory=value)


def test_new_report_moves_prior_user_copy_to_history_and_keeps_registered_bytes(app, tmp_path):
    run_id = start_case(app, tmp_path)
    analysis, _ = analyze_case(app, run_id)
    first = app.delivery.assemble_delivery(run_id, allow_draft=True)
    app.reading.publish()
    user_results = app.root / "01-研究项目/sample/05-成果交付"
    original_view = next(user_results.glob("报告-*"))
    original_bytes = (original_view / "report.html").read_bytes()
    app.research.submit_analysis(
        analysis.model_copy(update={"synthesis": "Revised synthetic interpretation."})
    )
    second = app.delivery.assemble_delivery(run_id, allow_draft=True)
    app.reading.publish()
    assert len(list(user_results.glob("报告-*"))) == 1
    historical = list((user_results / "历史版本").glob("报告-*"))
    assert len(historical) == 1 and (historical[0] / "report.html").read_bytes() == original_bytes
    assert app.publisher.verify(first.relative_path)["portable"]
    assert app.publisher.verify(second.relative_path)["portable"]
    assert_local_links(app.root / "01-研究项目")
    app.reading.publish()
    assert len(list((user_results / "历史版本").glob("报告-*"))) == 1
