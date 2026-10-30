from fastapi import APIRouter, Depends, HTTPException

from app.db.database import SessionLocal
from app.db.models import Goal, Skill
from app.models.schemas import CatalogGoalCreate, CatalogSkillCreate
from app.routes.auth_routes import get_current_user
from app.services.auth_service import auth_service
from app.utils.config import settings

router = APIRouter(prefix="/admin", tags=["Administration"])


def require_admin(user_id: str):
    profile = auth_service.get_user_by_id(user_id) or {}
    admins = {email.strip().lower() for email in settings.ADMIN_EMAILS.split(",") if email.strip()}
    if not admins or profile.get("email", "").lower() not in admins:
        raise HTTPException(status_code=403, detail="Administrator access required")
    return profile


@router.get("/goals")
def list_catalog_goals(current_user_id: str = Depends(get_current_user)):
    require_admin(current_user_id)
    db = SessionLocal()
    try:
        return [{"goal_id": row.goal_id, "goal_name": row.goal_name} for row in db.query(Goal).order_by(Goal.goal_name.asc()).all()]
    finally:
        db.close()


@router.post("/goals")
def create_catalog_goal(request: CatalogGoalCreate, current_user_id: str = Depends(get_current_user)):
    require_admin(current_user_id)
    db = SessionLocal()
    try:
        if db.query(Goal).filter(Goal.goal_name.ilike(request.goal_name)).first():
            raise HTTPException(status_code=409, detail="Goal already exists")
        row = Goal(goal_name=request.goal_name.strip())
        db.add(row)
        db.commit()
        return {"goal_id": row.goal_id, "goal_name": row.goal_name}
    finally:
        db.close()


@router.get("/skills")
def list_catalog_skills(current_user_id: str = Depends(get_current_user)):
    require_admin(current_user_id)
    db = SessionLocal()
    try:
        return [{"skill_id": row.skill_id, "skill_name": row.skill_name, "category": row.category, "aliases": row.aliases} for row in db.query(Skill).order_by(Skill.skill_name.asc()).all()]
    finally:
        db.close()


@router.post("/skills")
def create_catalog_skill(request: CatalogSkillCreate, current_user_id: str = Depends(get_current_user)):
    require_admin(current_user_id)
    db = SessionLocal()
    try:
        if db.query(Skill).filter(Skill.skill_name.ilike(request.skill_name)).first():
            raise HTTPException(status_code=409, detail="Skill already exists")
        row = Skill(skill_name=request.skill_name.strip(), category=request.category.strip(), aliases=request.aliases.strip())
        db.add(row)
        db.commit()
        return {"skill_id": row.skill_id, "skill_name": row.skill_name, "category": row.category, "aliases": row.aliases}
    finally:
        db.close()
