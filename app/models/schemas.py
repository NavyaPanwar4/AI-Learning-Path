from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from typing import List, Optional
import re

# Auth Schemas
class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str

    @field_validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if not re.search(r"[A-Z]", v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r"[0-9]", v):
            raise ValueError('Password must contain at least one number')
        return v

class UserLogin(BaseModel):
    username: str = Field(..., min_length=1, max_length=120)
    password: str = Field(..., min_length=1, max_length=256)

class UserProfileUpdate(BaseModel):
    goal_id: str = Field(..., min_length=1, max_length=100)
    experience_level: str = Field("beginner", min_length=1, max_length=30)
    available_hours_per_week: int = Field(10, ge=1, le=168)
    learning_style: str = Field("visual", min_length=1, max_length=30)
    # Optional — onboarding doesn't send these, the profile page's
    # "Learning Preferences" edit does.
    session_length: Optional[str] = Field(None, max_length=40)
    preferred_content: Optional[str] = Field(None, max_length=300)
    learning_pace: Optional[str] = Field(None, max_length=30)
    preferred_difficulty: Optional[str] = Field(None, max_length=30)

class PersonalInfoUpdate(BaseModel):
    bio: Optional[str] = Field("", max_length=1000)
    title: Optional[str] = Field("", max_length=120)
    education: Optional[str] = Field("", max_length=200)
    language: Optional[str] = Field("English", max_length=60)
    avatar_url: Optional[str] = Field("", max_length=500)

class SessionLogRequest(BaseModel):
    duration_minutes: float = Field(..., gt=0, le=720)

class QuizAnswerSubmission(BaseModel):
    """One answer to a server-issued quiz question."""

    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(..., min_length=1, max_length=64)
    selected_index: int = Field(..., ge=0, le=3)


class QuizSubmission(BaseModel):
    """Client supplies answers only; the server calculates all grading data."""

    model_config = ConfigDict(extra="forbid")

    quiz_id: str = Field(..., min_length=1, max_length=64)
    answers: List[QuizAnswerSubmission] = Field(..., min_length=1, max_length=100)

    @field_validator("answers")
    @classmethod
    def answers_must_have_unique_question_ids(cls, value):
        question_ids = [answer.question_id for answer in value]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("Each quiz question may be answered only once")
        return value

class Token(BaseModel):
    access_token: str
    token_type: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator('new_password')
    def validate_new_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if not re.search(r"[A-Z]", v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r"[0-9]", v):
            raise ValueError('Password must contain at least one number')
        return v

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

    @field_validator('new_password')
    def validate_new_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if not re.search(r"[A-Z]", v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r"[0-9]", v):
            raise ValueError('Password must contain at least one number')
        return v

class UserProfileResponse(BaseModel):
    username: str
    email: str
    goal_id: Optional[str] = None
    goal_name: Optional[str] = None
    experience_level: str = ""
    available_hours_per_week: int = 10
    learning_style: str = ""

# Skill Schemas
class ExtractSkillsRequest(BaseModel):
    free_text: str = Field(..., min_length=1, max_length=4000)

class ExtractedSkill(BaseModel):
    skill_name: str
    matched_skill_id: Optional[str] = None
    confidence: float

class ExtractSkillsResponse(BaseModel):
    extracted_skills: List[ExtractedSkill]
    desired_skills: Optional[List[ExtractedSkill]] = []

# Roadmap Schemas
class ResourceSchema(BaseModel):
    title: str
    url: str
    type: str = "resource"

class ProjectSchema(BaseModel):
    title: str
    description: str

class StudyConcept(BaseModel):
    term: str
    explanation: str

class StudyPlanStep(BaseModel):
    step: str
    action: str

class StudyNotes(BaseModel):
    title: str
    overview: str
    learning_objectives: List[str] = Field(default_factory=list)
    key_concepts: List[StudyConcept] = Field(default_factory=list)
    study_plan: List[StudyPlanStep] = Field(default_factory=list)
    practice_prompts: List[str] = Field(default_factory=list)
    quick_recap: List[str] = Field(default_factory=list)

class RoadmapPhase(BaseModel):
    title: str
    phase_id: Optional[str] = None
    remedial_for: Optional[str] = None
    duration: str = "Flexible"
    skills: List[str] = Field(default_factory=list)
    resources: List[ResourceSchema] = Field(default_factory=list)
    projects: List[ProjectSchema] = Field(default_factory=list)
    completed: bool = False
    is_remedial: bool = False
    ai_notes: Optional[StudyNotes] = None

class RoadmapResponse(BaseModel):
    goal_id: Optional[str] = None
    goal_name: Optional[str] = Field(None, max_length=160)
    phases: Optional[List[RoadmapPhase]] = []
    roadmap_text: Optional[str] = None
    is_complete: bool = False
    deadline: Optional[str] = Field(None, max_length=40)

# Feedback Schema
class FeedbackRequest(BaseModel):
    content_id: str = Field(..., min_length=1, max_length=500)
    content_type: str = Field(..., pattern="^(resource|project|phase|roadmap)$")
    rating: int = Field(..., ge=1, le=5)
    comments: Optional[str] = Field(None, max_length=2000)

class RoadmapFeedbackRequest(BaseModel):
    rating: int
    comments: Optional[str] = None

# Chat (AI tutor)
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    goal_id: Optional[str] = Field(None, max_length=100)

class ExplainAnswerRequest(BaseModel):
    """Ask the tutor to explain one question from a quiz the learner has submitted."""

    model_config = ConfigDict(extra="forbid")

    quiz_id: str = Field(..., min_length=1, max_length=64)
    question_id: str = Field(..., min_length=1, max_length=64)
    selected_index: int = Field(..., ge=0, le=3)


class ChatResponse(BaseModel):
    reply: str
    goal_id: Optional[str] = None

class DeadlineUpdate(BaseModel):
    deadline: Optional[str] = Field(None, max_length=40)

class ReminderCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=160)
    due_at: str = Field(..., min_length=10, max_length=40)
    goal_id: Optional[str] = Field(None, max_length=100)


class ReminderCompletionUpdate(BaseModel):
    completed: bool


class EmailPreferencesUpdate(BaseModel):
    email_reminders: bool

class ResourceReportRequest(BaseModel):
    resource_url: str = Field(..., min_length=8, max_length=1000)
    reason: str = Field(..., min_length=3, max_length=500)

class RoadmapImport(BaseModel):
    roadmap: RoadmapResponse

class CatalogGoalCreate(BaseModel):
    goal_name: str = Field(..., min_length=2, max_length=160)

class CatalogSkillCreate(BaseModel):
    skill_name: str = Field(..., min_length=2, max_length=120)
    category: str = Field("", max_length=80)
    aliases: str = Field("", max_length=500)
