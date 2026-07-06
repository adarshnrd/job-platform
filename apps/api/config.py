from pydantic_settings import BaseSettings, NoDecode
from pydantic import field_validator
from functools import lru_cache
from typing import List, Annotated


class Settings(BaseSettings):
    # App
    APP_NAME: str = "JobPlatform API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    API_PREFIX: str = "/api/v1"
    ALLOWED_ORIGINS: Annotated[List[str], NoDecode] = ["http://localhost:3000", "https://yourdomain.com"]

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, v):
        # Accept a comma-separated string in .env (not just a JSON array).
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    # Supabase
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_ROLE_KEY: str
    SUPABASE_JWT_SECRET: str = ""

    # Groq (free, OpenAI-compatible)
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # NVIDIA NIM (free credits, OpenAI-compatible)
    NVIDIA_API_KEY: str = ""
    NVIDIA_MODEL: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"

    # Anthropic (optional — used for high-quality reasoning tasks)
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"

    # Daily LLM budgets — hard stop across ALL providers once exceeded (0 = unlimited)
    LLM_DAILY_TOKEN_BUDGET: int = 0
    LLM_DAILY_BUDGET_USD: float = 0.0

    # Job-source aggregator APIs (optional — sources auto-skip when unset)
    ADZUNA_APP_ID: str = ""
    ADZUNA_APP_KEY: str = ""
    JOOBLE_API_KEY: str = ""
    JSEARCH_RAPIDAPI_KEY: str = ""

    # Email (Resend) — optional; email notifications disabled if unset
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "noreply@jobplatform.ai"
    EMAIL_FROM_NAME: str = "JobPlatform AI"

    # Session encryption
    SESSION_ENCRYPTION_KEY: str = "dev-key-change-in-production"
    SESSION_ENCRYPTION_KEY_VERSION: int = 1
    SESSION_HEALTH_CHECK_HOURS: int = 6

    # Automation
    PLAYWRIGHT_HEADLESS: bool = True
    PLAYWRIGHT_CHANNEL: str = "chrome"  # real Chrome; "" = bundled Chromium
    SCRAPER_ALLOW_HEADED: bool = True   # let bot-walled boards open a visible window
    BROWSER_TIMEOUT_MS: int = 30000
    MAX_APPLY_RETRIES: int = 3
    DISCOVERY_INTERVAL_HOURS: int = 4
    MAX_JOBS_PER_DISCOVERY: int = 50
    DISCOVERY_MAX_SEARCHES_PER_SOURCE: int = 6
    LISTING_REVALIDATION_HOURS: int = 12
    STUCK_RECOVERY_INTERVAL_MINUTES: int = 20
    STUCK_APPLYING_TIMEOUT_MINUTES: int = 30

    # Rate limiting — per-platform daily caps and human-like delays
    RATE_LIMIT_LINKEDIN_DAILY: int = 40
    RATE_LIMIT_LINKEDIN_MIN_DELAY: int = 30
    RATE_LIMIT_LINKEDIN_MAX_DELAY: int = 120
    RATE_LIMIT_NAUKRI_DAILY: int = 80
    RATE_LIMIT_NAUKRI_MIN_DELAY: int = 15
    RATE_LIMIT_NAUKRI_MAX_DELAY: int = 60
    RATE_LIMIT_DEFAULT_DAILY: int = 50
    RATE_LIMIT_DEFAULT_MIN_DELAY: int = 20
    RATE_LIMIT_DEFAULT_MAX_DELAY: int = 90

    # Matching
    AUTO_APPLY_THRESHOLD: int = 80
    RECOMMENDED_THRESHOLD: int = 60
    WATCHLIST_THRESHOLD: int = 50
    DASHBOARD_MIN_SCORE: int = 40

    # Storage
    STORAGE_BUCKET_RESUMES: str = "resumes"
    STORAGE_BUCKET_COVERS: str = "cover-letters"
    STORAGE_BUCKET_SCREENSHOTS: str = "screenshots"

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # .env also holds frontend NEXT_PUBLIC_* vars


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
