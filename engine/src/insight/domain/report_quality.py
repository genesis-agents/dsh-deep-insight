"""Report composition checks detect empty outlines without pretending to measure analytical truth."""

from insight.domain.contracts import AnalysisSubmission, ReportParagraph


def section_review_gaps(
    analysis: AnalysisSubmission | None, receipt: dict
) -> list[str]:
    """Require current, evidence-linked editorial findings for every report chapter."""
    if receipt.get("report_review_standard") != "professional-report@1":
        return ["Rerun isolated review with chapter-level editorial findings."]
    if analysis is None or analysis.narrative is None:
        return ["Write the report before requesting chapter-level review."]
    rows = receipt.get("section_checks")
    sections = analysis.narrative.sections
    if (
        not isinstance(rows, list)
        or len(rows) != len(sections)
        or any(
            not isinstance(row, dict) or not isinstance(row.get("section_id"), str)
            for row in rows
        )
        or {row["section_id"] for row in rows}
        != {section.section_id for section in sections}
    ):
        return ["Review each current chapter exactly once."]
    gaps = []
    for section in sections:
        row = next(row for row in rows if row["section_id"] == section.section_id)
        claim_ids = set(section.claim_ids)
        for block in section.blocks:
            claim_ids.update(getattr(block, "claim_ids", ()))
        evidence_ids = {
            link.evidence_id
            for claim in analysis.claims
            if claim.claim_id in claim_ids
            for link in claim.evidence_links
        }
        excerpt, cited = row.get("analysis_excerpt"), row.get("evidence_ids")
        anchored = (
            isinstance(excerpt, str)
            and bool(excerpt.strip())
            and any(
                excerpt in block.text
                for block in section.blocks
                if isinstance(block, ReportParagraph)
            )
            and isinstance(cited, list)
            and bool(cited)
            and all(isinstance(item, str) and item in evidence_ids for item in cited)
            and isinstance(row.get("rationale"), str)
            and bool(row["rationale"].strip())
            and row.get("required_changes") == []
        )
        if row.get("verdict") != "passed" or not anchored:
            changes = row.get("required_changes", [])
            gaps.append(
                section.section_id
                + ": "
                + str(row.get("rationale", "Missing chapter assessment"))
                + "; "
                + "; ".join(str(item) for item in changes if isinstance(item, str))
                if isinstance(changes, list)
                else section.section_id + ": invalid chapter assessment"
            )
    return gaps


def report_gaps(analysis: AnalysisSubmission | None) -> list[str]:
    """Identify missing conclusions, recommendations, explanations and useful visual structure."""
    if analysis is None or analysis.narrative is None:
        return ["Write an evidence-linked narrative, not only a title and synthesis."]
    narrative = analysis.narrative
    gaps = []
    if not narrative.conclusion:
        gaps.append("Add a final conclusion answering the overall research question.")
    if not narrative.recommendations:
        gaps.append(
            "Add evidence-linked recommendations or specific next verification steps."
        )
    for section in narrative.sections:
        paragraphs = [
            b.text.strip() for b in section.blocks if isinstance(b, ReportParagraph)
        ]
        if not any(text != section.answer.strip() for text in paragraphs):
            gaps.append(
                section.section_id
                + ": explain the evidence and implications beyond repeating the answer."
            )
        if len(paragraphs) != len(set(paragraphs)):
            gaps.append(section.section_id + ": remove repeated body paragraphs.")
    return gaps
