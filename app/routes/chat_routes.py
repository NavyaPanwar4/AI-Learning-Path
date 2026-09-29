import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.models.schemas import ChatRequest, ChatResponse
from app.routes.auth_routes import get_current_user
from app.services.chat_service import chat_service

router = APIRouter(prefix="/chat", tags=["Chat"])
logger = logging.getLogger("learning_path_generator")


@router.post("", response_model=ChatResponse)
def send_message(request: ChatRequest, current_user_id: str = Depends(get_current_user)):
    try:
        return chat_service.send_message(current_user_id, request.message, request.goal_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error in chat: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/history")
def get_history(goal_id: Optional[str] = None, current_user_id: str = Depends(get_current_user)):
    try:
        return chat_service.get_history(current_user_id, goal_id)
    except Exception as e:
        logger.error(f"Error fetching chat history: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
