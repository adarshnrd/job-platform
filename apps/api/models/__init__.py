from __future__ import annotations
from datetime import datetime
from typing import Optional, Any
from enum import Enum
from uuid import UUID
from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────────────
# ApplicationStatus and MatchTier are defined in models/application.py (canonical).
from models.application import ApplicationStatus, MatchTier  # noqa: F401


class JobSource(str, Enum):
    LINKEDIN = "linkedin"
    NAUKRI = "naukri"
    INDEED = "indeed"
    WELLFOUND = "wellfound"
    HIRIST = "hirist"
    INSTAHYRE = "instahyre"
    CUTSHORT = "cutshort"
    GLASSDOOR = "glassdoor"
    FOUNDIT = "foundit"
    REMOTEOK = "remoteok"
    WE_WORK_REMOTELY = "we_work_remotely"
    COMPANY_PORTAL = "company_portal"
    OTHER = "other"


class WorkMode(str, Enum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"


class EmploymentType(str, Enum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    FREELANCE = "freelance"
    INTERNSHIP = "internship"


# ── Profile ───────────────────────────────────────────────────────────────────

class ProfileBase(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    target_roles: list[str] = []
    target_companies: list[str] = []
    preferred_locations: list[str] = []
    open_to_remote: bool = True
    min_salary: Optional[int] = None
    max_salary: Optional[int] = None
    currency: str = "INR"
    years_experience: Optional[int] = None
    notice_period_days: int = 30
    primary_skills: list[str] = []
    secondary_skills: list[str] = []
    certifications: list[str] = []
    auto_apply_enabled: bool = False
    auto_apply_threshold: int = 80
    daily_application_limit: int = 20


class ProfileCreate(ProfileBase):
    email: str


class ProfileUpdate(ProfileBase):
    pass


class Profile(ProfileBase):
    id: UUID
    email: str
    avatar_url: Optional[str] = None
    onboarding_complete: bool = False
    linkedin_connected: bool = False
    naukri_connected: bool = False
    indeed_connected: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Resume ────────────────────────────────────────────────────────────────────

class ResumeBase(BaseModel):
    name: str
    is_primary: bool = False


class ResumeCreate(ResumeBase):
    file_url: str
    file_name: str
    file_size_kb: Optional[int] = None


class Resume(ResumeBase):
    id: UUID
    user_id: UUID
    file_url: str
    file_name: str
    file_size_kb: Optional[int] = None
    parsed_data: dict[str, Any] = {}
    ats_score: Optional[int] = None
    word_count: Optional[int] = None
    status: str = "active"
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ResumeParseResult(BaseModel):
    skills: list[str]
    experience: list[dict]
    education: list[dict]
    certifications: list[str]
    total_years: float
    summary: str
    ats_score: int
    improvement_tips: list[str]


# ── Job Listing ───────────────────────────────────────────────────────────────

class JobListingBase(BaseModel):
    title: str
    company: str
    company_logo_url: Optional[str] = None
    location: Optional[str] = None
    work_mode: Optional[WorkMode] = None
    employment_type: Optional[EmploymentType] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    currency: str = "INR"
    experience_min: Optional[int] = None
    experience_max: Optional[int] = None
    description: str
    requirements: list[str] = []
    benefits: list[str] = []
    tech_stack: list[str] = []
    source_platform: JobSource
    source_url: str
    apply_url: Optional[str] = None


class JobListingCreate(JobListingBase):
    external_id: Optional[str] = None
    application_deadline: Optional[datetime] = None


class JobListing(JobListingBase):
    id: UUID
    is_active: bool = True
    discovered_at: datetime
    expires_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class JobListingWithScore(JobListing):
    match_score: Optional[int] = None
    match_tier: Optional[MatchTier] = None
    matched_skills: list[str] = []
    missing_skills: list[str] = []


# ── Match Score ───────────────────────────────────────────────────────────────

class MatchScoreResult(BaseModel):
    overall_score: int = Field(..., ge=0, le=100)
    skill_score: int = Field(..., ge=0, le=100)
    experience_score: int = Field(..., ge=0, le=100)
    location_score: int = Field(..., ge=0, le=100)
    salary_score: int = Field(..., ge=0, le=100)
    tier: MatchTier
    matched_skills: list[str]
    missing_skills: list[str]
    analysis: str
    recommendation: str


class MatchScore(MatchScoreResult):
    id: UUID
    user_id: UUID
    job_listing_id: UUID
    resume_id: Optional[UUID] = None
    cover_letter: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ── Application ───────────────────────────────────────────────────────────────
# Canonical definitions live in models/application.py.
from models.application import (  # noqa: F401, E402
    ApplicationCreate,
    ApplicationUpdate,
    ApplicationOut as Application,
    MatchAnalysis,
)


# ── Interview Prep ────────────────────────────────────────────────────────────

class InterviewQuestion(BaseModel):
    question: str
    category: str
    difficulty: str
    model_answer: str
    tips: list[str] = []


class InterviewPrepResult(BaseModel):
    behavioral_questions: list[InterviewQuestion]
    technical_questions: list[InterviewQuestion]
    system_design_topics: list[dict]
    company_research: dict
    salary_negotiation: str
    prep_plan: str


# ── Notification ──────────────────────────────────────────────────────────────

class Notification(BaseModel):
    id: UUID
    user_id: UUID
    type: str
    title: str
    body: Optional[str] = None
    payload: dict = {}
    read_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ── Analytics ─────────────────────────────────────────────────────────────────

class ApplicationAnalytics(BaseModel):
    total_applied: int = 0
    in_interview: int = 0
    offers: int = 0
    accepted: int = 0
    rejected: int = 0
    interview_rate: float = 0.0
    offer_rate: float = 0.0
    applications_by_platform: dict[str, int] = {}
    applications_by_week: list[dict] = []
    top_skills_in_demand: list[dict] = []
    response_rate_by_platform: dict[str, float] = {}


# ── API Responses ─────────────────────────────────────────────────────────────

class PaginatedResponse(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int
    has_next: bool


class TaskResponse(BaseModel):
    task_id: str
    status: str
    message: str
