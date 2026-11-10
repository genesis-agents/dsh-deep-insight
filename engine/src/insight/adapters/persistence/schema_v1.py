"""Frozen migration-0001 schema. Add later migrations instead of changing this definition."""

from sqlalchemy import (
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

metadata = MetaData()
projects = Table(
    "project_revisions",
    metadata,
    Column("project_id", String, primary_key=True),
    Column("revision", Integer, primary_key=True),
    Column("payload", Text, nullable=False),
)
sources = Table(
    "sources",
    metadata,
    Column("source_id", String, primary_key=True),
    Column("payload", Text, nullable=False),
)
plans = Table(
    "source_plans",
    metadata,
    Column("plan_id", String, primary_key=True),
    Column("project_id", String, nullable=False),
    Column("project_revision", Integer, nullable=False),
    Column("payload", Text, nullable=False),
    ForeignKeyConstraint(
        ["project_id", "project_revision"],
        ["project_revisions.project_id", "project_revisions.revision"],
    ),
)
runs = Table(
    "research_runs",
    metadata,
    Column("run_id", String, primary_key=True),
    Column("project_id", String, nullable=False),
    Column("project_revision", Integer, nullable=False),
    Column("plan_id", ForeignKey("source_plans.plan_id"), nullable=False),
    Column("frozen_input", Text, nullable=False),
    Column("created_at", String, nullable=False),
    Column("quality", String, nullable=False, server_default="draft"),
    Column("gates", Text, nullable=False, server_default="[]"),
    Column("delivery_ref", Text),
    ForeignKeyConstraint(
        ["project_id", "project_revision"],
        ["project_revisions.project_id", "project_revisions.revision"],
    ),
)
jobs = Table(
    "jobs",
    metadata,
    Column("job_id", String, primary_key=True),
    Column("run_id", ForeignKey("research_runs.run_id"), unique=True, nullable=False),
    Column("state", String, nullable=False),
    Column("stage", String, nullable=False),
    Column("owner", String),
    Column("token", Integer, nullable=False, server_default="0"),
    Column("lease_until", String),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("reason", Text),
)
artifacts = Table(
    "artifacts",
    metadata,
    Column("artifact_id", String, primary_key=True),
    Column("sha256", String, nullable=False),
    Column("payload", Text, nullable=False),
)
versions = Table(
    "source_versions",
    metadata,
    Column("version_id", String, primary_key=True),
    Column("run_id", ForeignKey("research_runs.run_id"), nullable=False),
    Column("source_id", ForeignKey("sources.source_id"), nullable=False),
    Column("raw_artifact_id", ForeignKey("artifacts.artifact_id"), nullable=False),
    Column("extracted_artifact_id", ForeignKey("artifacts.artifact_id")),
    Column("payload", Text, nullable=False),
)
derivations = Table(
    "derivations",
    metadata,
    Column("derivation_id", String, primary_key=True),
    Column("input_artifact_id", ForeignKey("artifacts.artifact_id"), nullable=False),
    Column("output_artifact_id", ForeignKey("artifacts.artifact_id"), nullable=False),
    Column("payload", Text, nullable=False),
)
observations = Table(
    "acquisition_observations",
    metadata,
    Column("sequence", Integer, primary_key=True),
    Column("run_id", ForeignKey("research_runs.run_id"), nullable=False),
    Column("source_id", ForeignKey("sources.source_id"), nullable=False),
    Column("payload", Text, nullable=False),
)
evidence = Table(
    "evidence_spans",
    metadata,
    Column("evidence_id", String, primary_key=True),
    Column("run_id", ForeignKey("research_runs.run_id"), nullable=False),
    Column("version_id", ForeignKey("source_versions.version_id"), nullable=False),
    Column("artifact_id", ForeignKey("artifacts.artifact_id"), nullable=False),
    Column("payload", Text, nullable=False),
)
documents = Table(
    "research_documents",
    metadata,
    Column("sequence", Integer, primary_key=True),
    Column("run_id", ForeignKey("research_runs.run_id"), nullable=False),
    Column("kind", String, nullable=False),
    Column("fingerprint", String, nullable=False),
    Column("payload", Text, nullable=False),
    UniqueConstraint("run_id", "kind", "fingerprint"),
)
document_heads = Table(
    "research_document_heads",
    metadata,
    Column("run_id", String, primary_key=True),
    Column("kind", String, primary_key=True),
    Column("fingerprint", String, nullable=False),
    ForeignKeyConstraint(
        ["run_id", "kind", "fingerprint"],
        ["research_documents.run_id", "research_documents.kind", "research_documents.fingerprint"],
    ),
)
claim_links = Table(
    "claim_evidence_links",
    metadata,
    Column("run_id", ForeignKey("research_runs.run_id"), primary_key=True),
    Column("analysis_fingerprint", String, primary_key=True),
    Column("claim_id", String, primary_key=True),
    Column("evidence_id", ForeignKey("evidence_spans.evidence_id"), primary_key=True),
    Column("relation", String, primary_key=True),
)
deliveries = Table(
    "deliveries",
    metadata,
    Column("delivery_id", String, primary_key=True),
    Column("run_id", ForeignKey("research_runs.run_id"), nullable=False),
    Column("project_id", String, nullable=False),
    Column("payload", Text, nullable=False),
)
events = Table(
    "audit_events",
    metadata,
    Column("sequence", Integer, primary_key=True),
    Column("run_id", ForeignKey("research_runs.run_id"), nullable=False),
    Column("kind", String, nullable=False),
    Column("at", String, nullable=False),
    Column("payload", Text, nullable=False),
)
budgets = Table(
    "budget_ledger",
    metadata,
    Column("run_id", ForeignKey("research_runs.run_id"), primary_key=True),
    Column("category", String, primary_key=True),
    Column("consumed", Integer, nullable=False),
)
requests = Table(
    "idempotent_requests",
    metadata,
    Column("scope", String, primary_key=True),
    Column("key", String, primary_key=True),
    Column("input_hash", String, nullable=False),
    Column("payload", Text, nullable=False),
)
