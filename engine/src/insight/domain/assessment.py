"""Deterministic readiness checks over frozen research; no inferred search completeness."""

from __future__ import annotations

from datetime import date
from typing import Any

from insight.domain.contracts import (
    AnalysisSubmission,
    ContextSnapshot,
    FrozenInput,
    GateResult,
    SourceVersion,
    VerificationSubmission,
)
from insight.domain.report_quality import report_gaps, section_review_gaps
from insight.domain.rules import fingerprint


def assess_research(
    frozen: FrozenInput,
    versions: tuple[SourceVersion, ...],
    context: ContextSnapshot | None,
    analysis: AnalysisSubmission | None,
    verification: VerificationSubmission | None,
    events: list[dict[str, Any]],
) -> tuple[GateResult, ...]:
    """Return failures and next actions without changing historical inputs or assessments."""
    standard = frozen.project.quality_standard
    if standard is None:
        return (
            GateResult(
                gate_id="research_standard",
                state="not_performed",
                detail="Create a project revision with an explicit quality_standard.",
            ),
        )
    gates: list[GateResult] = []

    def check(name: str, passed: bool, detail: str) -> None:
        gates.append(
            GateResult(
                gate_id=name, state="passed" if passed else "failed", detail=detail
            )
        )

    composition = report_gaps(analysis) if standard.require_report_composition else []
    check(
        "report_composition",
        not composition,
        "; ".join(composition)
        or (
            "Summary, explanatory body, visual structure and next steps are present; analytical quality still requires review."
            if standard.require_report_composition
            else "Report composition explicitly waived: " + standard.rationale
        ),
    )

    check(
        "research_scope",
        bool(frozen.project.scope.regions),
        "Declare the geographic scope, including an explicit global scope when applicable.",
    )
    questions = frozen.project.subquestions
    coverage = context.coverage if context else ()
    missing = [
        q
        for q in questions
        if not any(
            c.subquestion == q and c.evidence_ids and not c.unresolved for c in coverage
        )
    ]
    check(
        "question_coverage",
        not missing,
        "Unresolved questions: " + "; ".join(missing)
        if missing
        else "Every declared question has evidence and no recorded unresolved gap.",
    )
    evidence = {e.evidence_id: e for e in context.evidence} if context else {}
    version_map = {v.version_id: v for v in versions}
    source_map = {s.source_id: s for s in frozen.sources}
    used_versions = {e.source_version_id for e in evidence.values()}
    date_gaps = []
    for version_id in used_versions:
        version = version_map[version_id]
        if not standard.require_publication_dates:
            continue
        try:
            published = date.fromisoformat((version.published_at or "")[:10])
        except ValueError:
            date_gaps.append(version.source_id + ": publication date unavailable")
            continue
        if published > date.fromisoformat(frozen.project.scope.as_of) or (
            frozen.project.scope.since
            and published < date.fromisoformat(frozen.project.scope.since)
        ):
            date_gaps.append(version.source_id + ": outside publication interval")
    check(
        "temporal_coverage",
        bool(evidence) and not date_gaps,
        "; ".join(date_gaps)
        or (
            "Publication interval checked."
            if standard.require_publication_dates
            else "Publication-date requirement explicitly waived: " + standard.rationale
        ),
    )
    weak = []
    for claim in analysis.claims if analysis else ():
        groups = set()
        raw_objects = set()
        for link in claim.evidence_links:
            if link.relation != "supports" or link.evidence_id not in evidence:
                continue
            version = version_map[evidence[link.evidence_id].source_version_id]
            source = source_map[version.source_id]
            # Identical archived bytes cannot count as independent corroboration.
            if version.raw_artifact_id in raw_objects:
                continue
            raw_objects.add(version.raw_artifact_id)
            if source.independence_group:
                groups.add(source.independence_group.casefold().strip())
            elif standard.min_supporting_groups == 1:
                groups.add(source.canonical_identity)
        if len(groups) < standard.min_supporting_groups:
            weak.append(claim.claim_id)
    check(
        "independent_support",
        bool(analysis) and not weak,
        "Insufficient declared independent supporting groups: " + ", ".join(weak)
        if weak
        else "Declared groups and duplicate artifact identities checked; independence still requires review.",
    )
    searches = [
        e.get("payload", {}) for e in events if e.get("kind") == "search_completed"
    ]
    searched = {
        q
        for event in searches
        if event.get("sources") and event.get("truncated") is False
        for q in event.get("questions", [])
    }
    check(
        "search_record",
        not standard.require_search_record or set(questions) <= searched,
        "Execute recorded searches for: "
        + "; ".join(q for q in questions if q not in searched)
        if standard.require_search_record
        else "Search record explicitly waived: " + standard.rationale,
    )
    isolated = bool(
        analysis
        and verification
        and verification.execution_ref
        and any(
            e.get("kind") == "review_completed"
            and e.get("payload", {}).get("execution_ref") == verification.execution_ref
            and e.get("payload", {}).get("analysis_fingerprint")
            == fingerprint(analysis)
            and e.get("payload", {}).get("checks")
            == [c.model_dump(mode="json") for c in verification.checks]
            for e in events
        )
    )
    check(
        "isolated_review",
        not standard.require_isolated_review or isolated,
        "Recorded isolated review matches this analysis and all submitted verdicts."
        if isolated
        else (
            "Isolated review explicitly waived: " + standard.rationale
            if not standard.require_isolated_review
            else "Run an isolated review against the current frozen evidence; self-submitted checks do not satisfy this requirement."
        ),
    )
    report_review_required = (
        standard.require_report_composition and standard.require_isolated_review
    )
    matching_review: dict[str, Any] = next(
        (
            e.get("payload", {})
            for e in reversed(events)
            if e.get("kind") == "review_completed"
            and analysis
            and verification
            and e.get("payload", {}).get("execution_ref") == verification.execution_ref
            and e.get("payload", {}).get("analysis_fingerprint")
            == fingerprint(analysis)
        ),
        {},
    )
    report_checks = matching_review.get("report_checks", [])
    chapter_gaps = section_review_gaps(analysis, matching_review)
    criteria = {
        "question_coverage",
        "analytical_depth",
        "synthesis",
        "visual_integrity",
        "limitations",
    }
    reviewed_report = bool(
        isolated
        and not chapter_gaps
        and isinstance(report_checks, list)
        and len(report_checks) == len(criteria)
        and all(
            isinstance(item, dict) and isinstance(item.get("criterion"), str)
            for item in report_checks
        )
        and {item.get("criterion") for item in report_checks} == criteria
        and all(
            item.get("verdict") == "passed"
            and item.get("required_changes") == []
            and isinstance(item.get("rationale"), str)
            and item["rationale"].strip()
            for item in report_checks
        )
    )
    revisions = list(chapter_gaps)
    for item in report_checks if isinstance(report_checks, list) else []:
        if not isinstance(item, dict) or item.get("verdict") == "passed":
            continue
        changes = item.get("required_changes")
        actions = (
            "; ".join(str(change) for change in changes)
            if isinstance(changes, list)
            else ""
        )
        revisions.append(
            str(item.get("criterion"))
            + ": "
            + str(item.get("rationale", ""))
            + " "
            + actions
        )
    check(
        "report_review",
        not report_review_required or reviewed_report,
        "Report rubric passed in the current isolated review; this is model assessment, not human acceptance."
        if reviewed_report
        else "; ".join(revisions)
        or (
            "Run isolated report review for question coverage, analytical depth, synthesis, visual integrity and limitations."
            if report_review_required
            else "Report-level isolated review not required by the declared research standard: "
            + standard.rationale
        ),
    )
    return tuple(gates)
