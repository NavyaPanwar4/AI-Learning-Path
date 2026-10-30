"""Read-only activity summaries used by the Overview dashboard.

All queries are scoped to the authenticated user. Database timestamps in the
current schema are naive UTC, so this service compares against naive UTC bounds
without altering the existing schema.
"""
from datetime import datetime, time, timedelta, timezone

from app.db.database import SessionLocal
from app.db.models import ActivityLog, QuizAttempt, Roadmap


_ACTIVITY_LABELS = {
    "session": "Study session logged",
    "roadmap_generated": "Learning path created",
    "roadmap_completed": "Learning path completed",
    "phase_completed": "Learning phase completed",
    "study_notes": "Study notes generated",
}


class DashboardActivityService:
    def get_summary(self, user_id: str) -> dict:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        today = now.date()
        start_day = today - timedelta(days=6)
        start_at = datetime.combine(start_day, time.min)
        end_at = datetime.combine(today + timedelta(days=1), time.min)

        db = SessionLocal()
        try:
            logs = (
                db.query(ActivityLog)
                .filter(
                    ActivityLog.user_id == str(user_id),
                    ActivityLog.created_at >= start_at,
                    ActivityLog.created_at < end_at,
                )
                .order_by(ActivityLog.created_at.desc())
                .all()
            )
            attempts = (
                db.query(QuizAttempt)
                .filter(
                    QuizAttempt.user_id == str(user_id),
                    QuizAttempt.created_at >= start_at,
                    QuizAttempt.created_at < end_at,
                )
                .order_by(QuizAttempt.created_at.desc())
                .all()
            )
            roadmaps = db.query(Roadmap).filter(Roadmap.user_id == str(user_id)).all()
            goal_names = {str(row.goal_id): row.goal_name for row in roadmaps}

            weekly_activity = []
            for offset in range(7):
                day = start_day + timedelta(days=offset)
                day_logs = [row for row in logs if row.created_at and row.created_at.date() == day]
                day_attempts = [row for row in attempts if row.created_at and row.created_at.date() == day]
                session_logs = [row for row in day_logs if row.activity_type == "session"]
                # QuizAttempt is the source of truth for quizzes. Ignore its
                # companion ActivityLog to avoid counting a quiz twice.
                other_events = [row for row in day_logs if row.activity_type not in {"session", "quiz_attempt"}]
                minutes = round(sum(float(row.duration_minutes or 0) for row in session_logs))
                activity_count = len(session_logs) + len(other_events) + len(day_attempts)
                weekly_activity.append({
                    "date": day.isoformat(),
                    "label": day.strftime("%a"),
                    "minutes": minutes,
                    "sessions": len(session_logs),
                    "quizzes": len(day_attempts),
                    "activity_count": activity_count,
                })

            # The weekly chart is limited to seven days, but the recent feed
            # should still be useful when the learner has not studied this week.
            recent_logs = (
                db.query(ActivityLog)
                .filter(ActivityLog.user_id == str(user_id))
                .order_by(ActivityLog.created_at.desc())
                .limit(20)
                .all()
            )
            recent_attempts = (
                db.query(QuizAttempt)
                .filter(QuizAttempt.user_id == str(user_id))
                .order_by(QuizAttempt.created_at.desc())
                .limit(20)
                .all()
            )
            recent = []
            for row in recent_logs:
                if row.activity_type == "quiz_attempt":
                    continue
                kind = row.activity_type or "activity"
                title = _ACTIVITY_LABELS.get(kind, kind.replace("_", " ").capitalize())
                if kind == "session":
                    duration = round(float(row.duration_minutes or 0))
                    detail = f"{duration} minutes recorded" if duration else "Study time recorded"
                elif kind == "roadmap_generated":
                    detail = "Your learning path is ready to continue"
                elif kind == "roadmap_completed":
                    detail = "You completed a learning path"
                elif kind == "phase_completed":
                    detail = "Progress saved to your learning path"
                elif kind == "study_notes":
                    detail = "New study notes were generated"
                else:
                    detail = "Learning activity recorded"
                recent.append({
                    "id": f"activity-{row.id}",
                    "type": kind,
                    "title": title,
                    "detail": detail,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "goal_id": None,
                    "goal_name": None,
                })

            for row in recent_attempts:
                score = int(row.score_pct or 0)
                correct = int(row.correct_answers or 0)
                total = int(row.total_questions or 0)
                goal_id = str(row.goal_id)
                recent.append({
                    "id": f"quiz-{row.id}",
                    "type": "quiz",
                    "title": "Quiz completed",
                    "detail": f"{correct} of {total} questions correct · {score}% score",
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "goal_id": goal_id,
                    "goal_name": goal_names.get(goal_id),
                })

            recent.sort(key=lambda item: item["created_at"] or "", reverse=True)
            recent = recent[:6]
            weekly_minutes = sum(item["minutes"] for item in weekly_activity)
            weekly_totals = {
                "minutes": weekly_minutes,
                "sessions": sum(item["sessions"] for item in weekly_activity),
                "quizzes": sum(item["quizzes"] for item in weekly_activity),
                "activity_count": sum(item["activity_count"] for item in weekly_activity),
            }
            return {
                "weekly_activity": weekly_activity,
                "weekly_totals": weekly_totals,
                "recent_activity": recent,
            }
        finally:
            db.close()


dashboard_activity_service = DashboardActivityService()
