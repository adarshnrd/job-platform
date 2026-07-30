from pydantic import BaseModel, validator
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
    # Phase 3/4 India + global sources
    iimjobs = "iimjobs"
    timesjobs = "timesjobs"
    shine = "shine"
    freshersworld = "freshersworld"
    ycombinator = "ycombinator"
    # API-first sources
    remotive = "remotive"
    arbeitnow = "arbeitnow"
    themuse = "themuse"
    adzuna = "adzuna"
    jooble = "jooble"
    jsearch = "jsearch"
    careerjet = "careerjet"
    jobicy = "jobicy"
    himalayas = "himalayas"
    # Global-first sources (phase: global expansion)
    arc = "arc"
    welcometothejungle = "welcometothejungle"
    peerlist = "peerlist"
    flexjobs = "flexjobs"
    google_jobs = "google_jobs"
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
    # HR contact (populated by services/hr_contact.py enrichment).
    # hr_email / hr_linkedin_url are verified-only (a provider returned them);
    # hr_linkedin_search_url is a keyless people-search deep-link, always present.
    hr_name: Optional[str] = None
    hr_email: Optional[str] = None
    hr_linkedin_url: Optional[str] = None
    hr_linkedin_search_url: Optional[str] = None
    hr_contact_source: Optional[str] = None       # 'hunter'|'apollo'|'proxycurl'|'search'
    hr_contact_confidence: Optional[int] = None    # 0..100 for verified data


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
    # None = "use my saved preference" (resolved per-user at the endpoint via
    # workers.job_discovery.resolve_region). An explicit value still wins, so a
    # one-off global run doesn't have to change the stored setting.
    region: Optional[str] = None  # "india" | "global" | None
    custom_keywords: Optional[List[str]] = None
    location_override: Optional[str] = None
    max_jobs: int = 50

    @validator("region")
    @classmethod
    def _valid_region(cls, v):
        if v is None:
            return None
        return v if v in ("india", "global") else "india"
