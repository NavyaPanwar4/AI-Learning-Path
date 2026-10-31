from app.utils.time import utcnow_naive
import json

from app.services.phase_identity import ensure_phase_ids
from datetime import datetime, timedelta

from app.db.database import SessionLocal
from app.db.models import (
    QuizAttempt,
    QuizQuestionHistory,
    ResourceReport,
    ReviewSchedule,
    Roadmap,
    RoadmapVersion,
    Skill,
    StudyReminder,
    UserSkill,
    GoalUserSkill,
)
from app.services.mastery_decay import (
    decay_mastery, elapsed_days, load_last_reviewed_at_by_skill, normalize_skill_name,
    review_interval_days,
)


class LearningFeaturesService:
    def _roadmap_row(self, db, user_id, goal_id):
        return db.query(Roadmap).filter(Roadmap.user_id == str(user_id), Roadmap.goal_id == str(goal_id)).first()

    def record_version(self, db, roadmap, data):
        latest = db.query(RoadmapVersion).filter(RoadmapVersion.roadmap_id == roadmap.id).order_by(RoadmapVersion.version_number.desc()).first()
        db.add(RoadmapVersion(roadmap_id=roadmap.id, version_number=(latest.version_number + 1 if latest else 1), data=data))

    def list_versions(self, user_id, goal_id):
        db = SessionLocal()
        try:
            roadmap = self._roadmap_row(db, user_id, goal_id)
            if not roadmap:
                return None
            rows = db.query(RoadmapVersion).filter(RoadmapVersion.roadmap_id == roadmap.id).order_by(RoadmapVersion.version_number.desc()).all()
            return [{"version_number": row.version_number, "created_at": row.created_at.isoformat()} for row in rows]
        finally:
            db.close()

    def restore_version(self, user_id, goal_id, version_number):
        db = SessionLocal()
        try:
            roadmap = self._roadmap_row(db, user_id, goal_id)
            if not roadmap:
                return None
            version = db.query(RoadmapVersion).filter(RoadmapVersion.roadmap_id == roadmap.id, RoadmapVersion.version_number == version_number).first()
            if not version:
                return None
            self.record_version(db, roadmap, roadmap.data)
            roadmap.data = version.data
            parsed = json.loads(version.data)
            roadmap.is_complete = bool(parsed.get("is_complete", False))
            db.commit()
            parsed["goal_id"] = goal_id
            parsed["goal_name"] = roadmap.goal_name or parsed.get("goal_name") or "Learning Roadmap"
            return parsed
        finally:
            db.close()

    def analytics(self, user_id, goal_id):
        db = SessionLocal()
        try:
            roadmap = self._roadmap_row(db, user_id, goal_id)
            if not roadmap:
                return None
            roadmap_data = json.loads(roadmap.data)
            if ensure_phase_ids(roadmap_data):
                roadmap.data = json.dumps(roadmap_data, ensure_ascii=False)
                db.commit()
            phases = roadmap_data.get("phases", [])
            from app.db.models import QuizAttempt
            attempts = db.query(QuizAttempt).filter(QuizAttempt.user_id == str(user_id), QuizAttempt.goal_id == str(goal_id)).order_by(QuizAttempt.created_at.asc()).all()
            attempt_ids = [attempt.id for attempt in attempts]
            question_history = db.query(QuizQuestionHistory).filter(QuizQuestionHistory.attempt_id.in_(attempt_ids)).order_by(QuizQuestionHistory.created_at.asc()).all() if attempt_ids else []
            by_phase = []
            skill_scores = {}
            for index, phase in enumerate(phases):
                phase_id = phase.get("phase_id")
                phase_attempts = [attempt for attempt in attempts if (phase_id and attempt.phase_id == phase_id) or (not attempt.phase_id and attempt.phase_index == index)]
                scores = [attempt.score_pct for attempt in phase_attempts]
                by_phase.append({"phase_index": index, "phase_title": phase.get("title"), "attempts": len(scores), "average_score": round(sum(scores) / len(scores)) if scores else None, "best_score": max(scores) if scores else None})
                for skill in set(phase.get("skills", []) or []):
                    skill_scores.setdefault(skill, []).extend(scores)
            return {"total_attempts": len(attempts), "by_phase": by_phase, "by_skill": [{"skill_name": skill, "attempts": len(scores), "average_score": round(sum(scores) / len(scores)) if scores else None} for skill, scores in sorted(skill_scores.items())], "question_history": [{"question_index": row.question_index, "skill_name": row.skill_name, "is_correct": row.is_correct, "created_at": row.created_at.isoformat()} for row in question_history]}
        finally:
            db.close()

    def schedule_review(self, user_id, goal_id, skill_names, score_pct):
        """Schedule only skills with goal-specific BKT evidence.

        The aggregate score is retained for display/history, never converted
        into a per-skill mastery observation or used to pick the interval.
        """
        now = utcnow_naive()
        db = SessionLocal()
        try:
            for skill_name in dict.fromkeys(str(name).strip() for name in (skill_names or []) if name and str(name).strip()):
                skill = db.query(Skill).filter(Skill.skill_name.ilike(skill_name)).first()
                if not skill:
                    continue
                goal_skill = db.query(GoalUserSkill).filter(
                    GoalUserSkill.user_id == str(user_id),
                    GoalUserSkill.goal_id == str(goal_id),
                    GoalUserSkill.skill_id == skill.skill_id,
                ).first()
                # No per-question evidence / no goal state -> do not manufacture
                # a review schedule from the phase-level score.
                if not goal_skill or goal_skill.mastery_probability is None:
                    continue

                interval = review_interval_days(goal_skill.mastery_probability)
                schedule = db.query(ReviewSchedule).filter(
                    ReviewSchedule.user_id == str(user_id),
                    ReviewSchedule.goal_id == str(goal_id),
                    ReviewSchedule.skill_name == skill_name,
                ).first()
                if not schedule:
                    schedule = ReviewSchedule(
                        user_id=str(user_id), goal_id=str(goal_id), skill_name=skill_name,
                        due_at=now + timedelta(days=interval), interval_days=interval,
                        created_at=now, last_score=score_pct,
                    )
                    db.add(schedule)
                else:
                    schedule.due_at = now + timedelta(days=interval)
                    schedule.interval_days = interval
                    schedule.repetitions += 1
                    schedule.created_at = now
                    schedule.last_score = score_pct
            db.commit()
        finally:
            db.close()

    def review_queue(self, user_id, goal_id=None):
        """Return due reviews from goal-specific mastery and evidence timestamps."""
        db = SessionLocal()
        try:
            now = utcnow_naive()
            query = db.query(ReviewSchedule).filter(ReviewSchedule.user_id == str(user_id))
            if goal_id is not None:
                query = query.filter(ReviewSchedule.goal_id == str(goal_id))
            rows = query.order_by(ReviewSchedule.due_at.asc()).all()

            goal_ids = {str(row.goal_id) for row in rows}
            last_reviewed_by_goal = {
                gid: load_last_reviewed_at_by_skill(db, str(user_id), gid)
                for gid in goal_ids
            }
            mastery_query = (
                db.query(GoalUserSkill, Skill)
                .join(Skill, GoalUserSkill.skill_id == Skill.skill_id)
                .filter(GoalUserSkill.user_id == str(user_id))
            )
            if goal_id is not None:
                mastery_query = mastery_query.filter(GoalUserSkill.goal_id == str(goal_id))
            mastery_by_key = {
                (str(goal_skill.goal_id), normalize_skill_name(skill.skill_name)): goal_skill.mastery_probability
                for goal_skill, skill in mastery_query.all()
            }

            results = []
            for row in rows:
                gid = str(row.goal_id)
                key = normalize_skill_name(row.skill_name)
                last_at = last_reviewed_by_goal.get(gid, {}).get(key)
                raw_mastery = mastery_by_key.get((gid, key))
                effective = decay_mastery(raw_mastery, last_at, now=now) if raw_mastery is not None else None
                age = elapsed_days(last_at, now)

                if raw_mastery is not None and last_at is not None:
                    interval = review_interval_days(raw_mastery)
                    effective_due_at = last_at + timedelta(days=interval)
                else:
                    # Legacy schedules without a goal-specific state are still
                    # honored by their stored due date; no fake mastery is shown.
                    interval = row.interval_days
                    effective_due_at = row.due_at
                if effective_due_at > now:
                    continue

                results.append({
                    "id": row.id,
                    "goal_id": row.goal_id,
                    "skill_name": row.skill_name,
                    "due_at": effective_due_at.isoformat(),
                    "last_score": row.last_score,
                    "mastery_pct": round(effective * 100) if effective is not None else None,
                    "last_reviewed_at": last_at.isoformat() if last_at else None,
                    "days_since_review": round(age, 1) if age is not None else None,
                    "interval_days": interval,
                })
            results.sort(key=lambda item: item["due_at"])
            return results
        finally:
            db.close()

    def reminders(self, user_id):
        db = SessionLocal()
        try:
            rows = db.query(StudyReminder).filter(StudyReminder.user_id == str(user_id)).order_by(StudyReminder.due_at.asc()).all()
            return [{"id": row.id, "title": row.title, "due_at": row.due_at.isoformat(), "goal_id": row.goal_id, "completed": row.completed} for row in rows]
        finally:
            db.close()

    def build_calendar(self, user_id, now=None) -> str:
        """iCalendar text with the learner's open reminders and roadmap deadlines."""
        from datetime import date as date_type
        from app.utils import ical

        now = now or utcnow_naive()
        events = []
        for reminder in self.reminders(user_id):
            if reminder.get("completed"):
                continue
            events.append(ical.event(
                uid=f"reminder-{reminder['id']}@learning-path",
                summary=reminder["title"],
                stamp=now,
                start=datetime.fromisoformat(reminder["due_at"]),
            ))
        db = SessionLocal()
        try:
            rows = db.query(Roadmap).filter(Roadmap.user_id == str(user_id)).all()
            for row in rows:
                if row.is_complete:
                    continue
                try:
                    deadline = json.loads(row.data).get("deadline")
                    day = date_type.fromisoformat(str(deadline)[:10]) if deadline else None
                except (ValueError, TypeError):
                    continue
                if day:
                    events.append(ical.event(
                        uid=f"deadline-{row.goal_id}@learning-path",
                        summary=f"Deadline: {row.goal_name or 'learning path'}",
                        stamp=now,
                        all_day=day,
                        description="Target date to finish this learning path.",
                    ))
        finally:
            db.close()
        return ical.calendar(events)

    def create_reminder(self, user_id, title, due_at, goal_id=None):
        parsed = datetime.fromisoformat(due_at.replace("Z", "+00:00")).replace(tzinfo=None)
        db = SessionLocal()
        try:
            row = StudyReminder(user_id=str(user_id), title=title, due_at=parsed, goal_id=goal_id)
            db.add(row)
            db.commit()
            return {"id": row.id, "title": row.title, "due_at": row.due_at.isoformat(), "goal_id": row.goal_id, "completed": False}
        finally:
            db.close()

    def complete_reminder(self, user_id, reminder_id, completed=True):
        """Set a reminder's completion state for its owner; defaults to legacy complete behavior."""
        db = SessionLocal()
        try:
            row = db.query(StudyReminder).filter(
                StudyReminder.id == reminder_id,
                StudyReminder.user_id == str(user_id),
            ).first()
            if not row:
                return False
            row.completed = bool(completed)
            db.commit()
            return True
        finally:
            db.close()

    def delete_reminder(self, user_id, reminder_id):
        """Delete a reminder only when it belongs to the requesting user."""
        db = SessionLocal()
        try:
            row = db.query(StudyReminder).filter(
                StudyReminder.id == reminder_id,
                StudyReminder.user_id == str(user_id),
            ).first()
            if not row:
                return False
            db.delete(row)
            db.commit()
            return True
        finally:
            db.close()

    def set_deadline(self, user_id, goal_id, deadline):
        db = SessionLocal()
        try:
            row = self._roadmap_row(db, user_id, goal_id)
            if not row:
                return None
            data = json.loads(row.data)
            if data.get("deadline") != deadline:
                self.record_version(db, row, row.data)
            if deadline is None:
                data.pop("deadline", None)
            else:
                data["deadline"] = deadline
            row.data = json.dumps(data)
            db.commit()
            data["goal_id"] = goal_id
            data["goal_name"] = row.goal_name or data.get("goal_name") or "Learning Roadmap"
            return data
        finally:
            db.close()

    def report_resource(self, user_id, resource_url, reason):
        db = SessionLocal()
        try:
            row = ResourceReport(user_id=str(user_id), resource_url=resource_url, reason=reason)
            db.add(row)
            db.commit()
            return {"id": row.id, "status": row.status}
        finally:
            db.close()

    def export_roadmap(self, user_id, goal_id):
        db = SessionLocal()
        try:
            row = self._roadmap_row(db, user_id, goal_id)
            if not row:
                return None
            return {"goal_id": row.goal_id, "goal_name": row.goal_name, "roadmap": json.loads(row.data), "exported_at": utcnow_naive().isoformat()}
        finally:
            db.close()

    def import_roadmap(self, user_id, goal_id, roadmap_data):
        db = SessionLocal()
        try:
            row = self._roadmap_row(db, user_id, goal_id)
            if not row:
                row = Roadmap(user_id=str(user_id), goal_id=goal_id, goal_name="Imported roadmap", data=json.dumps(roadmap_data))
                db.add(row)
            else:
                self.record_version(db, row, row.data)
                row.data = json.dumps(roadmap_data)
            db.commit()
            roadmap_data["goal_id"] = goal_id
            roadmap_data["goal_name"] = row.goal_name or roadmap_data.get("goal_name") or "Imported roadmap"
            return roadmap_data
        finally:
            db.close()


learning_features_service = LearningFeaturesService()
