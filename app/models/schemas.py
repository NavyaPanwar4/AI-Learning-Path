from pydantic import BaseModel, EmailStr, Field, field_validator
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
    username: str
    password: str

class UserProfileUpdate(BaseModel):
    goal_id: str
    experience_level: str = "beginner"
    available_hours_per_week: int = 10
    learning_style: str = "visual"

class Token(BaseModel):
    access_token: str
    token_type: str

# Skill Schemas
class ExtractSkillsRequest(BaseModel):
    free_text: str

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
    type: str

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
    duration: str
    skills: List[str] = Field(default_factory=list)
    resources: List[ResourceSchema] = Field(default_factory=list)
    projects: List[ProjectSchema] = Field(default_factory=list)
    completed: bool = False
    ai_notes: Optional[StudyNotes] = None

class RoadmapResponse(BaseModel):
    goal_id: Optional[str] = None
    phases: Optional[List[RoadmapPhase]] = []
    roadmap_text: Optional[str] = None
    is_complete: bool = False

# Feedback Schema
class FeedbackRequest(BaseModel):
    content_id: str
    content_type: str # resource, project, phase
    rating: int # 1-5
    comments: Optional[str] = None

class RoadmapFeedbackRequest(BaseModel):
    rating: int
    comments: Optional[str] = None
