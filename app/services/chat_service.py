import json
import logging
from datetime import timedelta

from app.db.database import SessionLocal
from app.db.models import ChatMessage, Goal, IssuedQuiz, QuizAttempt, Roadmap
from app.services.adaptive_service import adaptive_service
from app.services.auth_service import auth_service
from app.services.dashboard_service import dashboard_service
from app.services.llm_service import llm_service, LLMError
from app.utils.config import settings
from app.utils.time import utcnow_naive

MAX_HISTORY_TURNS = 12  # messages of context sent to the model each turn


class ChatService:
    """Builds live learner context (goal, roadmap phase, mastery, quiz
    performance) and drives the AI tutor chat through the local LLM.
    Conversation history is persisted per user+goal so the tutor keeps
    continuity across sessions."""

    def _history_cutoff(self):
        retention_days = max(1, int(settings.CHAT_HISTORY_RETENTION_DAYS))
        return utcnow_naive() - timedelta(days=retention_days)

    def _purge_expired_history(self, db, user_id: str) -> int:
        deleted = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.user_id == str(user_id),
                ChatMessage.created_at < self._history_cutoff(),
            )
            .delete(synchronize_session=False)
        )
        if deleted:
            db.commit()
        return int(deleted or 0)

    def clear_history(self, user_id: str) -> dict:
        """Delete all tutor history owned by the authenticated user."""
        db = SessionLocal()
        try:
            deleted = (
                db.query(ChatMessage)
                .filter(ChatMessage.user_id == str(user_id))
                .delete(synchronize_session=False)
            )
            db.commit()
            return {"deleted_count": int(deleted or 0)}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Context
    # ------------------------------------------------------------------

    def _resolve_goal_id(self, profile: dict, goal_id: str = None) -> str:
        target = goal_id or profile.get("goal_id")
        if goal_id and goal_id != profile.get("goal_id"):
            db = SessionLocal()
            try:
                owns_roadmap = db.query(Roadmap).filter(Roadmap.user_id == profile.get("user_id"), Roadmap.goal_id == goal_id).first()
            finally:
                db.close()
            if not owns_roadmap:
                raise ValueError("You do not have access to this learning goal")
        return target

    def _build_context(self, user_id: str, goal_id: str = None) -> dict:
        profile = auth_service.get_user_by_id(user_id)
        if not profile:
            raise ValueError("User not found")

        target_goal_id = self._resolve_goal_id(profile, goal_id)

        goal_name = None
        current_phase_title = None
        current_phase_skills = []
        phase_index = None
        phase_count = 0

        if target_goal_id:
            db = SessionLocal()
            try:
                goal = db.query(Goal).filter(Goal.goal_id == target_goal_id).first()
                goal_name = goal.goal_name if goal else None

                roadmap_row = (
                    db.query(Roadmap)
                    .filter(Roadmap.user_id == str(user_id), Roadmap.goal_id == str(target_goal_id))
                    .first()
                )
                if roadmap_row:
                    try:
                        data = json.loads(roadmap_row.data)
                    except (json.JSONDecodeError, TypeError):
                        data = {}
                    phases = data.get("phases", []) or []
                    phase_count = len(phases)

                    # "Current phase" = first not-yet-completed phase, else the last one.
                    for i, phase in enumerate(phases):
                        if not phase.get("completed"):
                            current_phase_title = phase.get("title")
                            current_phase_skills = phase.get("skills", []) or []
                            phase_index = i
                            break
                    if phase_index is None and phases:
                        phase_index = len(phases) - 1
                        current_phase_title = phases[-1].get("title")
                        current_phase_skills = phases[-1].get("skills", []) or []
            finally:
                db.close()

        skills_mastery = dashboard_service._skills_mastery(user_id, target_goal_id)
        strong_skills = [s["skill_name"] for s in skills_mastery if s["mastery_pct"] >= 70][:5]
        weak_skills = [s["skill_name"] for s in skills_mastery if s["mastery_pct"] < 70][:5]

        db = SessionLocal()
        try:
            recent_quizzes = (
                db.query(QuizAttempt)
                .filter(QuizAttempt.user_id == str(user_id), QuizAttempt.goal_id == str(target_goal_id))
                .order_by(QuizAttempt.created_at.desc())
                .limit(5)
                .all()
            )
        finally:
            db.close()

        quiz_summary = [
            {
                "phase_index": q.phase_index,
                "score_pct": q.score_pct,
                "correct_answers": q.correct_answers,
                "total_questions": q.total_questions,
            }
            for q in recent_quizzes
        ]

        try:
            recommendation = adaptive_service.get_recommendation(user_id, target_goal_id)
        except Exception:
            recommendation = None

        return {
            "goal_id": target_goal_id,
            "username": profile.get("username") or "there",
            "experience_level": profile.get("experience_level") or "beginner",
            "learning_style": profile.get("learning_style") or "visual",
            "goal_name": goal_name,
            "current_phase_title": current_phase_title,
            "current_phase_skills": current_phase_skills,
            "phase_index": phase_index,
            "phase_count": phase_count,
            "strong_skills": strong_skills,
            "weak_skills": weak_skills,
            "recent_quizzes": quiz_summary,
            "recommendation": recommendation,
        }

    def _build_system_prompt(self, ctx: dict) -> str:
        lines = [
            "You are the AI tutor built into a personalized learning-path app. "
            "You are NOT a generic assistant — you know this specific learner's goal, "
            "current roadmap phase, skill mastery and quiz history, given below. Always "
            "ground explanations, examples, coding help, summaries and practice questions "
            "in that context rather than giving generic answers.",
            "",
            f"Learner: {ctx['username']} ({ctx['experience_level']} level, prefers {ctx['learning_style']} learning)",
            f"Learning goal: {ctx['goal_name'] or 'not set yet — encourage them to pick one'}",
        ]

        if ctx["current_phase_title"]:
            lines.append(
                f"Current roadmap phase ({ctx['phase_index'] + 1} of {ctx['phase_count']}): "
                f"\"{ctx['current_phase_title']}\" — skills: {', '.join(ctx['current_phase_skills']) or 'n/a'}"
            )

        if ctx["strong_skills"]:
            lines.append(f"Strong skills: {', '.join(ctx['strong_skills'])}")
        if ctx["weak_skills"]:
            lines.append(f"Needs improvement: {', '.join(ctx['weak_skills'])}")

        if ctx["recent_quizzes"]:
            q_lines = [
                f"phase {q['phase_index'] + 1}: {q['score_pct']}% ({q['correct_answers']}/{q['total_questions']})"
                for q in ctx["recent_quizzes"]
            ]
            lines.append("Recent quiz scores: " + "; ".join(q_lines))
        else:
            lines.append("No quiz attempts yet.")

        rec = ctx.get("recommendation")
        if rec and rec.get("type") not in (None, "none"):
            lines.append(f"\nSYSTEM RECOMMENDATION (authoritative — this is what the roadmap page itself is telling the learner right now): {rec['message']}")

        lines.append(
            "\nWhen asked something like \"what should I learn next\", base your answer on the SYSTEM "
            "RECOMMENDATION above if one is present — don't invent a different suggestion or give a "
            "generic study plan. When helping with a quiz mistake, ask which question or topic they got "
            "wrong if they haven't said, then explain the concept clearly with an example. Keep replies "
            "focused and encouraging. Formatting: this renders in a narrow chat bubble, not a document — "
            "never use markdown headings (#, ##, ###) or horizontal rules, use **bold** sparingly (only "
            "1-2 key terms), skip emoji, and prefer short paragraphs or a plain bullet list over any "
            "heading/section structure."
        )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Conversation
    # ------------------------------------------------------------------

    def send_message(self, user_id: str, message: str, goal_id: str = None) -> dict:
        if not message or not message.strip():
            raise ValueError("Message cannot be empty")

        ctx = self._build_context(user_id, goal_id)
        system_prompt = self._build_system_prompt(ctx)
        scoped_goal_id = ctx["goal_id"]

        db = SessionLocal()
        try:
            self._purge_expired_history(db, user_id)
            rows = (
                db.query(ChatMessage)
                .filter(ChatMessage.user_id == str(user_id), ChatMessage.goal_id == scoped_goal_id)
                .order_by(ChatMessage.created_at.desc())
                .limit(MAX_HISTORY_TURNS)
                .all()
            )
            history = [{"role": r.role, "content": r.content} for r in reversed(rows)]

            db.add(ChatMessage(user_id=str(user_id), goal_id=scoped_goal_id, role="user", content=message.strip()))
            db.commit()
        finally:
            db.close()

        try:
            reply = llm_service.chat(system_prompt, history, message.strip())
        except LLMError:
            # Do not leave an unanswered user turn in the saved history.
            db = SessionLocal()
            try:
                last = (
                    db.query(ChatMessage)
                    .filter(ChatMessage.user_id == str(user_id), ChatMessage.goal_id == scoped_goal_id, ChatMessage.role == "user")
                    .order_by(ChatMessage.created_at.desc())
                    .first()
                )
                if last is not None:
                    db.delete(last)
                    db.commit()
            finally:
                db.close()
            raise

        db = SessionLocal()
        try:
            db.add(ChatMessage(user_id=str(user_id), goal_id=scoped_goal_id, role="assistant", content=reply))
            db.commit()
        finally:
            db.close()

        return {"reply": reply, "goal_id": scoped_goal_id}

    def stream_message(self, user_id: str, message: str, goal_id: str = None):
        """Prepare a chat turn and return an iterator of SSE event payloads.

        Validation/context lookup runs before a StreamingResponse is returned;
        the nested iterator streams tokens and persists the final assistant turn.
        """
        if not message or not message.strip():
            raise ValueError("Message cannot be empty")

        ctx = self._build_context(user_id, goal_id)
        system_prompt = self._build_system_prompt(ctx)
        scoped_goal_id = ctx["goal_id"]
        db = SessionLocal()
        try:
            self._purge_expired_history(db, user_id)
            rows = (
                db.query(ChatMessage)
                .filter(ChatMessage.user_id == str(user_id), ChatMessage.goal_id == scoped_goal_id)
                .order_by(ChatMessage.created_at.desc())
                .limit(MAX_HISTORY_TURNS)
                .all()
            )
            history = [{"role": r.role, "content": r.content} for r in reversed(rows)]
            db.add(ChatMessage(user_id=str(user_id), goal_id=scoped_goal_id, role="user", content=message.strip()))
            db.commit()
        finally:
            db.close()

        def events():
            pieces = []
            try:
                for piece in llm_service.chat_stream(system_prompt, history, message.strip()):
                    if not piece:
                        continue
                    pieces.append(piece)
                    yield {"type": "delta", "content": piece}
                reply = "".join(pieces).strip()
                if reply:
                    db = SessionLocal()
                    try:
                        db.add(ChatMessage(user_id=str(user_id), goal_id=scoped_goal_id, role="assistant", content=reply))
                        db.commit()
                    finally:
                        db.close()
                yield {"type": "done", "goal_id": scoped_goal_id}
            except LLMError as exc:
                logging.getLogger("learning_path_generator").warning("Tutor streaming failed: %s", exc.kind)
                yield {"type": "error", "message": str(exc)}
            except Exception:
                logging.getLogger("learning_path_generator").exception("Tutor streaming failed")
                # Preserve partial output if the model fails after yielding tokens.
                partial = "".join(pieces).strip()
                if partial:
                    db = SessionLocal()
                    try:
                        db.add(ChatMessage(user_id=str(user_id), goal_id=scoped_goal_id, role="assistant", content=partial))
                        db.commit()
                    finally:
                        db.close()
                yield {"type": "error", "message": "Tutor stream interrupted. Please send a new message to continue."}
        return events()

    # ------------------------------------------------------------------
    # Explain a quiz answer
    # ------------------------------------------------------------------

    def explain_answer(self, user_id: str, quiz_id: str, question_id: str, selected_index: int) -> dict:
        """Have the tutor explain one question from a quiz the learner has submitted.

        Only submitted quizzes are readable (so the answer key can never be
        fetched before answering), and only by the learner they were issued to.
        The saved chat shows a short request; the model receives the full
        question, the learner's pick, the correct answer and the stored
        explanation.
        """
        db = SessionLocal()
        try:
            issued = (
                db.query(IssuedQuiz)
                .filter(IssuedQuiz.quiz_id == str(quiz_id), IssuedQuiz.user_id == str(user_id))
                .first()
            )
            if issued is None or issued.submitted_at is None:
                raise ValueError("Submit the quiz before asking for an explanation.")
            try:
                questions = json.loads(issued.questions_json)
            except (TypeError, json.JSONDecodeError):
                raise ValueError("This quiz's questions are no longer available.")
            quiz_goal_id = issued.goal_id
        finally:
            db.close()

        question = next((q for q in questions if str(q.get("question_id")) == str(question_id)), None)
        if question is None:
            raise ValueError("That question is not part of this quiz.")
        options = question.get("options") or []
        if not 0 <= int(selected_index) < len(options):
            raise ValueError("That answer option does not exist.")
        correct_index = int(question["correct_index"])
        picked = int(selected_index)
        letters = "ABCD"

        lines = [
            "The learner just finished a quiz and wants help with one question.",
            f"Skill: {question.get('skill') or 'General foundations'}",
            f"Question: {question.get('question', '')}",
            "Options:",
            *[f"  {letters[i]}. {text}" for i, text in enumerate(options)],
            f"The learner chose: {letters[picked]}. {options[picked]}",
            f"The correct answer is: {letters[correct_index]}. {options[correct_index]}",
        ]
        if question.get("explanation"):
            lines.append(f"Reference explanation: {question['explanation']}")
        if picked == correct_index:
            lines.append("The learner was right. Briefly confirm why, then add one deeper insight or common pitfall.")
        else:
            lines.append(
                "Explain in plain words why the learner's choice is wrong (name the likely misunderstanding), "
                "then why the correct option is right, with one short example. End with one quick question "
                "they can answer to check they understood. Keep it under about 180 words."
            )
        instruction = "\n".join(lines)

        ctx = self._build_context(user_id, quiz_goal_id)
        system_prompt = self._build_system_prompt(ctx)
        scoped_goal_id = ctx["goal_id"]
        saved_request = f"Explain this quiz question: {str(question.get('question', ''))[:300]}"

        db = SessionLocal()
        try:
            self._purge_expired_history(db, user_id)
            rows = (
                db.query(ChatMessage)
                .filter(ChatMessage.user_id == str(user_id), ChatMessage.goal_id == scoped_goal_id)
                .order_by(ChatMessage.created_at.desc())
                .limit(MAX_HISTORY_TURNS)
                .all()
            )
            history = [{"role": r.role, "content": r.content} for r in reversed(rows)]
        finally:
            db.close()

        reply = llm_service.chat(system_prompt, history, instruction)  # LLMError propagates; nothing saved yet

        db = SessionLocal()
        try:
            db.add(ChatMessage(user_id=str(user_id), goal_id=scoped_goal_id, role="user", content=saved_request))
            db.add(ChatMessage(user_id=str(user_id), goal_id=scoped_goal_id, role="assistant", content=reply))
            db.commit()
        finally:
            db.close()
        return {"reply": reply, "goal_id": scoped_goal_id}

    def get_history(self, user_id: str, goal_id: str = None) -> list:
        profile = auth_service.get_user_by_id(user_id)
        target_goal_id = self._resolve_goal_id(profile or {}, goal_id)

        db = SessionLocal()
        try:
            self._purge_expired_history(db, user_id)
            rows = (
                db.query(ChatMessage)
                .filter(ChatMessage.user_id == str(user_id), ChatMessage.goal_id == target_goal_id)
                .order_by(ChatMessage.created_at.asc())
                .all()
            )
            return [
                {"role": r.role, "content": r.content, "created_at": r.created_at.isoformat()}
                for r in rows
            ]
        finally:
            db.close()


chat_service = ChatService()
