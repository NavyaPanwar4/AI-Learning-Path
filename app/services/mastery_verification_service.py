"""Server-side mastery verification for skills whose BKT estimate is strong.

A strong probability is provisional until the learner passes a multi-aspect
verification quiz. Failed verifications update goal-scoped BKT from each
question and force the skill into the next roadmap.
"""
from __future__ import annotations

import json
import uuid
from datetime import timedelta

from app.db.database import SessionLocal
from app.db.models import GoalSkill, GoalUserSkill, IssuedQuiz, Skill, SkillDependency, User
from app.services.llm_service import llm_service
from app.services.curriculum_service import curriculum_service
from app.services.mastery_decay import decay_mastery, load_last_reviewed_at_by_skill, normalize_skill_name
from app.services.skill_extraction import skill_extraction_service
from app.services.bkt_parameters import get_bkt_parameters
from app.utils.config import settings
from app.utils.time import utcnow_naive

QUIZ_LIFETIME = timedelta(hours=2)
PASS_SCORE = 80


class MasteryVerificationError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class MasteryVerificationService:
    def _candidate_ids(self, db, goal_id: str) -> set[str]:
        # Curated curricula are the source of truth for those goals; do not
        # accidentally reintroduce unrelated legacy graph ancestors.
        curated_ids = None
        if curriculum_service.has_curriculum(str(goal_id)):
            getter = getattr(curriculum_service, "get_skill_ids", None)
            if callable(getter):
                curated_ids = getter(str(goal_id))
            else:  # compatibility with older local curriculum service files
                curriculum = curriculum_service._load().get(str(goal_id), {})
                curated_ids = [
                    str(skill_id)
                    for phase in curriculum.get("phases", [])
                    for skill_id in phase.get("skill_ids", [])
                ]
            return set(str(skill_id) for skill_id in (curated_ids or []))

        targets = {str(row.skill_id) for row in db.query(GoalSkill).filter(GoalSkill.goal_id == str(goal_id)).all()}
        if not targets:
            return set()
        skills = {str(row.skill_id) for row in db.query(Skill).all()}
        prereqs: dict[str, set[str]] = {sid: set() for sid in skills}
        for edge in db.query(SkillDependency).all():
            prerequisite, dependent = str(edge.prerequisite_id), str(edge.skill_id)
            if prerequisite in skills and dependent in skills:
                prereqs[dependent].add(prerequisite)
        closure = set(targets) & skills
        stack = list(closure)
        while stack:
            current = stack.pop()
            for prerequisite in prereqs.get(current, set()):
                if prerequisite not in closure:
                    closure.add(prerequisite)
                    stack.append(prerequisite)
        return closure

    def list_pending(self, user_id: str, goal_id: str) -> dict:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.user_id == str(user_id)).first()
            if user is None or str(user.goal_id or "") != str(goal_id):
                raise MasteryVerificationError(404, "Learning goal not found for this learner.")
            candidates = self._candidate_ids(db, str(goal_id))
            if not candidates:
                return {"goal_id": str(goal_id), "pending_skills": []}
            skills = {str(row.skill_id): row for row in db.query(Skill).filter(Skill.skill_id.in_(candidates)).all()}
            states = {
                str(row.skill_id): row
                for row in db.query(GoalUserSkill).filter(
                    GoalUserSkill.user_id == str(user_id),
                    GoalUserSkill.goal_id == str(goal_id),
                    GoalUserSkill.skill_id.in_(candidates),
                ).all()
            }
            last_reviewed = load_last_reviewed_at_by_skill(db, str(user_id), str(goal_id))
            pending = []
            for sid in sorted(candidates, key=lambda value: (normalize_skill_name(skills[value].skill_name) if value in skills else value)):
                skill = skills.get(sid)
                if skill is None:
                    continue
                state = states.get(sid)
                # Only goal-scoped BKT state can trigger verification. A global
                # UserSkill row means the skill is in the learner's profile; it
                # does not imply high mastery or a verification requirement.
                if state is None:
                    continue
                status = str(getattr(state, "verification_status", "unverified") or "unverified")
                probability = float(state.mastery_probability if state.mastery_probability is not None else 0.0)
                probability = decay_mastery(
                    probability,
                    last_reviewed.get(normalize_skill_name(skill.skill_name)),
                )
                if probability < float(settings.PLANNER_STRONG_THRESHOLD) or status != "unverified":
                    continue
                pending.append({
                    "skill_id": sid,
                    "skill_name": skill.skill_name,
                    "mastery_pct": round(probability * 100),
                    "status": "provisional",
                    "verification_attempts": int(getattr(state, "verification_attempts", 0) or 0) if state else 0,
                })
            return {"goal_id": str(goal_id), "pending_skills": pending}
        finally:
            db.close()

    def pending_for_active_goal(self, user_id: str) -> dict:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.user_id == str(user_id)).first()
            goal_id = str(user.goal_id) if user and user.goal_id else None
        finally:
            db.close()
        if not goal_id:
            return {"goal_id": None, "pending_skills": []}
        return self.list_pending(user_id, goal_id)

    def issue_quiz(self, user_id: str, goal_id: str, skill_id: str) -> dict:
        pending = self.list_pending(user_id, goal_id)["pending_skills"]
        target = next((item for item in pending if item["skill_id"] == str(skill_id)), None)
        if target is None:
            raise MasteryVerificationError(409, "This skill does not currently require mastery verification.")
        questions = llm_service.generate_skill_verification_quiz(target["skill_name"])
        now = utcnow_naive()
        quiz_id = str(uuid.uuid4())
        stored, public = [], []
        for question in questions:
            question_id = str(uuid.uuid4())
            stored_item = {
                "question_id": question_id,
                "question": question["question"],
                "options": list(question["options"]),
                "correct_index": int(question["correct_index"]),
                "explanation": question.get("explanation", ""),
                "skill": target["skill_name"],
                "aspect": question["aspect"],
            }
            stored.append(stored_item)
            public.append({
                "question_id": question_id,
                "question": stored_item["question"],
                "options": stored_item["options"],
                "aspect": stored_item["aspect"],
            })
        db = SessionLocal()
        try:
            db.add(IssuedQuiz(
                quiz_id=quiz_id,
                user_id=str(user_id),
                goal_id=str(goal_id),
                phase_index=-1,
                difficulty="verification",
                quiz_type="mastery_verification",
                skill_id=str(skill_id),
                questions_json=json.dumps(stored, ensure_ascii=False),
                expires_at=now + QUIZ_LIFETIME,
                created_at=now,
            ))
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        return {
            "quiz_id": quiz_id,
            "skill_id": str(skill_id),
            "skill_name": target["skill_name"],
            "pass_score": PASS_SCORE,
            "questions": public,
            "expires_at": (now + QUIZ_LIFETIME).isoformat() + "Z",
        }

    def submit_quiz(self, user_id: str, goal_id: str, skill_id: str, quiz_id: str, answers) -> dict:
        now = utcnow_naive()
        db = SessionLocal()
        try:
            issued = db.query(IssuedQuiz).filter(
                IssuedQuiz.quiz_id == str(quiz_id),
                IssuedQuiz.user_id == str(user_id),
                IssuedQuiz.goal_id == str(goal_id),
                IssuedQuiz.skill_id == str(skill_id),
                IssuedQuiz.quiz_type == "mastery_verification",
            ).first()
            if issued is None:
                raise MasteryVerificationError(404, "Verification quiz not found for this learner and skill.")
            if issued.submitted_at is not None:
                raise MasteryVerificationError(409, "This verification quiz has already been submitted.")
            if issued.expires_at < now:
                raise MasteryVerificationError(410, "This verification quiz has expired. Please generate a new one.")
            questions = json.loads(issued.questions_json)
            submitted = {str(item.question_id): int(item.selected_index) for item in answers}
            expected = {item["question_id"] for item in questions}
            if set(submitted) != expected:
                raise MasteryVerificationError(422, "Submit exactly one answer for every verification question.")
            changed = db.query(IssuedQuiz).filter(
                IssuedQuiz.quiz_id == str(quiz_id),
                IssuedQuiz.user_id == str(user_id),
                IssuedQuiz.submitted_at.is_(None),
                IssuedQuiz.expires_at >= now,
            ).update({IssuedQuiz.submitted_at: now}, synchronize_session=False)
            if changed != 1:
                db.rollback()
                raise MasteryVerificationError(409, "This verification quiz has expired or was already submitted.")
            correct = 0
            question_results = []
            graded = []
            for index, question in enumerate(questions):
                selected = submitted[question["question_id"]]
                is_correct = selected == int(question["correct_index"])
                correct += int(is_correct)
                question_results.append({
                    "question_index": index,
                    "skill_name": question["skill"],
                    "is_correct": is_correct,
                })
                graded.append({
                    "question_id": question["question_id"],
                    "question": question["question"],
                    "options": question["options"],
                    "selected_index": selected,
                    "correct_index": int(question["correct_index"]),
                    "is_correct": is_correct,
                    "explanation": question.get("explanation", ""),
                    "skill": question["skill"],
                    "aspect": question.get("aspect"),
                })
            total = len(questions)
            score = round((correct / total) * 100) if total else 0
            passed = score >= PASS_SCORE
            skill = db.query(Skill).filter(Skill.skill_id == str(skill_id)).first()
            if skill is None:
                raise MasteryVerificationError(404, "Skill not found.")
            # A pass verifies the already-high BKT estimate without lowering it
            # because of one missed item. A failed check feeds all five labelled
            # responses to BKT so the learner's estimate is recalibrated.
            bkt_updates = []
            if not passed:
                bkt_updates = skill_extraction_service.update_proficiency_from_quiz(
                    user_id=str(user_id),
                    skill_names=[skill.skill_name],
                    db=db,
                    question_results=question_results,
                    goal_id=str(goal_id),
                )
            state = db.query(GoalUserSkill).filter(
                GoalUserSkill.user_id == str(user_id),
                GoalUserSkill.goal_id == str(goal_id),
                GoalUserSkill.skill_id == str(skill_id),
            ).first()
            if state is None and passed:
                # A profile-declared skill may not yet have goal-scoped quiz
                # evidence. Passing verification promotes its provisional
                # threshold-level prior into an explicit verified goal state.
                initial_mastery = float(get_bkt_parameters(db).p_initial)
                state = GoalUserSkill(
                    user_id=str(user_id),
                    goal_id=str(goal_id),
                    skill_id=str(skill_id),
                    proficiency=max(1, min(5, int(round(initial_mastery * 5)))),
                    mastery_probability=initial_mastery,
                    bkt_observations=0,
                )
                db.add(state)
                db.flush()
            if state is None:
                raise MasteryVerificationError(500, "Could not persist the skill mastery update.")
            state.verification_attempts = int(state.verification_attempts or 0) + 1
            state.last_verification_score = score
            state.verification_status = "verified" if passed else "failed"
            state.verified_at = now if passed else None
            db.commit()
            mastery_pct = round(float(state.mastery_probability or 0.0) * 100)
            return {
                "quiz_id": str(quiz_id),
                "skill_id": str(skill_id),
                "skill_name": skill.skill_name,
                "total_questions": total,
                "correct_answers": correct,
                "score_pct": score,
                "passed": passed,
                "verification_status": state.verification_status,
                "mastery_pct": mastery_pct,
                "bkt_updates": bkt_updates,
                "graded_questions": graded,
                "message": (
                    "Mastery verified. This skill can be skipped when its BKT mastery remains above the threshold."
                    if passed else
                    "Verification not passed. Your responses updated BKT, and this skill will be included in your roadmap for learning or revision."
                ),
            }
        except MasteryVerificationError:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


mastery_verification_service = MasteryVerificationService()
