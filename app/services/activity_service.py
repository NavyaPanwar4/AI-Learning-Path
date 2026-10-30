from app.utils.time import utcnow_naive
from datetime import datetime, timedelta

from app.db.database import SessionLocal
from app.db.models import ActivityLog, QuizAttempt, QuizQuestionHistory
from app.services.mastery_decay import load_last_reviewed_at_by_skill, normalize_skill_name
from app.services.mastery_decay import load_last_reviewed_at_by_skill


class ActivityService:
    def log_activity(self, user_id: str, activity_type: str, duration_minutes: float = None) -> None:
        db = SessionLocal()
        try:
            db.add(ActivityLog(user_id=str(user_id), activity_type=activity_type, duration_minutes=duration_minutes))
            db.commit()
        finally:
            db.close()

    def record_quiz_attempt(
        self,
        user_id: str,
        goal_id: str,
        phase_index: int,
        total_questions: int,
        correct_answers: int,
        skill_names=None,
        question_results=None,
        db=None,
        phase_id=None,
    ) -> dict:
        """Persist verified quiz results and BKT updates.

        When `db` is supplied, the caller owns the transaction. This lets the
        issued-quiz one-time submission flag and the resulting score/mastery
        update commit or roll back together.
        """
        score_pct = round((correct_answers / total_questions) * 100) if total_questions else 0
        owns_session = db is None
        db = db or SessionLocal()

        try:
            # Snapshot this goal's prior evidence before the current attempt is added.
            last_reviewed_at_by_skill = load_last_reviewed_at_by_skill(db, str(user_id), str(goal_id))
            attempt = QuizAttempt(
                user_id=str(user_id),
                goal_id=str(goal_id),
                phase_index=phase_index,
                phase_id=phase_id,
                total_questions=total_questions,
                correct_answers=correct_answers,
                score_pct=score_pct,
            )
            db.add(attempt)
            db.flush()
            for result in question_results or []:
                db.add(QuizQuestionHistory(
                    attempt_id=attempt.id,
                    question_index=int(result.get("question_index", 0)),
                    skill_name=result.get("skill_name"),
                    is_correct=bool(result.get("is_correct")),
                ))
            # Calibration can inspect the labelled history; the current attempt
            # is excluded from historical replay by current_attempt_id below.
            db.flush()
            skills_updated = []
            if skill_names:
                from app.services.skill_extraction import skill_extraction_service
                skills_updated = skill_extraction_service.update_proficiency_from_quiz(
                    user_id,
                    skill_names,
                    score_pct,
                    db=db,
                    question_results=question_results,
                    last_reviewed_at_by_skill=last_reviewed_at_by_skill,
                    goal_id=str(goal_id),
                    current_attempt_id=attempt.id,
                )
            if owns_session:
                db.commit()
        except Exception:
            if owns_session:
                db.rollback()
            raise
        finally:
            if owns_session:
                db.close()

        # Side effects belong after an owned transaction commits. Callers that
        # share a transaction run these only after their own commit.
        if owns_session:
            self._post_quiz_side_effects(user_id, goal_id, skill_names, score_pct, question_results=question_results)
        return {
            "score_pct": score_pct,
            "correct_answers": correct_answers,
            "total_questions": total_questions,
            "skills_updated": skills_updated,
        }

    def _post_quiz_side_effects(self, user_id, goal_id, skill_names, score_pct, question_results=None) -> None:
        try:
            self.log_activity(user_id, "quiz_attempt")
        except Exception:
            # The graded attempt has already committed; telemetry must not
            # turn a successful submission into an apparent grading failure.
            import logging
            logging.getLogger("learning_path_generator").exception("Could not record quiz activity log")
        if question_results is not None:
            evidence_keys = {
                normalize_skill_name(item.get("skill_name"))
                for item in question_results
                if item.get("skill_name") and normalize_skill_name(item.get("skill_name"))
            }
            skill_names = [name for name in (skill_names or []) if normalize_skill_name(name) in evidence_keys]
        if skill_names:
            try:
                from app.services.learning_features_service import learning_features_service
                learning_features_service.schedule_review(user_id, goal_id, skill_names, score_pct)
            except Exception:
                import logging
                logging.getLogger("learning_path_generator").exception("Could not schedule post-quiz review")

    @staticmethod
    def compute_streaks(activity_times, now, tz_offset_minutes: int = 0) -> dict:
        """Current and longest day streak, counted in the learner's own days.

        ``activity_times`` and ``now`` are naive UTC datetimes;
        ``tz_offset_minutes`` is minutes east of UTC (IST is +330). The current
        streak keeps counting while today has no activity yet: it only breaks
        once a whole day has passed without any, so it does not read 0 every
        morning before the learner has studied.
        """
        offset = timedelta(minutes=int(tz_offset_minutes or 0))
        days = {(t + offset).date() for t in activity_times if t}
        today = (now + offset).date()

        cursor = today if today in days else today - timedelta(days=1)
        current = 0
        while cursor in days:
            current += 1
            cursor -= timedelta(days=1)

        longest = run = 0
        previous = None
        for day in sorted(days):
            run = run + 1 if previous is not None and day - previous == timedelta(days=1) else 1
            longest = max(longest, run)
            previous = day
        return {"day_streak": current, "longest_streak": max(longest, current), "studied_today": today in days}

    def get_stats(self, user_id: str, tz_offset_minutes: int = 0) -> dict:
        db = SessionLocal()
        try:
            logs = db.query(ActivityLog).filter(ActivityLog.user_id == str(user_id)).all()
            attempts = db.query(QuizAttempt).filter(QuizAttempt.user_id == str(user_id)).all()
        finally:
            db.close()

        total_minutes = sum(log.duration_minutes or 0 for log in logs if log.activity_type == "session")
        total_hours = round(total_minutes / 60, 1)

        streaks = self.compute_streaks([log.created_at for log in logs], utcnow_naive(), tz_offset_minutes)

        practice_questions_solved = sum(a.total_questions for a in attempts)
        average_quiz_score = round(sum(a.score_pct for a in attempts) / len(attempts)) if attempts else None

        return {
            "total_learning_time_hours": total_hours,
            **streaks,
            "practice_questions_solved": practice_questions_solved,
            "average_quiz_score": average_quiz_score,
        }


activity_service = ActivityService()