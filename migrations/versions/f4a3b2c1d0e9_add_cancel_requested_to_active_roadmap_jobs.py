"""Keep cancellation-requested roadmap jobs unique until the worker stops.

Revision ID: f4a3b2c1d0e9
Revises: e17f4d8b2a91
Create Date: 2026-11-01
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "f4a3b2c1d0e9"
down_revision: Union[str, Sequence[str], None] = "e17f4d8b2a91"
branch_labels = None
depends_on = None

_NEW_PREDICATE = sa.text("goal_id IS NOT NULL AND status IN ('queued', 'running', 'cancel_requested')")
_OLD_PREDICATE = sa.text("goal_id IS NOT NULL AND status IN ('queued', 'running')")


def upgrade() -> None:
    op.drop_index("uq_active_roadmap_job_user_goal", table_name="roadmap_generation_jobs")
    op.create_index(
        "uq_active_roadmap_job_user_goal",
        "roadmap_generation_jobs",
        ["user_id", "goal_id"],
        unique=True,
        sqlite_where=_NEW_PREDICATE,
        postgresql_where=_NEW_PREDICATE,
    )


def downgrade() -> None:
    op.drop_index("uq_active_roadmap_job_user_goal", table_name="roadmap_generation_jobs")
    op.create_index(
        "uq_active_roadmap_job_user_goal",
        "roadmap_generation_jobs",
        ["user_id", "goal_id"],
        unique=True,
        sqlite_where=_OLD_PREDICATE,
        postgresql_where=_OLD_PREDICATE,
    )
