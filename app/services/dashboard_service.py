from app.utils.time import utcnow_naive
import json
import random
import re
from datetime import datetime, timedelta

from app.db.database import SessionLocal
from app.db.models import (
    Goal,
    Roadmap,
    Skill,
    User,
    UserSkill,
    GoalUserSkill,
)
from app.services.activity_service import activity_service
from app.services.auth_service import auth_service
from app.services.gap_analysis import gap_analysis_service
from app.services.mastery_decay import decay_mastery, elapsed_days, load_last_reviewed_at_by_skill, normalize_skill_name

# Curated fallback quotes — shown alongside the AI summary. Not LLM-generated
# (keeps this instant and free); rotates by day so it doesn't feel static.
_QUOTES = [
    "Small steps every day lead to big results.",
    "Consistency beats intensity — show up, even briefly.",
    "Every expert was once a beginner who kept going.",
    "Progress, not perfection.",
    "The best time to learn was yesterday. The next best time is now.",
]

_DURATION_RE = re.compile(r"(\d+)\s*(day|week|month)", re.IGNORECASE)
_UNIT_DAYS = {"day": 1, "week": 7, "month": 30}


def _parse_phase_days(duration_str: str) -> int:
    """Best-effort parse of free-text durations like '2 weeks' into days.
    Falls back to a 2-week default when the LLM's phrasing doesn't match."""
    if not duration_str:
        return 14
    match = _DURATION_RE.search(duration_str)
    if not match:
        return 14
    amount, unit = int(match.group(1)), match.group(2).lower()
    return amount * _UNIT_DAYS.get(unit, 7)


