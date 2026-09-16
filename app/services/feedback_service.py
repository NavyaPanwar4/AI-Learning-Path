import uuid

from app.db.database import SessionLocal
from app.db.models import UserFeedback
from app.models.schemas import FeedbackRequest


class FeedbackService:
    def process_feedback(self, user_id: str, feedback: FeedbackRequest):
        db = SessionLocal()
        try:
            db.add(
                UserFeedback(
                    feedback_id=str(uuid.uuid4()),
                    user_id=user_id,
                    content_id=feedback.content_id,
                    content_type=feedback.content_type,
                    rating=feedback.rating,
                    comments=feedback.comments or "",
                )
            )
            db.commit()
        finally:
            db.close()

    def get_user_feedback(self, user_id: str):
        db = SessionLocal()
        try:
            rows = db.query(UserFeedback).filter(UserFeedback.user_id == str(user_id)).all()
            return [
                {
                    "feedback_id": r.feedback_id,
                    "user_id": r.user_id,
                    "content_id": r.content_id,
                    "content_type": r.content_type,
                    "rating": r.rating,
                    "comments": r.comments,
                }
                for r in rows
            ]
        except Exception as e:
            from app.utils.logger import logger

            logger.error(f"Error in get_user_feedback: {e}")
            return []
        finally:
            db.close()


feedback_service = FeedbackService()