"""Additive schema 0002; the initial schema remains frozen."""

from sqlalchemy import Column, ForeignKey, MetaData, String, Table, Text

from insight.adapters.persistence.schema_v1 import runs

metadata = MetaData()
runs.to_metadata(metadata)
publications = Table(
    "publications",
    metadata,
    Column("publication_id", String, primary_key=True),
    Column("run_id", ForeignKey("research_runs.run_id"), nullable=False),
    Column("project_id", String, nullable=False),
    Column("payload", Text, nullable=False),
)
