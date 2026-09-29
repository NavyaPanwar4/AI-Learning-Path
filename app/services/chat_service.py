import json

from app.db.database import SessionLocal
from app.db.models import ChatMessage, Goal, QuizAttempt, Roadmap
from app.services.adaptive_service import adaptive_service
from app.services.auth_service import auth_service
from app.services.dashboard_service import dashboard_service
from app.services.llm_service import llm_service

MAX_HISTORY_TURNS = 12  # messages of context sent to the model each turn


class ChatService:
    """Builds live learner context (goal, roadmap phase, mastery, quiz
    performance) and drives the AI tutor chat through the local LLM.
    Conversation history is persisted per user+goal so the tutor keeps
    continuity across sessions."""

    # ------------------------------------------------------------------
    # Context
    # ------------------------------------------------------------------

    def _resolve_goal_id(self, profile: dict, goal_id: str = None) -> str:
        return goal_id or profile.get("goal_id")

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

        skills_mastery = dashboard_service._skills_mastery(user_id)
        strong_skills = [s["skill_name"] for s in skills_mastery if s["mastery_pct"] >= 70][:5]
        weak_skills = [s["skill_name"] for s in skills_mastery if s["mastery_pct"] < 70][:5]

        db = SessionLocal()
        try:
            recent_quizzes = (
                db.query(QuizAttempt)
                .filter(QuizAttempt.user_id == str(user_id))
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

        reply = llm_service.chat(system_prompt, history, message.strip())

        db = SessionLocal()
        try:
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
