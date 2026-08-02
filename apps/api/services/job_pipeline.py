"""
Durable discovery pipeline — persistence and per-job stage state.

The discovery worker used to hold every scraped job in a Python list until all
AI stages had finished, so a single transient fault threw away hours of
scraping. This module inverts that: a job is written to `job_listings` the
moment a scraper returns it, and a `job_pipeline_items` row records where that
job is in the post-scrape pipeline.

    scraped ──parse──> parsed ──enrich──> enriched ──score──> scored ──> done
                                                                └ prefiltered (terminal)

Every stage reads and writes the database, so a crash, a restart or a provider
outage costs at most the in-flight batch — never the scrape. Failed stages back
off and retry independently; the scrape output is already safe.

Everything here is non-fatal by contract: functions log and return a falsy
value rather than raising, so a caller can never lose a batch to one bad row.
Design notes: docs/PIPELINE_DURABILITY_DESIGN.md

Requires database/16_pipeline_durability.sql. Until that migration is applied,
`pipeline_available()` returns False and the worker falls back to the legacy
in-memory flow.
"""
from datetime import datetime, timedelta, timezone

from loguru import logger

from config import settings
from database import get_db
from services.dedup import job_fingerprint

db = get_db()

TABLE = "job_pipeline_items"

# Ordered pipeline stages. `done` and `prefiltered` are terminal.
STAGE_SCRAPED = "scraped"
STAGE_PARSED = "parsed"
STAGE_ENRICHED = "enriched"
STAGE_SCORED = "scored"
STAGE_DONE = "done"
STAGE_PREFILTERED = "prefiltered"

# What each work stage produces. The keys are the stages a worker claims from.
NEXT_STAGE = {
    STAGE_SCRAPED: STAGE_PARSED,
    STAGE_PARSED: STAGE_ENRICHED,
    STAGE_ENRICHED: STAGE_SCORED,
    STAGE_SCORED: STAGE_DONE,
}

# HR-contact columns (migration 12) — stripped from the payload if the live DB
# hasn't run 12_hr_contact.sql yet. Keep in sync with models.job.JobListingCreate.
_HR_CONTACT_COLUMNS = (
    "hr_name", "hr_email", "hr_linkedin_url",
    "hr_linkedin_search_url", "hr_contact_source", "hr_contact_confidence",
)

_MAX_ERROR_LEN = 500

# Probed once per process: is migration 16 applied?
_available: bool | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def pipeline_available() -> bool:
    """True when `job_pipeline_items` exists (migration 16 applied).

    Probed once and cached. A False result makes the discovery worker fall back
    to the legacy in-memory pipeline, so a database that hasn't been migrated
    keeps working exactly as before.
    """
    global _available
    if _available is not None:
        return _available
    if not settings.PIPELINE_DURABLE_ENABLED:
        logger.info("Durable pipeline disabled by PIPELINE_DURABLE_ENABLED=false")
        _available = False
        return _available
    try:
        db.table(TABLE).select("id").limit(1).execute()
        _available = True
    except Exception as e:
        logger.warning(
            f"job_pipeline_items unavailable ({e}) — falling back to the in-memory "
            f"pipeline. Run database/16_pipeline_durability.sql to make discovery "
            f"crash-safe."
        )
        _available = False
    return _available


def _reset_availability_for_tests():
    """Clear the cached probe — tests only."""
    global _available
    _available = None


# ══════════════════════════════════════════════════════════════
#  JOB LISTING PERSISTENCE
# ══════════════════════════════════════════════════════════════

