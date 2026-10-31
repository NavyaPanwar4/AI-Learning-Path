import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.models.schemas import ChatRequest, ChatResponse, ExplainAnswerRequest
from app.routes.auth_routes import get_current_user
from app.services.chat_service import chat_service
from app.services.llm_service import LLMError

router = APIRouter(prefix="/chat", tags=["Chat"])
logger = logging.getLogger("learning_path_generator")


@router.post("", response_model=ChatResponse)
def send_message(request: ChatRequest, current_user_id: str = Depends(get_current_user)):
    try:
        return chat_service.send_message(current_user_id, request.message, request.goal_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LLMError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except Exception as e:
        logger.error(f"Error in chat: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/explain-answer", response_model=ChatResponse)
def explain_answer(request: ExplainAnswerRequest, current_user_id: str = Depends(get_current_user)):
    try:
        return chat_service.explain_answer(
            current_user_id, request.quiz_id, request.question_id, request.selected_index
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LLMError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except Exception as e:
        logger.error(f"Error explaining quiz answer: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/stream")
def stream_message(request: ChatRequest, current_user_id: str = Depends(get_current_user)):
    try:
        events = chat_service.stream_message(current_user_id, request.message, request.goal_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Could not initialize tutor stream: %s", exc)
        raise HTTPException(status_code=500, detail="Unable to start tutor response")

    def encode_events():
        for event in events:
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        encode_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.get("/history")
def get_history(goal_id: Optional[str] = None, current_user_id: str = Depends(get_current_user)):
    try:
        return chat_service.get_history(current_user_id, goal_id)
    except Exception as e:
        logger.error(f"Error fetching chat history: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.delete("/history")
def clear_history(current_user_id: str = Depends(get_current_user)):
    try:
        return chat_service.clear_history(current_user_id)
    except Exception as e:
        logger.error("Error clearing chat history: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")

