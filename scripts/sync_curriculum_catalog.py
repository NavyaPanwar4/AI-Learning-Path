"""Synchronize seeded curriculum mappings and prerequisite edges from CSV.

Run after updating dataset/goal_skills.csv and dataset/skill_dependencies.csv:
    python scripts/sync_curriculum_catalog.py

This updates catalog relationship tables only. It does not delete users,
user skill/mastery records, roadmaps, quiz attempts, or learning history.
Custom goal mappings are preserved; only the seeded goal IDs in goals.csv are
replaced, and only dependency edges touching seeded numeric skills are rebuilt.
"""
from __future__ import annotations

import csv
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import or_  # noqa: E402

from app.db.database import SessionLocal  # noqa: E402
from app.db.models import Goal, GoalSkill, Skill, SkillDependency  # noqa: E402
from app.utils.config import settings  # noqa: E402


def normalize_id(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"[+-]?\d+\.0+", text):
        return str(int(float(text)))
    return text


def read_csv(name: str) -> list[dict[str, str]]:
    path = Path(settings.DATASET_DIR) / name
    if not path.exists():
        raise FileNotFoundError(f"Required catalog file not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sync() -> None:
    goals = read_csv("goals.csv")
    skills = read_csv("skills.csv")
    goal_skill_rows = read_csv("goal_skills.csv")
    dependency_rows = read_csv("skill_dependencies.csv")

    seeded_goal_ids = {normalize_id(row.get("goal_id")) for row in goals}
    seeded_goal_ids.discard(None)
    seeded_skill_ids = {normalize_id(row.get("skill_id")) for row in skills}
    seeded_skill_ids.discard(None)
    # The bundled prerequisite graph is defined for numeric seeded catalog IDs.
    seeded_numeric_skill_ids = {sid for sid in seeded_skill_ids if sid.isdigit()}

    cleaned_goal_skills = []
    for row in goal_skill_rows:
        goal_id = normalize_id(row.get("goal_id"))
        skill_id = normalize_id(row.get("skill_id"))
        if not goal_id or not skill_id:
            continue
        if goal_id not in seeded_goal_ids or skill_id not in seeded_skill_ids:
            raise ValueError(
                f"goal_skills.csv has an unknown seeded reference: {goal_id} -> {skill_id}"
            )
        cleaned_goal_skills.append((goal_id, skill_id, row.get("importance_level", "core")))

    cleaned_dependencies = set()
    for row in dependency_rows:
        skill_id = normalize_id(row.get("skill_id"))
        prerequisite_id = normalize_id(
            row.get("prerequisite_skill_id") or row.get("prerequisite_id")
        )
        if not skill_id or not prerequisite_id:
            continue
        if skill_id not in seeded_numeric_skill_ids or prerequisite_id not in seeded_numeric_skill_ids:
            raise ValueError(
                "skill_dependencies.csv must reference known numeric seeded skills: "
                f"{skill_id} -> {prerequisite_id}"
            )
        if skill_id == prerequisite_id:
            raise ValueError(f"Self-dependency is invalid: {skill_id}")
        cleaned_dependencies.add((skill_id, prerequisite_id))

    db = SessionLocal()
    try:
        db_goals = {str(row.goal_id) for row in db.query(Goal).all()}
        db_skills = {str(row.skill_id) for row in db.query(Skill).all()}
        missing_goals = sorted(seeded_goal_ids - db_goals)
        missing_skills = sorted(seeded_skill_ids - db_skills)
        if missing_goals or missing_skills:
            raise RuntimeError(
                "The database is missing seeded catalog rows. Run "
                "`python scripts/migrate_csv_to_db.py` first. "
                f"Missing goals: {missing_goals[:10]}; missing skills: {missing_skills[:10]}"
            )

        # Replace seeded goal mappings exactly; preserve custom goal mappings.
        db.query(GoalSkill).filter(GoalSkill.goal_id.in_(seeded_goal_ids)).delete(
            synchronize_session=False
        )
        importance_map = {"core": 5, "important": 4, "recommended": 3, "optional": 2}
        for goal_id, skill_id, importance_label in cleaned_goal_skills:
            importance = importance_map.get(str(importance_label or "core").strip().lower(), 5)
            db.add(GoalSkill(goal_id=goal_id, skill_id=skill_id, importance=importance))

        # Remove the old noisy graph for bundled numeric skill IDs, including
        # old edges that are absent from the corrected CSV. Preserve edges that
        # connect only custom/extracted UUID skills.
        db.query(SkillDependency).filter(
            or_(
                SkillDependency.skill_id.in_(seeded_numeric_skill_ids),
                SkillDependency.prerequisite_id.in_(seeded_numeric_skill_ids),
            )
        ).delete(synchronize_session=False)
        for skill_id, prerequisite_id in sorted(
            cleaned_dependencies, key=lambda pair: (int(pair[0]), int(pair[1]))
        ):
            db.add(
                SkillDependency(skill_id=skill_id, prerequisite_id=prerequisite_id)
            )

        db.commit()
        print("Curriculum catalog synchronized successfully.")
        print(f"Seeded goal-skill mappings: {len(cleaned_goal_skills)}")
        print(f"Seeded prerequisite edges: {len(cleaned_dependencies)}")
        print("Users, user skills/mastery, saved roadmaps and learning history were not modified.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sync()
