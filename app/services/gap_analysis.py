from app.db.database import SessionLocal
from app.db.models import GoalSkill, Skill, SkillDependency, User, UserSkill


class GapAnalysisService:
    def identify_missing_skills(self, user_id: str) -> list:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.user_id == user_id).first()
            if not user or not user.goal_id:
                return []
            goal_id = user.goal_id

            current_skill_ids = {
                us.skill_id for us in db.query(UserSkill).filter(UserSkill.user_id == user_id).all()
            }
            target_skill_ids = {
                gs.skill_id for gs in db.query(GoalSkill).filter(GoalSkill.goal_id == goal_id).all()
            }

            if not target_skill_ids:
                return []

            missing_skill_ids = target_skill_ids - current_skill_ids

            # Enforce dependencies (if a missing skill has prerequisites, add them)
            dep_map = {}
            for d in db.query(SkillDependency).all():
                dep_map.setdefault(d.skill_id, []).append(d.prerequisite_id)

            added_deps = True
            while added_deps:
                added_deps = False
                for ms_id in list(missing_skill_ids):
                    for req in dep_map.get(ms_id, []):
                        if req not in current_skill_ids and req not in missing_skill_ids:
                            missing_skill_ids.add(req)
                            added_deps = True

            # Map IDs to names
            missing_skill_names = []
            for ms_id in missing_skill_ids:
                skill = db.query(Skill).filter(Skill.skill_id == ms_id).first()
                if skill:
                    missing_skill_names.append(skill.skill_name)

            return missing_skill_names
        finally:
            db.close()


gap_analysis_service = GapAnalysisService()