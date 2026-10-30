from app.utils.time import utcnow_naive
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List

from app.db.database import SessionLocal
from app.db.models import IssuedQuiz
from app.services.activity_service import activity_service

logger = logging.getLogger("learning_path_generator")
QUIZ_LIFETIME = timedelta(hours=2)


class QuizSubmissionError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class QuizService:
    def create_session(
        self,
        user_id: str,
        goal_id: str,
        phase_index: int,
        difficulty: str,
        questions: List[dict],
    ) -> dict:
        """Store grading keys server-side and return a sanitized quiz."""
        if not isinstance(questions, list) or not questions:
            raise ValueError("Cannot issue an empty quiz")

        stored_questions = []
        public_questions = []
        for question in questions:
            if not isinstance(question, dict):
                continue
            prompt = question.get("question")
            options = question.get("options")
            correct_index = question.get("correct_index")
            if (
                not isinstance(prompt, str) or not prompt.strip()
                or not isinstance(options, list) or len(options) != 4
                or not all(isinstance(option, str) and option.strip() for option in options)
                or isinstance(correct_index, bool) or not isinstance(correct_index, int)
                or correct_index < 0 or correct_index >= len(options)
            ):
                continue

            question_id = str(uuid.uuid4())
            skill = str(question.get("skill") or "General foundations")
            stored = {
                "question_id": question_id,
                "question": prompt.strip(),
                "options": options,
                "correct_index": correct_index,
                "explanation": str(question.get("explanation") or ""),
                "skill": skill,
            }
            stored_questions.append(stored)
            # Crucial: no correct_index, answer key, or explanation in the
            # pre-submission payload.
            public_questions.append({
                "question_id": question_id,
                "question": stored["question"],
                "options": list(options),
                "skill": skill,
            })

        if not stored_questions:
            raise ValueError("No valid quiz questions could be issued")

        now = utcnow_naive()
        quiz_id = str(uuid.uuid4())
        db = SessionLocal()
        try:
            db.add(IssuedQuiz(
                quiz_id=quiz_id,
                user_id=str(user_id),
                goal_id=str(goal_id),
                phase_index=int(phase_index),
                difficulty=str(difficulty or "beginner"),
                questions_json=json.dumps(stored_questions, ensure_ascii=False),
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
            "questions": public_questions,
            "expires_at": (now + QUIZ_LIFETIME).isoformat() + "Z",
        }

    def grade_submission(
        self,
        user_id: str,
        goal_id: str,
        phase_index: int,
        quiz_id: str,
        answers: List[Any],
        phase_id=None,
    ) -> dict:
        """Grade only against the stored key, atomically consuming one quiz."""
        now = utcnow_naive()
        db = SessionLocal()
        skill_names = []
        score_pct = 0
        try:
            issued = (
                db.query(IssuedQuiz)
                .filter(
                    IssuedQuiz.quiz_id == str(quiz_id),
                    IssuedQuiz.user_id == str(user_id),
                    IssuedQuiz.goal_id == str(goal_id),
                    IssuedQuiz.phase_index == int(phase_index),
                )
                .first()
            )
            if issued is None:
                raise QuizSubmissionError(404, "Quiz session not found for this user, roadmap, or phase")
            if issued.submitted_at is not None:
                raise QuizSubmissionError(409, "This quiz has already been submitted")
            if issued.expires_at < now:
                raise QuizSubmissionError(410, "This quiz session has expired. Generate a new quiz.")

            try:
                questions = json.loads(issued.questions_json)
            except (TypeError, json.JSONDecodeError) as exc:
                logger.exception("Stored quiz %s has invalid question JSON", quiz_id)
                raise QuizSubmissionError(500, "Stored quiz data is invalid") from exc

            submitted = {}
            for answer in answers:
                question_id = str(answer.question_id)
                if question_id in submitted:
                    raise QuizSubmissionError(422, "Duplicate answer for a quiz question")
                submitted[question_id] = int(answer.selected_index)

            expected_ids = {question["question_id"] for question in questions}
            received_ids = set(submitted)
            if received_ids != expected_ids:
                raise QuizSubmissionError(422, "Submit exactly one answer for every question in this quiz")

            # Atomic compare-and-set: concurrent/replayed submissions cannot
            # both consume the same quiz session.
            changed = (
                db.query(IssuedQuiz)
                .filter(
                    IssuedQuiz.quiz_id == str(quiz_id),
                    IssuedQuiz.user_id == str(user_id),
                    IssuedQuiz.submitted_at.is_(None),
                    IssuedQuiz.expires_at >= now,
                )
                .update({IssuedQuiz.submitted_at: now}, synchronize_session=False)
            )
            if changed != 1:
                db.rollback()
                raise QuizSubmissionError(409, "This quiz has expired or has already been submitted")

            question_results = []
            graded_questions = []
            correct_answers = 0
            for index, question in enumerate(questions):
                selected_index = submitted[question["question_id"]]
                correct_index = int(question["correct_index"])
                is_correct = selected_index == correct_index
                correct_answers += int(is_correct)
                skill_name = question.get("skill") or "General foundations"
                question_results.append({
                    "question_index": index,
                    "skill_name": skill_name,
                    "is_correct": is_correct,
                })
                graded_questions.append({
                    "question_id": question["question_id"],
                    "question": question["question"],
                    "options": question["options"],
                    "selected_index": selected_index,
                    "correct_index": correct_index,
                    "is_correct": is_correct,
                    "explanation": question.get("explanation", ""),
                    "skill": skill_name,
                })

            total_questions = len(questions)
            score_pct = round((correct_answers / total_questions) * 100) if total_questions else 0
            skill_names = list(dict.fromkeys(
                item["skill_name"] for item in question_results if item.get("skill_name")
            ))

            recorded = activity_service.record_quiz_attempt(
                user_id=str(user_id),
                goal_id=str(goal_id),
                phase_index=int(phase_index),
                phase_id=phase_id,
                total_questions=total_questions,
                correct_answers=correct_answers,
                skill_names=skill_names,
                question_results=question_results,
                db=db,
            )
            # The consume flag, graded attempt, per-question history and BKT
            # updates commit together.
            db.commit()
        except QuizSubmissionError:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        activity_service._post_quiz_side_effects(user_id, goal_id, skill_names, score_pct, question_results=question_results)
        recorded.update({
            "quiz_id": str(quiz_id),
            "total_questions": total_questions,
            "correct_answers": correct_answers,
            "score_pct": score_pct,
            "graded_questions": graded_questions,
        })
        return recorded


quiz_service = QuizService()
