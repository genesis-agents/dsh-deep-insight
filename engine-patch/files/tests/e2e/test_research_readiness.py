"""Research readiness fails closed while drafts and historical inputs remain readable."""

import json
import pytest

from insight.application.research import research_basis
from insight.domain.assessment import assess_research
from insight.domain.contracts import (
    Attribution,
    Limits,
    PlatformError,
    ResearchStandard,
    ResearchNarrative,
    SemanticCheck,
    VerificationSubmission,
)
from insight.domain.rules import fingerprint
from tests.helpers import analyze_case, start_case


def test_unverified_report_requires_explicit_draft(app, tmp_path):
    run = start_case(app, tmp_path)
    analyze_case(app, run)
    with pytest.raises(PlatformError) as error:
        app.delivery.assemble_delivery(run)
    assert error.value.code == "QUALITY_BLOCKED"
    draft = app.delivery.assemble_delivery(run, allow_draft=True)
    assert draft.quality_state == "draft"
    assert app.publisher.verify(draft.relative_path)["portable"]


def test_date_independence_search_and_isolation_are_separate_requirements(
    app, tmp_path
):
    run = start_case(app, tmp_path)
    analysis, _ = analyze_case(app, run)
    with app.db.transaction(None) as repo:
        frozen, versions, context = (
            repo.frozen_input(run),
            repo.versions(run),
            repo.context(run),
        )
    standard = ResearchStandard(
        rationale="Broad evidence review", require_report_composition=False
    )
    frozen = frozen.model_copy(
        update={
            "project": frozen.project.model_copy(update={"quality_standard": standard})
        }
    )
    checks = (
        SemanticCheck(
            claim_id="claim_1", verdict="supported", rationale="Fixture support"
        ),
    )
    review = VerificationSubmission(
        run_id=run,
        analysis_fingerprint=fingerprint(analysis),
        verifier=Attribution(mode="model_api", name="Isolated", notes="Fixture"),
        checks=checks,
        execution_ref="exec_fixture",
    )

    def gates(f=frozen, vs=versions, ctx=context, events=None):
        return {
            g.gate_id: g.state
            for g in assess_research(f, vs, ctx, analysis, review, events or [])
        }

    result = gates()
    assert result["question_coverage"] == "passed"
    for name in (
        "temporal_coverage",
        "independent_support",
        "search_record",
        "isolated_review",
    ):
        assert result[name] == "failed"
    one = frozen.model_copy(
        update={
            "project": frozen.project.model_copy(
                update={
                    "quality_standard": standard.model_copy(
                        update={"min_supporting_groups": 1}
                    )
                }
            )
        }
    )
    dated = tuple(v.model_copy(update={"published_at": "2026-10-25"}) for v in versions)
    events = [
        {
            "kind": "search_completed",
            "payload": {
                "questions": list(frozen.project.subquestions),
                "sources": [{"url": "https://example.org"}],
                "truncated": False,
            },
        },
        {
            "kind": "review_completed",
            "payload": {
                "execution_ref": "exec_fixture",
                "analysis_fingerprint": fingerprint(analysis),
                "checks": [c.model_dump(mode="json") for c in checks],
            },
        },
    ]
    assert all(
        state == "passed" for state in gates(one, dated, context, events).values()
    )
    full_report = one.model_copy(
        update={
            "project": one.project.model_copy(
                update={
                    "quality_standard": standard.model_copy(
                        update={"require_report_composition": True}
                    )
                }
            )
        }
    )
    assert gates(full_report, dated, context, events)["report_review"] == "failed"
    report_checks = [
        {
            "criterion": criterion,
            "verdict": "passed",
            "rationale": "Chapter assessed",
            "required_changes": [],
        }
        for criterion in (
            "question_coverage",
            "analytical_depth",
            "synthesis",
            "visual_integrity",
            "limitations",
        )
    ]
    events[1]["payload"]["report_checks"] = report_checks
    assert gates(full_report, dated, context, events)["report_review"] == "failed"
    analysis = analysis.model_copy(
        update={
            "narrative": ResearchNarrative.model_validate_json(
                json.dumps(
                    {
                        "headline": "Synthetic bounded finding",
                        "standfirst": "Fixture scope",
                        "takeaways": [
                            {"text": "Conditional finding", "claim_ids": ["claim_1"]}
                        ],
                        "sections": [
                            {
                                "section_id": "conditions",
                                "question": "What conditions apply?",
                                "answer": "The retained setup only.",
                                "bridge": "Compare other setups before generalizing.",
                                "claim_ids": ["claim_1"],
                                "blocks": [
                                    {
                                        "kind": "paragraph",
                                        "text": "The observed result applies only to the retained setup.",
                                        "claim_ids": ["claim_1"],
                                    }
                                ],
                            }
                        ],
                    }
                )
            )
        }
    )
    review = review.model_copy(update={"analysis_fingerprint": fingerprint(analysis)})
    events[1]["payload"].update(
        {
            "analysis_fingerprint": fingerprint(analysis),
            "report_review_standard": "professional-report@1",
            "section_checks": [
                {
                    "section_id": "conditions",
                    "verdict": "passed",
                    "analysis_excerpt": "applies only to the retained setup",
                    "evidence_ids": [analysis.claims[0].evidence_links[0].evidence_id],
                    "rationale": "The chapter bounds its finding to the measured setup.",
                    "required_changes": [],
                }
            ],
        }
    )
    assert gates(full_report, dated, context, events)["report_review"] == "passed"
    chapter = events[1]["payload"]["section_checks"][0]
    chapter["analysis_excerpt"] = "This text is absent from the chapter"
    assert gates(full_report, dated, context, events)["report_review"] == "failed"
    chapter["analysis_excerpt"] = "applies only to the retained setup"
    chapter["evidence_ids"] = ["unrelated"]
    assert gates(full_report, dated, context, events)["report_review"] == "failed"
    chapter["evidence_ids"] = [analysis.claims[0].evidence_links[0].evidence_id]
    chapter["verdict"] = "failed"
    chapter["required_changes"] = ["Explain the causal mechanism"]
    assert gates(full_report, dated, context, events)["report_review"] == "failed"
    chapter["verdict"] = "passed"
    chapter["required_changes"] = []
    report_checks[0]["verdict"] = "failed"
    assert gates(full_report, dated, context, events)["report_review"] == "failed"
    report_checks[0]["verdict"] = "passed"
    events[1]["payload"]["analysis_fingerprint"] = "stale"
    assert gates(full_report, dated, context, events)["report_review"] == "failed"
    events[1]["payload"]["analysis_fingerprint"] = fingerprint(analysis)
    events[1]["payload"]["report_checks"] = [{"criterion": []}]
    assert gates(full_report, dated, context, events)["report_review"] == "failed"
    events[0]["payload"]["truncated"] = True
    assert gates(one, dated, context, events)["search_record"] == "failed"
    events[0]["payload"]["truncated"] = False
    future = tuple(
        v.model_copy(update={"published_at": "2026-10-27"}) for v in versions
    )
    assert gates(one, future, context, events)["temporal_coverage"] == "failed"
    conflict = context.model_copy(
        update={
            "coverage": tuple(
                c.model_copy(update={"unresolved": "Conflicting observations"})
                for c in context.coverage
            )
        }
    )
    assert gates(one, dated, conflict, events)["question_coverage"] == "failed"
    events[-1]["payload"]["checks"][0]["verdict"] = "unclear"
    assert gates(one, dated, context, events)["isolated_review"] == "failed"
    legacy = frozen.model_copy(
        update={"project": frozen.project.model_copy(update={"quality_standard": None})}
    )
    assert gates(legacy) == {"research_standard": "not_performed"}


