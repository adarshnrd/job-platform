from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid


class ResumeExperience(BaseModel):
    company: str
    title: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    is_current: bool = False
    description: Optional[str] = None
    achievements: List[str] = []
    skills_used: List[str] = []
    location: Optional[str] = None


class ResumeEducation(BaseModel):
    institution: str
    degree: Optional[str] = None
    field: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    gpa: Optional[str] = None
    achievements: List[str] = []


class ResumeProject(BaseModel):
    name: str
    description: Optional[str] = None
    tech_stack: List[str] = []
    url: Optional[str] = None
    achievements: List[str] = []


class ParsedResume(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    summary: Optional[str] = None
    skills: List[str] = []
    tech_stack: Dict[str, int] = {}      # {"React": 5, "Node.js": 3}
    soft_skills: List[str] = []
    experience: List[ResumeExperience] = []
    education: List[ResumeEducation] = []
    projects: List[ResumeProject] = []
    certifications: List[Dict[str, str]] = []
    languages: List[str] = []
    total_experience_years: float = 0.0


class ResumeOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    file_url: str
    file_size: Optional[int]
    is_primary: bool
    is_active: bool
    parsed_data: Dict[str, Any]
    ats_score: Optional[int]
    word_count: Optional[int]
    version: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TailoringRequest(BaseModel):
    resume_id: uuid.UUID
    job_listing_id: uuid.UUID
    emphasis_skills: Optional[List[str]] = None
    output_format: str = "pdf"  # "pdf" | "docx"


class TailoringResult(BaseModel):
    original_resume_id: uuid.UUID
    job_listing_id: uuid.UUID
    tailored_file_url: str
    ats_score_before: Optional[int]
    ats_score_after: Optional[int]
    changes_made: List[str] = []
    keywords_added: List[str] = []