def _ilike_exact(text: str) -> str:
    """Escape LIKE wildcards so .ilike() does a case-insensitive exact match."""
    return (text or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _find_existing_listing(job_data: dict) -> str | None:
    """Content-level dedup: a listing with the same normalized title+company is
    the same job, no matter what URL the portal minted for the repost."""
    try:
        res = db.table("job_listings").select("id")\
            .eq("dedupe_key", job_data["dedupe_key"]).limit(1).execute()
        return res.data[0]["id"] if res.data else None
    except Exception:
        # Pre-migration: dedupe_key column missing (run database/11_job_dedup.sql).
        # Fall back to case-insensitive exact title+company — catches identical
        # reposts, just not punctuation/suffix variants.
        try:
            res = db.table("job_listings").select("id")\
                .ilike("title", _ilike_exact(job_data.get("title")))\
                .ilike("company", _ilike_exact(job_data.get("company")))\
                .limit(1).execute()
            return res.data[0]["id"] if res.data else None
        except Exception as e:
            logger.warning(f"Dedup lookup skipped: {e}")
            return None


async def upsert_job_listing(job) -> str | None:
    """Store one scraped listing, returning its id (None if it could not be stored).

    This is the durability checkpoint for a single job: everything a listing row
    needs comes from the scraper, so it is written before any AI runs.
    """
    from services.portals import normalize_job_url

    job_data = job.dict()
    # Canonicalize the URL (e.g. angel.co → wellfound.com) so the same role from
    # different hosts collapses onto one listing via the unique source_url index.
    if job_data.get("source_url"):
        job_data["source_url"] = normalize_job_url(job_data["source_url"])
    job_data["dedupe_key"] = job_fingerprint(job_data.get("title"), job_data.get("company"))
    # Same role already stored under a different URL? Reuse that listing so the
    # application lands on it instead of creating a duplicate row.
    existing_id = _find_existing_listing(job_data)
    if existing_id:
        return existing_id
    job_data["required_skills"] = list(job_data.get("required_skills") or [])
    job_data["nice_to_have_skills"] = list(job_data.get("nice_to_have_skills") or [])
    # Pydantic enum → its string value for the Postgres enum column.
    platform_value = getattr(job_data.get("source_platform"), "value", job_data.get("source_platform"))
    job_data["source_platform"] = platform_value
    if job_data.get("posted_at"):
        job_data["posted_at"] = job_data["posted_at"].isoformat() if isinstance(job_data["posted_at"], datetime) else job_data["posted_at"]
    else:
        job_data["posted_at"] = datetime.utcnow().isoformat()

    # Pre-migration safety: the live DB may lack optional columns/enum values
    # (dedupe_key from migration 11, hr_* from migration 12, new platform enum
    # values from 02). PostgREST reports one missing column per attempt, so strip
    # the offending class and retry — up to a few times to clear a stacked set.
    for _ in range(4):
        try:
            result = db.table("job_listings").upsert(job_data, on_conflict="source_url").execute()
            return result.data[0]["id"] if result.data else None
        except Exception as e:
            err = str(e).lower()
            if "dedupe_key" in err and "dedupe_key" in job_data:
                logger.warning("dedupe_key column missing — run database/11_job_dedup.sql for DB-level dedup.")
                job_data.pop("dedupe_key", None)
            elif any(k in err for k in ("hr_email", "hr_linkedin", "hr_name", "hr_contact")) \
                    and any(k in job_data for k in _HR_CONTACT_COLUMNS):
                logger.warning("hr_* contact columns missing — run database/12_hr_contact.sql to store HR contacts.")
                for k in _HR_CONTACT_COLUMNS:
                    job_data.pop(k, None)
            elif "invalid input value for enum" in err and job_data.get("source_platform") != "other":
                logger.warning(f"Enum value '{platform_value}' not in DB yet — storing as 'other'. Run 02_api_sources.sql.")
                job_data["source_platform"] = "other"
            else:
                logger.error(f"Job upsert failed: {e}")
                return None
    logger.error("Job upsert failed after stripping optional columns")
    return None


def experience_fields(job) -> dict:
    """Experience columns to write back after the parse stage filled them in."""
    return {
        "min_experience": getattr(job, "min_experience", None),
        "max_experience": getattr(job, "max_experience", None),
        "experience_level": getattr(
            getattr(job, "experience_level", None), "value", getattr(job, "experience_level", None)
        ),
    }


def hr_contact_fields(job) -> dict:
    """HR-contact columns to write back after the enrich stage populated them."""
    return {k: getattr(job, k, None) for k in _HR_CONTACT_COLUMNS}


def update_listing(listing_id: str, fields: dict) -> bool:
    """Patch an already-stored listing with enrichment (experience, HR contact).

    Drops optional columns the live DB doesn't have yet rather than failing —
    the same self-healing contract as `upsert_job_listing`.
    """
    payload = {k: v for k, v in fields.items() if v is not None}
    if not payload or not listing_id:
        return False
    for _ in range(3):
        try:
            db.table("job_listings").update(payload).eq("id", listing_id).execute()
            return True
        except Exception as e:
            err = str(e).lower()
            dropped = [k for k in list(payload) if k.lower() in err]
            if dropped:
                logger.warning(f"Listing columns missing, skipping {dropped} — check pending migrations.")
                for k in dropped:
                    payload.pop(k, None)
                if not payload:
                    return False
                continue
            logger.warning(f"Listing enrichment update failed for {listing_id}: {e}")
            return False
    return False


# ══════════════════════════════════════════════════════════════
#  WORK ITEMS
# ══════════════════════════════════════════════════════════════

async def persist_scraped_batch(
    jobs: list,
    *,
    user_id: str,
    run_id: str = "",
    prefiltered: set[int] | frozenset = frozenset(),
) -> list[str | None]:
    """Persist a freshly scraped batch and enqueue it for AI processing.

    Called after every query result, not at the end of the run — this is what
    guarantees that a later failure can never discard scrape work. Returns the
    listing id per input job (None where the listing could not be stored).

    Indices in `prefiltered` are stored as listings but enqueued at the terminal
    `prefiltered` stage: the rule-based gate keeps protecting the LLM budget,
    while the job itself stays recorded and revivable.
    """
    listing_ids: list[str | None] = []
    items: list[dict] = []

    for i, job in enumerate(jobs):
        try:
            listing_id = await upsert_job_listing(job)
        except Exception as e:
            # upsert_job_listing swallows its own errors; this is belt-and-braces
            # so one pathological job can never abort the batch.
            logger.error(f"Listing persist failed for '{getattr(job, 'title', '?')}': {e}")
            listing_id = None
        listing_ids.append(listing_id)
        if not listing_id:
            continue
        items.append({
            "user_id": user_id,
            "run_id": run_id,
            "job_listing_id": listing_id,
            "source_platform": str(
                getattr(job.source_platform, "value", job.source_platform) or ""
            ),
            "stage": STAGE_PREFILTERED if i in prefiltered else STAGE_SCRAPED,
            "stage_status": "pending",
            "next_attempt_at": _iso(_now()),
        })

    if items and pipeline_available():
        # ignore_duplicates: a job this user already has an item for keeps its
        # existing stage. Re-discovering a listing must never rewind a finished
        # item to 'scraped' and re-run (and re-bill) the AI stages.
        try:
            db.table(TABLE).upsert(
                items, on_conflict="user_id,job_listing_id", ignore_duplicates=True
            ).execute()
        except Exception as e:
            logger.error(f"Enqueueing {len(items)} pipeline item(s) failed: {e}")

    return listing_ids


def claim_batch(stage: str, limit: int | None = None, user_id: str | None = None) -> list[dict]:
    """Lease up to `limit` claimable items in `stage`.

    Uses the claim_pipeline_items RPC (FOR UPDATE SKIP LOCKED) so an inline
    discovery run and the scheduled drain can never process — and bill for —
    the same job twice. Falls back to a conditional UPDATE when the function
    isn't present.
    """
    if not pipeline_available():
        return []
    limit = limit or settings.PIPELINE_BATCH_SIZE
    params = {"p_stage": stage, "p_limit": limit}
    if user_id:
        params["p_user_id"] = user_id
    try:
        res = db.rpc("claim_pipeline_items", params).execute()
        return res.data or []
    except Exception as e:
        logger.debug(f"claim_pipeline_items RPC unavailable ({e}) — using fallback claim")

    try:
        q = (
            db.table(TABLE).select("id")
            .eq("stage", stage)
            .eq("stage_status", "pending")
            .lte("next_attempt_at", _iso(_now()))
        )
        if user_id:
            q = q.eq("user_id", user_id)
        rows = q.order("created_at").limit(limit).execute().data or []
        ids = [r["id"] for r in rows]
        if not ids:
            return []
        # .eq("stage_status", "pending") makes the claim conditional: a racing
        # claimer's rows simply don't match and aren't returned.
        res = (
            db.table(TABLE)
            .update({"stage_status": "processing", "claimed_at": _iso(_now())})
            .in_("id", ids)
            .eq("stage_status", "pending")
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.error(f"Claiming {stage} batch failed: {e}")
        return []


def advance(item_id: str, next_stage: str, **fields) -> bool:
    """Move an item to its next stage, clearing retry state.

    Called only after the stage's own writes have landed, so a crash in between
    re-runs the stage — every stage is idempotent by design.
    """
    payload = {
        "stage": next_stage,
        "stage_status": "pending",
        "attempts": 0,
        "last_error": None,
        "claimed_at": None,
        "next_attempt_at": _iso(_now()),
        **fields,
    }
    try:
        db.table(TABLE).update(payload).eq("id", item_id).execute()
        return True
    except Exception as e:
        logger.error(f"Advancing item {item_id} to {next_stage} failed: {e}")
        return False


def fail(
    item_id: str,
    error: str,
    *,
    attempts: int = 0,
    max_attempts: int | None = None,
    retry_after_seconds: int | None = None,
) -> bool:
    """Record a stage failure: back off and retry, or give up on this stage.

    `retry_after_seconds` schedules a wait *without* consuming an attempt — used
    for LLM budget exhaustion, which is a "come back later", not a defect. The
    listing itself is already stored either way.
    """
    max_attempts = max_attempts or settings.PIPELINE_MAX_ATTEMPTS
    message = str(error)[:_MAX_ERROR_LEN]

    if retry_after_seconds is not None:
        payload = {
            "stage_status": "pending",
            "claimed_at": None,
            "last_error": message,
            "next_attempt_at": _iso(_now() + timedelta(seconds=retry_after_seconds)),
        }
    else:
        attempts += 1
        if attempts >= max_attempts:
            payload = {
                "stage_status": "failed",
                "attempts": attempts,
                "claimed_at": None,
                "last_error": message,
            }
        else:
            # 2, 4, 8 minutes — transient DNS/5xx faults self-heal on a later drain.
            payload = {
                "stage_status": "pending",
                "attempts": attempts,
                "claimed_at": None,
                "last_error": message,
                "next_attempt_at": _iso(_now() + timedelta(minutes=2 ** attempts)),
            }
    try:
        db.table(TABLE).update(payload).eq("id", item_id).execute()
        return True
    except Exception as e:
        logger.error(f"Recording failure for item {item_id} failed: {e}")
        return False


def release_stale_claims(minutes: int | None = None) -> int:
    """Return items leased by a worker that died back to the pending pool."""
    if not pipeline_available():
        return 0
    minutes = minutes or settings.PIPELINE_CLAIM_TIMEOUT_MINUTES
    try:
        res = db.rpc("release_stale_pipeline_claims", {"p_minutes": minutes}).execute()
        return int(res.data or 0)
    except Exception as e:
        logger.debug(f"release_stale_pipeline_claims RPC unavailable ({e}) — using fallback")

    cutoff = _iso(_now() - timedelta(minutes=minutes))
    try:
        res = (
            db.table(TABLE)
            .update({"stage_status": "pending", "claimed_at": None})
            .eq("stage_status", "processing")
            .lt("claimed_at", cutoff)
            .execute()
        )
        return len(res.data or [])
    except Exception as e:
        logger.error(f"Releasing stale claims failed: {e}")
        return 0


def pending_counts(user_id: str | None = None) -> dict:
    """{stage: {pending, processing, failed}} — drives the queue panel and drain."""
    if not pipeline_available():
        return {}
    try:
        q = db.table(TABLE).select("stage, stage_status")
        if user_id:
            q = q.eq("user_id", user_id)
        rows = q.limit(10000).execute().data or []
    except Exception as e:
        logger.error(f"Pipeline counts lookup failed: {e}")
        return {}

    counts: dict[str, dict] = {}
    for row in rows:
        bucket = counts.setdefault(
            row.get("stage") or "unknown", {"pending": 0, "processing": 0, "failed": 0}
        )
        status = row.get("stage_status") or "pending"
        bucket[status] = bucket.get(status, 0) + 1
    return counts


def has_work(user_id: str | None = None) -> bool:
    """True if any item is claimable now — the drain loop's stop condition."""
    if not pipeline_available():
        return False
    try:
        q = (
            db.table(TABLE).select("id")
            .in_("stage", list(NEXT_STAGE))
            .eq("stage_status", "pending")
            .lte("next_attempt_at", _iso(_now()))
        )
        if user_id:
            q = q.eq("user_id", user_id)
        return bool(q.limit(1).execute().data)
    except Exception as e:
        logger.error(f"Pipeline work check failed: {e}")
        return False


def users_with_work() -> list[str]:
    """Distinct user ids with claimable items — used by the scheduled drain."""
    if not pipeline_available():
        return []
    try:
        rows = (
            db.table(TABLE).select("user_id")
            .in_("stage", list(NEXT_STAGE))
            .eq("stage_status", "pending")
            .lte("next_attempt_at", _iso(_now()))
            .limit(5000)
            .execute()
        ).data or []
        return list(dict.fromkeys(r["user_id"] for r in rows if r.get("user_id")))
    except Exception as e:
        logger.error(f"Pipeline user lookup failed: {e}")
        return []


def staged_listing_ids(user_id: str) -> list[str]:
    """Listing ids this user already has items for — seeds discovery's dedup set
    so a staged-but-unscored job is never re-scraped and re-processed."""
    if not pipeline_available():
        return []
    try:
        rows = (
            db.table(TABLE).select("job_listing_id")
            .eq("user_id", user_id)
            .limit(20000)
            .execute()
        ).data or []
        return [r["job_listing_id"] for r in rows if r.get("job_listing_id")]
    except Exception as e:
        logger.error(f"Staged-listing lookup failed: {e}")
        return []


def failed_items(user_id: str, limit: int = 50) -> list[dict]:
    """Failed items with enough context for the UI to explain what went wrong."""
    if not pipeline_available():
        return []
    try:
        rows = (
            db.table(TABLE)
            .select("id, stage, attempts, last_error, source_platform, job_listing_id, updated_at")
            .eq("user_id", user_id)
            .eq("stage_status", "failed")
            .order("updated_at", desc=True)
            .limit(limit)
            .execute()
        ).data or []
    except Exception as e:
        logger.error(f"Failed-item lookup failed: {e}")
        return []

    listing_ids = [r["job_listing_id"] for r in rows if r.get("job_listing_id")]
    titles: dict[str, dict] = {}
    if listing_ids:
        try:
            from database import select_in_batches
            for row in select_in_batches(db, "job_listings", "id, title, company", "id", listing_ids):
                titles[row["id"]] = row
        except Exception as e:
            logger.warning(f"Failed-item title lookup skipped: {e}")

    for row in rows:
        listing = titles.get(row.get("job_listing_id"), {})
        row["job_title"] = listing.get("title")
        row["job_company"] = listing.get("company")
    return rows


def requeue_failed(user_id: str, stage: str | None = None) -> int:
    """Reset failed items to pending so the next drain retries them."""
    if not pipeline_available():
        return 0
    try:
        q = (
            db.table(TABLE)
            .update({
                "stage_status": "pending",
                "attempts": 0,
                "last_error": None,
                "claimed_at": None,
                "next_attempt_at": _iso(_now()),
            })
            .eq("user_id", user_id)
            .eq("stage_status", "failed")
        )
        if stage:
            q = q.eq("stage", stage)
        return len(q.execute().data or [])
    except Exception as e:
        logger.error(f"Requeueing failed items failed: {e}")
        return 0


def revive_prefiltered(user_id: str, limit: int = 500) -> int:
    """Send prefiltered jobs back through the AI stages.

    The rule-based gate is recall-first but not infallible; because those jobs
    were still persisted, a tuning fix can replay them instead of costing
    another multi-hour scrape.
    """
    if not pipeline_available():
        return 0
    try:
        rows = (
            db.table(TABLE).select("id")
            .eq("user_id", user_id)
            .eq("stage", STAGE_PREFILTERED)
            .limit(limit)
            .execute()
        ).data or []
        ids = [r["id"] for r in rows]
        if not ids:
            return 0
        db.table(TABLE).update({
            "stage": STAGE_SCRAPED,
            "stage_status": "pending",
            "attempts": 0,
            "last_error": None,
            "next_attempt_at": _iso(_now()),
        }).in_("id", ids).execute()
        return len(ids)
    except Exception as e:
        logger.error(f"Reviving prefiltered items failed: {e}")
        return 0
