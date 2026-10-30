"""create server-issued quiz sessions

Revision ID: 2ab74f5e9c10
Revises: 419d5272c9f8
Create Date: 2026-10-22 19:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2ab74f5e9c10"
down_revision: Union[str, Sequence[str], None] = "419d5272c9f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "issued_quizzes",
        sa.Column("quiz_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("goal_id", sa.String(), nullable=False),
        sa.Column("phase_index", sa.Integer(), nullable=False),
        sa.Column("difficulty", sa.String(), nullable=False),
        sa.Column("questions_json", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"]),
        sa.PrimaryKeyConstraint("quiz_id"),
    )
    op.create_index("ix_issued_quizzes_user_id", "issued_quizzes", ["user_id"], unique=False)
    op.create_index("ix_issued_quizzes_goal_id", "issued_quizzes", ["goal_id"], unique=False)
    op.create_index("ix_issued_quizzes_expires_at", "issued_quizzes", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_issued_quizzes_expires_at", table_name="issued_quizzes")
    op.drop_index("ix_issued_quizzes_goal_id", table_name="issued_quizzes")
    op.drop_index("ix_issued_quizzes_user_id", table_name="issued_quizzes")
    op.drop_table("issued_quizzes")
