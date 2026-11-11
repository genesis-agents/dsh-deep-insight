"""Question-led research rejects false completeness without conflating acquisition and reasoning."""
import json

import pytest
from insight.domain.assessment import assess_research
from insight.domain.contracts import (
    Claim,
    PlatformError,
    ProjectSpec,
    QuestionAssessment,
    QuestionDesign,
    ResearchNarrative,
    ResearchStandard,
)
from insight.domain.report_quality import section_review_gaps
from insight.domain.rules import fingerprint
from pydantic import ValidationError
from tests.helpers import analyze_case, start_case


def design():
    return QuestionDesign(
        subquestion="What conditions apply?",
        decision_relevance="Choose whether the result justifies a production trial",
        alternatives=("The setup causes the reported effect", "An uncontrolled workload explains it"),
        evidence_needed=("Comparable workload and measurement conditions",),
        stop_condition="A bounded finding distinguishes observation from generalization",
    )


def test_acquisition_stays_passed_when_report_composition_fails(app, tmp_path):
    standard = ResearchStandard(
        min_supporting_groups=1, require_publication_dates=False,
        require_search_record=False, require_isolated_review=False,
        require_report_composition=True, rationale="Local editorial regression scenario",
    )
    run = start_case(app, tmp_path, quality_standard=standard)
    analyze_case(app, run)
    result = app.research.evaluate(run)
    gates = {g["gate_id"]: g["state"] for g in result["gates"]}
    assert gates["source_coverage"] == "passed"
    assert gates["report_composition"] == "failed"
    assert result["quality_state"] == "draft"
    with pytest.raises(PlatformError) as error:
        app.delivery.assemble_delivery(run)
    assert error.value.code == "QUALITY_BLOCKED"


def test_evidence_membership_does_not_complete_a_designed_question(app, tmp_path):
    run = start_case(app, tmp_path, research_design=(design(),))
    analysis, _ = analyze_case(app, run)
    with app.db.transaction(None) as repo:
        frozen, versions, context = repo.frozen_input(run), repo.versions(run), repo.context(run)

    def assess(f=frozen, ctx=context, a=analysis, events=None):
        return {g.gate_id: g.state for g in assess_research(f, versions, ctx, a, None, events or [])}

    assert assess()["question_coverage"] == "passed"
    assert assess()["question_analysis"] == "failed"
    assessment = QuestionAssessment(
        answer="The source reports a result only for its stated setup",
        reasoning="The source has no comparable production control",
        alternatives_considered=("Uncontrolled workload remains possible",),
        remaining_gaps=("Production comparison unavailable",),
        next_action="Acquire a paired production measurement before generalizing",
    )
    row = context.coverage[0].model_copy(update={"assessment": assessment})
    updated = context.model_copy(update={"coverage": (row,)})
    assert assess(ctx=updated)["question_analysis"] == "passed"
    # A bounded answer can retain disclosed uncertainty; an unanswered question cannot pass.
    unresolved = row.model_copy(update={"unresolved": "The stated question remains unanswered"})
    assert assess(ctx=context.model_copy(update={"coverage": (unresolved,)}))["question_analysis"] == "failed"

    standard = frozen.project.quality_standard.model_copy(update={"require_search_record": True})
    searched_project = frozen.project.model_copy(update={"quality_standard": standard})
    searched = frozen.model_copy(update={"project": searched_project})
    payload = {"questions": list(searched_project.subquestions), "sources": [{"url": "https://example.org"}], "truncated": False}
    event = {"kind": "search_completed", "payload": payload}
    assert assess(f=searched, events=[event])["search_record"] == "failed"
    payload["results"] = [{"question": design().subquestion, "sources": payload["sources"], "truncated": False}]
    assert assess(f=searched, events=[event])["search_record"] == "passed"
    payload["results"][0]["truncated"] = True
    assert assess(f=searched, events=[event])["search_record"] == "failed"


