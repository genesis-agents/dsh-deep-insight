import base64
import json

import pytest
from pydantic import ValidationError
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from insight.adapters.export import publisher as publisher_module
from insight.adapters.persistence.objects import native_path
from insight.domain.contracts import (
    AnalysisSubmission,
    Attribution,
    PlatformError,
    ResearchNarrative,
    SemanticCheck,
    VerificationSubmission,
)
from insight.domain.rules import fingerprint
from tests.helpers import analyze_case, start_case


def story(blocks=None):
    return ResearchNarrative.model_validate_json(
        json.dumps(
            {
                "headline": "A conditional result, with its baseline",
                "standfirst": "A synthetic narrative fixture, not real-world research.",
                "takeaways": [
                    {
                        "text": "Inspect the condition before adopting the result",
                        "claim_ids": ["claim_1"],
                    }
                ],
                "sections": [
                    {
                        "section_id": "conditions",
                        "question": "When does the result apply?",
                        "answer": "Only in the fixture's stated conditions",
                        "bridge": "The source makes a conditional claim; we examine that condition next.",
                        "claim_ids": ["claim_1"],
                        "blocks": blocks
                        or [
                            {
                                "kind": "paragraph",
                                "text": "<img src=x onerror=alert('fixture')>",
                                "claim_ids": ["claim_1"],
                            }
                        ],
                    }
                ],
            }
        )
    )


