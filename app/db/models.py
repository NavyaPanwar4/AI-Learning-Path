from app.utils.time import utcnow_naive
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
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
    # Opt-in: email me when a study reminder is due (needs SMTP + REMINDER_EMAILS_ENABLED).
    email_reminders = Column(Boolean, nullable=False, default=False, server_default=false())
    # Extra learning preferences beyond experience_level/learning_style
    session_length = Column(String, default="30-60 min")
    preferred_content = Column(String, default="Videos, Docs")  # comma-separated
    learning_pace = Column(String, default="Normal")
    preferred_difficulty = Column(String, default="")
    created_at = Column(DateTime, default=utcnow_naive)
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
    mastery_probability = Column(Float, nullable=True)
    bkt_observations = Column(Integer, nullable=False, default=0)

    user = relationship("User", back_populates="skills")


class GoalUserSkill(Base):
    """BKT mastery state scoped to a user and learning goal.

    UserSkill remains the global profile/possessed-skill relation. This table
    is the authoritative source for goal-specific mastery and observations.
    """

    __tablename__ = "goal_user_skills"

    user_id = Column(String, ForeignKey("users.user_id"), primary_key=True)
    goal_id = Column(String, primary_key=True)
    skill_id = Column(String, ForeignKey("skills.skill_id"), primary_key=True)
    proficiency = Column(Integer, nullable=False, default=1)
    mastery_probability = Column(Float, nullable=False, default=0.2)
    bkt_observations = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utcnow_naive)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)


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


class RoadmapVersion(Base):
    __tablename__ = "roadmap_versions"
    __table_args__ = (UniqueConstraint("roadmap_id", "version_number", name="uq_roadmap_version"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    roadmap_id = Column(Integer, ForeignKey("roadmaps.id"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    data = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow_naive)


class RoadmapGenerationJob(Base):
    __tablename__ = "roadmap_generation_jobs"

    job_id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False, index=True)
    status = Column(String, nullable=False, default="queued")
    goal_id = Column(String, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow_naive)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)

class ActivityLog(Base):
    """Powers real Total Learning Time + Day Streak. A row is created either
    from an explicit study-session duration (frontend timer) or from a real
    action the user already takes (completing a phase, generating study
    notes, generating/completing a roadmap, a quiz attempt) — so the streak
    responds immediately, not only after sitting on a page for a while."""

    __tablename__ = "activity_log"
    __table_args__ = (CheckConstraint("duration_minutes IS NULL OR (duration_minutes >= 0 AND duration_minutes <= 720)", name="ck_activity_duration"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.user_id"))
    activity_type = Column(String, nullable=False)  # session, phase_completed, study_notes, quiz_attempt, roadmap_generated, roadmap_completed
    duration_minutes = Column(Float, nullable=True)  # only set for activity_type == "session"
    created_at = Column(DateTime, default=utcnow_naive)


class QuizAttempt(Base):
    """One row per practice quiz a learner takes on a phase."""

    __tablename__ = "quiz_attempts"
    __table_args__ = (
        CheckConstraint("total_questions BETWEEN 1 AND 100", name="ck_quiz_total_questions"),
        CheckConstraint("correct_answers BETWEEN 0 AND total_questions", name="ck_quiz_correct_answers"),
        CheckConstraint("score_pct BETWEEN 0 AND 100", name="ck_quiz_score"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.user_id"))
    goal_id = Column(String, nullable=False)
    phase_index = Column(Integer, nullable=False)
    phase_id = Column(String, nullable=True, index=True)  # stable ID; nullable for legacy attempts
    total_questions = Column(Integer, nullable=False)
    correct_answers = Column(Integer, nullable=False)
    score_pct = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=utcnow_naive)


class QuizQuestionHistory(Base):
    __tablename__ = "quiz_question_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    attempt_id = Column(Integer, ForeignKey("quiz_attempts.id"), nullable=False, index=True)
    question_index = Column(Integer, nullable=False)
    skill_name = Column(String, nullable=True)
    is_correct = Column(Boolean, nullable=False)
    created_at = Column(DateTime, default=utcnow_naive)


class IssuedQuiz(Base):
    """Server-side copy of a quiz and its answer key, issued to one learner."""

    __tablename__ = "issued_quizzes"

    quiz_id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False, index=True)
    goal_id = Column(String, nullable=False, index=True)
    phase_index = Column(Integer, nullable=False)
    difficulty = Column(String, nullable=False, default="beginner")
    questions_json = Column(Text, nullable=False)  # Includes answer key; never expose before submission.
    expires_at = Column(DateTime, nullable=False, index=True)
    submitted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow_naive, nullable=False)


class ReviewSchedule(Base):
    __tablename__ = "review_schedules"
    __table_args__ = (UniqueConstraint("user_id", "goal_id", "skill_name", name="uq_review_skill"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False, index=True)
    goal_id = Column(String, nullable=False)
    skill_name = Column(String, nullable=False)
    due_at = Column(DateTime, nullable=False)
    interval_days = Column(Integer, nullable=False, default=1)
    repetitions = Column(Integer, nullable=False, default=0)
    last_score = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=utcnow_naive)


class StudyReminder(Base):
    __tablename__ = "study_reminders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False, index=True)
    goal_id = Column(String, nullable=True)
    title = Column(String, nullable=False)
    due_at = Column(DateTime, nullable=False)
    completed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow_naive)
    emailed_at = Column(DateTime, nullable=True)  # set atomically when the reminder email is claimed


class ShareLink(Base):
    """Opt-in public, read-only progress page for one of the learner's goals."""

    __tablename__ = "share_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False, index=True)
    goal_id = Column(String, nullable=False)
    token = Column(String, nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=utcnow_naive)
    revoked_at = Column(DateTime, nullable=True)


class ResourceReport(Base):
    __tablename__ = "resource_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False, index=True)
    resource_url = Column(String, nullable=False)
    reason = Column(String, nullable=False)
    status = Column(String, nullable=False, default="open")
    created_at = Column(DateTime, default=utcnow_naive)


class ChatMessage(Base):
    """One row per chat turn with the AI tutor. goal_id scopes history to the
    learner's active goal so switching goals doesn't mix up conversations."""

    __tablename__ = "chat_messages"
    __table_args__ = (CheckConstraint("role IN ('user', 'assistant')", name="ck_chat_role"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.user_id"))
    goal_id = Column(String, nullable=True)
    role = Column(String, nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow_naive)