def test_isolated_review_requires_budget_and_prior_request(app, tmp_path):
    run = start_case(app, tmp_path)
    analysis, _ = analyze_case(app, run)
    with pytest.raises(PlatformError):
        app.research.record_execution(
            run, "review_requested", {"execution_ref": "exec_test"}
        )
    with pytest.raises(PlatformError):
        app.research.record_execution(
            run,
            "review_completed",
            {
                "execution_ref": "exec_test",
                "analysis_fingerprint": fingerprint(analysis),
            },
        )


def test_execution_receipts_invalidate_assessment_and_cannot_claim_unrequested_search(
    app, tmp_path
):
    run = start_case(app, tmp_path, limits=Limits(model_calls=1, network_requests=1))
    analysis, _ = analyze_case(app, run)
    payload = {
        "execution_ref": "exec_search",
        "queries": ["fixture"],
        "questions": ["What conditions apply?"],
    }
    completed = {
        **payload,
        "sources": [{"url": "https://example.org"}],
        "truncated": False,
    }
    with pytest.raises(PlatformError):
        app.research.record_execution(run, "search_completed", completed)
    with app.db.transaction(None) as repo:
        before = research_basis(repo, run)
    app.research.record_execution(run, "search_started", payload)
    app.research.record_execution(run, "search_completed", completed)
    with app.db.transaction(None) as repo:
        assert research_basis(repo, run) != before
    with pytest.raises(PlatformError):
        app.research.record_execution(run, "search_started", payload)
    request = {
        "execution_ref": "exec_review",
        "analysis_fingerprint": fingerprint(analysis),
    }
    app.research.record_execution(run, "review_requested", request)
    app.research.record_execution(run, "review_completed", {**request, "checks": []})
    with pytest.raises(PlatformError):
        app.research.record_execution(
            run, "review_completed", {**request, "analysis_fingerprint": "stale"}
        )
