from app.utils.time import utcnow_naive
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional

from app.db.database import SessionLocal
from app.db.models import Goal, User
from app.models.schemas import Token, UserCreate, UserLogin
from app.services.email_service import email_service
from app.utils.config import settings
from app.utils.security import create_access_token, get_password_hash, verify_password


class AuthService:
    def register_user(self, user_data: UserCreate) -> Token:
        db = SessionLocal()
        try:
            if db.query(User).filter(User.email == user_data.email).first():
                raise ValueError("Email already registered")
            if db.query(User).filter(User.username == user_data.username).first():
                raise ValueError("Username already taken")

            user = User(
                user_id=str(uuid.uuid4()),
                username=user_data.username,
                email=user_data.email,
                hashed_password=get_password_hash(user_data.password),
                goal_id=None,
                experience_level="",
                available_hours_per_week=10,
                learning_style="",
            )
            db.add(user)
            db.commit()

            access_token = create_access_token(data={"sub": user.user_id})
            return Token(access_token=access_token, token_type="bearer")
        finally:
            db.close()

    def authenticate_user(self, user_login: UserLogin) -> Token:
        db = SessionLocal()
        try:
            user = (
                db.query(User)
                .filter((User.email == user_login.username) | (User.username == user_login.username))
                .first()
            )
            if not user:
                raise ValueError("Incorrect username/email or password")
            if not verify_password(user_login.password, user.hashed_password):
                raise ValueError("Invalid credentials")

            access_token = create_access_token(data={"sub": user.user_id})
            return Token(access_token=access_token, token_type="bearer")
        finally:
            db.close()

    def get_user_by_id(self, user_id: str) -> Optional[dict]:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.user_id == user_id).first()
            if not user:
                return None
            return {
                "user_id": user.user_id,
                "username": user.username,
                "email": user.email,
                "hashed_password": user.hashed_password,
                "goal_id": user.goal_id,
                "experience_level": user.experience_level,
                "available_hours_per_week": user.available_hours_per_week,
                "learning_style": user.learning_style,
                "bio": user.bio or "",
                "title": user.title or "",
                "education": user.education or "",
                "language": user.language or "English",
                "avatar_url": user.avatar_url or "",
                "session_length": user.session_length or "30-60 min",
                "preferred_content": user.preferred_content or "Videos, Docs",
                "learning_pace": user.learning_pace or "Normal",
                "preferred_difficulty": user.preferred_difficulty or "",
                "created_at": user.created_at,
            }
        finally:
            db.close()

    def update_user_profile(self, user_id: str, profile_data):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.user_id == user_id).first()
            if not user:
                raise ValueError("User not found")

            if not db.query(Goal).filter(Goal.goal_id == profile_data.goal_id).first():
                raise ValueError("Selected goal does not exist")

            user.goal_id = profile_data.goal_id
            user.experience_level = profile_data.experience_level
            user.available_hours_per_week = profile_data.available_hours_per_week
            user.learning_style = profile_data.learning_style
            if profile_data.session_length is not None:
                user.session_length = profile_data.session_length
            if profile_data.preferred_content is not None:
                user.preferred_content = profile_data.preferred_content
            if profile_data.learning_pace is not None:
                user.learning_pace = profile_data.learning_pace
            if profile_data.preferred_difficulty is not None:
                user.preferred_difficulty = profile_data.preferred_difficulty
            db.commit()
            return {"status": "success", "message": "Profile updated successfully."}
        finally:
            db.close()

    def update_personal_info(self, user_id: str, info) -> dict:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.user_id == user_id).first()
            if not user:
                raise ValueError("User not found")

            user.bio = info.bio or ""
            user.title = info.title or ""
            user.education = info.education or ""
            user.language = info.language or "English"
            user.avatar_url = info.avatar_url or ""
            db.commit()
            return {"status": "success", "message": "Personal info updated successfully."}
        finally:
            db.close()

    def get_all_goals(self) -> list:
        db = SessionLocal()
        try:
            goals = db.query(Goal).all()
            return [{"goal_id": g.goal_id, "goal_name": g.goal_name} for g in goals]
        finally:
            db.close()

    def request_password_reset(self, email: str) -> None:
        """Silently does nothing if the email isn't registered — the caller's
        response is the same either way, so account existence is never leaked."""
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == email).first()
            if not user:
                return

            token = secrets.token_urlsafe(32)
            user.reset_token = token
            user.reset_token_expires = utcnow_naive() + timedelta(
                minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES
            )
            db.commit()

            reset_link = f"{settings.FRONTEND_URL}/reset-password?token={token}"
            email_service.send_password_reset(email, reset_link)
        finally:
            db.close()

    def reset_password(self, token: str, new_password: str) -> None:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.reset_token == token).first()
            if not user or not user.reset_token_expires or user.reset_token_expires < utcnow_naive():
                raise ValueError("This reset link is invalid or has expired.")

            user.hashed_password = get_password_hash(new_password)
            user.reset_token = None
            user.reset_token_expires = None
            db.commit()
        finally:
            db.close()

    def change_password(self, user_id: str, old_password: str, new_password: str) -> None:
        """For a logged-in user changing their own password (knows the old one) —
        distinct from the forgot-password token flow above."""
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.user_id == user_id).first()
            if not user:
                raise ValueError("User not found")
            if not user.hashed_password or not verify_password(old_password, user.hashed_password):
                raise ValueError("Current password is incorrect")

            user.hashed_password = get_password_hash(new_password)
            db.commit()
        finally:
            db.close()


auth_service = AuthService()