def test_attribution_and_internal_checks_do_not_claim_independent_effect_verification(app, tmp_path):
    run = start_case(app, tmp_path)
    analysis, _ = analyze_case(app, run)
    with app.db.transaction(None) as repo:
        frozen, versions, context = repo.frozen_input(run), repo.versions(run), repo.context(run)
    project = frozen.project.model_copy(update={"quality_standard": frozen.project.quality_standard.model_copy(update={"min_supporting_groups": 2})})
    frozen = frozen.model_copy(update={"project": project})

    def supported(claim):
        updated = analysis.model_copy(update={"claims": (claim,)})
        return next(g.state for g in assess_research(frozen, versions, context, updated, None, []) if g.gate_id == "independent_support")

    claim = analysis.claims[0]
    assert supported(claim) == "failed"
    attributed = Claim.model_validate({**claim.model_dump(), "support_basis": "attributed"})
    assert supported(attributed) == "passed"
    internal = Claim.model_validate({**claim.model_dump(), "kind": "observation", "support_basis": "internal_check"})
    assert supported(internal) == "passed"
    with pytest.raises(ValidationError):
        Claim.model_validate({**claim.model_dump(), "kind": "inference", "support_basis": "attributed"})
    with pytest.raises(ValidationError):
        Claim.model_validate({**claim.model_dump(), "kind": "inference", "support_basis": "internal_check"})


def test_optional_research_fields_preserve_legacy_fingerprints(app, tmp_path):
    run = start_case(app, tmp_path)
    analysis, _ = analyze_case(app, run)
    original = analysis.model_dump(mode="json")
    assert "support_basis" not in original["claims"][0]
    assert "assessment" not in original["coverage"][0]
    assert fingerprint(analysis) == fingerprint(original)
    with app.db.transaction(None) as repo:
        project = repo.frozen_input(run).project
    assert "research_design" not in project.model_dump(mode="json")
    data = project.model_dump()
    data.pop("revision")
    data["research_design"] = [design().model_dump()]
    assert ProjectSpec.model_validate_json(json.dumps(data)).research_design[0] == design()
    data["research_design"] *= 2
    with pytest.raises(ValidationError):
        ProjectSpec.model_validate_json(json.dumps(data))
    narrative = ResearchNarrative.model_validate_json(json.dumps({
        "headline": "Bounded finding", "standfirst": "Retained evidence",
        "takeaways": [{"text": "Source attribution", "claim_ids": ["claim_1"]}],
        "sections": [{"section_id": "comparison", "question": "What is comparable?",
                      "answer": "Only the stated setup", "bridge": "Verify production conditions",
                      "claim_ids": ["claim_1"], "blocks": [
                          {"kind": "paragraph", "text": "The fixed setup limits the comparison.", "claim_ids": ["claim_1"]},
                          {"kind": "table", "caption": "Retained conditions", "columns": ["Setup", "Limit"],
                           "rows": [{"cells": ["Fixed", "No production comparison"], "claim_ids": ["claim_1"]}]},
                      ]}],
    }))
    reviewed = analysis.model_copy(update={"narrative": narrative})
    receipt = {"report_review_standard": "professional-report@1", "section_checks": [{
        "section_id": "comparison", "verdict": "passed", "analysis_excerpt": "limits the comparison",
        "evidence_ids": [analysis.claims[0].evidence_links[0].evidence_id],
        "rationale": "The comparison retains the measured conditions", "required_changes": [],
    }]}
    assert section_review_gaps(reviewed, receipt) == []


def test_question_search_receipts_preserve_the_requested_assignment(app, tmp_path):
    run = start_case(app, tmp_path, research_design=(design(),))
    request = {
        "execution_ref": "search_assignment",
        "queries": ["controlled workload comparison"],
        "questions": [design().subquestion],
        "assignments": [{"query": "controlled workload comparison", "question": design().subquestion}],
    }
    app.research.record_execution(run, "search_started", request)
    result = {**request, "sources": [{"url": "https://example.org"}], "truncated": False,
              "results": [{"query": "different query", "question": design().subquestion,
                           "sources": [{"url": "https://example.org"}], "truncated": False}]}
    with pytest.raises(PlatformError) as error:
        app.research.record_execution(run, "search_completed", result)
    assert error.value.code == "INVALID_SPEC"
    result["results"][0]["query"] = request["queries"][0]
    app.research.record_execution(run, "search_completed", result)
    with app.db.transaction(None) as repo:
        saved = [event for event in repo.events(run) if event["kind"] == "search_completed"]
    assert len(saved) == 1
    assert saved[0]["payload"]["results"][0]["question"] == design().subquestion


def test_selected_worker_leaves_other_queued_runs_untouched(app, tmp_path):
    start_case(app, tmp_path, project_id="selected")
    first = app.projects.start_run("plan_selected")["run_id"]
    second = app.projects.start_run("plan_selected")["run_id"]
    assert app.worker.run_once(second) == second
    with app.db.transaction(None) as repo:
        assert repo.run(first).execution_state == "queued"
        assert repo.versions(first) == ()
        assert len(repo.versions(second)) == 1
    assert app.worker.run_once(second) is None
