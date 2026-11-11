"""Baseline schema: creates every table from the current models.

Revision ID: 0001
Revises:
Later schema changes must be separate revisions:  alembic revision --autogenerate -m "..."
"""
from alembic import op

from backend.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
