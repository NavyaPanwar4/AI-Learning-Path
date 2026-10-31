import json

from app.services.phase_identity import ensure_phase_ids, backfill_attempt_phase_ids, shift_attempt_indices_after_insertion

from app.db.database import SessionLocal
from app.db.models import QuizAttempt, Roadmap
from app.services.auth_service import auth_service
from app.services.dashboard_service import dashboard_service
from app.services.link_validator import filter_valid_resources
from app.services.link_validator import deduplicate_resources_across_phases
from app.services.llm_service import llm_service
from app.services.web_search_service import web_search_service
from app.utils.logger import logger

WEAK_MASTERY_THRESHOLD = 50   # below this, a skill counts as "weak"
STRONG_MASTERY_THRESHOLD = 85  # at/above this, learner may be ready to move faster
LOW_QUIZ_THRESHOLD = 50        # quiz score below this signals real struggle
QUIZ_DIFFICULTIES = ("beginner", "intermediate", "advanced")
MIN_BKT_EVIDENCE = 4           # labelled answers needed before mastery may move the quiz level
HIGH_MASTERY_FOR_HARDER = 80   # average phase mastery (%) at/above which quizzes get harder
LOW_MASTERY_FOR_EASIER = 40    # average phase mastery (%) below which quizzes get lighter


