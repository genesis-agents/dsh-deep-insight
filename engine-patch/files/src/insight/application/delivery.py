from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from insight.application.research import ResearchService, research_basis
from insight.domain.contracts import DeliveryRecord, PlatformError, ReportFigure
from insight.domain.rules import fingerprint
from insight.ports.storage import BlobStore, DeliveryPublisher, Transaction


def public_snapshot(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: public_snapshot(v) for k, v in value.items() if k != "credential_ref"
        }
    if isinstance(value, list):
        return [public_snapshot(v) for v in value]
    return value


class DeliveryService:
    def __init__(
        self,
        transaction: Transaction,
        research: ResearchService,
        publisher: DeliveryPublisher,
        blobs: BlobStore,
        clock: Callable[[], str],
    ) -> None:
        self.tx, self.research, self.publisher, self.blobs, self.clock = (
            transaction,
            research,
            publisher,
            blobs,
            clock,
        )

    def assemble_delivery(
        self, run_id: str, *, allow_draft: bool = False
    ) -> DeliveryRecord:
        evaluation = self.research.evaluate(run_id)
        if not allow_draft and evaluation["quality_state"] not in (
            "machine_verified",
            "reviewed",
        ):
            raise PlatformError(
                "QUALITY_BLOCKED",
                "Delivery requires passed research gates. Resolve next_actions from quality, or explicitly export a draft with --draft.",
            )
        with self.tx(None) as repo:
            current_review = repo.review(run_id)
            if (
                research_basis(repo, run_id) != evaluation["basis_fingerprint"]
                or (fingerprint(current_review) if current_review else None)
                != evaluation["review_fingerprint"]
            ):
                raise PlatformError(
                    "REVISION_CONFLICT", "Research changed before export"
                )
            frozen, analysis, context = (
                repo.frozen_input(run_id),
                repo.analysis(run_id),
                repo.context(run_id),
            )
            if analysis is None or context is None:
                raise PlatformError(
                    "INVALID_STATE",
                    "Select evidence and submit analysis before exporting a report",
                )
            observations = repo.observations(run_id)
            versions = repo.versions(run_id)
            artifact_ids = {v.raw_artifact_id for v in versions} | {
                v.extracted_artifact_id for v in versions if v.extracted_artifact_id
            }
            publications = tuple(
                p
                for p in repo.publications(frozen.project.project_id)
                if p.run_id == run_id
                and p.registration_mode == "research_bound"
                and p.basis_fingerprint == evaluation["basis_fingerprint"]
            )
            artifact_ids |= {
                f.artifact_id
                for p in publications
                for f in (p.presentation, *p.supplements)
            }
            if analysis.narrative:
                artifact_ids |= {
                    block.image_artifact_id
                    for section in analysis.narrative.sections
                    for block in section.blocks
                    if isinstance(block, ReportFigure) and block.image_artifact_id
                }
            artifacts = tuple(repo.artifact(i) for i in sorted(artifact_ids))
            package: dict[str, Any] = dict(
                delivery_id="delivery_" + uuid4().hex,
                run_id=run_id,
                project_id=frozen.project.project_id,
                created_at=self.clock(),
                basis_fingerprint=evaluation["basis_fingerprint"],
                quality_state=evaluation["quality_state"],
                frozen_input=public_snapshot(frozen.model_dump(mode="json")),
                analysis=analysis.model_dump(mode="json"),
                context=context.model_dump(mode="json"),
                observations=[o.model_dump(mode="json") for o in observations],
                source_versions=[v.model_dump(mode="json") for v in versions],
                quality=evaluation,
                budget_usage=repo.budget_usage(run_id),
                publications=[p.model_dump(mode="json") for p in publications],
            )
        record = self.publisher.prepare(package, artifacts)
        # Prepared versions are immutable and verified before any user-facing latest pointer changes.
        with self.tx(None) as repo:
            current_review = repo.review(run_id)
            if (
                research_basis(repo, run_id) != evaluation["basis_fingerprint"]
                or (fingerprint(current_review) if current_review else None)
                != evaluation["review_fingerprint"]
            ):
                raise PlatformError(
                    "REVISION_CONFLICT",
                    "Research changed during export; prepared version left unpublished",
                )
            current = repo.analysis(run_id)
            if current is None or fingerprint(current) != fingerprint(analysis):
                raise PlatformError(
                    "REVISION_CONFLICT",
                    "Analysis changed during export; prepared version left unpublished",
                )
            repo.save_delivery(record)
            repo.event(
                run_id,
                "delivery_prepared",
                {"delivery_id": record.delivery_id},
                self.clock(),
            )
            all_deliveries = repo.deliveries()
        self.publisher.activate(record, all_deliveries)
        with self.tx(None) as repo:
            repo.event(
                run_id,
                "delivery_published",
                {"delivery_id": record.delivery_id},
                self.clock(),
            )
        return record

    def reconcile_outputs(self) -> int:
        """Rebuild derived latest/index views from verified, database-registered versions."""
        with self.tx(None) as repo:
            deliveries = repo.deliveries()
        latest = {d.project_id: d for d in deliveries}
        for record in latest.values():
            self.publisher.verify(record.relative_path)
            self.publisher.activate(record, deliveries)
        return len(latest)
