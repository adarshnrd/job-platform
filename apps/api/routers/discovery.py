"""Discovery activity router — live run status, logs, history, recent finds."""
from datetime import datetime, timedelta, timezone

from auth import get_user_id
from database import get_db
from fastapi import APIRouter, Depends
from loguru import logger

from services import discovery_progress as progress

router = APIRouter(prefix="/discovery", tags=["discovery"])

db = get_db()

# Lookback windows for the "recently discovered" summary.
WINDOW_MINUTES = {"10m": 10, "1h": 60, "24h": 1440, "7d": 10080}


@router.get("/sources")
async def list_sources(user_id: str = Depends(get_user_id)):
    """The full source registry with availability — drives the Settings UI.

    An empty `preferred_platforms` profile means ALL browser sources run for
    the user's region; a non-empty list narrows to that subset.
    """
    from workers.job_discovery import SOURCE_REGISTRY, _has_key

    sources = []
    for name, src in sorted(SOURCE_REGISTRY.items()):
        sources.append({
            "name": name,
            "regions": sorted(src.regions),
            "api_based": src.api_based,
            "requires_key": src.requires_key,
            "key_configured": _has_key(src.cls) if src.requires_key else None,
            "login_capable": src.login_capable,
            "discoverable": src.discoverable,
        })
    return {"sources": sources}


@router.get("/status")
async def get_status(user_id: str = Depends(get_user_id)):
    """The user's active discovery run, or their most recent one."""
    return progress.snapshot(user_id)


@router.get("/runs")
async def list_runs(user_id: str = Depends(get_user_id)):
    """Recent run history, newest first."""
    return {"runs": progress.list_runs(user_id)}


@router.get("/events")
async def get_events(run_id: str, after: int = 0, user_id: str = Depends(get_user_id)):
    """Incremental event log for a run — pass the last seen seq as `after`."""
    return progress.get_events(run_id, after)


@router.get("/recent")
async def recent_jobs(window: str = "1h", user_id: str = Depends(get_user_id)):
    """Jobs discovered for this user within the lookback window."""
    minutes = WINDOW_MINUTES.get(window, 60)
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    try:
        res = (
            db.table("application_details")
            .select("id, job_title, job_company, source_platform, job_location, match_score, match_tier, status, created_at")
            .eq("user_id", user_id)
            .gte("created_at", cutoff)
            .order("created_at", desc=True)
            .limit(100)
            .execute()
        )
        jobs = res.data or []
        return {"window": window, "count": len(jobs), "jobs": jobs}
    except Exception as e:
        logger.error(f"Recent-discoveries lookup failed: {e}")
        return {"window": window, "count": 0, "jobs": []}
