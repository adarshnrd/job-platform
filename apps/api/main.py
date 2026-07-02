"""FastAPI application entry point."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from config import settings
from logging_config import setup_logging
from scheduler import start_scheduler, stop_scheduler
from routers import jobs, applications, resumes, ai, automation
from routers.copilot import router as copilot_router
from routers.export import router as export_router
from routers.profile import router as profile_router
from routers.sessions import router as sessions_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: configure logging, validate config, start scheduler. Shutdown: stop scheduler."""
    setup_logging()
    _validate_config()
    start_scheduler()
    logger.info(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} started")
    yield
    stop_scheduler()
    logger.info("Application shut down")


def _validate_config():
    """Fail fast if critical configuration is missing."""
    errors = []

    if not settings.SUPABASE_URL or "YOUR_PROJECT_ID" in settings.SUPABASE_URL:
        errors.append("SUPABASE_URL is not configured")
    if not settings.SUPABASE_ANON_KEY or settings.SUPABASE_ANON_KEY.startswith("your_"):
        errors.append("SUPABASE_ANON_KEY is not configured")
    if not settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_SERVICE_ROLE_KEY.startswith("your_"):
        errors.append("SUPABASE_SERVICE_ROLE_KEY is not configured")

    ai_keys = [settings.GROQ_API_KEY, settings.NVIDIA_API_KEY, settings.ANTHROPIC_API_KEY]
    if not any(k and k.strip() and not k.startswith("your_") for k in ai_keys):
        errors.append("No AI provider configured — set at least one of GROQ_API_KEY, NVIDIA_API_KEY, or ANTHROPIC_API_KEY")

    enc_key = settings.SESSION_ENCRYPTION_KEY
    if enc_key == "dev-key-change-in-production":
        if not settings.DEBUG:
            errors.append(
                "SESSION_ENCRYPTION_KEY must be changed from the default in production "
                "(set DEBUG=True for development). Generate a key: "
                "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        else:
            logger.warning(
                "SESSION_ENCRYPTION_KEY is using the insecure default. "
                "Generate a real key: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )

    if errors:
        for e in errors:
            logger.error(f"Config error: {e}")
        raise SystemExit(f"Startup aborted — {len(errors)} configuration error(s). Check logs above.")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs.router, prefix=settings.API_PREFIX)
app.include_router(applications.router, prefix=settings.API_PREFIX)
app.include_router(resumes.router, prefix=settings.API_PREFIX)
app.include_router(ai.router, prefix=settings.API_PREFIX)
app.include_router(automation.router, prefix=settings.API_PREFIX)
app.include_router(copilot_router, prefix=settings.API_PREFIX)
app.include_router(export_router, prefix=settings.API_PREFIX)
app.include_router(profile_router, prefix=settings.API_PREFIX)
app.include_router(sessions_router, prefix=settings.API_PREFIX)


@app.get("/health")
async def health():
    from scheduler import scheduler
    scheduler_status = "running" if scheduler.running else "stopped"
    try:
        from database import get_supabase_admin
        db = get_supabase_admin()
        db.table("users").select("id").limit(1).execute()
        db_status = "connected"
    except Exception:
        db_status = "unreachable"

    status = "ok" if db_status == "connected" and scheduler_status == "running" else "degraded"
    return {
        "status": status,
        "version": settings.APP_VERSION,
        "database": db_status,
        "scheduler": scheduler_status,
    }
