"""Import an existing deck against an exact, immutable research revision."""

import hashlib
from collections.abc import Callable
from typing import Any

from insight.application.research import ResearchService, research_basis
from insight.domain.contracts import Artifact, ExtractedDocument, PlatformError
from insight.domain.publications import PublicationFile, PublicationRecord, PublicationRequest
from insight.domain.rules import fingerprint, stable_id
from insight.ports.presentations import PresentationInspector
from insight.ports.storage import BlobStore, Transaction


class PublicationService:
    def __init__(
        self,
        tx: Transaction,
        blobs: BlobStore,
        research: ResearchService,
        inspector: PresentationInspector,
        clock: Callable[[], str],
        maximum: int,
    ) -> None:
        self.tx, self.blobs, self.research = tx, blobs, research
        self.inspector, self.clock, self.maximum = inspector, clock, maximum

    def register(self, request: PublicationRequest) -> PublicationRecord:
        evaluation = self.research.evaluate(request.run_id)
        with self.tx(None) as repo:
            analysis = repo.analysis(request.run_id)
            if (
                analysis is None
                or fingerprint(analysis) != request.analysis_fingerprint
                or (research_basis(repo, request.run_id) != request.basis_fingerprint)
            ):
                raise PlatformError("REVISION_CONFLICT", "Presentation uses stale research")
            claims = {c.claim_id: c for c in analysis.claims}
            used = {c for s in request.slides for c in s.claim_ids}
            if (
                not used and request.registration_mode == "research_bound"
            ) or not used <= claims.keys():
                raise PlatformError("EVIDENCE_INVALID", "Slides reference unknown or no claims")
            versions = {v.version_id: v for v in repo.versions(request.run_id)}
            docs = {}
            for coverage in request.source_pages:
                v = versions.get(coverage.source_version_id)
                if v is None or not v.extracted_artifact_id:
                    raise PlatformError("EVIDENCE_INVALID", "Unknown coverage source version")
                docs[v.version_id] = repo.artifact(v.extracted_artifact_id)
            evidence = {e.evidence_id: e for e in repo.evidence(request.run_id)}
            project_id = repo.run(request.run_id).project_id
        for coverage in request.source_pages:
            doc = ExtractedDocument.model_validate_json(
                self.blobs.read(docs[coverage.source_version_id])
            )
            if coverage.unit_index not in {u.index for u in doc.units}:
                raise PlatformError("EVIDENCE_INVALID", "Coverage page is outside fixed source")
            if not set(coverage.claim_ids) <= used:
                raise PlatformError("EVIDENCE_INVALID", "Coverage claim is absent from slides")
            for claim_id in coverage.claim_ids:
                links = claims[claim_id].evidence_links
                if not any(
                    evidence[e.evidence_id].source_version_id == coverage.source_version_id
                    and evidence[e.evidence_id].locator.unit_index == coverage.unit_index
                    for e in links
                ):
                    raise PlatformError(
                        "EVIDENCE_INVALID", "Coverage claim has no evidence on this page"
                    )
                mapped = {s.slide for s in request.slides if claim_id in s.claim_ids}
                if not set(coverage.slides) <= mapped:
                    raise PlatformError(
                        "EVIDENCE_INVALID", "Source-page and slide claim mapping differ"
                    )
        artifacts: list[Artifact] = []
        files = []
        for index, item in enumerate((request.presentation, *request.supplements)):
            uri = self.blobs.stage_local(item.native_path, self.maximum)
            content, media = self.blobs.read_inbox(uri, self.maximum)
            if hashlib.sha256(content).hexdigest() != item.sha256:
                raise PlatformError("EVIDENCE_INVALID", "Imported publication checksum differs")
            if index == 0:
                count = self.inspector.slide_count(content)
                if sorted(s.slide for s in request.slides) != list(range(1, count + 1)):
                    raise PlatformError("EVIDENCE_INVALID", "Map every slide exactly once")
                if any(n < 1 or n > count for p in request.source_pages for n in p.slides):
                    raise PlatformError(
                        "EVIDENCE_INVALID", "Coverage slide is outside presentation"
                    )
            artifact = self.blobs.put(
                content,
                media,
                "reconstructed_deck" if index == 0 else "source_metadata",
                "publication-import@1",
            )
            artifacts.append(artifact)
            files.append(
                PublicationFile(
                    name=item.name,
                    artifact_id=artifact.artifact_id,
                    sha256=artifact.sha256,
                    size=artifact.size,
                )
            )
        identity = dict(
            registration_mode=request.registration_mode,
            run=request.run_id,
            basis=request.basis_fingerprint,
            title=request.title,
            files=[f.model_dump(mode="json") for f in files],
            slides=[s.model_dump(mode="json") for s in request.slides],
            source_pages=[p.model_dump(mode="json") for p in request.source_pages],
            producer=request.producer.model_dump(mode="json"),
            limitations=list(request.limitations),
        )
        publication_id = stable_id("pub", fingerprint(identity))
        with self.tx(None) as repo:
            if research_basis(repo, request.run_id) != request.basis_fingerprint:
                raise PlatformError("REVISION_CONFLICT", "Research changed while importing deck")
            existing = next(
                (p for p in repo.publications(project_id) if p.publication_id == publication_id),
                None,
            )
            if existing:
                return existing
            record = PublicationRecord(
                registration_mode=request.registration_mode,
                publication_id=publication_id,
                project_id=project_id,
                run_id=request.run_id,
                basis_fingerprint=request.basis_fingerprint,
                analysis_fingerprint=request.analysis_fingerprint,
                title=request.title,
                producer=request.producer,
                presentation=files[0],
                supplements=tuple(files[1:]),
                slides=request.slides,
                source_pages=request.source_pages,
                claim_fingerprints={c: fingerprint(claims[c]) for c in sorted(used)},
                limitations=request.limitations,
                quality_state=evaluation["quality_state"]
                if request.registration_mode == "research_bound"
                else "unreviewed_external",
                created_at=self.clock(),
            )
            for artifact in artifacts:
                repo.save_artifact(artifact)
            repo.save_publication(record)
            repo.event(
                request.run_id,
                "presentation_registered",
                {
                    "publication_id": publication_id,
                    "analysis_fingerprint": request.analysis_fingerprint,
                },
                self.clock(),
            )
        return record

    def verify(self, publication_id: str) -> dict[str, Any]:
        with self.tx(None) as repo:
            record = next(
                (p for p in repo.publications() if p.publication_id == publication_id), None
            )
            if record is None:
                raise PlatformError("NOT_FOUND", "Unknown publication")
            artifacts = [
                repo.artifact(f.artifact_id) for f in (record.presentation, *record.supplements)
            ]
            current = research_basis(repo, record.run_id) == record.basis_fingerprint
        for artifact in artifacts:
            self.blobs.read(artifact)
        count = self.inspector.slide_count(self.blobs.read(artifacts[0]))
        return dict(
            publication_id=publication_id,
            files_verified=len(artifacts),
            slides=count,
            current_basis=current,
            user_acceptance="not_recorded_by_registration",
        )
