from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import Response
from app.routes.auth_routes import get_current_user
from app.models.schemas import RoadmapResponse, FeedbackRequest, StudyNotes, QuizSubmission
from app.services.roadmap_service import roadmap_service
from app.services.feedback_service import feedback_service
from app.services.llm_service import llm_service, LLMError
from app.services.activity_service import activity_service
from app.services.skill_extraction import skill_extraction_service
from app.services.adaptive_service import adaptive_service
from app.services.report_service import report_service
from app.services.quiz_service import quiz_service, QuizSubmissionError
import logging

router = APIRouter(prefix="/roadmap", tags=["Roadmap"])
logger = logging.getLogger("learning_path_generator")

def _queue_roadmap_generation(background_tasks: BackgroundTasks, current_user_id: str):
    """Persist a generation job and run generation outside the request response."""
    job = roadmap_service.create_generation_job(current_user_id)
    background_tasks.add_task(roadmap_service.run_generation_job, job["job_id"], current_user_id)
    return job


@router.post("/generate-roadmap", status_code=202)
def generate_roadmap(background_tasks: BackgroundTasks, current_user_id: str = Depends(get_current_user)):
    """Compatibility endpoint: roadmap generation is queued, never run inline."""
    return _queue_roadmap_generation(background_tasks, current_user_id)


@router.post("/generate-roadmap/async", status_code=202)
def queue_roadmap_generation(background_tasks: BackgroundTasks, current_user_id: str = Depends(get_current_user)):
    return _queue_roadmap_generation(background_tasks, current_user_id)

@router.get("/generation-jobs/{job_id}")
def get_generation_job(job_id: str, current_user_id: str = Depends(get_current_user)):
    job = roadmap_service.get_generation_job(job_id, current_user_id)
    if not job:
        raise HTTPException(status_code=404, detail="Generation job not found")
    return job

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
    except LLMError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except Exception as exc:
        logger.error("Error generating study notes: %s", exc)
        raise HTTPException(status_code=500, detail="Unable to generate study notes")

@router.post("/{goal_id}/complete")
def complete_roadmap(goal_id: str, current_user_id: str = Depends(get_current_user)):
    try:
        roadmap = roadmap_service.complete_roadmap(current_user_id, goal_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
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
        difficulty = adaptive_service.get_quiz_difficulty(current_user_id, goal_id, phase_index)
        questions = llm_service.generate_quiz(
            phase.get("title", ""), phase.get("skills", []), difficulty=difficulty["difficulty"]
        )
    except LLMError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except Exception as e:
        logger.error(f"Error generating quiz: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

    if not questions:
        raise HTTPException(status_code=502, detail="Could not generate a quiz right now. Please try again.")
    try:
        issued_quiz = quiz_service.create_session(
            current_user_id,
            goal_id,
            phase_index,
            difficulty.get("difficulty", "beginner"),
            questions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        logger.error("Could not store issued quiz: %s", exc)
        raise HTTPException(status_code=500, detail="Could not issue a quiz right now. Please try again.")

    return {**issued_quiz, **difficulty}

@router.get("/{goal_id}/report")
def download_learning_report(goal_id: str, current_user_id: str = Depends(get_current_user)):
    try:
        pdf = report_service.generate_learning_report(current_user_id, goal_id)
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="learning-report-{goal_id}.pdf"'},
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("Error generating learning report: %s", exc)
        raise HTTPException(status_code=500, detail="Unable to generate learning report")

@router.post("/{goal_id}/phase/{phase_index}/quiz/submit")
def submit_phase_quiz(goal_id: str, phase_index: int, submission: QuizSubmission, current_user_id: str = Depends(get_current_user)):
    try:
        roadmap = roadmap_service.get_saved_roadmap(current_user_id, goal_id)
        if not roadmap:
            raise HTTPException(status_code=404, detail="Roadmap not found")
        phases = roadmap.get("phases", [])
        if not 0 <= phase_index < len(phases):
            raise HTTPException(status_code=404, detail="Phase not found")

        result = quiz_service.grade_submission(
            user_id=current_user_id,
            goal_id=goal_id,
            phase_index=phase_index,
            quiz_id=submission.quiz_id,
            answers=submission.answers,
            phase_id=phases[phase_index].get("phase_id"),
        )
        try:
            result["recommendation"] = adaptive_service.get_recommendation_for_phase(
                current_user_id, goal_id, phase_index
            )
        except Exception as e:
            logger.error("Error computing recommendation after quiz: %s", e)
            result["recommendation"] = None
        return result
    except QuizSubmissionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error recording verified quiz attempt: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/{goal_id}/recommendation")
def get_recommendation(goal_id: str, current_user_id: str = Depends(get_current_user)):
    try:
        return adaptive_service.get_recommendation(current_user_id, goal_id)
    except Exception as e:
        logger.error(f"Error computing recommendation: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/{goal_id}/phase/{phase_index}/insert-remedial")
def insert_remedial_phase(goal_id: str, phase_index: int, current_user_id: str = Depends(get_current_user)):
    try:
        return adaptive_service.insert_remedial_phase(current_user_id, goal_id, phase_index)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Error inserting remedial phase: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
