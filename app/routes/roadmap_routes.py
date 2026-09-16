from fastapi import APIRouter, HTTPException, Depends
from app.routes.auth_routes import get_current_user
from app.models.schemas import RoadmapResponse, FeedbackRequest, StudyNotes, QuizSubmission
from app.services.roadmap_service import roadmap_service
from app.services.feedback_service import feedback_service
from app.services.llm_service import llm_service
from app.services.activity_service import activity_service
from app.services.skill_extraction import skill_extraction_service
import logging

router = APIRouter(prefix="/roadmap", tags=["Roadmap"])
logger = logging.getLogger("learning_path_generator")

@router.post("/generate-roadmap", response_model=RoadmapResponse)
def generate_roadmap(current_user_id: str = Depends(get_current_user)):
    try:
        roadmap_dict = roadmap_service.generate_personalized_roadmap(current_user_id)
        if not roadmap_dict or (not roadmap_dict.get("phases") and not roadmap_dict.get("roadmap_text")):
            raise HTTPException(status_code=502, detail="The AI service could not generate a roadmap. Please try again.")
            
        # Pydantic will validate the dict directly into RoadmapResponse format because of the return type
        return roadmap_dict 
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error generating roadmap: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/saved")
def get_saved_roadmaps(current_user_id: str = Depends(get_current_user)):
    return roadmap_service.get_saved_roadmaps(current_user_id)

@router.get("/feedback/user")
def get_user_feedback(current_user_id: str = Depends(get_current_user)):
    return feedback_service.get_user_feedback(current_user_id)

@router.get("/{goal_id}", response_model=RoadmapResponse)
def get_saved_roadmap(goal_id: str, current_user_id: str = Depends(get_current_user)):
    roadmap = roadmap_service.get_saved_roadmap(current_user_id, goal_id)
    if not roadmap:
        raise HTTPException(status_code=404, detail="Saved roadmap not found")
    return roadmap

@router.delete("/{goal_id}")
def delete_roadmap(goal_id: str, current_user_id: str = Depends(get_current_user)):
    deleted = roadmap_service.delete_roadmap(current_user_id, goal_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Saved roadmap not found")
    return {"message": "Roadmap deleted successfully."}

@router.post("/feedback")
def submit_feedback(request: FeedbackRequest, current_user_id: str = Depends(get_current_user)):
    try:
        return feedback_service.process_feedback(current_user_id, request)
    except Exception as e:
        logger.error(f"Error submitting feedback: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.patch("/{goal_id}/phase/{phase_index}")
def update_phase_status(goal_id: str, phase_index: int, completed: bool, current_user_id: str = Depends(get_current_user)):
    roadmap = roadmap_service.update_phase_status(current_user_id, goal_id, phase_index, completed)
    if not roadmap:
        raise HTTPException(status_code=404, detail="Roadmap or phase not found")
    return roadmap

@router.post("/{goal_id}/phase/{phase_index}/study-notes", response_model=StudyNotes)
def generate_phase_study_notes(goal_id: str, phase_index: int, current_user_id: str = Depends(get_current_user)):
    try:
        notes = roadmap_service.generate_phase_study_notes(current_user_id, goal_id, phase_index)
        if not notes:
            raise HTTPException(status_code=404, detail="Roadmap or phase not found")
        return notes
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        logger.error("Error generating study notes: %s", exc)
        raise HTTPException(status_code=500, detail="Unable to generate study notes")

@router.post("/{goal_id}/complete")
def complete_roadmap(goal_id: str, current_user_id: str = Depends(get_current_user)):
    roadmap = roadmap_service.complete_roadmap(current_user_id, goal_id)
    if not roadmap:
        raise HTTPException(status_code=404, detail="Roadmap not found")
    return roadmap

@router.post("/{goal_id}/phase/{phase_index}/quiz")
def generate_phase_quiz(goal_id: str, phase_index: int, current_user_id: str = Depends(get_current_user)):
    roadmap = roadmap_service.get_saved_roadmap(current_user_id, goal_id)
    if not roadmap:
        raise HTTPException(status_code=404, detail="Roadmap not found")

    phases = roadmap.get("phases", [])
    if not 0 <= phase_index < len(phases):
        raise HTTPException(status_code=404, detail="Phase not found")

    phase = phases[phase_index]
    try:
        questions = llm_service.generate_quiz(phase.get("title", ""), phase.get("skills", []))
    except Exception as e:
        logger.error(f"Error generating quiz: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    if not questions:
        raise HTTPException(status_code=502, detail="Could not generate a quiz right now. Please try again.")
    return {"questions": questions}

@router.post("/{goal_id}/phase/{phase_index}/quiz/submit")
def submit_phase_quiz(goal_id: str, phase_index: int, submission: QuizSubmission, current_user_id: str = Depends(get_current_user)):
    try:
        result = activity_service.record_quiz_attempt(
            current_user_id, goal_id, phase_index, submission.total_questions, submission.correct_answers
        )

        skills_updated = []
        roadmap = roadmap_service.get_saved_roadmap(current_user_id, goal_id)
        if roadmap:
            phases = roadmap.get("phases", [])
            if 0 <= phase_index < len(phases):
                skills_updated = skill_extraction_service.update_proficiency_from_quiz(
                    current_user_id, phases[phase_index].get("skills", []), result["score_pct"]
                )

        result["skills_updated"] = skills_updated
        return result
    except Exception as e:
        logger.error(f"Error recording quiz attempt: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
