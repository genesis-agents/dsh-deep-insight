"""SQLAlchemy Core repository. External I/O is never performed inside these transactions."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypeVar

from alembic import command
from alembic.config import Config
from insight.adapters.persistence import schema_v1 as t
from insight.adapters.persistence.objects import native_path
from insight.adapters.persistence.schema_v2 import publications
from insight.domain.contracts import (
    AnalysisSubmission,
    Artifact,
    ContextSnapshot,
    Contract,
    DeliveryRecord,
    Derivation,
    EvidenceSpan,
    FrozenInput,
    GateResult,
    JobState,
    Lease,
    Observation,
    PlanSpec,
    PlatformError,
    ProjectRevision,
    ReviewSubmission,
    RunView,
    Source,
    SourceVersion,
    VerificationSubmission,
)
from insight.domain.publications import PublicationRecord
from insight.domain.rules import canonical, fingerprint
from insight.ports.storage import Repository
from sqlalchemy import Connection, Table, and_, create_engine, event, func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.engine import URL
from sqlalchemy.exc import DatabaseError, IntegrityError

T = TypeVar("T", bound=Contract)


class SqlRepository:
    def save_publication(self, record: PublicationRecord) -> None:
        self._immutable(
            publications,
            dict(
                publication_id=record.publication_id,
                run_id=record.run_id,
                project_id=record.project_id,
            ),
            record,
        )

    def publications(self, project_id: str | None = None) -> tuple[PublicationRecord, ...]:
        query = select(publications.c.payload)
        if project_id:
            query = query.where(publications.c.project_id == project_id)
        values = [PublicationRecord.model_validate_json(p) for p in self.c.scalars(query)]
        return tuple(sorted(values, key=lambda p: (p.created_at, p.publication_id)))

    def __init__(self, connection: Connection) -> None:
        self.c = connection

    def _one(self, table: Table, clause: Any, model: type[T]) -> T:
        payload = self.c.scalar(select(table.c.payload).where(clause))
        if payload is None:
            raise PlatformError("NOT_FOUND", f"Record not found in {table.name}")
        return model.model_validate_json(payload)

    def _immutable(self, table: Table, values: dict[str, Any], model: Contract) -> None:
        payload = canonical(model).decode()
        where = and_(*(table.c[key.name] == values[key.name] for key in table.primary_key))
        previous = self.c.scalar(select(table.c.payload).where(where))
        if previous is not None:
            if previous != payload:
                raise PlatformError("REVISION_CONFLICT", f"Immutable {table.name} record exists")
            return
        self.c.execute(table.insert().values(**values, payload=payload))

    def latest_project_revision(self, project_id: str) -> int:
        return int(
            self.c.scalar(
                select(func.max(t.projects.c.revision)).where(t.projects.c.project_id == project_id)
            )
            or 0
        )

    def save_project(self, project: ProjectRevision) -> None:
        self._immutable(
            t.projects, {"project_id": project.project_id, "revision": project.revision}, project
        )

    def project(self, project_id: str, revision: int) -> ProjectRevision:
        return self._one(
            t.projects,
            and_(t.projects.c.project_id == project_id, t.projects.c.revision == revision),
            ProjectRevision,
        )

    def save_source(self, source: Source) -> None:
        self._immutable(t.sources, {"source_id": source.source_id}, source)

    def list_projects(self) -> tuple[ProjectRevision, ...]:
        latest = {}
        for payload in self.c.scalars(
            select(t.projects.c.payload).order_by(t.projects.c.project_id, t.projects.c.revision)
        ):
            project = ProjectRevision.model_validate_json(payload)
            latest[project.project_id] = project
        return tuple(latest.values())

    def source(self, source_id: str) -> Source:
        return self._one(t.sources, t.sources.c.source_id == source_id, Source)

    def save_plan(self, plan: PlanSpec) -> None:
        self._immutable(
            t.plans,
            {
                "plan_id": plan.plan_id,
                "project_id": plan.project_id,
                "project_revision": plan.project_revision,
            },
            plan,
        )

    def plan(self, plan_id: str) -> PlanSpec:
        return self._one(t.plans, t.plans.c.plan_id == plan_id, PlanSpec)

    def create_run(self, run_id: str, job_id: str, frozen: FrozenInput, now: str) -> None:
        self.c.execute(
            t.runs.insert().values(
                run_id=run_id,
                project_id=frozen.project.project_id,
                project_revision=frozen.project.revision,
                plan_id=frozen.plan.plan_id,
                frozen_input=canonical(frozen).decode(),
                created_at=now,
            )
        )
        self.c.execute(
            t.jobs.insert().values(job_id=job_id, run_id=run_id, state="queued", stage="W3")
        )

    def frozen_input(self, run_id: str) -> FrozenInput:
        value = self.c.scalar(select(t.runs.c.frozen_input).where(t.runs.c.run_id == run_id))
        if value is None:
            raise PlatformError("NOT_FOUND", "Unknown run")
        return FrozenInput.model_validate_json(value)

    def run(self, run_id: str) -> RunView:
        row = (
            self.c.execute(
                select(t.runs, t.jobs.c.job_id, t.jobs.c.state, t.jobs.c.stage, t.jobs.c.reason)
                .join(t.jobs)
                .where(t.runs.c.run_id == run_id)
            )
            .mappings()
            .first()
        )
        if row is None:
            raise PlatformError("NOT_FOUND", "Unknown run")
        return RunView.model_validate_json(
            json.dumps(
                dict(
                    run_id=run_id,
                    project_id=row["project_id"],
                    job_id=row["job_id"],
                    execution_state=row["state"],
                    stage=row["stage"],
                    quality_state=row["quality"],
                    goal_results=[o.model_dump(mode="json") for o in self.observations(run_id)],
                    gates=json.loads(row["gates"]),
                    delivery_ref=row["delivery_ref"],
                    waiting_reason=row["reason"],
                )
            )
        )

    def list_runs(self) -> tuple[RunView, ...]:
        return tuple(
            self.run(r)
            for r in self.c.scalars(select(t.runs.c.run_id).order_by(t.runs.c.created_at))
        )

    def event(self, run_id: str, kind: str, payload: dict[str, Any], now: str) -> None:
        self.c.execute(
            t.events.insert().values(
                run_id=run_id, kind=kind, at=now, payload=canonical(payload).decode()
            )
        )

    def events(self, run_id: str) -> list[dict[str, Any]]:
        return [
            dict(sequence=r.sequence, kind=r.kind, at=r.at, payload=json.loads(r.payload))
            for r in self.c.execute(
                select(t.events).where(t.events.c.run_id == run_id).order_by(t.events.c.sequence)
            )
        ]

    def budget_consume(self, run_id: str, category: str, amount: int, limit: int) -> None:
        if amount < 0:
            raise PlatformError("INVALID_SPEC", "Budget reservations cannot be negative")
        where = and_(t.budgets.c.run_id == run_id, t.budgets.c.category == category)
        old = int(self.c.scalar(select(t.budgets.c.consumed).where(where)) or 0)
        if old + amount > limit:
            raise PlatformError("BUDGET_EXCEEDED", f"{category} budget exhausted ({old}/{limit})")
        statement = insert(t.budgets).values(
            run_id=run_id, category=category, consumed=old + amount
        )
        self.c.execute(
            statement.on_conflict_do_update(
                index_elements=["run_id", "category"], set_={"consumed": old + amount}
            )
        )

    def budget_usage(self, run_id: str) -> dict[str, int]:
        return {
            r.category: r.consumed
            for r in self.c.execute(select(t.budgets).where(t.budgets.c.run_id == run_id))
        }

    def save_artifact(self, artifact: Artifact) -> None:
        self._immutable(
            t.artifacts, {"artifact_id": artifact.artifact_id, "sha256": artifact.sha256}, artifact
        )

    def artifact(self, artifact_id: str) -> Artifact:
        return self._one(t.artifacts, t.artifacts.c.artifact_id == artifact_id, Artifact)

    def save_acquisition(self, version: SourceVersion, derivation: Derivation | None) -> None:
        if derivation:
            self._immutable(
                t.derivations,
                {
                    "derivation_id": derivation.derivation_id,
                    "input_artifact_id": derivation.input_artifact_id,
                    "output_artifact_id": derivation.output_artifact_id,
                },
                derivation,
            )
        self._immutable(
            t.versions,
            dict(
                version_id=version.version_id,
                run_id=version.run_id,
                source_id=version.source_id,
                raw_artifact_id=version.raw_artifact_id,
                extracted_artifact_id=version.extracted_artifact_id,
            ),
            version,
        )

    def versions(self, run_id: str) -> tuple[SourceVersion, ...]:
        return tuple(
            SourceVersion.model_validate_json(v)
            for v in self.c.scalars(
                select(t.versions.c.payload).where(t.versions.c.run_id == run_id)
            )
        )

    def observe(self, run_id: str, observation: Observation) -> None:
        self.c.execute(
            t.observations.insert().values(
                run_id=run_id,
                source_id=observation.source_id,
                payload=canonical(observation).decode(),
            )
        )

    def observations(self, run_id: str) -> tuple[Observation, ...]:
        latest: dict[str, Observation] = {}
        for payload in self.c.scalars(
            select(t.observations.c.payload)
            .where(t.observations.c.run_id == run_id)
            .order_by(t.observations.c.sequence)
        ):
            observation = Observation.model_validate_json(payload)
            latest[observation.source_id] = observation
        return tuple(latest.values())

    def save_evidence(self, evidence: EvidenceSpan) -> None:
        self._immutable(
            t.evidence,
            dict(
                evidence_id=evidence.evidence_id,
                run_id=evidence.run_id,
                version_id=evidence.source_version_id,
                artifact_id=evidence.artifact_id,
            ),
            evidence,
        )

    def evidence(self, run_id: str) -> tuple[EvidenceSpan, ...]:
        return tuple(
            EvidenceSpan.model_validate_json(v)
            for v in self.c.scalars(
                select(t.evidence.c.payload).where(t.evidence.c.run_id == run_id)
            )
        )

    def _save_document(self, run_id: str, kind: str, value: Contract) -> None:
        fp = fingerprint(value)
        self.c.execute(
            insert(t.documents)
            .values(run_id=run_id, kind=kind, fingerprint=fp, payload=canonical(value).decode())
            .on_conflict_do_nothing()
        )
        statement = insert(t.document_heads).values(run_id=run_id, kind=kind, fingerprint=fp)
        self.c.execute(
            statement.on_conflict_do_update(
                index_elements=["run_id", "kind"], set_={"fingerprint": fp}
            )
        )

    def _document(self, run_id: str, kind: str, model: type[T]) -> T | None:
        value = self.c.scalar(
            select(t.documents.c.payload)
            .join(
                t.document_heads,
                and_(
                    t.documents.c.run_id == t.document_heads.c.run_id,
                    t.documents.c.kind == t.document_heads.c.kind,
                    t.documents.c.fingerprint == t.document_heads.c.fingerprint,
                ),
            )
            .where(t.document_heads.c.run_id == run_id, t.document_heads.c.kind == kind)
        )
        return model.model_validate_json(value) if value else None

    def save_context(self, snapshot: ContextSnapshot) -> None:
        self._save_document(snapshot.run_id, "context", snapshot)

    def context(self, run_id: str) -> ContextSnapshot | None:
        return self._document(run_id, "context", ContextSnapshot)

    def save_analysis(self, analysis: AnalysisSubmission) -> None:
        self._save_document(analysis.run_id, "analysis", analysis)
        fp = fingerprint(analysis)
        for claim in analysis.claims:
            for link in claim.evidence_links:
                self.c.execute(
                    insert(t.claim_links)
                    .values(
                        run_id=analysis.run_id,
                        analysis_fingerprint=fp,
                        claim_id=claim.claim_id,
                        evidence_id=link.evidence_id,
                        relation=link.relation,
                    )
                    .on_conflict_do_nothing()
                )

    def analysis(self, run_id: str) -> AnalysisSubmission | None:
        return self._document(run_id, "analysis", AnalysisSubmission)

    def save_verification(self, verification: VerificationSubmission) -> None:
        self._save_document(verification.run_id, "verification", verification)

    def verification(self, run_id: str) -> VerificationSubmission | None:
        return self._document(run_id, "verification", VerificationSubmission)

    def save_review(self, review: ReviewSubmission) -> None:
        self._save_document(review.run_id, "review", review)

    def review(self, run_id: str) -> ReviewSubmission | None:
        return self._document(run_id, "review", ReviewSubmission)

    def save_gates(self, run_id: str, gates: tuple[GateResult, ...], quality: str) -> None:
        self.c.execute(
            t.runs.update()
            .where(t.runs.c.run_id == run_id)
            .values(
                quality=quality,
                gates=canonical([g.model_dump(mode="json") for g in gates]).decode(),
            )
        )

    def set_job_state(self, run_id: str, state: JobState, stage: str, reason: str | None) -> None:
        self.c.execute(
            t.jobs.update()
            .where(t.jobs.c.run_id == run_id)
            .values(state=state, stage=stage, reason=reason, lease_until=None, owner=None)
        )

    def save_delivery(self, delivery: DeliveryRecord) -> None:
        self._immutable(
            t.deliveries,
            dict(
                delivery_id=delivery.delivery_id,
                run_id=delivery.run_id,
                project_id=delivery.project_id,
            ),
            delivery,
        )
        self.c.execute(
            t.runs.update()
            .where(t.runs.c.run_id == delivery.run_id)
            .values(delivery_ref=delivery.relative_path)
        )

    def deliveries(self, project_id: str | None = None) -> tuple[DeliveryRecord, ...]:
        query = select(t.deliveries.c.payload)
        if project_id:
            query = query.where(t.deliveries.c.project_id == project_id)
        values = [DeliveryRecord.model_validate_json(p) for p in self.c.scalars(query)]
        return tuple(sorted(values, key=lambda d: (d.created_at, d.delivery_id)))

    def request_result(self, scope: str, key: str, input_hash: str) -> dict[str, Any] | None:
        r = self.c.execute(
            select(t.requests).where(t.requests.c.scope == scope, t.requests.c.key == key)
        ).first()
        if r is None:
            return None
        if r.input_hash != input_hash:
            raise PlatformError("REVISION_CONFLICT", "Idempotency key reused for different input")
        return dict(json.loads(r.payload))

    def save_request_result(
        self, scope: str, key: str, input_hash: str, result: dict[str, Any]
    ) -> None:
        self.c.execute(
            t.requests.insert().values(
                scope=scope, key=key, input_hash=input_hash, payload=canonical(result).decode()
            )
        )


class Database:
    def __init__(self, path: Path, clock: Callable[[], str]) -> None:
        self.path, self.clock = native_path(path), clock
        if sqlite3.sqlite_version_info < (3, 51, 3):
            raise PlatformError("UNSUPPORTED_RUNTIME", "SQLite >= 3.51.3 required (WAL-reset fix)")
        self.engine = create_engine(
            URL.create("sqlite", database=str(self.path)), connect_args={"timeout": 15}
        )

        @event.listens_for(self.engine, "connect")
        def configure(dbapi: Any, record: Any) -> None:
            dbapi.execute("PRAGMA foreign_keys=ON")
            dbapi.execute("PRAGMA busy_timeout=15000")
            dbapi.execute("PRAGMA synchronous=FULL")

    def migrate(self, migration_directory: Path) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        config = Config()
        config.set_main_option("script_location", str(migration_directory))
        with self.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            connection.commit()
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

    @contextmanager
    def transaction(self, lease: Lease | None = None) -> Iterator[Repository]:
        if not self.path.is_file():
            raise PlatformError("WORKSPACE_NOT_INITIALIZED", "Initialize the workspace first")
        try:
            with self.engine.begin() as c:
                self._check_revision(c)
                if lease:
                    self._fence(c, lease, self.clock())
                yield SqlRepository(c)
        except IntegrityError as exc:
            raise PlatformError(
                "REVISION_CONFLICT", "Concurrent or inconsistent immutable record request"
            ) from exc

    @staticmethod
    def _check_revision(c: Connection) -> str:
        try:
            revision = c.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()
        except DatabaseError as exc:
            raise PlatformError(
                "MIGRATION_REQUIRED",
                "Workspace schema is missing or unreadable; run init to migrate",
            ) from exc
        if revision != "0002":
            raise PlatformError(
                "MIGRATION_REQUIRED", "Workspace schema does not match this application version"
            )
        return str(revision)

    def schema_revision(self) -> str:
        with self.engine.connect() as c:
            return self._check_revision(c)

    @staticmethod
    def _fence(c: Connection, lease: Lease, now: str) -> None:
        result = c.execute(
            t.jobs.update()
            .where(
                t.jobs.c.job_id == lease.job_id,
                t.jobs.c.owner == lease.owner,
                t.jobs.c.token == lease.token,
                t.jobs.c.lease_until > now,
                t.jobs.c.state.in_(["leased", "running"]),
            )
            .values(token=lease.token)
        )
        if result.rowcount != 1:
            raise PlatformError("LEASE_LOST", "Expired, cancelled or superseded worker lease")

    def claim(self, owner: str, now: str, lease_until: str, run_id: str | None = None) -> Lease | None:
        with self.engine.begin() as c:
            self._check_revision(c)
            query = select(t.jobs).where(t.jobs.c.state == "queued")
            if run_id is not None:
                query = query.where(t.jobs.c.run_id == run_id)
            row = c.execute(query.order_by(t.jobs.c.job_id).limit(1)).first()
            if row is None:
                return None
            result = c.execute(
                t.jobs.update()
                .where(
                    t.jobs.c.job_id == row.job_id,
                    t.jobs.c.state == "queued",
                    t.jobs.c.token == row.token,
                )
                .values(
                    state="running",
                    owner=owner,
                    token=row.token + 1,
                    lease_until=lease_until,
                    attempts=row.attempts + 1,
                )
            )
            if result.rowcount != 1:
                return None
            return Lease(job_id=row.job_id, run_id=row.run_id, owner=owner, token=row.token + 1)

    def heartbeat(self, lease: Lease, now: str, lease_until: str) -> None:
        with self.engine.begin() as c:
            self._check_revision(c)
            self._fence(c, lease, now)
            c.execute(
                t.jobs.update()
                .where(t.jobs.c.job_id == lease.job_id)
                .values(lease_until=lease_until)
            )

    def recover(self, now: str) -> int:
        with self.engine.begin() as c:
            self._check_revision(c)
            result = c.execute(
                t.jobs.update()
                .where(t.jobs.c.state.in_(["leased", "running"]), t.jobs.c.lease_until <= now)
                .values(
                    state="queued",
                    owner=None,
                    lease_until=None,
                    reason="Lease expired; resume committed sources",
                )
            )
            c.execute(
                t.jobs.update()
                .where(t.jobs.c.state == "cancel_requested")
                .values(state="cancelled", owner=None, lease_until=None)
            )
            return result.rowcount

    def backup(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise PlatformError("REVISION_CONFLICT", "Backup target already exists")
        with sqlite3.connect(self.path) as source, sqlite3.connect(destination) as target:
            source.backup(target)

    def close(self) -> None:
        self.engine.dispose()
