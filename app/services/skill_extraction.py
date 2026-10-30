from app.utils.time import utcnow_naive
import uuid
import math
from datetime import datetime
from typing import Dict, List

from app.db.database import SessionLocal
from app.db.models import (
    Skill,
    UserSkill,
    GoalUserSkill,
    QuizAttempt,
    QuizQuestionHistory,
)
from app.models.schemas import ExtractedSkill
from app.services.embeddings_service import embeddings_service
from app.services.llm_service import llm_service
from app.services.mastery_decay import decay_mastery, load_last_reviewed_at_by_skill, normalize_skill_name
from app.services.bkt_parameters import get_bkt_parameters


class SkillExtractionService:
    def _semantic_match_list(self, db, skill_list, master_skills):
        matched_results = {}

        # Encode the catalogue once per batch rather than once per skill —
        # re-encoding the whole catalogue on every lookup is the main
        # performance trap with embedding-based matching. Skills added to
        # master_skills partway through this same batch (see below) won't
        # be matchable against each other within the batch, which mirrors
        # how the previous fuzzy-matching version behaved in practice.
        choices = list(master_skills.keys())
        choice_embeddings = embeddings_service.encode(choices) if choices else None

        for skill in skill_list:
            skill_name = skill.get("skill_name", "")
            confidence = float(skill.get("confidence", 0.8) or 0.8)
            if confidence > 1:
                confidence /= 100
            confidence = max(0.0, min(1.0, confidence))

            best_match_id = None
            semantic_score = None
            if choices and skill_name:
                exact_key = next((choice for choice in choices if choice.casefold() == str(skill_name).casefold()), None)
                if exact_key:
                    best_match_id = master_skills[exact_key]
                    semantic_score = 1.0
                    primary = db.query(Skill).filter(Skill.skill_id == best_match_id).first()
                    if primary:
                        skill_name = primary.skill_name
                best_match_string, score = embeddings_service.best_match_precomputed(
                    skill_name, choices, choice_embeddings
                )

                if not best_match_id and best_match_string:
                    best_match_id = master_skills[best_match_string]
                    semantic_score = score

                    primary = db.query(Skill).filter(Skill.skill_id == best_match_id).first()
                    if primary:
                        skill_name = primary.skill_name

            if not best_match_id and skill_name:
                existing_key = next((choice for choice in master_skills if choice.casefold() == str(skill_name).casefold()), None)
                if existing_key:
                    best_match_id = master_skills[existing_key]
                else:
                    best_match_id = str(uuid.uuid4())
                    db.add(Skill(skill_id=best_match_id, skill_name=skill_name, category="Extracted"))
                    master_skills[skill_name] = best_match_id

            if best_match_id:
                final_confidence = max(0.0, min(1.0, float(semantic_score))) if semantic_score is not None else confidence
                candidate = ExtractedSkill(skill_name=skill_name, matched_skill_id=best_match_id, confidence=final_confidence)
                previous = matched_results.get(best_match_id)
                if previous is None or candidate.confidence > previous.confidence:
                    matched_results[best_match_id] = candidate
        return list(matched_results.values())

    def extract_and_match(self, user_id: str, free_text: str) -> Dict[str, List[ExtractedSkill]]:
        # 1. Ask LLM to extract skills from free_text
        llm_response = llm_service.extract_skills(free_text)
        extracted = llm_response.get("extracted_skills", [])
        desired = llm_response.get("desired_skills", [])

        db = SessionLocal()
        try:
            # 2. Build master skills lookup (name/alias -> skill_id)
            master_skills = {}
            for s in db.query(Skill).all():
                master_skills[s.skill_name] = s.skill_id
                if s.aliases:
                    for alias in s.aliases.split(","):
                        if alias.strip():
                            master_skills[alias.strip()] = s.skill_id

            # 3. Fuzzy match
            matched_extracted = self._semantic_match_list(db, extracted, master_skills)
            matched_desired = self._semantic_match_list(db, desired, master_skills)

            # 4. Store possessed skills only
            added_skill_ids = set()
            for es in matched_extracted:
                if es.matched_skill_id in added_skill_ids:
                    continue
                exists = (
                    db.query(UserSkill)
                    .filter(UserSkill.user_id == user_id, UserSkill.skill_id == es.matched_skill_id)
                    .first()
                )
                if not exists:
                    db.add(UserSkill(user_id=user_id, skill_id=es.matched_skill_id, proficiency=1, mastery_probability=None, bkt_observations=0))
                    added_skill_ids.add(es.matched_skill_id)
            db.commit() 

            return {"extracted_skills": matched_extracted, "desired_skills": matched_desired}
        finally:
            db.close()

    def _historical_goal_evidence(self, db, user_id: str, goal_id: str, skill_name: str, exclude_attempt_id=None) -> list[bool]:
        """Return only explicitly labelled per-question evidence for this goal/skill."""
        query = (
            db.query(
                QuizQuestionHistory.skill_name,
                QuizQuestionHistory.is_correct,
                QuizAttempt.created_at,
                QuizQuestionHistory.question_index,
                QuizQuestionHistory.id,
                QuizAttempt.id,
            )
            .join(QuizAttempt, QuizQuestionHistory.attempt_id == QuizAttempt.id)
            .filter(
                QuizAttempt.user_id == str(user_id),
                QuizAttempt.goal_id == str(goal_id),
                QuizQuestionHistory.skill_name.isnot(None),
            )
            .order_by(QuizAttempt.created_at, QuizQuestionHistory.question_index, QuizQuestionHistory.id)
        )
        if exclude_attempt_id is not None:
            query = query.filter(QuizAttempt.id != int(exclude_attempt_id))
        target = normalize_skill_name(skill_name)
        return [
            bool(is_correct)
            for recorded_name, is_correct, *_ in query.all()
            if normalize_skill_name(recorded_name) == target
        ]

    def update_proficiency_from_quiz(
        self,
        user_id: str,
        skill_names: List[str],
        score_pct: int | None = None,
        db=None,
        question_results=None,
        last_reviewed_at_by_skill=None,
        goal_id: str | None = None,
        current_attempt_id: int | None = None,
    ) -> List[dict]:
        """Update mastery strictly from per-question evidence within one goal.

        Aggregate quiz percentage is intentionally not used as a BKT response.
        Skills with no explicitly labelled responses are left unchanged. When a
        goal/skill state is first created, its earlier labelled history for that
        same goal is replayed; other goals and aggregate-only attempts are never
        used to initialize it.
        """
        if not skill_names or goal_id is None:
            return []

        question_results = question_results or []
        updated = []
        owns_session = db is None
        db = db or SessionLocal()
        try:
            params = get_bkt_parameters(db)
            last_reviewed = (
                last_reviewed_at_by_skill
                if last_reviewed_at_by_skill is not None
                else load_last_reviewed_at_by_skill(db, str(user_id), str(goal_id))
            )
            now = utcnow_naive()
            for requested_name in dict.fromkeys(str(name).strip() for name in skill_names if name and str(name).strip()):
                requested_key = normalize_skill_name(requested_name)
                if not requested_key:
                    continue

                skill = db.query(Skill).filter(Skill.skill_name.ilike(requested_name)).first()
                canonical_key = normalize_skill_name(skill.skill_name) if skill else requested_key
                evidence = [
                    bool(item.get("is_correct"))
                    for item in question_results
                    if normalize_skill_name(item.get("skill_name")) in {requested_key, canonical_key}
                    and item.get("skill_name") is not None
                ]
                # No aggregate-score fallback: no labelled question means no BKT observation.
                if not evidence:
                    continue

                if skill is None:
                    skill = Skill(
                        skill_id=str(uuid.uuid4()),
                        skill_name=requested_name,
                        category="Learned from Quiz",
                    )
                    db.add(skill)
                    db.flush()

                name_key = normalize_skill_name(skill.skill_name)
                goal_skill = (
                    db.query(GoalUserSkill)
                    .filter(
                        GoalUserSkill.user_id == str(user_id),
                        GoalUserSkill.goal_id == str(goal_id),
                        GoalUserSkill.skill_id == str(skill.skill_id),
                    )
                    .first()
                )
                if goal_skill is None:
                    # Backfill only from labelled history for this user + goal + skill.
                    historical = self._historical_goal_evidence(
                        db, str(user_id), str(goal_id), skill.skill_name,
                        exclude_attempt_id=current_attempt_id,
                    )
                    probability = params.p_initial
                    for was_correct in historical:
                        probability = self.bkt_update(
                            probability, was_correct,
                            p_learn=params.p_learn, p_guess=params.p_guess, p_slip=params.p_slip,
                        )
                    goal_skill = GoalUserSkill(
                        user_id=str(user_id), goal_id=str(goal_id), skill_id=str(skill.skill_id),
                        proficiency=max(1, min(5, math.ceil(probability * 5))),
                        mastery_probability=probability,
                        bkt_observations=len(historical),
                    )
                    db.add(goal_skill)
                    db.flush()
                else:
                    historical = []
                    # A prior-only row may have been created when a roadmap was
                    # completed. If labelled evidence already exists, rebuild
                    # that goal state from its own history before adding this quiz.
                    if int(goal_skill.bkt_observations or 0) == 0:
                        historical = self._historical_goal_evidence(
                            db, str(user_id), str(goal_id), skill.skill_name,
                            exclude_attempt_id=current_attempt_id,
                        )
                        if historical:
                            probability = params.p_initial
                            for was_correct in historical:
                                probability = self.bkt_update(
                                    probability, was_correct,
                                    p_learn=params.p_learn, p_guess=params.p_guess, p_slip=params.p_slip,
                                )
                            goal_skill.mastery_probability = probability
                            goal_skill.proficiency = max(1, min(5, math.ceil(probability * 5)))
                            goal_skill.bkt_observations = len(historical)

                old_probability = max(0.0, min(1.0, float(goal_skill.mastery_probability if goal_skill.mastery_probability is not None else params.p_initial)))
                old_probability = decay_mastery(
                    old_probability,
                    last_reviewed.get(name_key) or last_reviewed.get(requested_key),
                    now=now,
                )
                probability = old_probability
                for was_correct in evidence:
                    probability = self.bkt_update(
                        probability, was_correct,
                        p_learn=params.p_learn, p_guess=params.p_guess, p_slip=params.p_slip,
                    )

                new_level = max(1, min(5, math.ceil(probability * 5)))
                goal_skill.mastery_probability = probability
                goal_skill.proficiency = new_level
                goal_skill.bkt_observations = (goal_skill.bkt_observations or 0) + len(evidence)

                # Keep the legacy UserSkill row only as a global possessed-skill/profile record.
                profile_skill = db.query(UserSkill).filter(
                    UserSkill.user_id == str(user_id), UserSkill.skill_id == str(skill.skill_id)
                ).first()
                if profile_skill is None:
                    db.add(UserSkill(
                        user_id=str(user_id), skill_id=str(skill.skill_id), proficiency=1,
                        mastery_probability=None, bkt_observations=0,
                    ))

                updated.append({
                    "skill_name": skill.skill_name,
                    "goal_id": str(goal_id),
                    "new_level": new_level,
                    "mastery_pct": round(probability * 100),
                    "observations_applied": len(evidence),
                    "parameter_source": params.source,
                    "direction": "up" if probability > old_probability else "down" if probability < old_probability else "unchanged",
                })
            if owns_session:
                db.commit()
            return updated
        except Exception:
            if owns_session:
                db.rollback()
            raise
        finally:
            if owns_session:
                db.close()

    @staticmethod
    def bkt_update(
        probability: float,
        correct: bool,
        p_learn: float | None = None,
        p_guess: float | None = None,
        p_slip: float | None = None,
    ) -> float:
        """Return P(known) after one response and one learning transition."""
        from app.services.bkt_parameters import default_bkt_parameters
        defaults = default_bkt_parameters()
        p_learn = defaults.p_learn if p_learn is None else p_learn
        p_guess = defaults.p_guess if p_guess is None else p_guess
        p_slip = defaults.p_slip if p_slip is None else p_slip
        probability = max(0.0, min(1.0, probability))
        if correct:
            denominator = probability * (1 - p_slip) + (1 - probability) * p_guess
            posterior = (probability * (1 - p_slip)) / denominator if denominator else probability
        else:
            denominator = probability * p_slip + (1 - probability) * (1 - p_guess)
            posterior = (probability * p_slip) / denominator if denominator else probability
        return max(0.0, min(1.0, posterior + (1 - posterior) * p_learn))

    def delete_user_skill(self, user_id: str, skill_id: str) -> bool:
        db = SessionLocal()
        try:
            row = (
                db.query(UserSkill)
                .filter(UserSkill.user_id == str(user_id), UserSkill.skill_id == str(skill_id))
                .first()
            )
            if not row:
                return False
            db.delete(row)
            db.commit()
            return True
        finally:
            db.close()


skill_extraction_service = SkillExtractionService()
