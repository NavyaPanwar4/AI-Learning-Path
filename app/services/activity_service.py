from datetime import datetime, timedelta

from app.db.database import SessionLocal
from app.db.models import ActivityLog, QuizAttempt


class ActivityService:
    def log_activity(self, user_id: str, activity_type: str, duration_minutes: float = None) -> None:
        db = SessionLocal()
        try:
            db.add(ActivityLog(user_id=str(user_id), activity_type=activity_type, duration_minutes=duration_minutes))
            db.commit()
        finally:
            db.close()

    def record_quiz_attempt(self, user_id: str, goal_id: str, phase_index: int, total_questions: int, correct_answers: int) -> dict:
        total_questions = max(total_questions, 0)
        correct_answers = max(min(correct_answers, total_questions), 0)
        score_pct = round((correct_answers / total_questions) * 100) if total_questions else 0

        db = SessionLocal()
        try:
            db.add(QuizAttempt(
                user_id=str(user_id),
                goal_id=str(goal_id),
                phase_index=phase_index,
                total_questions=total_questions,
                correct_answers=correct_answers,
                score_pct=score_pct,
            ))
            db.commit()
        finally:
            db.close()

        self.log_activity(user_id, "quiz_attempt")
        return {"score_pct": score_pct}

    def get_stats(self, user_id: str) -> dict:
        db = SessionLocal()
        try:
            logs = db.query(ActivityLog).filter(ActivityLog.user_id == str(user_id)).all()
            attempts = db.query(QuizAttempt).filter(QuizAttempt.user_id == str(user_id)).all()
        finally:
            db.close()

        total_minutes = sum(log.duration_minutes or 0 for log in logs if log.activity_type == "session")
        total_hours = round(total_minutes / 60, 1)

        days_with_activity = {log.created_at.date() for log in logs if log.created_at}
        streak = 0
        cursor = datetime.utcnow().date()
        while cursor in days_with_activity:
            streak += 1
            cursor -= timedelta(days=1)

        practice_questions_solved = sum(a.total_questions for a in attempts)
        average_quiz_score = round(sum(a.score_pct for a in attempts) / len(attempts)) if attempts else None

        return {
            "total_learning_time_hours": total_hours,
            "day_streak": streak,
            "practice_questions_solved": practice_questions_solved,
            "average_quiz_score": average_quiz_score,
        }


activity_service = ActivityService()