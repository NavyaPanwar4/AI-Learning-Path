"""Prevent more than one active roadmap generation job per user and goal.

Revision ID: e17f4d8b2a91
Revises: c8d91a4e7f32
Create Date: 2026-11-01
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "e17f4d8b2a91"
down_revision: Union[str, Sequence[str], None] = "c8d91a4e7f32"
branch_labels = None
depends_on = None

_ACTIVE_JOB_PREDICATE = sa.text("goal_id IS NOT NULL AND status IN ('queued', 'running')")


def upgrade() -> None:
    op.create_index(
        "uq_active_roadmap_job_user_goal",
        "roadmap_generation_jobs",
        ["user_id", "goal_id"],
        unique=True,
        sqlite_where=_ACTIVE_JOB_PREDICATE,
        postgresql_where=_ACTIVE_JOB_PREDICATE,
    )


def downgrade() -> None:
    op.drop_index("uq_active_roadmap_job_user_goal", table_name="roadmap_generation_jobs")
