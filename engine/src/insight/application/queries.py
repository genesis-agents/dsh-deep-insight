from __future__ import annotations

from typing import Any

from insight.domain.collection import collection_coverage
from insight.domain.contracts import ExtractedDocument, PlatformError, RunView
from insight.ports.storage import BlobStore, Transaction


class QueryService:
    def __init__(self, transaction: Transaction, blobs: BlobStore) -> None:
        self.tx, self.blobs = transaction, blobs

    def inspect_run(self, run_id: str) -> dict[str, Any]:
        with self.tx(None) as repo:
            context = repo.context(run_id)
            snapshot = repo.frozen_input(run_id).model_dump(mode="json")
            for source in snapshot["sources"]:
                source.pop("credential_ref", None)
            return {
                "run": repo.run(run_id).model_dump(mode="json"),
                "input_snapshot": snapshot,
                "source_versions": [v.model_dump(mode="json") for v in repo.versions(run_id)],
                "evidence": [e.model_dump(mode="json") for e in repo.evidence(run_id)],
                "context": context.model_dump(mode="json") if context else None,
                "budget_usage": repo.budget_usage(run_id),
                "events": repo.events(run_id),
                "collection_coverage": collection_coverage(
                    repo.frozen_input(run_id), repo.observations(run_id)
                ),
            }

    def list_runs(self) -> tuple[RunView, ...]:
        with self.tx(None) as repo:
            return repo.list_runs()

    def document(self, run_id: str, source_version_id: str) -> ExtractedDocument:
        with self.tx(None) as repo:
            version = next(
                (v for v in repo.versions(run_id) if v.version_id == source_version_id), None
            )
            if version is None or version.extracted_artifact_id is None:
                raise PlatformError("NOT_FOUND", "No extracted document in this run")
            artifact = repo.artifact(version.extracted_artifact_id)
        return ExtractedDocument.model_validate_json(self.blobs.read(artifact))
