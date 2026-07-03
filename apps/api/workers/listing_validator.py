"""
Listing revalidation worker — periodically checks active job listings and marks
dead ones inactive so they drop out of the dashboard, jobs list, and tracker.

Prioritizes listings that (a) are still active and (b) are attached to an
application the user might still act on (not already applied/rejected/withdrawn).
Runs on a schedule via scheduler.py and can be triggered manually.
"""
import asyncio
from datetime import datetime, timezone, timedelta

from loguru import logger

from database import get_supabase_admin
from services.listing_validator import revalidate_batch

# Statuses where the user has already moved on — no need to revalidate.
_TERMINAL_STATUSES = {"applied", "under_review", "assessment", "interview_scheduled",
                      "technical_round", "hr_round", "offer_received", "accepted",
                      "rejected", "withdrawn"}

# Don't recheck a listing more often than this.
_MIN_REVALIDATE_AGE_HOURS = 12
# Cap work per run so a scheduled tick stays bounded.
_MAX_PER_RUN = 100


def run_listing_revalidation() -> dict:
    """Entry point for the scheduler. Runs the async revalidation to completion."""
    try:
        return asyncio.run(_revalidate_async())
    except Exception as e:
        logger.error(f"Listing revalidation failed: {e}")
        return {"checked": 0, "expired": 0, "error": str(e)}


async def _revalidate_async() -> dict:
    db = get_supabase_admin()

    # Candidate listings: still active, attached to a non-terminal application,
    # and not validated recently. We resolve the set via job_applications so we
    # only spend checks on jobs someone actually cares about.
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=_MIN_REVALIDATE_AGE_HOURS)).isoformat()

    apps = (
        db.table("job_applications")
        .select("job_listing_id, status")
        .not_.in_("status", list(_TERMINAL_STATUSES))
        .limit(1000)
        .execute()
    )
    listing_ids = list({a["job_listing_id"] for a in (apps.data or []) if a.get("job_listing_id")})
    if not listing_ids:
        logger.info("Revalidation: no active-application listings to check")
        return {"checked": 0, "expired": 0}

    # Fetch those listings that are active and stale (batched to avoid URL limits).
    listings: list[dict] = []
    for i in range(0, len(listing_ids), 100):
        chunk = listing_ids[i:i + 100]
        res = (
            db.table("job_listings")
            .select("id, source_url, source_platform, last_validated_at, is_active")
            .in_("id", chunk)
            .eq("is_active", True)
            .execute()
        )
        for row in (res.data or []):
            lv = row.get("last_validated_at")
            if lv is None or lv < cutoff:
                listings.append(row)

    if not listings:
        logger.info("Revalidation: all candidate listings recently checked")
        return {"checked": 0, "expired": 0}

    listings = listings[:_MAX_PER_RUN]
    logger.info(f"Revalidating {len(listings)} active listings…")
    result = await revalidate_batch(listings, concurrency=5)
    logger.info(f"Revalidation done: {result['expired']}/{result['checked']} listings expired")
    return result
