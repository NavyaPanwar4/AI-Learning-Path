"""Add explicit statistics coverage to the Data Analyst curriculum.

Revision ID: d8a5c2e7f104
Revises: c7e4a1b9d203
Create Date: 2026-11-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d8a5c2e7f104"
down_revision: Union[str, Sequence[str], None] = "c7e4a1b9d203"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO goal_skills (goal_id, skill_id, importance) "
            "SELECT '24', '129', 5 WHERE NOT EXISTS "
            "(SELECT 1 FROM goal_skills WHERE goal_id = '24' AND skill_id = '129')"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM goal_skills WHERE goal_id = '24' AND skill_id = '129'")
    )
