from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime
import uuid


class ApplicationStatus(str, Enum):
    discovered = "discovered"
    matched = "matched"
    queued = "queued"
    applying = "applying"
    applied = "applied"
    under_review = "under_review"
    assessment = "assessment"
    interview_scheduled = "interview_scheduled"
    technical_round = "technical_round"
    hr_round = "hr_round"
    offer_received = "offer_received"
    rejected = "rejected"
    withdrawn = "withdrawn"
    accepted = "accepted"


class MatchTier(str, Enum):
    auto_apply = "auto_apply"
    recommended = "recommended"
    watchlist = "watchlist"
    archived = "archived"


class MatchAnalysis(BaseModel):
    strengths: List[str] = []
    gaps: List[str] = []
    recommendations: List[str] = []
    culture_fit: Optional[str] = None
    growth_potential: Optional[str] = None
    score_breakdown: Dict[str, int] = {}   # {"skills": 40, "experience": 30, ...}
    summary: Optional[str] = None


class ApplicationCreate(BaseModel):
    job_listing_id: uuid.UUID
    resume_id: Optional[uuid.UUID] = None
    notes: Optional[str] = None


class ApplicationUpdate(BaseModel):
    status: Optional[ApplicationStatus] = None
    resume_id: Optional[uuid.UUID] = None
    cover_letter: Optional[str] = None
    interview_date: Optional[datetime] = None
    interview_notes: Optional[str] = None
    interviewer_name: Optional[str] = None
    offered_salary: Optional[int] = None
    offer_deadline: Optional[datetime] = None
    is_starred: Optional[bool] = None
    notes: Optional[str] = None
    rejection_reason: Optional[str] = None
    follow_up_at: Optional[datetime] = None


class ApplicationOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    job_listing_id: uuid.UUID
    resume_id: Optional[uuid.UUID]
    match_score: int
    match_tier: MatchTier
    match_analysis: Dict[str, Any]
    skill_gaps: List[str]
    missing_skills: List[str]
    status: ApplicationStatus
    cover_letter: Optional[str]
    applied_at: Optional[datetime]
    application_id: Optional[str]
    is_starred: bool
    notes: Optional[str]
    follow_up_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    # Joined fields from application_details view
    job_title: Optional[str]
    job_company: Optional[str]
    company_logo_url: Optional[str]
    job_location: Optional[str]
    job_work_mode: Optional[str]
    salary_min: Optional[int]
    salary_max: Optional[int]
    salary_currency: Optional[str]
    source_platform: Optional[str]
    source_url: Optional[str]
    is_easy_apply: Optional[bool]
    job_required_skills: Optional[List[str]]

    class Config:
        from_attributes = True


class PipelineStats(BaseModel):
    status: ApplicationStatus
    count: int


class KanbanColumn(BaseModel):
    id: str
    title: str
    status_list: List[ApplicationStatus]
    applications: List[ApplicationOut] = []
    count: int = 0
