import uuid
import pandas as pd
from app.utils.csv_handler import csv_handler
from app.models.schemas import FeedbackRequest

class FeedbackService:
    def process_feedback(self, user_id: str, feedback: FeedbackRequest):
        feedback_id = str(uuid.uuid4())
        
        new_feedback = {
            "feedback_id": feedback_id,
            "user_id": user_id,
            "content_id": feedback.content_id,
            "content_type": feedback.content_type,
            "rating": feedback.rating,
            "comments": feedback.comments or ""
        }
        
        csv_handler.append_row("user_feedback.csv", new_feedback)
        
    def get_user_feedback(self, user_id: str):
        try:
            df = csv_handler.read_csv("user_feedback.csv")
            if df.empty:
                return []
            
            # Ensure user_id is compared correctly (as string)
            user_df = df[df['user_id'].astype(str) == str(user_id)]
            
            # Replace NaNs with None so it's JSON serializable
            records = user_df.to_dict(orient='records')
            for row in records:
                for k, v in row.items():
                    if pd.isna(v):
                        row[k] = None
            return records
        except Exception as e:
            from app.utils.logger import logger
            logger.error(f"Error in get_user_feedback: {e}")
            return []

feedback_service = FeedbackService()