class DashboardService:
    def _goal_progress(self, user_id: str) -> list:
        db = SessionLocal()
        try:
            rows = db.query(Roadmap).filter(Roadmap.user_id == str(user_id)).all()
            goals = []
            for row in rows:
                try:
                    data = json.loads(row.data)
                except (json.JSONDecodeError, TypeError):
                    data = {}
                phases = data.get("phases", [])

                total_skills, completed_skills = 0, 0
                total_days = 0
                phases_completed = 0
                for phase in phases:
                    phase_skills = list(dict.fromkeys(phase.get("skills", []) or []))
                    total_skills += len(phase_skills)
                    total_days += _parse_phase_days(phase.get("duration", ""))
                    if phase.get("completed"):
                        completed_skills += len(phase_skills)
                        phases_completed += 1

                progress_pct = round((completed_skills / total_skills) * 100) if total_skills else 0
                started_at = row.created_at
                est_completion = (started_at + timedelta(days=total_days)) if started_at else None

                goals.append({
                    "goal_id": row.goal_id,
                    "goal_name": row.goal_name,
                    "progress_pct": progress_pct,
                    "phases_completed": phases_completed,
                    "phases_total": len(phases),
                    "is_complete": row.is_complete,
                    "started_at": started_at.isoformat() if started_at else None,
                    "estimated_completion": est_completion.isoformat() if est_completion else None,
                    "skills_completed": completed_skills,
                    "skills_total": total_skills,
                })
            return goals
        finally:
            db.close()

    def _skills_mastery(self, user_id: str, goal_id: str | None = None):
        """Return decayed mastery for the requested goal, never global skill mastery."""
        db = SessionLocal()
        try:
            query = (
                db.query(GoalUserSkill, Skill)
                .join(Skill, GoalUserSkill.skill_id == Skill.skill_id)
                .filter(GoalUserSkill.user_id == str(user_id))
            )
            if goal_id is not None:
                query = query.filter(GoalUserSkill.goal_id == str(goal_id))
            rows = query.all()
            goal_ids = {str(goal_skill.goal_id) for goal_skill, _skill in rows}
            last_reviewed_by_goal = {
                gid: load_last_reviewed_at_by_skill(db, str(user_id), gid)
                for gid in goal_ids
            }
            now = utcnow_naive()
            mastery = []
            seen = set()
            for goal_skill, skill in rows:
                key = (str(goal_skill.goal_id), normalize_skill_name(skill.skill_name))
                if key in seen:
                    continue
                seen.add(key)
                probability = goal_skill.mastery_probability
                if probability is None:
                    continue
                last_at = last_reviewed_by_goal.get(key[0], {}).get(key[1])
                effective = decay_mastery(probability, last_at, now=now)
                age = elapsed_days(last_at, now)
                pct = round(max(0.0, min(1.0, effective)) * 100)
                mastery.append({
                    "goal_id": str(goal_skill.goal_id),
                    "skill_name": skill.skill_name,
                    "mastery_pct": pct,
                    "bkt_observations": int(goal_skill.bkt_observations or 0),
                    "last_reviewed_at": last_at.isoformat() if last_at else None,
                    "days_since_review": round(age, 1) if age is not None else None,
                })
            mastery.sort(key=lambda item: item["mastery_pct"], reverse=True)
            return mastery
        finally:
            db.close()

    def get_dashboard(self, user_id: str, tz_offset_minutes: int = 0) -> dict:
        profile = auth_service.get_user_by_id(user_id)
        if not profile:
            raise ValueError("User not found")

        goal_name = None
        if profile.get("goal_id"):
            db = SessionLocal()
            try:
                goal = db.query(Goal).filter(Goal.goal_id == profile["goal_id"]).first()
                goal_name = goal.goal_name if goal else None
            finally:
                db.close()

        skills_mastery = self._skills_mastery(user_id, profile.get("goal_id"))
        strong = [s["skill_name"] for s in skills_mastery if s["mastery_pct"] >= 70][:5]
        needs_improvement = [s["skill_name"] for s in skills_mastery if 30 <= s["mastery_pct"] < 70][:5]

        goals = self._goal_progress(user_id)

        # Only surface "not started" skills once a roadmap actually exists —
        # profile.goal_id gets saved as soon as a goal is picked on the
        # Build Your Learning Plan form, one step before a roadmap is
        # actually generated. Gating on goal_id alone showed a confusing
        # "Not Started: X, Y, Z" list even when Current Learning Goals said
        # "No learning paths yet" for someone who picked a goal but never
        # finished generating a roadmap for it.
        not_started = gap_analysis_service.identify_missing_skills(user_id)[:5] if goals else []

        db = SessionLocal()
        try:
            learning_paths_completed = (
                db.query(Roadmap).filter(Roadmap.user_id == str(user_id), Roadmap.is_complete == True).count()  # noqa: E712
            )
        finally:
            db.close()

        quote = random.choice(_QUOTES)

        activity_stats = activity_service.get_stats(user_id, tz_offset_minutes)
        skills_mastered_count = len([s for s in skills_mastery if s["mastery_pct"] >= 80])
        
        return {
            "profile": {
                "username": profile["username"],
                "email": profile["email"],
                "bio": profile["bio"],
                "title": profile["title"],
                "education": profile["education"],
                "language": profile["language"],
                "avatar_url": profile["avatar_url"],
                "joined_date": profile["created_at"].isoformat() if profile.get("created_at") else None,
            },
            "preferences": {
                "goal_id": profile.get("goal_id"),
                "goal_name": goal_name,
                "experience_level": profile.get("experience_level") or "",
                "available_hours_per_week": profile.get("available_hours_per_week") or 10,
                "learning_style": profile.get("learning_style") or "",
                "session_length": profile.get("session_length") or "",
                "preferred_content": profile.get("preferred_content") or "",
                "learning_pace": profile.get("learning_pace") or "",
                "preferred_difficulty": profile.get("preferred_difficulty") or "",
            },
            "goals": goals,
            "skills_mastery": skills_mastery,
            "skill_buckets": {
                "strong": strong,
                "needs_improvement": needs_improvement,
                "not_started": not_started,
            },
            "quote": quote,
                        "stats": {
                "topics_completed": sum(g["phases_completed"] for g in goals),
                "skills_in_progress": len(skills_mastery) - skills_mastered_count,
                "skills_mastered": skills_mastered_count,
                "learning_paths_completed": learning_paths_completed,
                "total_learning_time_hours": activity_stats["total_learning_time_hours"],
                "average_quiz_score": activity_stats["average_quiz_score"],
                "day_streak": activity_stats["day_streak"],
                "practice_questions_solved": activity_stats["practice_questions_solved"],
            },
        }


dashboard_service = DashboardService()