def pdf_case(app, tmp_path):
    previous = start_case(app, tmp_path)
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
    stream.set_data(b"BT /F1 12 Tf 20 200 Td (Synthetic result applies at batch 32) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    path = tmp_path / "figure.pdf"
    writer.write(path)
    source = app.projects.import_local(
        "pdf", str(path), "Synthetic author", "Synthetic fixture, not independent evidence"
    )
    with app.db.transaction(None) as repo:
        old = repo.frozen_input(previous).plan
    plan = old.model_copy(
        update={
            "plan_id": "figure-plan",
            "items": (old.items[0].model_copy(update={"source_ref": source.source_id}),),
        }
    )
    app.projects.freeze_source_plan(plan)
    run = app.projects.start_run(plan.plan_id)["run_id"]
    app.worker.run_once()
    analysis, evidence = analyze_case(app, run)
    return run, analysis, evidence


def figure(version, page=1):
    return {
        "kind": "figure",
        "caption": "Original fixture page",
        "source_version_id": version,
        "unit_index": page,
        "explanation": "Only the printed fixture condition is supported",
        "reading_note": "Synthetic page inspection, not research acceptance",
        "claim_ids": ["claim_1"],
    }


def test_legacy_analysis_roundtrip_keeps_original_fingerprint(app, tmp_path):
    run = start_case(app, tmp_path)
    analysis, _ = analyze_case(app, run)
    original = analysis.model_dump(mode="json")
    assert "narrative" not in original
    restored = AnalysisSubmission.model_validate_json(json.dumps(original))
    assert fingerprint(restored) == fingerprint(original)
    assert "narrative" not in json.loads(restored.model_dump_json())


def test_report_sentences_link_exact_saved_quotations_without_inserting_html(app, tmp_path):
    run = start_case(app, tmp_path)
    analysis, evidence = analyze_case(app, run)
    text = "<script>fixture</script>{{evidence:" + evidence.evidence_id + "}} {{evidence:another-run}}"
    narrative = story([{"kind": "paragraph", "text": text, "claim_ids": ["claim_1"]}])
    app.research.submit_analysis(analysis.model_copy(update={"narrative": narrative}))
    delivery = app.delivery.assemble_delivery(run, allow_draft=True)
    body = (app.output_root / delivery.relative_path / "report.html").read_text(encoding="utf-8")
    assert '<sup class="inline-citation"><a href="#citation-1"' in body
    assert "&lt;script&gt;fixture&lt;/script&gt;" in body
    assert "<script>fixture</script>" not in body
    assert "{{evidence:another-run}}" in body


def test_story_references_and_table_shape_are_strict(app, tmp_path):
    run = start_case(app, tmp_path)
    analysis, _ = analyze_case(app, run)
    data = analysis.model_dump(mode="json")
    data["narrative"] = story().model_dump(mode="json")
    data["narrative"]["takeaways"][0]["claim_ids"] = ["foreign"]
    with pytest.raises(ValidationError, match="unknown analysis claim"):
        AnalysisSubmission.model_validate_json(json.dumps(data))
    with pytest.raises(ValidationError, match="table columns"):
        story(
            [
                {
                    "kind": "table",
                    "caption": "A malformed comparison",
                    "columns": ["A", "B"],
                    "rows": [{"cells": ["one"], "claim_ids": ["claim_1"]}],
                }
            ]
        )


@pytest.mark.parametrize("profile", ["technical", "industry"])
def test_new_body_invalidates_semantics_and_preserves_old_version(app, tmp_path, profile):
    run = start_case(app, tmp_path, profile=profile)
    analysis, _ = analyze_case(app, run)
    app.research.submit_verification(
        VerificationSubmission(
            run_id=run,
            analysis_fingerprint=fingerprint(analysis),
            verifier=Attribution(
                mode="human", name="Fixture verifier", notes="Synthetic fixture only"
            ),
            checks=(
                SemanticCheck(
                    claim_id="claim_1",
                    verdict="supported",
                    rationale="The fixture states its own condition",
                ),
            ),
        )
    )
    old = app.delivery.assemble_delivery(run, allow_draft=True)
    before = (app.output_root / old.relative_path / "index.html").read_bytes()
    app.research.submit_analysis(analysis.model_copy(update={"narrative": story()}))
    assert app.research.evaluate(run)["quality_state"] == "draft"
    current = app.delivery.assemble_delivery(run, allow_draft=True)
    text = (app.output_root / current.relative_path / "index.html").read_text(encoding="utf-8")
    assert "When does the result apply?" in text
    assert "<img src=x" not in text and "&lt;img" in text
    assert text.count("<blockquote>") == 1
    assert (app.output_root / old.relative_path / "index.html").read_bytes() == before


def test_original_figure_requires_current_context_and_existing_page(app, tmp_path):
    run, analysis, evidence = pdf_case(app, tmp_path)
    with pytest.raises(PlatformError, match="outside the fixed context"):
        app.research.submit_analysis(
            analysis.model_copy(update={"narrative": story([figure("sv_foreign")])})
        )
    with pytest.raises(PlatformError, match="outside the fixed document"):
        app.research.submit_analysis(
            analysis.model_copy(
                update={"narrative": story([figure(evidence.source_version_id, 2)])}
            )
        )
    app.research.submit_analysis(
        analysis.model_copy(update={"narrative": story([figure(evidence.source_version_id)])})
    )
    assert app.research.evaluate(run)["quality_state"] == "draft"


def test_figure_export_is_checked_and_renderer_failure_keeps_latest(app, tmp_path, monkeypatch):
    run, analysis, evidence = pdf_case(app, tmp_path)
    old = app.delivery.assemble_delivery(run, allow_draft=True)
    pointer = app.output_root / "projects/sample/latest.json"
    before = pointer.read_bytes()
    app.research.submit_analysis(
        analysis.model_copy(update={"narrative": story([figure(evidence.source_version_id)])})
    )

    def unavailable(*args):
        raise PlatformError("EXPORT_FAILED", "Injected renderer failure")

    monkeypatch.setattr(publisher_module, "render_pdf_page", unavailable)
    with pytest.raises(PlatformError, match="Injected renderer"):
        app.delivery.assemble_delivery(run, allow_draft=True)
    assert pointer.read_bytes() == before
    pixel = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
    )
    monkeypatch.setattr(publisher_module, "render_pdf_page", lambda *args: pixel)
    current = app.delivery.assemble_delivery(run, allow_draft=True)
    root = native_path(app.output_root / current.relative_path)
    manifest = json.loads((root / "manifest.json").read_bytes())
    image = next(f for f in manifest["files"] if f["role"] == "rendered_original_page")
    assert (root / image["path"]).read_bytes() == pixel
    assert app.publisher.verify(current.relative_path)["portable"]
    (root / image["path"]).write_bytes(b"tampered")
    with pytest.raises(PlatformError, match="checksum mismatch"):
        app.publisher.verify(current.relative_path)
    assert app.publisher.verify(old.relative_path)["portable"]
