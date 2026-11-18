"""Add mastery-verification state and quiz metadata.

Revision ID: c8d91a4e7f32
Revises: b52e07a9c4d1
Create Date: 2026-11-01
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "c8d91a4e7f32"
down_revision: Union[str, Sequence[str], None] = "b52e07a9c4d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("goal_user_skills") as batch:
        batch.add_column(sa.Column("verification_status", sa.String(length=20), nullable=False, server_default="unverified"))
        batch.add_column(sa.Column("verification_attempts", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("last_verification_score", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("verified_at", sa.DateTime(), nullable=True))
    with op.batch_alter_table("issued_quizzes") as batch:
        batch.add_column(sa.Column("quiz_type", sa.String(length=30), nullable=False, server_default="phase"))
        batch.add_column(sa.Column("skill_id", sa.String(), nullable=True))
        batch.create_foreign_key("fk_issued_quizzes_skill_id_skills", "skills", ["skill_id"], ["skill_id"])
        batch.create_index("ix_issued_quizzes_skill_id", ["skill_id"])


def downgrade() -> None:
    with op.batch_alter_table("issued_quizzes") as batch:
        batch.drop_index("ix_issued_quizzes_skill_id")
        batch.drop_constraint("fk_issued_quizzes_skill_id_skills", type_="foreignkey")
        batch.drop_column("skill_id")
        batch.drop_column("quiz_type")
    with op.batch_alter_table("goal_user_skills") as batch:
        batch.drop_column("verified_at")
        batch.drop_column("last_verification_score")
        batch.drop_column("verification_attempts")
        batch.drop_column("verification_status")