class AdaptiveService:
    """Single decision engine for 'what should this learner do next.'
    Reads current mastery + latest quiz performance for the learner's
    current roadmap phase and turns that into one concrete recommendation.
    The roadmap page, the quiz result screen, and the AI tutor's own
    'what should I learn next' answer all read from this same place —
    that's what makes the recommendation adaptive rather than decorative."""

    @staticmethod
    def _latest_attempt_for_phase(db, user_id: str, goal_id: str, phase: dict, phase_index: int):
        from sqlalchemy import and_, or_
        query = db.query(QuizAttempt).filter(QuizAttempt.user_id == str(user_id), QuizAttempt.goal_id == str(goal_id))
        phase_id = phase.get("phase_id") if isinstance(phase, dict) else None
        if phase_id:
            query = query.filter(or_(QuizAttempt.phase_id == phase_id, and_(QuizAttempt.phase_id.is_(None), QuizAttempt.phase_index == phase_index)))
        else:
            query = query.filter(QuizAttempt.phase_index == phase_index)
        return query.order_by(QuizAttempt.created_at.desc()).first()

    # ------------------------------------------------------------------
    # Recommendation
    # ------------------------------------------------------------------

    @staticmethod
    def _skill_label(skill) -> str:
        if isinstance(skill, dict):
            skill = skill.get("name") or skill.get("skill_name") or ""
        return str(skill or "").strip().lower()

    @staticmethod
    def difficulty_step(latest_score, average_mastery, evidence_count):
        """Return (step, reason) with step in {-1, 0, +1}.

        Two independent signals: the latest quiz score for this phase, and the
        goal-scoped BKT mastery of the phase's skills. Mastery is trusted only
        once there are at least MIN_BKT_EVIDENCE labelled answers behind it;
        one lucky or unlucky quiz must not swing the level on its own. When the
        two signals disagree they cancel, and when they agree the level moves
        by one step, never two.
        """
        score_step, score_note = 0, None
        if latest_score is not None:
            if latest_score < LOW_QUIZ_THRESHOLD:
                score_step, score_note = -1, f"your latest score was {latest_score}%"
            elif latest_score >= STRONG_MASTERY_THRESHOLD:
                score_step, score_note = 1, f"your latest score was {latest_score}%"
            else:
                score_note = f"your latest score was {latest_score}%"

        mastery_step, mastery_note = 0, None
        if average_mastery is not None and evidence_count >= MIN_BKT_EVIDENCE:
            if average_mastery >= HIGH_MASTERY_FOR_HARDER:
                mastery_step, mastery_note = 1, f"your tracked mastery of this phase is {average_mastery}%"
            elif average_mastery < LOW_MASTERY_FOR_EASIER:
                mastery_step, mastery_note = -1, f"your tracked mastery of this phase is {average_mastery}%"
            else:
                mastery_note = f"your tracked mastery of this phase is {average_mastery}%"

        total = score_step + mastery_step
        step = max(-1, min(1, total))
        notes = [n for n in (score_note, mastery_note) if n]
        if not notes:
            return 0, "Based on your profile"
        joined = " and ".join(notes)
        joined = joined[0].upper() + joined[1:]
        if step > 0:
            return step, f"{joined}, so the next quiz is harder."
        if step < 0:
            return step, f"{joined}, so the next quiz is lighter."
        if score_step and mastery_step:
            return 0, f"{joined} point in different directions, so the quiz stays at a steady level."
        return 0, f"{joined}, so the quiz stays at a steady level."

    def get_quiz_difficulty(self, user_id: str, goal_id: str, phase_index: int) -> dict:
        """Choose the next quiz level from the profile, the latest score and BKT mastery."""
        profile = auth_service.get_user_by_id(user_id) or {}
        preferred = (profile.get("preferred_difficulty") or profile.get("experience_level") or "beginner").lower()
        aliases = {"basic": "beginner", "easy": "beginner", "medium": "intermediate", "hard": "advanced"}
        difficulty = aliases.get(preferred, preferred)
        if difficulty not in QUIZ_DIFFICULTIES:
            difficulty = "beginner"

        roadmap = self._load_roadmap(user_id, goal_id)
        phases = (roadmap or {}).get("phases", []) if roadmap else []
        phase_skills = phases[phase_index].get("skills", []) if 0 <= phase_index < len(phases) else []
        wanted = {self._skill_label(skill) for skill in phase_skills} - {""}

        # Goal-scoped (never another goal's) decayed mastery for this phase's skills.
        mastery_rows = dashboard_service._skills_mastery(user_id, goal_id)
        phase_rows = [row for row in mastery_rows if row["skill_name"].strip().lower() in wanted]
        mastery_values = [row["mastery_pct"] for row in phase_rows]
        average_mastery = round(sum(mastery_values) / len(mastery_values)) if mastery_values else None
        evidence_count = sum(int(row.get("bkt_observations") or 0) for row in phase_rows)

        db = SessionLocal()
        try:
            phase = phases[phase_index] if 0 <= phase_index < len(phases) else {}
            latest_quiz = self._latest_attempt_for_phase(db, user_id, goal_id, phase, phase_index)
            latest_score = latest_quiz.score_pct if latest_quiz else None
        finally:
            db.close()

        step, reason = self.difficulty_step(latest_score, average_mastery, evidence_count)
        difficulty = QUIZ_DIFFICULTIES[max(0, min(len(QUIZ_DIFFICULTIES) - 1, QUIZ_DIFFICULTIES.index(difficulty) + step))]

        return {
            "difficulty": difficulty,
            "reason": reason,
            "average_mastery": average_mastery,
            "evidence_count": evidence_count,
            "confident": evidence_count >= MIN_BKT_EVIDENCE,
        }

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
                roadmap = json.loads(row.data)
                changed = ensure_phase_ids(roadmap)
                if changed:
                    row.data = json.dumps(roadmap, ensure_ascii=False)
                    db.commit()
                return roadmap
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
            phase = phases[phase_index] if 0 <= phase_index < len(phases) else {}
            latest_quiz = self._latest_attempt_for_phase(db, user_id, goal_id, phase, phase_index)
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

            try:
                roadmap = json.loads(row.data)
            except (json.JSONDecodeError, TypeError) as exc:
                raise ValueError("Saved roadmap data is invalid. Please regenerate the roadmap.") from exc
            ensure_phase_ids(roadmap)
            phases = roadmap.get("phases", [])
            if not 0 <= phase_index < len(phases):
                raise ValueError("Phase not found")

            source_title = phases[phase_index].get("title")
            if phase_index + 1 < len(phases):
                next_phase = phases[phase_index + 1]
                if next_phase.get("is_remedial") and next_phase.get("remedial_for") == source_title:
                    roadmap["goal_id"] = row.goal_id
                    roadmap["goal_name"] = row.goal_name or roadmap.get("goal_name") or "Learning Roadmap"
                    return roadmap

            latest_quiz = self._latest_attempt_for_phase(db, user_id, goal_id, phases[phase_index], phase_index)

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
            remedial_phase["remedial_for"] = source_title
            import uuid
            remedial_phase.setdefault("phase_id", str(uuid.uuid4()))

            # Resolve index-only attempts to stable IDs before changing ordinals.
            goal_attempts = db.query(QuizAttempt).filter(QuizAttempt.user_id == str(user_id), QuizAttempt.goal_id == str(goal_id)).all()
            backfill_attempt_phase_ids(goal_attempts, phases)

            phases.insert(phase_index + 1, remedial_phase)
            roadmap["phases"] = phases
            roadmap = deduplicate_resources_across_phases(roadmap)

            # Keep legacy ordinal indices aligned; phase_id remains the identity.
            shift_attempt_indices_after_insertion(goal_attempts, phase_index)
            # QuizQuestionHistory follows attempt_id; ReviewSchedule is skill-scoped, not phase-indexed.

            row.data = json.dumps(roadmap)
            db.commit()

            roadmap["goal_id"] = goal_id
            roadmap["goal_name"] = row.goal_name or roadmap.get("goal_name") or "Learning Roadmap"
            return roadmap
        finally:
            db.close()


adaptive_service = AdaptiveService()
