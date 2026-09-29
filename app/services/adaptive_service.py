import json

from app.db.database import SessionLocal
from app.db.models import QuizAttempt, Roadmap
from app.services.auth_service import auth_service
from app.services.dashboard_service import dashboard_service
from app.services.link_validator import filter_valid_resources
from app.services.llm_service import llm_service
from app.services.web_search_service import web_search_service
from app.utils.logger import logger

WEAK_MASTERY_THRESHOLD = 50   # below this, a skill counts as "weak"
STRONG_MASTERY_THRESHOLD = 85  # at/above this, learner may be ready to move faster
LOW_QUIZ_THRESHOLD = 50        # quiz score below this signals real struggle


class AdaptiveService:
    """Single decision engine for 'what should this learner do next.'
    Reads current mastery + latest quiz performance for the learner's
    current roadmap phase and turns that into one concrete recommendation.
    The roadmap page, the quiz result screen, and the AI tutor's own
    'what should I learn next' answer all read from this same place —
    that's what makes the recommendation adaptive rather than decorative."""

    # ------------------------------------------------------------------
    # Recommendation
    # ------------------------------------------------------------------

    def _resolve_goal_id(self, profile: dict, goal_id: str = None) -> str:
        return goal_id or (profile.get("goal_id") if profile else None)

    def _load_roadmap(self, user_id: str, goal_id: str):
        db = SessionLocal()
        try:
            row = (
                db.query(Roadmap)
                .filter(Roadmap.user_id == str(user_id), Roadmap.goal_id == str(goal_id))
                .first()
            )
            if not row:
                return None
            try:
                return json.loads(row.data)
            except (json.JSONDecodeError, TypeError):
                return None
        finally:
            db.close()

    def _evaluate_phase(self, user_id: str, goal_id: str, phases: list, phase_index: int) -> dict:
        """Core decision logic for ONE specific phase index. Used both by
        get_recommendation (for the guessed 'current' phase) and directly
        after a quiz submission (for the exact phase just quizzed — which
        is not always the same phase, since a learner can quiz any phase,
        not only the current one)."""

        phase = phases[phase_index]
        phase_title = phase.get("title")
        phase_skills = phase.get("skills", []) or []

        mastery_rows = dashboard_service._skills_mastery(user_id)
        mastery_map = {m["skill_name"].strip().lower(): m["mastery_pct"] for m in mastery_rows}

        phase_mastery_vals = [mastery_map.get(s.strip().lower()) for s in phase_skills]
        phase_mastery_vals = [v for v in phase_mastery_vals if v is not None]
        avg_mastery = round(sum(phase_mastery_vals) / len(phase_mastery_vals)) if phase_mastery_vals else None

        weak_skills = [
            s for s in phase_skills
            if mastery_map.get(s.strip().lower(), 0) < WEAK_MASTERY_THRESHOLD
        ]

        db = SessionLocal()
        try:
            latest_quiz = (
                db.query(QuizAttempt)
                .filter(
                    QuizAttempt.user_id == str(user_id),
                    QuizAttempt.goal_id == str(goal_id),
                    QuizAttempt.phase_index == phase_index,
                )
                .order_by(QuizAttempt.created_at.desc())
                .first()
            )
        finally:
            db.close()

        result = {
            "goal_id": goal_id,
            "phase_index": phase_index,
            "phase_title": phase_title,
            "weak_skills": weak_skills,
            "avg_mastery": avg_mastery,
        }

        # --- Decision ---
        # A bad quiz just now is sufficient signal on its own — don't also
        # require smoothed mastery to already read "weak". The mastery
        # blend is deliberately dampened (resists one-off swings), so a
        # single 0% quiz might only pull mastery from 80% to 60%, which
        # wouldn't clear WEAK_MASTERY_THRESHOLD even though the quiz was a
        # flat failure. If mastery-based weak_skills came up empty despite
        # a bad score, fall back to every skill this quiz actually covered.
        if latest_quiz and latest_quiz.score_pct < LOW_QUIZ_THRESHOLD:
            remedial_skills = weak_skills or phase_skills
            result["weak_skills"] = remedial_skills
            result["type"] = "remedial"
            result["message"] = (
                f"You scored {latest_quiz.score_pct}% on the \"{phase_title}\" quiz. A short review phase "
                f"covering {', '.join(remedial_skills)} before continuing would help."
            )
            return result

        if (
            avg_mastery is not None and avg_mastery >= STRONG_MASTERY_THRESHOLD
            and (latest_quiz is None or latest_quiz.score_pct >= STRONG_MASTERY_THRESHOLD)
            and phase_index + 1 < len(phases)
        ):
            result["type"] = "skip_ahead"
            result["next_phase_title"] = phases[phase_index + 1].get("title")
            result["message"] = (
                f"Mastery in \"{phase_title}\" is strong (~{avg_mastery}% average) — you're ready to move "
                f"faster into \"{result['next_phase_title']}\"."
            )
            return result

        result["type"] = "continue"
        if weak_skills:
            result["message"] = (
                f"Keep working through \"{phase_title}\" — focus on {', '.join(weak_skills)} before moving on."
            )
        else:
            result["message"] = f"Keep working through \"{phase_title}\"."
        return result

    def get_recommendation(self, user_id: str, goal_id: str = None) -> dict:
        """Recommendation for the learner's current phase (first incomplete
        phase, else the last one) — used for the dashboard/chat 'what's
        next overall' view."""

        profile = auth_service.get_user_by_id(user_id)
        target_goal_id = self._resolve_goal_id(profile or {}, goal_id)

        base = {
            "type": "none",
            "goal_id": target_goal_id,
            "phase_index": None,
            "phase_title": None,
            "weak_skills": [],
            "avg_mastery": None,
            "message": "No active learning goal yet — start one to get a personalized recommendation.",
        }

        if not target_goal_id:
            return base

        roadmap = self._load_roadmap(user_id, target_goal_id)
        phases = (roadmap or {}).get("phases", []) if roadmap else []
        if not phases:
            base["message"] = "No roadmap yet for this goal — generate one to get started."
            return base

        # Current phase = first incomplete, else the last one.
        phase_index = None
        for i, phase in enumerate(phases):
            if not phase.get("completed"):
                phase_index = i
                break
        if phase_index is None:
            phase_index = len(phases) - 1

        return self._evaluate_phase(user_id, target_goal_id, phases, phase_index)

    def get_recommendation_for_phase(self, user_id: str, goal_id: str, phase_index: int) -> dict:
        """Recommendation for a SPECIFIC phase — used right after a quiz
        submission, since the quizzed phase isn't always the 'current'
        one (a learner can practice-quiz any unlocked phase)."""

        roadmap = self._load_roadmap(user_id, goal_id)
        phases = (roadmap or {}).get("phases", []) if roadmap else []
        if not 0 <= phase_index < len(phases):
            return {
                "type": "none", "goal_id": goal_id, "phase_index": phase_index,
                "phase_title": None, "weak_skills": [], "avg_mastery": None,
                "message": "Phase not found.",
            }
        return self._evaluate_phase(user_id, goal_id, phases, phase_index)

    # ------------------------------------------------------------------
    # Acting on the recommendation: remedial phase insertion
    # ------------------------------------------------------------------

    def insert_remedial_phase(self, user_id: str, goal_id: str, phase_index: int) -> dict:
        """Inserts a short, LLM-generated review phase right after
        phase_index, targeting whatever skills the recommendation engine
        currently flags as weak for that phase. Re-derives the weak skills
        itself rather than trusting a client-supplied list."""

        recommendation = self.get_recommendation_for_phase(user_id, goal_id, phase_index)
        if recommendation.get("type") != "remedial" or not recommendation.get("weak_skills"):
            raise ValueError("No remedial recommendation currently applies to this phase")

        weak_skills = recommendation["weak_skills"]
        profile = auth_service.get_user_by_id(user_id) or {}

        db = SessionLocal()
        try:
            row = (
                db.query(Roadmap)
                .filter(Roadmap.user_id == str(user_id), Roadmap.goal_id == str(goal_id))
                .first()
            )
            if not row:
                raise ValueError("Roadmap not found")

            roadmap = json.loads(row.data)
            phases = roadmap.get("phases", [])
            if not 0 <= phase_index < len(phases):
                raise ValueError("Phase not found")

            latest_quiz = (
                db.query(QuizAttempt)
                .filter(
                    QuizAttempt.user_id == str(user_id),
                    QuizAttempt.goal_id == str(goal_id),
                    QuizAttempt.phase_index == phase_index,
                )
                .order_by(QuizAttempt.created_at.desc())
                .first()
            )

            try:
                verified_resources = web_search_service.search_courses(weak_skills)
            except Exception as exc:
                logger.error(f"Live web search failed for remedial phase, continuing without it: {exc}")
                verified_resources = []

            remedial_phase = llm_service.generate_remedial_phase({
                "weak_skills": weak_skills,
                "phase_skills": phases[phase_index].get("skills", []),
                "score_pct": latest_quiz.score_pct if latest_quiz else None,
                "experience_level": profile.get("experience_level") or "beginner",
                "learning_style": profile.get("learning_style") or "visual",
                "verified_live_resources": verified_resources,
            })

            if remedial_phase.get("resources"):
                remedial_phase["resources"] = filter_valid_resources(remedial_phase["resources"])
            remedial_phase["completed"] = False
            remedial_phase["is_remedial"] = True

            phases.insert(phase_index + 1, remedial_phase)
            roadmap["phases"] = phases

            # Any quiz attempts recorded against phases AFTER the insertion
            # point now point at the wrong phase unless shifted forward.
            (
                db.query(QuizAttempt)
                .filter(
                    QuizAttempt.user_id == str(user_id),
                    QuizAttempt.goal_id == str(goal_id),
                    QuizAttempt.phase_index > phase_index,
                )
                .update({QuizAttempt.phase_index: QuizAttempt.phase_index + 1}, synchronize_session=False)
            )

            row.data = json.dumps(roadmap)
            db.commit()

            roadmap["goal_id"] = goal_id
            return roadmap
        finally:
            db.close()


adaptive_service = AdaptiveService()
