import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime

from app.db.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    user_id = Column(String, primary_key=True, default=gen_uuid)
    # Nullable: real registered users always have both; some seed/profile rows
    # imported from the old dataset don't (see scripts/migrate_csv_to_db.py).
    # NULL, not "", so multiple incomplete rows don't collide on the unique index.
    username = Column(String, unique=True, nullable=True, index=True)
    email = Column(String, unique=True, nullable=True, index=True)
    hashed_password = Column(String, nullable=True)
    goal_id = Column(String, ForeignKey("goals.goal_id"), nullable=True)
    experience_level = Column(String, default="")
    available_hours_per_week = Column(Integer, default=10)
    learning_style = Column(String, default="")
    # Profile display fields (all optional, user-editable)
    bio = Column(Text, default="")
    title = Column(String, default="")       # e.g. "Engineering Student"
    education = Column(String, default="")   # e.g. "B.Tech, MAIT"
    language = Column(String, default="English")
    avatar_url = Column(String, default="")
    # Extra learning preferences beyond experience_level/learning_style
    session_length = Column(String, default="30-60 min")
    preferred_content = Column(String, default="Videos, Docs")  # comma-separated
    learning_pace = Column(String, default="Normal")
    preferred_difficulty = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    # Forgot-password: a random token + its expiry, cleared once used or replaced
    reset_token = Column(String, nullable=True, index=True)
    reset_token_expires = Column(DateTime, nullable=True)

    skills = relationship("UserSkill", back_populates="user", cascade="all, delete-orphan")
    feedback = relationship("UserFeedback", back_populates="user", cascade="all, delete-orphan")
    roadmaps = relationship("Roadmap", back_populates="user", cascade="all, delete-orphan")


class Skill(Base):
    __tablename__ = "skills"

    skill_id = Column(String, primary_key=True, default=gen_uuid)
    skill_name = Column(String, unique=True, nullable=False, index=True)
    category = Column(String, default="")
    aliases = Column(String, default="")  # comma-separated, same convention as old CSV


class SkillDependency(Base):
    __tablename__ = "skill_dependencies"

    skill_id = Column(String, ForeignKey("skills.skill_id"), primary_key=True)
    prerequisite_id = Column(String, ForeignKey("skills.skill_id"), primary_key=True)


class Goal(Base):
    __tablename__ = "goals"

    goal_id = Column(String, primary_key=True, default=gen_uuid)
    goal_name = Column(String, unique=True, nullable=False)


class GoalSkill(Base):
    __tablename__ = "goal_skills"

    goal_id = Column(String, ForeignKey("goals.goal_id"), primary_key=True)
    skill_id = Column(String, ForeignKey("skills.skill_id"), primary_key=True)
    importance = Column(Integer, default=1)
    

class UserSkill(Base):
    __tablename__ = "user_skills"

    user_id = Column(String, ForeignKey("users.user_id"), primary_key=True)
    skill_id = Column(String, ForeignKey("skills.skill_id"), primary_key=True)
    proficiency = Column(Integer, default=1)

    user = relationship("User", back_populates="skills")


class UserFeedback(Base):
    __tablename__ = "user_feedback"

    feedback_id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.user_id"))
    content_id = Column(String)
    content_type = Column(String)
    rating = Column(Integer)
    comments = Column(Text, default="")

    user = relationship("User", back_populates="feedback")


class Roadmap(Base):
    """Replaces the old <user_id>_<goal_id>_roadmap.json cache files."""

    __tablename__ = "roadmaps"
    __table_args__ = (UniqueConstraint("user_id", "goal_id", name="uq_user_goal"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.user_id"))
    goal_id = Column(String, nullable=False)
    goal_name = Column(String, default="")
    data = Column(Text, nullable=False)  # JSON-serialized roadmap dict (phases, ai_notes, etc.)
    is_complete = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="roadmaps")

class ActivityLog(Base):
    """Powers real Total Learning Time + Day Streak. A row is created either
    from an explicit study-session duration (frontend timer) or from a real
    action the user already takes (completing a phase, generating study
    notes, generating/completing a roadmap, a quiz attempt) — so the streak
    responds immediately, not only after sitting on a page for a while."""

    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.user_id"))
    activity_type = Column(String, nullable=False)  # session, phase_completed, study_notes, quiz_attempt, roadmap_generated, roadmap_completed
    duration_minutes = Column(Float, nullable=True)  # only set for activity_type == "session"
    created_at = Column(DateTime, default=datetime.utcnow)


class QuizAttempt(Base):
    """One row per practice quiz a learner takes on a phase."""

    __tablename__ = "quiz_attempts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.user_id"))
    goal_id = Column(String, nullable=False)
    phase_index = Column(Integer, nullable=False)
    total_questions = Column(Integer, nullable=False)
    correct_answers = Column(Integer, nullable=False)
    score_pct = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
