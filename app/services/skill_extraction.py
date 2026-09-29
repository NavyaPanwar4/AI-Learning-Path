import uuid
from typing import Dict, List

from app.db.database import SessionLocal
from app.db.models import Skill, UserSkill
from app.models.schemas import ExtractedSkill
from app.services.embeddings_service import embeddings_service
from app.services.llm_service import llm_service


class SkillExtractionService:
    def _semantic_match_list(self, db, skill_list, master_skills):
        matched_results = []

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
            confidence = skill.get("confidence", 0.8)

            best_match_id = None
            if choices and skill_name:
                best_match_string, score = embeddings_service.best_match_precomputed(
                    skill_name, choices, choice_embeddings
                )

                if best_match_string:
                    best_match_id = master_skills[best_match_string]

                    primary = db.query(Skill).filter(Skill.skill_id == best_match_id).first()
                    if primary:
                        skill_name = primary.skill_name

            if not best_match_id and skill_name:
                best_match_id = str(uuid.uuid4())
                db.add(Skill(skill_id=best_match_id, skill_name=skill_name, category="Extracted"))
                db.commit()
                master_skills[skill_name] = best_match_id

            if best_match_id:
                matched_results.append(
                    ExtractedSkill(skill_name=skill_name, matched_skill_id=best_match_id, confidence=confidence)
                )
        return matched_results

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
                    db.add(UserSkill(user_id=user_id, skill_id=es.matched_skill_id, proficiency=1))
                    added_skill_ids.add(es.matched_skill_id)
            db.commit() 

            return {"extracted_skills": matched_extracted, "desired_skills": matched_desired}
        finally:
            db.close()

    def update_proficiency_from_quiz(self, user_id: str, skill_names: List[str], score_pct: int) -> List[dict]:
        """Maps a quiz score to a 1-5 proficiency level and moves each
        quizzed skill's mastery toward it — in EITHER direction. Weighted
        2:1 toward the prior level so a single unlucky quiz doesn't crater
        a skill the learner has otherwise demonstrated, but sustained poor
        performance genuinely pulls mastery back down (this is what makes
        the recommendation engine's signal real, not one-way ratcheting)."""
        if not skill_names:
            return []

        if score_pct >= 90:
            level = 5
        elif score_pct >= 75:
            level = 4
        elif score_pct >= 50:
            level = 3
        elif score_pct >= 25:
            level = 2
        else:
            level = 1

        updated = []
        db = SessionLocal()
        try:
            for name in skill_names:
                if not name:
                    continue
                skill = db.query(Skill).filter(Skill.skill_name.ilike(str(name))).first()
                if not skill:
                    skill = Skill(skill_id=str(uuid.uuid4()), skill_name=str(name), category="Learned from Quiz")
                    db.add(skill)
                    db.commit()

                user_skill = (
                    db.query(UserSkill)
                    .filter(UserSkill.user_id == str(user_id), UserSkill.skill_id == skill.skill_id)
                    .first()
                )
                old_level = user_skill.proficiency if user_skill else 0

                if old_level:
                    # Weighted toward the prior level — moves gradually in
                    # whichever direction repeated performance points.
                    new_level = round((old_level * 2 + level) / 3)
                else:
                    new_level = level
                new_level = max(1, min(5, new_level))

                if user_skill:
                    user_skill.proficiency = new_level
                else:
                    db.add(UserSkill(user_id=str(user_id), skill_id=skill.skill_id, proficiency=new_level))
                db.commit()

                if new_level != old_level:
                    updated.append({
                        "skill_name": skill.skill_name,
                        "new_level": new_level,
                        "direction": "up" if new_level > old_level else "down",
                    })
            return updated
        finally:
            db.close()

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
