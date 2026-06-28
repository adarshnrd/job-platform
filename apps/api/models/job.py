from pydantic import BaseModel, HttpUrl, validator
from typing import Optional, List
from enum import Enum
from datetime import datetime
import uuid


class Platform(str, Enum):
    linkedin = "linkedin"
    naukri = "naukri"
    indeed = "indeed"
    wellfound = "wellfound"
    hirist = "hirist"
    instahyre = "instahyre"
    cutshort = "cutshort"
    glassdoor = "glassdoor"
    foundit = "foundit"
    remoteok = "remoteok"
    weworkremotely = "weworkremotely"
    dice = "dice"
    ziprecruiter = "ziprecruiter"
    angellist = "angellist"
    # API-first sources
    remotive = "remotive"
    arbeitnow = "arbeitnow"
    themuse = "themuse"
    adzuna = "adzuna"
    jooble = "jooble"
    jsearch = "jsearch"
    company_portal = "company_portal"
    other = "other"


class WorkMode(str, Enum):
    remote = "remote"
    hybrid = "hybrid"
    onsite = "onsite"


class JobType(str, Enum):
    full_time = "full_time"
    part_time = "part_time"
    contract = "contract"
    freelance = "freelance"
    internship = "internship"


class ExperienceLevel(str, Enum):
    entry = "entry"
    mid = "mid"
    senior = "senior"
    lead = "lead"
    principal = "principal"
    executive = "executive"


class JobListingCreate(BaseModel):
    title: str
    company: str
    company_logo_url: Optional[str] = None
    company_website: Optional[str] = None
    location: Optional[str] = None
    work_mode: Optional[WorkMode] = None
    job_type: JobType = JobType.full_time
    experience_level: Optional[ExperienceLevel] = None
    min_experience: Optional[int] = None
    max_experience: Optional[int] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_currency: str = "INR"
    jd_text: str
    jd_html: Optional[str] = None
    required_skills: List[str] = []
    nice_to_have_skills: List[str] = []
    source_platform: Platform
    source_url: str
    source_job_id: Optional[str] = None
    apply_url: Optional[str] = None
    is_easy_apply: bool = False
    is_remote_friendly: bool = False
    hiring_manager: Optional[str] = None
    posted_at: Optional[datetime] = None
    hiring_manager_url: Optional[str] = None
    company_size: Optional[str] = None
    company_industry: Optional[str] = None


class JobListingOut(JobListingCreate):
    id: uuid.UUID
    is_active: bool
    views_count: int
    discovered_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class JobSearchFilters(BaseModel):
    query: Optional[str] = None
    platforms: Optional[List[Platform]] = None
    work_modes: Optional[List[WorkMode]] = None
    job_types: Optional[List[JobType]] = None
    experience_levels: Optional[List[ExperienceLevel]] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    min_match_score: Optional[int] = None
    is_easy_apply: Optional[bool] = None
    skills: Optional[List[str]] = None
    location: Optional[str] = None
    limit: int = 20
    offset: int = 0


class DiscoveryRequest(BaseModel):
    platforms: List[Platform] = [Platform.linkedin, Platform.naukri, Platform.indeed]
    region: str = "india"  # "india" | "global"
    custom_keywords: Optional[List[str]] = None
    location_override: Optional[str] = None
    max_jobs: int = 50

    @validator("region")
    @classmethod
    def _valid_region(cls, v):
        return v if v in ("india", "global") else "india"
