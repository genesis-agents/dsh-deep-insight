"""Versioned research-bound presentations."""

from alembic import op

from insight.adapters.persistence.schema_v2 import publications

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    publications.create(op.get_bind())


def downgrade() -> None:
    publications.drop(op.get_bind())
