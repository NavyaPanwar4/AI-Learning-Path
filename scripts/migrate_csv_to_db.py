"""One-time migration: import existing dataset/*.csv rows (and the old
per-user *_roadmap.json cache files under app/data/) into the new DB.

Run once, from the repo root, after pulling this update:

    python scripts/migrate_csv_to_db.py

Safe to re-run — every insert checks for an existing row first, so nothing
is duplicated. Your original CSV files and JSON cache files are left
untouched; delete them yourself once you've confirmed the app works
against the new DB.

NOTE: users.csv, user_skills.csv, and user_feedback.csv are intentionally
NOT present in this repo — an earlier version of this file contained real
registered accounts (emails + bcrypt password hashes), which should never
be committed to a shared repository. The sections below that read those
files degrade gracefully to a no-op when the files are absent, which is
what you want on a fresh setup: only the goal/skill catalog (goals.csv,
skills.csv, goal_skills.csv, skill_dependencies.csv) gets seeded. Don't
re-add real user exports here — if you need to migrate real user data,
do it as a private, untracked local file instead.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from app.utils.config import settings  # noqa: E402
from app.db.database import Base, SessionLocal, engine  # noqa: E402
from app.db import models as m  # noqa: E402

Base.metadata.create_all(bind=engine)


def _read(name: str) -> pd.DataFrame:
    path = os.path.join(settings.DATASET_DIR, name)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return pd.read_csv(path)
    return pd.DataFrame()


def _clean(value, default=""):
    return default if pd.isna(value) else value


def migrate():
    db = SessionLocal()
    try:
        # --- goals ---
        for _, row in _read("goals.csv").iterrows():
            gid = str(row["goal_id"])
            if not db.query(m.Goal).filter(m.Goal.goal_id == gid).first():
                db.add(m.Goal(goal_id=gid, goal_name=_clean(row.get("goal_name"))))
        db.commit()

        # --- skills ---
        for _, row in _read("skills.csv").iterrows():
            sid = str(row["skill_id"])
            if not db.query(m.Skill).filter(m.Skill.skill_id == sid).first():
                db.add(m.Skill(
                    skill_id=sid,
                    skill_name=_clean(row.get("skill_name")),
                    category=_clean(row.get("category")),
                    aliases=str(_clean(row.get("aliases"))),
                ))
        db.commit()

        # --- skill dependencies ---
        # NOTE: the shipped CSV uses "prerequisite_skill_id", not "prerequisite_id"
        # (the app's own csv_handler column list never matched this file, so this
        # join was silently empty before — fixed here).
        for _, row in _read("skill_dependencies.csv").iterrows():
            sid = str(row["skill_id"])
            pid = str(row.get("prerequisite_skill_id", row.get("prerequisite_id")))
            exists = db.query(m.SkillDependency).filter(
                m.SkillDependency.skill_id == sid, m.SkillDependency.prerequisite_id == pid
            ).first()
            if not exists:
                db.add(m.SkillDependency(skill_id=sid, prerequisite_id=pid))
        db.commit()

        # --- goal <-> skill links ---
        # Shipped CSV uses "importance_level" (a category: "core"/"optional"),
        # not a 1-5 "importance" int. Map it onto the same numeric scale the
        # app's schema expects.
        importance_map = {"core": 5, "important": 4, "recommended": 3, "optional": 2}
        for _, row in _read("goal_skills.csv").iterrows():
            gid, sid = str(row["goal_id"]), str(row["skill_id"])
            exists = db.query(m.GoalSkill).filter(
                m.GoalSkill.goal_id == gid, m.GoalSkill.skill_id == sid
            ).first()
            if not exists:
                level = str(_clean(row.get("importance_level"), "")).lower()
                importance = row.get("importance", importance_map.get(level, 3))
                db.add(m.GoalSkill(goal_id=gid, skill_id=sid, importance=int(_clean(importance, 3) or 3)))
        db.commit()

        # --- users ---
        # The shipped CSV mixes real registered accounts (username/email/
        # hashed_password all set) with synthetic seed profiles that have none
        # of those (used only for skill/goal reference data). Blank -> None,
        # not "", so the synthetic rows don't collide on the unique index.
        for _, row in _read("users.csv").iterrows():
            uid = str(_clean(row.get("user_id")))
            if uid and not db.query(m.User).filter(m.User.user_id == uid).first():
                goal_id = _clean(row.get("goal_id"))
                username = _clean(row.get("username")) or None
                email = _clean(row.get("email")) or None
                hashed_password = _clean(row.get("hashed_password")) or None
                db.add(m.User(
                    user_id=uid,
                    username=username,
                    email=email,
                    hashed_password=hashed_password,
                    goal_id=str(goal_id) if goal_id else None,
                    experience_level=_clean(row.get("experience_level")),
                    available_hours_per_week=int(_clean(row.get("available_hours_per_week"), 10) or 10),
                    learning_style=_clean(row.get("learning_style")),
                ))
        db.commit()

        # --- user <-> skill links ---
        # Shipped CSV mostly has "proficiency_level" (a category), not the
        # numeric "proficiency" the app schema expects; map it when the
        # numeric column is blank.
        proficiency_map = {"novice": 1, "beginner": 1, "intermediate": 3, "advanced": 4, "expert": 5}
        for _, row in _read("user_skills.csv").iterrows():
            uid, sid = str(_clean(row.get("user_id"))), str(_clean(row.get("skill_id")))
            if uid and sid:
                exists = db.query(m.UserSkill).filter(
                    m.UserSkill.user_id == uid, m.UserSkill.skill_id == sid
                ).first()
                if not exists:
                    level = str(_clean(row.get("proficiency_level"), "")).lower()
                    proficiency = row.get("proficiency", proficiency_map.get(level, 1))
                    db.add(m.UserSkill(user_id=uid, skill_id=sid, proficiency=int(_clean(proficiency, 1) or 1)))
        db.commit()

        # --- feedback ---
        # The app's live feedback flow (feedback_service.process_feedback) writes
        # feedback_id/content_id/content_type/rating/comments. The shipped CSV
        # also contains a separate batch of resource_id/completed/feedback_text
        # seed rows with no feedback_id — those are a different shape of data
        # (per-resource ratings, not phase/project feedback) and are skipped
        # here rather than guessed at; only rows the app itself produced are
        # migrated.
        skipped_seed_feedback = 0
        for _, row in _read("user_feedback.csv").iterrows():
            fid = _clean(row.get("feedback_id"))
            if not fid:
                skipped_seed_feedback += 1
                continue
            fid = str(fid)
            if not db.query(m.UserFeedback).filter(m.UserFeedback.feedback_id == fid).first():
                db.add(m.UserFeedback(
                    feedback_id=fid,
                    user_id=str(_clean(row.get("user_id"))),
                    content_id=str(_clean(row.get("content_id"))),
                    content_type=str(_clean(row.get("content_type"))),
                    rating=int(_clean(row.get("rating"), 0) or 0),
                    comments=_clean(row.get("comments")),
                ))
        db.commit()
        if skipped_seed_feedback:
            print(
                f"Skipped {skipped_seed_feedback} row(s) in user_feedback.csv that look like "
                "resource-rating seed data (no feedback_id) rather than app-generated feedback."
            )

        # --- old per-user roadmap JSON cache files ---
        data_dir = settings.APP_DATA_DIR
        if os.path.exists(data_dir):
            for filename in os.listdir(data_dir):
                if not filename.endswith("_roadmap.json"):
                    continue
                stem = filename[: -len("_roadmap.json")]
                if "_" not in stem:
                    continue
                user_id, goal_id = stem.split("_", 1)

                if db.query(m.Roadmap).filter(
                    m.Roadmap.user_id == user_id, m.Roadmap.goal_id == goal_id
                ).first():
                    continue

                with open(os.path.join(data_dir, filename)) as f:
                    rdata = json.load(f)

                goal = db.query(m.Goal).filter(m.Goal.goal_id == goal_id).first()
                db.add(m.Roadmap(
                    user_id=user_id,
                    goal_id=goal_id,
                    goal_name=goal.goal_name if goal else "Unknown Goal",
                    data=json.dumps(rdata),
                    is_complete=bool(rdata.get("is_complete", False)),
                ))
            db.commit()

        print("Migration complete.")
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
