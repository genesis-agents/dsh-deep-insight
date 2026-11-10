from __future__ import annotations

from collections.abc import Callable
from typing import Literal
from uuid import uuid4

from insight.domain.contracts import (
    FrozenInput,
    JobState,
    PlanSpec,
    PlatformError,
    ProjectRevision,
    ProjectSpec,
    Source,
    SourceOrigin,
)
from insight.domain.rules import fingerprint
from insight.ports.storage import BlobStore, ProfileStore, Transaction


class ProjectService:
    def __init__(
        self,
        transaction: Transaction,
        profiles: ProfileStore,
        blobs: BlobStore,
        clock: Callable[[], str],
        code_ref: str,
        maximum_bytes: int,
    ) -> None:
        self.tx, self.profiles, self.blobs = transaction, profiles, blobs
        self.clock, self.code_ref, self.maximum_bytes = clock, code_ref, maximum_bytes

    def define_project(self, spec: ProjectSpec, expected_revision: int) -> ProjectRevision:
        if spec.collection_requirements is None:
            raise PlatformError(
                "INVALID_SPEC",
                "New project revisions must explicitly declare collection_requirements; omitted channels cannot silently pass",
            )
        self.profiles.get(spec.profile_ref)
        with self.tx(None) as repo:
            old = repo.latest_project_revision(spec.project_id)
            if old != expected_revision:
                raise PlatformError(
                    "REVISION_CONFLICT", f"Expected revision {expected_revision}, actual {old}"
                )
            project = ProjectRevision(**spec.model_dump(), revision=old + 1)
            repo.save_project(project)
            return project

    def import_local(
        self,
        source_id: str,
        native_path: str,
        publisher: str,
        provenance: str,
        origin: SourceOrigin | None = None,
        material_role: Literal["raw_document", "original_slides", "raw_audio", "raw_video"]
        | None = None,
    ) -> Source:
        # Native paths are consumed by the adapter and never enter research-domain records.
        uri = self.blobs.stage_local(native_path, self.maximum_bytes)
        source = Source(
            source_id=source_id,
            provider="local",
            canonical_identity="user-file:" + uuid4().hex,
            resource_uri=uri,
            publisher=publisher,
            identity_status="user_provided",
            identity_basis=(provenance,),
            origin=origin,
            declared_material_role=material_role,
        )
        return self.register_source(source)

    def register_source(self, source: Source) -> Source:
        with self.tx(None) as repo:
            repo.save_source(source)
        return source

    def freeze_source_plan(self, plan: PlanSpec) -> PlanSpec:
        with self.tx(None) as repo:
            repo.project(plan.project_id, plan.project_revision)
            for item in plan.items:
                source = repo.source(item.source_ref)
                expected_access = {
                    "local": "user_file",
                    "http": "public_http",
                    "conference": "public_http",
                    "youtube": "public_http",
                    "x": "authorized_api",
                    "feed": "public_http",
                    "browser": "browser_assisted",
                }[source.provider]
                if source.provider == "x" and item.goal == "public_post":
                    expected_access = "public_http"
                if item.access_mode != expected_access:
                    raise PlatformError(
                        "UNSUPPORTED_CAPABILITY",
                        "Access mode does not match the installed source adapter",
                    )
                if source.provider == "local" and item.access_mode != "user_file":
                    raise PlatformError(
                        "INVALID_SPEC", "Local sources require user_file access mode"
                    )
                if source.provider != "local" and item.access_mode == "user_file":
                    raise PlatformError(
                        "INVALID_SPEC", "Remote sources cannot use user_file access mode"
                    )
            repo.save_plan(plan)
        return plan

    def start_run(self, plan_id: str, idempotency_key: str | None = None) -> dict[str, str]:
        with self.tx(None) as repo:
            plan = repo.plan(plan_id)
            project = repo.project(plan.project_id, plan.project_revision)
            frozen = FrozenInput(
                project=project,
                plan=plan,
                profile=self.profiles.get(project.profile_ref),
                sources=tuple(repo.source(i.source_ref) for i in plan.items),
                code_ref=self.code_ref,
            )
            input_hash = fingerprint(frozen)
            if idempotency_key:
                previous = repo.request_result("start_run", idempotency_key, input_hash)
                if previous:
                    return {k: str(v) for k, v in previous.items()}
            run_id, job_id = "run_" + uuid4().hex, "job_" + uuid4().hex
            repo.create_run(run_id, job_id, frozen, self.clock())
            result = {"run_id": run_id, "job_id": job_id}
            repo.event(run_id, "run_created", {"input_fingerprint": input_hash}, self.clock())
            if idempotency_key:
                repo.save_request_result("start_run", idempotency_key, input_hash, result)
            return result

    def resume_run(self, run_id: str) -> None:
        with self.tx(None) as repo:
            view = repo.run(run_id)
            if (
                view.execution_state not in ("waiting_input", "retry_scheduled")
                or view.stage != "W3"
            ):
                raise PlatformError(
                    "INVALID_STATE",
                    "Only acquisition waits can be requeued; terminal attempts need a new run",
                )
            repo.set_job_state(run_id, "queued", "W3", None)
            repo.event(run_id, "acquisition_resumed", {}, self.clock())

    def cancel_run(self, run_id: str) -> None:
        with self.tx(None) as repo:
            view = repo.run(run_id)
            if view.execution_state in ("succeeded", "failed", "cancelled"):
                raise PlatformError(
                    "INVALID_STATE", "Terminal execution cannot be reopened or cancelled"
                )
            state: JobState = (
                "cancel_requested" if view.execution_state in ("running", "leased") else "cancelled"
            )
            repo.set_job_state(run_id, state, view.stage, "User cancellation")
            repo.event(run_id, "cancellation_requested", {}, self.clock())
