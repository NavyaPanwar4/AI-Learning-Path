import json
import uuid

from app.db.database import SessionLocal
from app.db.models import Goal, Roadmap, Skill, UserSkill
from app.services.activity_service import activity_service
from app.services.auth_service import auth_service
from app.services.gap_analysis import gap_analysis_service
from app.services.link_validator import filter_valid_resources
from app.services.llm_service import llm_service
from app.services.web_search_service import web_search_service


class RoadmapService:
    def generate_personalized_roadmap(self, user_id: str):
        # 1. Load user profile
        user_profile = auth_service.get_user_by_id(user_id)
        if not user_profile:
            raise ValueError("User not found")

        goal_id = str(user_profile.get("goal_id") or "default")

        db = SessionLocal()
        try:
            goal = db.query(Goal).filter(Goal.goal_id == goal_id).first()
            goal_name = goal.goal_name if goal else "Unknown Goal"

            # 2. Identify missing + possessed skills
            missing_skills = gap_analysis_service.identify_missing_skills(user_id)

            possessed_skill_ids = [
                us.skill_id for us in db.query(UserSkill).filter(UserSkill.user_id == str(user_id)).all()
            ]
            possessed_skills = []
            for sid in possessed_skill_ids:
                skill = db.query(Skill).filter(Skill.skill_id == str(sid)).first()
                if skill:
                    possessed_skills.append(skill.skill_name)
        finally:
            db.close()

        # 3. Retrieve RAG context
        try:
            verified_live_resources = web_search_service.search_courses(missing_skills)
        except Exception as exc:
            from app.utils.logger import logger
            logger.error(f"Live web search failed, continuing without it: {exc}")
            verified_live_resources = []

        # 4. Construct context for LLM
        context = {
            "experience_level": user_profile.get("experience_level"),
            "available_hours_per_week": user_profile.get("available_hours_per_week"),
            "learning_style": user_profile.get("learning_style"),
            "missing_skills": missing_skills,
            "possessed_skills": possessed_skills,
            "verified_live_resources": verified_live_resources,
            "goal_skill_name": goal_name,
        }

        # 5. Generate roadmap via LLM (designs its own projects; picks from/around
        # the verified live resources above)
        roadmap_dict = llm_service.generate_roadmap(context)

        # 5.5 Belt-and-suspenders: re-validate every resource link the LLM actually
        # output, in case it added one beyond the pre-verified list.
        if isinstance(roadmap_dict, dict):
            for phase in roadmap_dict.get("phases", []):
                if phase.get("resources"):
                    phase["resources"] = filter_valid_resources(phase["resources"])

        # 6. Upsert into DB (replaces the old per-user JSON cache file)
        if roadmap_dict and (roadmap_dict.get("phases") or roadmap_dict.get("roadmap_text")):
            db = SessionLocal()
            try:
                existing = (
                    db.query(Roadmap)
                    .filter(Roadmap.user_id == str(user_id), Roadmap.goal_id == goal_id)
                    .first()
                )
                if existing:
                    existing.data = json.dumps(roadmap_dict)
                    existing.goal_name = goal_name
                    existing.is_complete = False
                else:
                    db.add(
                        Roadmap(
                            user_id=str(user_id),
                            goal_id=goal_id,
                            goal_name=goal_name,
                            data=json.dumps(roadmap_dict),
                            is_complete=False,
                        )
                    )
                db.commit()
            except Exception:
                db.rollback()
            finally:
                db.close()

        activity_service.log_activity(user_id, "roadmap_generated")
        return roadmap_dict

    def get_saved_roadmaps(self, user_id: str):
        db = SessionLocal()
        try:
            rows = db.query(Roadmap).filter(Roadmap.user_id == str(user_id)).all()
            return [
                {"goal_id": r.goal_id, "goal_name": r.goal_name, "is_complete": r.is_complete} for r in rows
            ]
        finally:
            db.close()

    def get_saved_roadmap(self, user_id: str, goal_id: str):
        db = SessionLocal()
        try:
            row = (
                db.query(Roadmap)
                .filter(Roadmap.user_id == str(user_id), Roadmap.goal_id == str(goal_id))
                .first()
            )
            if not row:
                return None
            roadmap = json.loads(row.data)
            roadmap["goal_id"] = row.goal_id
            return roadmap
        finally:
            db.close()

    def delete_roadmap(self, user_id: str, goal_id: str) -> bool:
        db = SessionLocal()
        try:
            row = (
                db.query(Roadmap)
                .filter(Roadmap.user_id == str(user_id), Roadmap.goal_id == str(goal_id))
                .first()
            )
            if not row:
                return False
            db.delete(row)
            db.commit()
            return True
        finally:
            db.close()

    def update_phase_status(self, user_id: str, goal_id: str, phase_index: int, completed: bool):
        db = SessionLocal()
        try:
            row = (
                db.query(Roadmap)
                .filter(Roadmap.user_id == str(user_id), Roadmap.goal_id == str(goal_id))
                .first()
            )
            if not row:
                return None

            roadmap = json.loads(row.data)
            phases = roadmap.get("phases", [])
            if 0 <= phase_index < len(phases):
                phases[phase_index]["completed"] = completed

            row.data = json.dumps(roadmap)
            db.commit()
            return roadmap
        finally:
            db.close()

    def generate_phase_study_notes(self, user_id: str, goal_id: str, phase_index: int):
        """Generate and persist notes so learners do not pay for the same phase twice."""
        db = SessionLocal()
        try:
            row = (
                db.query(Roadmap)
                .filter(Roadmap.user_id == str(user_id), Roadmap.goal_id == str(goal_id))
                .first()
            )
            if not row:
                return None

            roadmap = json.loads(row.data)
            phases = roadmap.get("phases", [])
            if not 0 <= phase_index < len(phases):
                return None

            phase = phases[phase_index]
            if phase.get("ai_notes"):
                return phase["ai_notes"]

            profile = auth_service.get_user_by_id(user_id) or {}
            notes = llm_service.generate_study_notes(
                phase_title=phase.get("title", f"Phase {phase_index + 1}"),
                skills=phase.get("skills", []),
                duration=phase.get("duration", "At your own pace"),
                experience_level=profile.get("experience_level", "beginner"),
            )
            required_fields = {"title", "overview"}
            if not notes or not required_fields.issubset(notes):
                raise ValueError("Groq could not generate study notes. Please try again.")

            phase["ai_notes"] = notes
            row.data = json.dumps(roadmap)
            db.commit()
            return notes
        finally:
            db.close()

    def complete_roadmap(self, user_id: str, goal_id: str):
        db = SessionLocal()
        try:
            row = (
                db.query(Roadmap)
                .filter(Roadmap.user_id == str(user_id), Roadmap.goal_id == str(goal_id))
                .first()
            )
            if not row:
                return None

            roadmap = json.loads(row.data)
            roadmap["is_complete"] = True
            row.data = json.dumps(roadmap)
            row.is_complete = True
            db.commit()

            # Add learned skills
            try:
                learned_skills = set()
                for phase in roadmap.get("phases", []):
                    for skill in phase.get("skills", []):
                        learned_skills.add(skill)

                for skill_name in learned_skills:
                    skill = (
                        db.query(Skill).filter(Skill.skill_name.ilike(str(skill_name))).first()
                    )
                    if skill:
                        skill_id = skill.skill_id
                    else:
                        skill_id = str(uuid.uuid4())
                        db.add(Skill(skill_id=skill_id, skill_name=str(skill_name), category="Learned from Roadmap"))
                        db.commit()

                    exists = (
                        db.query(UserSkill)
                        .filter(UserSkill.user_id == str(user_id), UserSkill.skill_id == skill_id)
                        .first()
                    )
                    if not exists:
                        db.add(UserSkill(user_id=str(user_id), skill_id=skill_id, proficiency=1))
                db.commit()
            except Exception as e:
                from app.utils.logger import logger

                logger.error(f"Error adding learned skills on roadmap completion: {e}")
                db.rollback()

            activity_service.log_activity(user_id, "roadmap_completed")
            return roadmap
        finally:
            db.close()


roadmap_service = RoadmapService()
