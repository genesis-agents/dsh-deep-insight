from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import uuid4

from insight.domain.collection import collection_coverage
from insight.domain.contracts import (
    Derivation,
    GoalResult,
    Lease,
    Limits,
    Observation,
    PlatformError,
    SourceVersion,
)
from insight.domain.rules import canonical, fingerprint, stable_id
from insight.ports.sources import SourceProvider, TextExtractor
from insight.ports.storage import BlobStore, JobQueue, Transaction


class RunBudget:
    def __init__(self, transaction: Transaction, lease: Lease, limits: Limits) -> None:
        self.tx, self.lease, self.limits = transaction, lease, limits

    def consume(self, category: str, amount: int) -> None:
        values = self.limits.model_dump()
        if category not in values:
            if category == "media_model_calls":
                raise PlatformError(
                    "BUDGET_EXCEEDED",
                    "Local ASR requires an explicit media_model_calls allowance in the frozen plan",
                )
            raise PlatformError("INVALID_SPEC", "Unknown budget category")
        with self.tx(self.lease) as repo:
            repo.budget_consume(self.lease.run_id, category, amount, int(values[category]))


class AcquisitionWorker:
    def __init__(
        self,
        transaction: Transaction,
        queue: JobQueue,
        blobs: BlobStore,
        providers: dict[str, SourceProvider],
        extractor: TextExtractor,
        clock: Callable[[], str],
        lease_seconds: int = 120,
    ) -> None:
        self.tx, self.queue, self.blobs, self.providers = transaction, queue, blobs, providers
        self.extractor, self.clock, self.lease_seconds = extractor, clock, lease_seconds

    def _until(self) -> str:
        return (
            datetime.fromisoformat(self.clock().replace("Z", "+00:00"))
            + timedelta(seconds=self.lease_seconds)
        ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    def run_once(self) -> str | None:
        self.queue.recover(self.clock())
        lease = self.queue.claim("worker_" + uuid4().hex, self.clock(), self._until())
        if lease is None:
            return None
        stop = threading.Event()

        def keep_alive() -> None:
            while not stop.wait(max(1, self.lease_seconds / 3)):
                try:
                    self.queue.heartbeat(lease, self.clock(), self._until())
                except PlatformError:
                    return

        heartbeat = threading.Thread(target=keep_alive, daemon=True)
        heartbeat.start()
        try:
            self._acquire(lease)
        except PlatformError as exc:
            if exc.code != "LEASE_LOST":
                with self.tx(lease) as repo:
                    repo.set_job_state(lease.run_id, "failed", "W3", exc.code + ": " + exc.detail)
                    repo.event(lease.run_id, "worker_failed", {"code": exc.code}, self.clock())
        finally:
            stop.set()
            heartbeat.join(timeout=2)
        return lease.run_id

    def _acquire(self, lease: Lease) -> None:
        with self.tx(lease) as repo:
            frozen = repo.frozen_input(lease.run_id)
            completed = {
                o.source_id for o in repo.observations(lease.run_id) if o.goal_result.state == "met"
            }
            checkpoints = {o.source_id: o.checkpoint for o in repo.observations(lease.run_id)}
            existing_versions = {
                (v.source_id, v.raw_artifact_id, v.extracted_artifact_id): v
                for v in repo.versions(lease.run_id)
            }
        budget = RunBudget(self.tx, lease, frozen.plan.limits)
        needs_access = False
        for item, source in zip(frozen.plan.items, frozen.sources, strict=True):
            if source.source_id in completed:
                continue
            provider = self.providers.get(source.provider)
            raw_records = []
            parsed_records = []
            unparsed_records = []
            try:
                deferred = checkpoints.get(source.source_id, {}).get("retry_not_before")
                if isinstance(deferred, str) and datetime.fromisoformat(
                    self.clock().replace("Z", "+00:00")
                ) < datetime.fromisoformat(deferred.replace("Z", "+00:00")):
                    raise PlatformError(
                        "RATE_LIMITED", "Provider retry window has not elapsed; no request sent"
                    )
                if provider is None:
                    raise PlatformError(
                        "UNSUPPORTED_CAPABILITY", "Source provider is not enabled in this release"
                    )
                acquired = provider.acquire(
                    source, item, budget, checkpoints.get(source.source_id, {})
                )
                observation = acquired.observation
                if observation.source_id != source.source_id:
                    raise PlatformError(
                        "INVALID_PROVIDER_RESPONSE",
                        "Acquisition returned a different source identity",
                    )
                for doc in acquired.documents:
                    raw = self.blobs.put(
                        doc.data, doc.media_type, doc.role, "acquire:" + source.provider + "@1"
                    )
                    raw_records.append(raw)
                    try:
                        extracted = self.extractor.extract(doc.data, doc.media_type, doc.role)
                    except PlatformError:
                        # Keep failed/challenge/unsupported original bytes visible without inventing text.
                        unparsed_records.append(
                            SourceVersion(
                                version_id=stable_id(
                                    "sv",
                                    lease.run_id,
                                    source.source_id,
                                    raw.artifact_id,
                                    "unparsed",
                                ),
                                run_id=lease.run_id,
                                source_id=source.source_id,
                                raw_artifact_id=raw.artifact_id,
                                extracted_artifact_id=None,
                                acquired_at=self.clock(),
                                origin_uri=doc.origin_uri,
                            )
                        )
                        raise
                    if item.goal == "document_text" and not any(
                        u.text.strip() for u in extracted.units if u.kind != "metadata"
                    ):
                        observation = observation.model_copy(
                            update={
                                "goal_result": GoalResult(
                                    state="not_met",
                                    reason_code="TEXT_UNAVAILABLE",
                                    detail="Original bytes archived but no substantive text; scanned pages require an explicit OCR/visual workflow",
                                )
                            }
                        )
                    if (
                        doc.media_type == "text/html"
                        and doc.role == "raw_document"
                        and item.goal == "document_text"
                    ):
                        size = sum(len(u.text.strip()) for u in extracted.units)
                        if size < (item.minimum_text_characters or 400):
                            observation = observation.model_copy(
                                update={
                                    "goal_result": GoalResult(
                                        state="not_met",
                                        reason_code="CONTENT_INCOMPLETE",
                                        detail=f"Only {size} body characters; below the declared content minimum; archived as a partial lead",
                                    )
                                }
                            )
                    text = self.blobs.put(
                        canonical(extracted),
                        "application/json",
                        "extracted_text",
                        extracted.processor_ref,
                    )
                    derivation = Derivation(
                        derivation_id=stable_id(
                            "der", raw.artifact_id, text.artifact_id, extracted.processor_ref
                        ),
                        input_artifact_id=raw.artifact_id,
                        output_artifact_id=text.artifact_id,
                        processor_ref=extracted.processor_ref,
                        parameters_hash=fingerprint({"mode": "text", "normalization": "none"}),
                    )
                    version_key = (source.source_id, raw.artifact_id, text.artifact_id)
                    source_version = existing_versions.get(version_key) or SourceVersion(
                        version_id=stable_id(
                            "sv",
                            lease.run_id,
                            source.source_id,
                            raw.artifact_id,
                            text.artifact_id,
                        ),
                        run_id=lease.run_id,
                        source_id=source.source_id,
                        raw_artifact_id=raw.artifact_id,
                        extracted_artifact_id=text.artifact_id,
                        acquired_at=self.clock(),
                        origin_uri=doc.origin_uri,
                        published_at=doc.published_at,
                    )
                    existing_versions[version_key] = source_version
                    parsed_records.append((raw, text, source_version, derivation))
                    if extracted.warnings:
                        observation = observation.model_copy(
                            update={
                                "coverage_notes": observation.coverage_notes + extracted.warnings
                            }
                        )
                expected_role = {
                    "document_text": "raw_document",
                    "slides_only": "original_slides",
                    "editable_original_pptx": "original_slides",
                    "metadata": "source_metadata",
                    "full_talk_analysis": "transcript",
                    "latest_posts": "post",
                    "public_post": "post",
                    "video_transcript": "transcript",
                    "video_frames": "derived_slide_frames",
                    "discover_updates": "source_metadata",
                    "observed_posts": "post",
                }[item.goal]
                if observation.goal_result.state == "met":
                    roles = {doc.role for doc in acquired.documents}
                    if expected_role not in item.accepted_material_roles or (
                        expected_role not in roles and item.goal != "latest_posts"
                    ):
                        raise PlatformError(
                            "GOAL_NOT_MET", "Required material role was not acquired"
                        )
                    if item.goal == "latest_posts" and not observation.pagination_complete:
                        raise PlatformError(
                            "GOAL_NOT_MET", "Requested post window is not fully committed"
                        )
            except PlatformError as exc:
                if exc.code == "LEASE_LOST":
                    raise
                needs_access = needs_access or (
                    item.required and exc.code in ("ACCESS_REQUIRED", "RATE_LIMITED")
                )
                observation = Observation(
                    source_id=source.source_id,
                    requested_window=item.requested_window,
                    goal_result=GoalResult(
                        state="not_met", reason_code=exc.code, detail=exc.detail
                    ),
                    checkpoint={
                        **checkpoints.get(source.source_id, {}),
                        **(
                            {
                                "retry_not_before": (
                                    datetime.fromisoformat(self.clock().replace("Z", "+00:00"))
                                    + timedelta(seconds=exc.retry_after_seconds)
                                ).isoformat()
                            }
                            if exc.retry_after_seconds is not None
                            else {}
                        ),
                    },
                )
            with self.tx(lease) as repo:
                for raw in raw_records:
                    repo.save_artifact(raw)
                for _raw, text, source_version, derivation in parsed_records:
                    repo.save_artifact(text)
                    repo.save_acquisition(source_version, derivation)
                for version in unparsed_records:
                    repo.save_acquisition(version, None)
                repo.observe(lease.run_id, observation)
                repo.event(
                    lease.run_id,
                    "source_processed",
                    {
                        "source_id": source.source_id,
                        "goal_result": observation.goal_result.model_dump(mode="json"),
                    },
                    self.clock(),
                )
        with self.tx(lease) as repo:
            observations = repo.observations(lease.run_id)
            pending = any(
                o.goal_result.reason_code in ("PAGINATION_PENDING", "CURSOR_RESET_PENDING")
                for o in observations
            )
            needs_access = needs_access or any(
                o.goal_result.reason_code
                in ("PAGE_BUDGET_EXCEEDED", "RATE_LIMITED", "ACCESS_REQUIRED", "BUDGET_EXCEEDED")
                for o in observations
            )
            has_gaps = any(
                i.required
                and not any(
                    o.source_id == i.source_ref and o.goal_result.state == "met"
                    for o in observations
                )
                for i in frozen.plan.items
            )
            channel_gaps = not collection_coverage(frozen, observations)["complete"]
            stage = "W3" if needs_access or has_gaps or channel_gaps else "W5"
            reason = (
                "Source access or rate-limit gap; explicit resume required"
                if needs_access
                else "Collection incomplete; inspect source reasons and independent channel requirements before resuming or creating a revised plan"
                if has_gaps or channel_gaps
                else "Select evidence and submit structured analysis"
            )
            if pending:
                repo.set_job_state(
                    lease.run_id,
                    "queued",
                    "W3",
                    "Continue committed API pagination within the frozen budget",
                )
            else:
                repo.set_job_state(lease.run_id, "waiting_input", stage, reason)
            repo.event(lease.run_id, "acquisition_checkpoint", {"stage": stage}, self.clock())
