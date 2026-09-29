from fastapi import APIRouter, HTTPException, Depends
from app.routes.auth_routes import get_current_user
from app.models.schemas import ExtractSkillsRequest, ExtractSkillsResponse, UserProfileUpdate, ChangePasswordRequest, PersonalInfoUpdate, SessionLogRequest
from app.services.skill_extraction import skill_extraction_service
from app.services.auth_service import auth_service
from app.services.dashboard_service import dashboard_service
from app.services.activity_service import activity_service
from app.db.database import SessionLocal
from app.db.models import Skill, UserSkill, Goal
import logging

router = APIRouter(prefix="/users", tags=["Users"])
logger = logging.getLogger("learning_path_generator")

@router.post("/extract-skills", response_model=ExtractSkillsResponse)
def extract_skills(request: ExtractSkillsRequest, current_user_id: str = Depends(get_current_user)):
    try:
        if not request.free_text or not request.free_text.strip():
            raise HTTPException(status_code=400, detail="Text cannot be empty")
            
        extracted_data = skill_extraction_service.extract_and_match(current_user_id, request.free_text)
        return ExtractSkillsResponse(
            extracted_skills=extracted_data["extracted_skills"],
            desired_skills=extracted_data["desired_skills"]
        )
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error in extract-skills: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/skills")
def get_user_skills(current_user_id: str = Depends(get_current_user)):
    db = SessionLocal()
    try:
        rows = db.query(UserSkill).filter(UserSkill.user_id == str(current_user_id)).all()
        skills = []
        for row in rows:
            skill = db.query(Skill).filter(Skill.skill_id == row.skill_id).first()
            skills.append({
                "skill_id": row.skill_id,
                "skill_name": skill.skill_name if skill else "Unknown Skill",
                # proficiency is stored 1-5; normalize to 0-1 since the
                # frontend renders this as confidence * 100%.
                "confidence": min(int(row.proficiency or 1), 5) / 5.0,
            })
        return skills
    except Exception as e:
        logger.error(f"Error fetching user skills: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        db.close()

@router.put("/profile")
def update_profile(profile: UserProfileUpdate, current_user_id: str = Depends(get_current_user)):
    try:
        return auth_service.update_user_profile(current_user_id, profile)
    except Exception as e:
        logger.error(f"Error updating profile: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/goals")
def get_goals(current_user_id: str = Depends(get_current_user)):
    try:
        return auth_service.get_all_goals()
    except Exception as e:
        logger.error(f"Error fetching goals: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/me")
def get_my_profile(current_user_id: str = Depends(get_current_user)):
    profile = auth_service.get_user_by_id(current_user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="User not found")

    goal_name = None
    if profile.get("goal_id"):
        db = SessionLocal()
        try:
            goal = db.query(Goal).filter(Goal.goal_id == profile["goal_id"]).first()
            goal_name = goal.goal_name if goal else None
        finally:
            db.close()

    return {
        "username": profile["username"],
        "email": profile["email"],
        "goal_id": profile.get("goal_id"),
        "goal_name": goal_name,
        "experience_level": profile.get("experience_level", ""),
        "available_hours_per_week": profile.get("available_hours_per_week", 10),
        "learning_style": profile.get("learning_style", ""),
    }

@router.put("/change-password")
def change_password(request: ChangePasswordRequest, current_user_id: str = Depends(get_current_user)):
    try:
        auth_service.change_password(current_user_id, request.old_password, request.new_password)
        return {"message": "Password updated successfully."}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error changing password: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/dashboard")
def get_dashboard(current_user_id: str = Depends(get_current_user)):
    try:
        return dashboard_service.get_dashboard(current_user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error building dashboard: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.put("/personal-info")
def update_personal_info(info: PersonalInfoUpdate, current_user_id: str = Depends(get_current_user)):
    try:
        return auth_service.update_personal_info(current_user_id, info)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating personal info: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/activity/session")
def log_session(request: SessionLogRequest, current_user_id: str = Depends(get_current_user)):
    if request.duration_minutes and request.duration_minutes >= 0.1:
        activity_service.log_activity(current_user_id, "session", request.duration_minutes)
    return {"status": "ok"}

@router.delete("/skills/{skill_id}")
def delete_skill(skill_id: str, current_user_id: str = Depends(get_current_user)):
    deleted = skill_extraction_service.delete_user_skill(current_user_id, skill_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"message": "Skill removed."}