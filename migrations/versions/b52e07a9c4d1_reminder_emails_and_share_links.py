"""Add email-reminder opt-in, reminder emailed_at, and share_links.

Revision ID: b52e07a9c4d1
Revises: a31bc8d91e72
Create Date: 2026-10-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b52e07a9c4d1"
down_revision: Union[str, Sequence[str], None] = "a31bc8d91e72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("email_reminders", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("study_reminders") as batch:
        batch.add_column(sa.Column("emailed_at", sa.DateTime(), nullable=True))
    op.create_table(
        "share_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("goal_id", sa.String(), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"]),
    )
    op.create_index("ix_share_links_user_id", "share_links", ["user_id"])
    op.create_index("ix_share_links_token", "share_links", ["token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_share_links_token", table_name="share_links")
    op.drop_index("ix_share_links_user_id", table_name="share_links")
    op.drop_table("share_links")
    with op.batch_alter_table("study_reminders") as batch:
        batch.drop_column("emailed_at")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("email_reminders")
