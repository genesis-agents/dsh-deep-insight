import shutil

import pytest

from insight.adapters.export import publisher as publisher_module
from insight.adapters.persistence.objects import native_path
from insight.bootstrap import Application
from insight.domain.contracts import (
    Attribution,
    CoverageItem,
    EvidenceInput,
    Locator,
    PlatformError,
    ReviewSubmission,
    SemanticCheck,
    VerificationSubmission,
)
from insight.domain.rules import fingerprint
from tests.helpers import analyze_case, start_case


@pytest.mark.acceptance
@pytest.mark.parametrize("profile", ["technical", "industry"])
def test_A01_same_kernel_two_profiles(app, tmp_path, profile):
    run_id = start_case(app, tmp_path, profile=profile)
    analysis, _ = analyze_case(app, run_id)
    assert app.research.evaluate(run_id)["quality_state"] == "draft"
    app.research.submit_verification(
        VerificationSubmission(
            run_id=run_id,
            analysis_fingerprint=fingerprint(analysis),
            verifier=Attribution(
                mode="human",
                name="Test verifier",
                notes="Synthetic fixture semantic check, not real-world validation",
            ),
            checks=(
                SemanticCheck(
                    claim_id="claim_1",
                    verdict="supported",
                    rationale="The exact fixture quotation states its condition",
                ),
            ),
        )
    )
    quality = app.research.evaluate(run_id)
    assert quality["quality_state"] == "machine_verified"
    assert (
        next(g for g in quality["gates"] if g["gate_id"] == "research_review")["state"]
        == "not_performed"
    )
    delivery = app.delivery.assemble_delivery(run_id)
    result = app.publisher.verify(delivery.relative_path)
    assert result["portable"] is True
    assert (app.output_root / "index.html").is_file()
    assert (app.output_root / "projects/sample/latest.json").is_file()
    assert str(app.root) not in (
        app.output_root / delivery.relative_path / "input-snapshot.json"
    ).read_text(encoding="utf-8")
    assert (app.output_root / delivery.relative_path / "manifest.sha256").is_file()


def test_A09_wrong_quote_and_cross_run_evidence_are_rejected(app, tmp_path):
    first = start_case(app, tmp_path, project_id="first")
    second = start_case(app, tmp_path, project_id="second")
    with app.db.transaction(None) as repo:
        version = repo.versions(first)[0]
    selection = EvidenceInput(
        source_version_id=version.version_id,
        artifact_id=version.extracted_artifact_id,
        locator=Locator(unit_index=1, char_start=0, char_end=5),
        quote="WRONG",
    )
    with pytest.raises(PlatformError, match="outside this run"):
        app.research.add_evidence(second, selection)
    with pytest.raises(PlatformError, match="exactly match"):
        app.research.add_evidence(first, selection)


def test_A10_review_is_bound_and_old_versions_are_not_rewritten(app, tmp_path):
    run_id = start_case(app, tmp_path)
    analysis, _ = analyze_case(app, run_id)
    app.research.submit_verification(
        VerificationSubmission(
            run_id=run_id,
            analysis_fingerprint=fingerprint(analysis),
            verifier=Attribution(
                mode="human", name="Test verifier", notes="Synthetic fixture only"
            ),
            checks=(
                SemanticCheck(
                    claim_id="claim_1",
                    verdict="supported",
                    rationale="Fixture states the condition",
                ),
            ),
        )
    )
    basis = app.research.evaluate(run_id)
    review = ReviewSubmission(
        run_id=run_id,
        basis_fingerprint=basis["basis_fingerprint"],
        reviewer="Explicit test reviewer",
        checked_items=tuple(basis["required_review_checks"]),
        decision="accepted",
        notes="Test-only acceptance, no real user approval",
    )
    app.research.record_review(review)
    assert app.research.evaluate(run_id)["quality_state"] == "reviewed"
    old = app.delivery.assemble_delivery(run_id, allow_draft=True)
    old_bytes = (app.output_root / old.relative_path / "report.html").read_bytes()
    revised = analysis.model_copy(
        update={"synthesis": "A new interpretation requires a new semantic check and review."}
    )
    app.research.submit_analysis(revised)
    assert app.research.evaluate(run_id)["quality_state"] == "draft"
    with pytest.raises(PlatformError, match="stale"):
        app.research.record_review(review)
    assert (app.output_root / old.relative_path / "report.html").read_bytes() == old_bytes


def test_A11_export_failure_preserves_previous_latest(app, tmp_path, monkeypatch):
    run_id = start_case(app, tmp_path)
    analyze_case(app, run_id)
    previous = app.delivery.assemble_delivery(run_id, allow_draft=True)
    pointer = app.output_root / "projects/sample/latest.json"
    before = pointer.read_bytes()
    original = publisher_module.atomic_write

    def fail(path, data):
        if path.name == "manifest.json":
            raise OSError("Injected full-disk failure")
        original(path, data)

    monkeypatch.setattr(publisher_module, "atomic_write", fail)
    with pytest.raises(OSError):
        app.delivery.assemble_delivery(run_id, allow_draft=True)
    assert pointer.read_bytes() == before
    assert app.publisher.verify(previous.relative_path)["portable"]


