"""Reports retain legacy readability but expose thin outlines before delivery."""

import json

from insight.domain.assessment import assess_research
from insight.domain.contracts import AnalysisSubmission
from insight.domain.report_quality import report_gaps
from tests.helpers import analyze_case, start_case


def test_repeated_answer_is_not_explanatory_body_and_conclusion_survives_export(app, tmp_path):
    run = start_case(app, tmp_path)
    analysis, _ = analyze_case(app, run)
    original = analysis.model_dump(mode="json")
    assert "narrative" not in original
    data = json.loads(analysis.model_dump_json())
    claim = data["claims"][0]["claim_id"]
    narrative = {
        "headline": "Fixture research",
        "standfirst": "Synthetic retained evidence",
        "takeaways": [{"text": "Conditional finding", "claim_ids": [claim]}],
        "sections": [
            {
                "section_id": "finding",
                "question": "What applies?",
                "answer": "Only the stated condition.",
                "bridge": "Check the conditions.",
                "claim_ids": [claim],
                "blocks": [
                    {
                        "kind": "paragraph",
                        "text": "Only the stated condition.",
                        "claim_ids": [claim],
                    }
                ],
            }
        ],
    }
    data["narrative"] = narrative
    thin = AnalysisSubmission.model_validate_json(json.dumps(data))
    assert len(report_gaps(thin)) == 3
    with app.db.transaction(None) as repo:
        frozen = repo.frozen_input(run)
        standard = frozen.project.quality_standard.model_copy(
            update={"require_report_composition": True}
        )
        frozen = frozen.model_copy(
            update={"project": frozen.project.model_copy(update={"quality_standard": standard})}
        )
        gates = assess_research(
            frozen, repo.versions(run), repo.context(run), thin, None, repo.events(run)
        )
    assert next(g for g in gates if g.gate_id == "report_composition").state == "failed"
    response = app.research.submit_analysis(thin)
    assert response["report_gaps"] == report_gaps(thin)
    assert "conclusion" not in thin.narrative.model_dump(mode="json")
    narrative["conclusion"] = {
        "text": "Final synthesis from the retained evidence.",
        "claim_ids": [claim],
    }
    narrative["recommendations"] = [
        {"text": "Verify the conditions before applying the finding.", "claim_ids": [claim]}
    ]
    narrative["sections"][0]["blocks"][0]["text"] = (
        "The test material states one fixed setup; it does not establish results for other setups."
    )
    complete = AnalysisSubmission.model_validate_json(json.dumps(data))
    assert report_gaps(complete) == []
    data["claims"].append({**data["claims"][0], "claim_id": "comparison"})
    narrative["sections"][0]["blocks"].append({
        "kind": "table", "caption": "Retained evidence comparison",
        "columns": ["Observation", "Limit"],
        "rows": [{"cells": ["Fixed setup", "No cross-setup result"], "claim_ids": [claim]}],
    })
    table_only = AnalysisSubmission.model_validate_json(json.dumps(data))
    assert report_gaps(table_only) == []
    narrative["sections"][0]["blocks"].append({
        "kind": "diagram", "caption": "Applicability depends on the retained setup",
        "nodes": [
            {"node_id": "setup", "label": "Recorded setup", "detail": "Fixed test conditions", "column": 0, "row": 0},
            {"node_id": "finding", "label": "Conditional finding", "detail": "No cross-setup extrapolation", "column": 1, "row": 0},
        ],
        "edges": [{"source": "setup", "target": "finding", "label": "Limits applicability"}],
        "note": "Logical scope, not a measured effect size", "claim_ids": [claim],
    })
    assert report_gaps(AnalysisSubmission.model_validate_json(json.dumps(data))) == []
    app.research.submit_analysis(complete)
    delivery = app.delivery.assemble_delivery(run, allow_draft=True)
    for file in ("report.html", "report.md"):
        body = (app.output_root / delivery.relative_path / file).read_text(encoding="utf-8")
        assert narrative["conclusion"]["text"] in body
        assert narrative["recommendations"][0]["text"] in body
