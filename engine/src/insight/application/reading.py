"""Read-only projection of registered research into a human-readable workspace."""

from __future__ import annotations

from typing import Any

from insight.application.delivery import public_snapshot
from insight.application.research import research_basis
from insight.domain.collection import collection_coverage
from insight.domain.rules import fingerprint
from insight.ports.storage import ReadingPublisher, Transaction


class ReadingService:
    def __init__(self, transaction: Transaction, publisher: ReadingPublisher) -> None:
        self.tx, self.publisher = transaction, publisher

    def publish(self) -> dict[str, Any]:
        runs = []
        artifacts = {}
        with self.tx(None) as repo:
            projects = [p.model_dump(mode="json") for p in repo.list_projects()]
            publications = []
            for publication in repo.publications():
                for file in (publication.presentation, *publication.supplements):
                    artifacts[file.artifact_id] = repo.artifact(file.artifact_id)
                publications.append(
                    {
                        **publication.model_dump(mode="json"),
                        "current_basis": publication.basis_fingerprint
                        == research_basis(repo, publication.run_id),
                    }
                )
            for view in repo.list_runs():
                run_id = view.run_id
                versions = repo.versions(run_id)
                for version in versions:
                    for artifact_id in (version.raw_artifact_id, version.extracted_artifact_id):
                        if artifact_id:
                            artifacts[artifact_id] = repo.artifact(artifact_id)
                analysis = repo.analysis(run_id)
                verification = repo.verification(run_id)
                review = repo.review(run_id)
                context = repo.context(run_id)
                basis = research_basis(repo, run_id)
                runs.append(
                    dict(
                        view=view.model_dump(mode="json"),
                        input=repo.frozen_input(run_id).model_dump(mode="json"),
                        versions=[v.model_dump(mode="json") for v in versions],
                        observations=[o.model_dump(mode="json") for o in repo.observations(run_id)],
                        evidence=[e.model_dump(mode="json") for e in repo.evidence(run_id)],
                        analysis=analysis.model_dump(mode="json") if analysis else None,
                        context=context.model_dump(mode="json") if context else None,
                        verification=verification.model_dump(mode="json") if verification else None,
                        verification_current=bool(
                            analysis
                            and verification
                            and verification.analysis_fingerprint == fingerprint(analysis)
                        ),
                        review=review.model_dump(mode="json") if review else None,
                        review_current=bool(review and review.basis_fingerprint == basis),
                        deliveries=[
                            {
                                **d.model_dump(mode="json"),
                                "current_basis": d.basis_fingerprint == basis,
                            }
                            for d in repo.deliveries(view.project_id)
                            if d.run_id == run_id
                        ],
                        events=repo.events(run_id),
                        collection_coverage=collection_coverage(
                            repo.frozen_input(run_id), repo.observations(run_id)
                        ),
                    )
                )
        # This projection neither changes research state nor becomes a second authority.
        return self.publisher.publish(
            public_snapshot({"projects": projects, "runs": runs, "publications": publications}),
            tuple(artifacts.values()),
        )
