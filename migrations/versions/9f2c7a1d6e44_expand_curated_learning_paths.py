"""Expand curated learning paths with missing core skills.

Revision ID: 9f2c7a1d6e44
Revises: f4a3b2c1d0e9
Create Date: 2026-11-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "9f2c7a1d6e44"
down_revision: Union[str, Sequence[str], None] = "f4a3b2c1d0e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO skills (skill_id, skill_name, category, aliases) "
            "SELECT :skill_id, :skill_name, :category, :aliases "
            "WHERE NOT EXISTS (SELECT 1 FROM skills WHERE skill_id = :skill_id)"
        ),
        {
            "skill_id": "166",
            "skill_name": "Excel and Spreadsheet Analysis",
            "category": "Data Analytics",
            "aliases": "excel,spreadsheets,google-sheets",
        },
    )
    for goal_id, skill_id in (
        ("6", "18"), ("6", "79"),
        ("11", "35"), ("11", "14"), ("11", "8"),
        ("12", "94"), ("12", "99"),
        ("13", "120"),
        ("14", "18"), ("14", "92"),
        ("15", "60"),
        ("16", "9"), ("16", "14"),
        ("17", "122"), ("17", "103"),
        ("18", "10"), ("18", "118"), ("18", "122"),
        ("20", "28"), ("20", "14"),
        ("22", "18"), ("22", "98"),
        ("24", "1"), ("24", "15"), ("24", "166"),
    ):
        bind.execute(
            sa.text(
                "INSERT INTO goal_skills (goal_id, skill_id, importance) "
                "SELECT :goal_id, :skill_id, 5 "
                "WHERE NOT EXISTS (SELECT 1 FROM goal_skills "
                "WHERE goal_id = :goal_id AND skill_id = :skill_id)"
            ),
            {"goal_id": goal_id, "skill_id": skill_id},
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM goal_skills WHERE "
            "(goal_id, skill_id) IN "
            "((6, '18'), (6, '79'), (11, '35'), (11, '14'), (11, '8'), "
            "(12, '94'), (12, '99'), (13, '120'), (14, '18'), (14, '92'), "
            "(15, '60'), (16, '9'), (16, '14'), (17, '122'), (17, '103'), "
            "(18, '10'), (18, '118'), (18, '122'), (20, '28'), (20, '14'), "
            "(22, '18'), (22, '98'), (24, '1'), (24, '15'), (24, '166'))"
        )
    )
    op.execute(sa.text("DELETE FROM skills WHERE skill_id = '166'"))
