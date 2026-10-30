"""Opt-in public progress page. Exposes only safe aggregates, never email or ids."""
import json
import secrets

from app.db.database import SessionLocal
from app.db.models import GoalUserSkill, QuizAttempt, Roadmap, ShareLink, User
from app.services.activity_service import activity_service
from app.utils.time import utcnow_naive

MASTERED_AT = 0.8  # same 80% line the dashboard uses


class ShareService:
    def _active(self, db, user_id, goal_id):
        return db.query(ShareLink).filter(
            ShareLink.user_id == str(user_id), ShareLink.goal_id == str(goal_id), ShareLink.revoked_at.is_(None)
        ).first()

    def get_link(self, user_id, goal_id):
        db = SessionLocal()
        try:
            link = self._active(db, user_id, goal_id)
            return {"token": link.token if link else None}
        finally:
            db.close()

    def create_link(self, user_id, goal_id):
        """Return the active link for this goal, creating one if needed. None if no roadmap."""
        db = SessionLocal()
        try:
            if not db.query(Roadmap).filter(Roadmap.user_id == str(user_id), Roadmap.goal_id == str(goal_id)).first():
                return None
            link = self._active(db, user_id, goal_id)
            if not link:
                link = ShareLink(user_id=str(user_id), goal_id=str(goal_id), token=secrets.token_urlsafe(16))
                db.add(link)
                db.commit()
            return {"token": link.token}
        finally:
            db.close()

    def revoke_link(self, user_id, goal_id) -> bool:
        db = SessionLocal()
        try:
            link = self._active(db, user_id, goal_id)
            if not link:
                return False
            link.revoked_at = utcnow_naive()
            db.commit()
            return True
        finally:
            db.close()

    def public_view(self, token):
        """Safe progress summary for a token, or None if unknown/revoked."""
        db = SessionLocal()
        try:
            link = db.query(ShareLink).filter(ShareLink.token == token, ShareLink.revoked_at.is_(None)).first()
            if not link:
                return None
            user = db.query(User).filter(User.user_id == link.user_id).first()
            roadmap = db.query(Roadmap).filter(Roadmap.user_id == link.user_id, Roadmap.goal_id == link.goal_id).first()
            if not user or not roadmap:
                return None
            phases = json.loads(roadmap.data).get("phases", [])
            done = sum(1 for p in phases if p.get("completed"))
            attempts = db.query(QuizAttempt).filter(QuizAttempt.user_id == link.user_id, QuizAttempt.goal_id == link.goal_id).all()
            mastered = db.query(GoalUserSkill).filter(
                GoalUserSkill.user_id == link.user_id, GoalUserSkill.goal_id == link.goal_id,
                GoalUserSkill.mastery_probability >= MASTERED_AT, GoalUserSkill.bkt_observations > 0,
            ).count()
            name = user.username or "A learner"
            goal_name = roadmap.goal_name
            user_id = link.user_id
        finally:
            db.close()
        stats = activity_service.get_stats(user_id)
        return {
            "learner": name,
            "goal_name": goal_name,
            "phases": [{"title": p.get("title", ""), "completed": bool(p.get("completed"))} for p in phases],
            "phases_completed": done,
            "phases_total": len(phases),
            "progress_pct": round(100 * done / len(phases)) if phases else 0,
            "skills_mastered": mastered,
            "quizzes_taken": len(attempts),
            "average_quiz_score": round(sum(a.score_pct for a in attempts) / len(attempts)) if attempts else None,
            "day_streak": stats["day_streak"],
            "longest_streak": stats["longest_streak"],
        }


share_service = ShareService()