def test_pointer_write_failure_rolls_back_previous_index(app, tmp_path, monkeypatch):
    run_id = start_case(app, tmp_path)
    analyze_case(app, run_id)
    app.delivery.assemble_delivery(run_id, allow_draft=True)
    pointer = app.output_root / "projects/sample/latest.json"
    index = pointer.with_name("index.html")
    before, index_before = pointer.read_bytes(), index.read_bytes()
    original = publisher_module.atomic_write
    failed = False

    def fail_once(path, data):
        nonlocal failed
        if path.name == "latest.json" and not failed:
            failed = True
            raise OSError("Injected pointer write failure")
        original(path, data)

    monkeypatch.setattr(publisher_module, "atomic_write", fail_once)
    with pytest.raises(OSError):
        app.delivery.assemble_delivery(run_id, allow_draft=True)
    assert pointer.read_bytes() == before
    assert index.read_bytes() == index_before


def test_A12_move_workspace_to_new_unicode_path(app, tmp_path):
    run_id = start_case(app, tmp_path)
    analyze_case(app, run_id)
    delivery = app.delivery.assemble_delivery(run_id, allow_draft=True)
    old_root = app.root
    app.close()
    new_root = tmp_path / "迁移 目的地" / "new workspace"
    shutil.copytree(native_path(old_root), native_path(new_root))
    moved = Application(new_root)
    try:
        assert moved.queries.inspect_run(run_id)["run"]["execution_state"] == "succeeded"
        assert moved.publisher.verify(delivery.relative_path)["portable"]
        assert moved.research.evaluate(run_id)["quality_state"] == "draft"
    finally:
        moved.close()


def test_tampered_raw_original_and_manifest_are_detected(app, tmp_path):
    run_id = start_case(app, tmp_path)
    analyze_case(app, run_id)
    delivery = app.delivery.assemble_delivery(run_id, allow_draft=True)
    (app.output_root / delivery.relative_path / "claims.json").write_text("tampered")
    with pytest.raises(PlatformError, match="checksum mismatch"):
        app.publisher.verify(delivery.relative_path)
    with app.db.transaction(None) as repo:
        original = repo.artifact(repo.versions(run_id)[0].raw_artifact_id)
    app.blobs.object_path(original.sha256).write_bytes(b"tampered raw bytes")
    with pytest.raises(PlatformError):
        app.research.evaluate(run_id)


def test_context_budget_and_stale_context_never_silently_pass(app, tmp_path):
    run_id = start_case(app, tmp_path)
    analysis, evidence = analyze_case(app, run_id)
    different_coverage = (
        CoverageItem(
            subquestion="What conditions apply?",
            evidence_ids=(evidence.evidence_id,),
            unresolved="Independent evidence still missing",
        ),
    )
    app.research.prepare_context(run_id, different_coverage)
    quality = app.research.evaluate(run_id)
    assert (
        next(g for g in quality["gates"] if g["gate_id"] == "exact_citations")["state"] != "passed"
    )
    with pytest.raises(PlatformError, match="stale"):
        app.research.submit_analysis(analysis)


def test_untrusted_text_is_escaped_in_offline_report(app, tmp_path):
    run_id = start_case(
        app,
        tmp_path,
        content="<script>alert('fixture')</script> is untrusted source text. It must not execute in a research report.",
    )
    analyze_case(app, run_id, statement="<img src=x onerror=alert('fixture')>")
    delivery = app.delivery.assemble_delivery(run_id, allow_draft=True)
    report = (app.output_root / delivery.relative_path / "report.html").read_text(encoding="utf-8")
    assert "<script>alert" not in report and "&lt;script&gt;" in report
    assert "<img src=x" not in report and "&lt;img" in report


def test_export_cannot_attach_old_quality_to_a_changed_context(app, tmp_path, monkeypatch):
    run = start_case(app, tmp_path)
    _, evidence = analyze_case(app, run)
    original = app.publisher.prepare

    def changed(package, artifacts):
        record = original(package, artifacts)
        app.research.prepare_context(
            run,
            (
                CoverageItem(
                    subquestion="What conditions apply?",
                    evidence_ids=(evidence.evidence_id,),
                    unresolved="New conflict appeared during export",
                ),
            ),
        )
        return record

    monkeypatch.setattr(app.publisher, "prepare", changed)
    with pytest.raises(PlatformError, match="Research changed during export"):
        app.delivery.assemble_delivery(run, allow_draft=True)
    assert not (app.output_root / "projects/sample/latest.json").exists()
