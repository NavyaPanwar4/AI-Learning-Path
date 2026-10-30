"""Add per-goal learner mastery state for BKT.

Revision ID: a31bc8d91e72
Revises: 2ab74f5e9c10
Create Date: 2026-10-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a31bc8d91e72"
down_revision: Union[str, Sequence[str], None] = "2ab74f5e9c10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "goal_user_skills",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("goal_id", sa.String(), nullable=False),
        sa.Column("skill_id", sa.String(), nullable=False),
        sa.Column("proficiency", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("mastery_probability", sa.Float(), nullable=False, server_default="0.2"),
        sa.Column("bkt_observations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.skill_id"]),
        sa.PrimaryKeyConstraint("user_id", "goal_id", "skill_id"),
    )


def downgrade() -> None:
    op.drop_table("goal_user_skills")
