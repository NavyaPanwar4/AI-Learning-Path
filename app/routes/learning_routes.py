from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from datetime import datetime

from app.models.schemas import EmailPreferencesUpdate, DeadlineUpdate, ReminderCompletionUpdate, ReminderCreate, ResourceReportRequest, RoadmapImport
from app.routes.auth_routes import get_current_user
from app.services.learning_features_service import learning_features_service
from app.services.share_service import share_service
from app.db.database import SessionLocal
from app.db.models import User
from app.utils.config import settings

router = APIRouter(prefix="/learning", tags=["Learning insights"])


@router.get("/email-preferences")
def get_email_preferences(current_user_id: str = Depends(get_current_user)):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.user_id == current_user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return {
            "email_reminders": bool(user.email_reminders),
            "has_email": bool(user.email),
            # Tells the UI whether the server will actually send anything.
            "delivery_enabled": bool(settings.REMINDER_EMAILS_ENABLED and settings.SMTP_HOST),
        }
    finally:
        db.close()


@router.put("/email-preferences")
def set_email_preferences(request: EmailPreferencesUpdate, current_user_id: str = Depends(get_current_user)):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.user_id == current_user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if request.email_reminders and not user.email:
            raise HTTPException(status_code=400, detail="Add an email address to your profile first.")
        user.email_reminders = request.email_reminders
        db.commit()
        return {"email_reminders": bool(user.email_reminders)}
    finally:
        db.close()


@router.get("/{goal_id}/share")
def get_share_link(goal_id: str, current_user_id: str = Depends(get_current_user)):
    return share_service.get_link(current_user_id, goal_id)


@router.post("/{goal_id}/share")
def create_share_link(goal_id: str, current_user_id: str = Depends(get_current_user)):
    result = share_service.create_link(current_user_id, goal_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Roadmap not found")
    return result


@router.delete("/{goal_id}/share")
def revoke_share_link(goal_id: str, current_user_id: str = Depends(get_current_user)):
    return {"revoked": share_service.revoke_link(current_user_id, goal_id)}


@router.get("/{goal_id}/analytics")
def get_learning_analytics(goal_id: str, current_user_id: str = Depends(get_current_user)):
    result = learning_features_service.analytics(current_user_id, goal_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Roadmap not found")
    return result

@router.get("/{goal_id}/question-history")
def get_question_history(goal_id: str, current_user_id: str = Depends(get_current_user)):
    result = learning_features_service.analytics(current_user_id, goal_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Roadmap not found")
    return result["question_history"]


@router.get("/review-queue")
def get_review_queue(goal_id: str | None = None, current_user_id: str = Depends(get_current_user)):
    return learning_features_service.review_queue(current_user_id, goal_id)


@router.get("/reminders")
def get_reminders(current_user_id: str = Depends(get_current_user)):
    return learning_features_service.reminders(current_user_id)


@router.post("/reminders")
def create_reminder(request: ReminderCreate, current_user_id: str = Depends(get_current_user)):
    try:
        return learning_features_service.create_reminder(current_user_id, request.title, request.due_at, request.goal_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="due_at must be a valid ISO date")


@router.patch("/reminders/{reminder_id}/complete")
def complete_reminder(
    reminder_id: int,
    request: ReminderCompletionUpdate | None = None,
    current_user_id: str = Depends(get_current_user),
):
    # A missing body retains the original endpoint behavior for older clients.
    completed = request.completed if request is not None else True
    if not learning_features_service.complete_reminder(current_user_id, reminder_id, completed):
        raise HTTPException(status_code=404, detail="Reminder not found")
    return {"status": "completed" if completed else "reopened", "completed": completed}


@router.delete("/reminders/{reminder_id}")
def delete_reminder(reminder_id: int, current_user_id: str = Depends(get_current_user)):
    if not learning_features_service.delete_reminder(current_user_id, reminder_id):
        raise HTTPException(status_code=404, detail="Reminder not found")
    return {"status": "deleted", "id": reminder_id}


@router.post("/{goal_id}/deadline")
def set_deadline(goal_id: str, request: DeadlineUpdate, current_user_id: str = Depends(get_current_user)):
    roadmap = learning_features_service.set_deadline(current_user_id, goal_id, request.deadline)
    if roadmap is None:
        raise HTTPException(status_code=404, detail="Roadmap not found")
    return roadmap


@router.post("/resource-report")
def report_resource(request: ResourceReportRequest, current_user_id: str = Depends(get_current_user)):
    return learning_features_service.report_resource(current_user_id, request.resource_url, request.reason)


@router.get("/{goal_id}/export")
def export_roadmap(goal_id: str, current_user_id: str = Depends(get_current_user)):
    export = learning_features_service.export_roadmap(current_user_id, goal_id)
    if export is None:
        raise HTTPException(status_code=404, detail="Roadmap not found")
    return JSONResponse(content=export, headers={"Content-Disposition": f'attachment; filename="roadmap-{goal_id}.json"'})


@router.post("/{goal_id}/import")
def import_roadmap(goal_id: str, request: RoadmapImport, current_user_id: str = Depends(get_current_user)):
    return learning_features_service.import_roadmap(current_user_id, goal_id, request.roadmap.model_dump(exclude_none=True))


@router.get("/{goal_id}/versions")
def list_versions(goal_id: str, current_user_id: str = Depends(get_current_user)):
    versions = learning_features_service.list_versions(current_user_id, goal_id)
    if versions is None:
        raise HTTPException(status_code=404, detail="Roadmap not found")
    return versions


@router.post("/{goal_id}/versions/{version_number}/restore")
def restore_version(goal_id: str, version_number: int, current_user_id: str = Depends(get_current_user)):
    roadmap = learning_features_service.restore_version(current_user_id, goal_id, version_number)
    if roadmap is None:
        raise HTTPException(status_code=404, detail="Roadmap version not found")
    return roadmap


@router.get("/calendar.ics")
def export_calendar(current_user_id: str = Depends(get_current_user)):
    return Response(
        learning_features_service.build_calendar(current_user_id),
        media_type="text/calendar",
        headers={"Content-Disposition": "attachment; filename=learning-path.ics"},
    )
