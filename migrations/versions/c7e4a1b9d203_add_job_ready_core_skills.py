"""Add job-ready skills to priority curricula.

Revision ID: c7e4a1b9d203
Revises: 9f2c7a1d6e44
Create Date: 2026-11-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c7e4a1b9d203"
down_revision: Union[str, Sequence[str], None] = "9f2c7a1d6e44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SKILLS = (
    ("167", "KPI and Business Requirements", "Data Analytics", "kpi,business-analysis,requirements"),
    ("168", "Data Modeling and Warehousing", "Data Engineering", "data-modeling,data-warehouse"),
    ("169", "Workflow Orchestration", "Data Engineering", "airflow,orchestration"),
    ("170", "Experiment Tracking and Reproducibility", "Artificial Intelligence", "mlflow,experiment-tracking"),
    ("171", "Feature Stores and Model Serving", "Artificial Intelligence", "feature-store,model-serving"),
    ("172", "Linux and Endpoint Security", "Cybersecurity", "linux,endpoint-security"),
    ("173", "Financial Markets and Portfolio Management", "Finance", "quantitative-finance,portfolio"),
    ("174", "NLP Preprocessing and Information Retrieval", "Artificial Intelligence", "nlp-preprocessing,information-retrieval"),
    ("175", "Image Processing and Dataset Curation", "Artificial Intelligence", "image-processing,data-labeling"),
    ("176", "Product Discovery and Prioritization", "Product Management", "product-discovery,prioritization"),
)

GOAL_SKILLS = (
    ("10", "173"), ("11", "170"), ("11", "171"),
    ("13", "172"), ("13", "112"), ("14", "168"), ("14", "169"),
    ("15", "174"), ("20", "175"), ("21", "176"),
    ("22", "168"), ("24", "167"),
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM goal_skills WHERE goal_id = '11' AND skill_id = '8'")
    )
    for skill_id, name, category, aliases in SKILLS:
        bind.execute(
            sa.text(
                "INSERT INTO skills (skill_id, skill_name, category, aliases) "
                "SELECT :skill_id, :name, :category, :aliases "
                "WHERE NOT EXISTS (SELECT 1 FROM skills WHERE skill_id = :skill_id)"
            ),
            {"skill_id": skill_id, "name": name, "category": category, "aliases": aliases},
        )
    for goal_id, skill_id in GOAL_SKILLS:
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
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO goal_skills (goal_id, skill_id, importance) "
            "SELECT '11', '8', 5 WHERE NOT EXISTS "
            "(SELECT 1 FROM goal_skills WHERE goal_id = '11' AND skill_id = '8')"
        )
    )
    for goal_id, skill_id in GOAL_SKILLS:
        bind.execute(
            sa.text("DELETE FROM goal_skills WHERE goal_id = :goal_id AND skill_id = :skill_id"),
            {"goal_id": goal_id, "skill_id": skill_id},
        )
    for skill_id, *_ in SKILLS:
        bind.execute(sa.text("DELETE FROM skills WHERE skill_id = :skill_id"), {"skill_id": skill_id})
