"""Original HTML figures remain traceable in analysis and portable report exports."""

import base64
import json

import httpx
import pytest

from insight.application.source_images import source_images
from insight.domain.contracts import AnalysisSubmission, PlatformError
from tests.helpers import analyze_case, start_case


def test_original_html_image_is_budgeted_archived_bound_and_exported(
    app, tmp_path, monkeypatch
):
    html = (
        "<html><body><article><p>"
        + ("Synthetic research material with conditions and limitations. " * 10)
        + '</p><img src="https://example.org/architecture.png" alt="Original architecture"></article></body></html>'
    )
    run = start_case(app, tmp_path, suffix=".html", content=html)
    analysis, evidence = analyze_case(app, run)
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
    )
    requests = []
    app.http.client.close()
    app.http.client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (
                requests.append(request),
                httpx.Response(200, content=png),
            )[1]
        )
    )
    monkeypatch.setattr(
        "insight.application.source_images.socket.getaddrinfo",
        lambda *args: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    listing = source_images(app, run, evidence.source_version_id, None)
    assert len(listing["images"]) == 1
    assert requests == []
    captured = source_images(app, run, evidence.source_version_id, 1)
    assert source_images(app, run, evidence.source_version_id, 1) == captured
    assert len(requests) == 1
    assert (app.root / captured["path"]).read_bytes() == png
    data = analysis.model_dump(mode="json")
    figure = dict(
        kind="figure",
        source_version_id=evidence.source_version_id,
        unit_index=1,
        image_artifact_id=captured["image_artifact_id"],
        caption="Original architecture",
        explanation="Read the original components in relation to the stated conditions.",
        reading_note="Synthetic image fixture",
        claim_ids=["claim_1"],
    )
    data["narrative"] = dict(
        headline="Synthetic subject",
        standfirst="Subject summary",
        takeaways=[dict(text="Conditional result", claim_ids=["claim_1"])],
        sections=[
            dict(
                section_id="architecture",
                question="How does it work?",
                answer="Under stated conditions.",
                bridge="Conditions bound the result.",
                claim_ids=["claim_1"],
                blocks=[figure],
            )
        ],
    )
    app.research.submit_analysis(AnalysisSubmission.model_validate_json(json.dumps(data)))
    exported = app.delivery.assemble_delivery(run, allow_draft=True)
    report = app.output_root / exported.relative_path
    assert next((report / "figures").glob("*.png")).read_bytes() == png
    assert captured["image_artifact_id"] in (report / "report.html").read_text(
        encoding="utf-8"
    )
    # Archived HTML still has other remote references; selected report figures are local.
    assert app.publisher.verify(exported.relative_path)["portable"] is False
    assert 'src="https://example.org/' not in (report / "report.html").read_text(encoding="utf-8")
    figure["image_artifact_id"] = "art_unrelated"
    with pytest.raises(PlatformError, match="not an archived image"):
        app.research.submit_analysis(AnalysisSubmission.model_validate_json(json.dumps(data)))
    with pytest.raises(PlatformError, match="outside this fixed source"):
        source_images(app, run, evidence.source_version_id, 2)


def test_source_image_refuses_private_destinations(app, tmp_path, monkeypatch):
    run = start_case(
        app,
        tmp_path,
        suffix=".html",
        content="<html><body><article><p>"
        + ("Synthetic document text. " * 20)
        + '</p><img src="http://127.0.0.1/private.png"></article></body></html>',
    )
    with app.db.transaction(None) as repo:
        version = repo.versions(run)[0]
    monkeypatch.setattr(
        "insight.application.source_images.socket.getaddrinfo",
        lambda *args: [(2, 1, 6, "", ("127.0.0.1", 80))],
    )
    with pytest.raises(PlatformError, match="not public"):
        source_images(app, run, version.version_id, 1)
