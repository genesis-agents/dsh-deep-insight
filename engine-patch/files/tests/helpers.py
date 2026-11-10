from pathlib import Path

from insight.bootstrap import Application
from insight.domain.contracts import (
    AnalysisSubmission,
    Attribution,
    ChannelRequirement,
    Claim,
    CoverageItem,
    EvidenceInput,
    EvidenceLink,
    Limits,
    Locator,
    PlanSpec,
    ProjectSpec,
    ResearchStandard,
    Scope,
    SourcePlanItem,
    Window,
)


def start_case(
    app: Application,
    directory: Path,
    profile="technical",
    project_id="sample",
    content=None,
    limits=None,
    suffix=".txt",
):
    default_text = "Synthetic technical fixture: throughput doubled only for a fixed batch of 32. This is not an observed business fact."
    if profile == "industry":
        default_text = "Synthetic industry fixture: a survey of 12 firms in one region reports adoption plans, not completed deployments. It is not a market estimate or a real observation."
    text = content or default_text
    path = directory / (project_id + suffix)
    path.write_text(text, encoding="utf-8")
    project = app.projects.define_project(
        ProjectSpec(
            quality_standard=ResearchStandard(
                min_supporting_groups=1,
                require_publication_dates=False,
                require_search_record=False,
                require_isolated_review=False,
                require_report_composition=False,
                rationale="Offline single-source fixture; not real research assurance",
            ),
            collection_requirements=(
                ChannelRequirement(
                    channel="local",
                    disposition="required",
                    rationale="Synthetic local fixture scope",
                ),
            ),
            project_id=project_id,
            question="What does the material support?",
            decision="Decide whether further verification is needed",
            scope=Scope(regions=("North America",), as_of="2026-10-26"),
            profile_ref=profile + "@1",
            subquestions=("What conditions apply?",),
        ),
        0,
    )
    source_id = "source_" + project_id
    app.projects.import_local(
        source_id,
        str(path),
        "Synthetic fixture author",
        "Generated test material, not real-world evidence",
    )
    plan = PlanSpec(
        plan_id="plan_" + project_id,
        project_id=project_id,
        project_revision=project.revision,
        items=(
            SourcePlanItem(
                source_ref=source_id,
                goal="document_text",
                accepted_material_roles=("raw_document",),
                requested_window=Window(end="2026-10-26"),
                access_mode="user_file",
                completion_rule="fixed_file_and_text_acquired",
                freshness_rule="user_supplied_snapshot",
            ),
        ),
        limits=limits or Limits(),
    )
    app.projects.freeze_source_plan(plan)
    run = app.projects.start_run(plan.plan_id)
    app.worker.run_once()
    return run["run_id"]


def analyze_case(
    app: Application, run_id: str, *, statement="The fixture reports a condition-dependent result."
):
    with app.db.transaction(None) as repo:
        version = repo.versions(run_id)[0]
    document = app.queries.document(run_id, version.version_id)
    unit = document.units[0]
    quote = unit.text[: min(len(unit.text), 120)]
    evidence = app.research.add_evidence(
        run_id,
        EvidenceInput(
            source_version_id=version.version_id,
            artifact_id=version.extracted_artifact_id,
            locator=Locator(unit_index=1, char_start=0, char_end=len(quote)),
            quote=quote,
        ),
    )
    coverage = (
        CoverageItem(subquestion="What conditions apply?", evidence_ids=(evidence.evidence_id,)),
    )
    context = app.research.prepare_context(run_id, coverage)
    analysis = AnalysisSubmission(
        run_id=run_id,
        context_fingerprint=context["context_fingerprint"],
        producer=Attribution(
            mode="human",
            name="Acceptance fixture generator",
            notes="Synthetic test submission; not a user research acceptance",
        ),
        title="Synthetic acceptance example",
        synthesis="Only the fixture's stated conditions are supported.",
        claims=(
            Claim(
                claim_id="claim_1",
                kind="source_claim",
                statement=statement,
                conditions=("Synthetic material only",),
                evidence_links=(
                    EvidenceLink(evidence_id=evidence.evidence_id, relation="supports"),
                ),
            ),
        ),
        coverage=coverage,
        limitations=("Not real-world validation",),
    )
    app.research.submit_analysis(analysis)
    return analysis, evidence
