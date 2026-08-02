"""
Pipeline worker — runs the post-scrape AI stages off the durable queue.

Scraping persists jobs immediately (workers/job_discovery._checkpoint); this
module does everything that comes after, one claimed batch at a time:

    scraped ──parse──> parsed ──enrich──> enriched ──score──> scored → done

Each stage claims a bounded batch, does its work, writes the result, and only
then advances the item. Every per-item write is isolated, so one bad job can
never abort a batch, and every stage is idempotent, so an interrupted item is
simply re-run. Nothing here can lose scrape work: the listing rows already
exist before the first LLM call.

Two callers:
  • a discovery run drains its own queue inline (unchanged live UX);
  • APScheduler drains every user's queue on an interval, which is what makes
    the pipeline resume by itself after a crash or restart.

Design notes: docs/PIPELINE_DURABILITY_DESIGN.md
"""
import asyncio

from loguru import logger

from config import settings
from database import get_db, select_in_batches
from services import discovery_progress as progress
from services import job_pipeline as pipeline
from services.ai import batch_parse_jds, batch_score_jobs, failed_result
from services.experience import merge_experience

db = get_db()

_LISTING_COLUMNS = (
    "id, title, company, jd_text, company_website, apply_url, source_url, "
    "source_platform, min_experience, max_experience, experience_level"
)

# Safety cap on drain rounds so a persistent claim/advance mismatch can never
# spin forever.
_MAX_DRAIN_ROUNDS = 200


class _ListingView:
    """Mutable, duck-typed stand-in for JobListingCreate over a job_listings row.

    `merge_experience` and `hr_contact.enrich_jobs` were written against the
    pydantic model and mutate their argument in place. Once listings live in the
    database, the pipeline works with rows instead — this adapts them without
    forcing a full model round-trip (the row is deliberately a partial select).
    """

    _FIELDS = (
        "title", "company", "jd_text", "company_website", "apply_url", "source_url",
        "min_experience", "max_experience", "experience_level",
        "hr_name", "hr_email", "hr_linkedin_url", "hr_linkedin_search_url",
        "hr_contact_source", "hr_contact_confidence",
    )

    def __init__(self, row: dict):
        for field in self._FIELDS:
            setattr(self, field, row.get(field))
        self.id = row.get("id")


def _load_listings(items: list[dict]) -> dict[str, dict]:
    """Rows for a claimed batch, keyed by listing id."""
    ids = [i["job_listing_id"] for i in items if i.get("job_listing_id")]
    if not ids:
        return {}
    try:
        rows = select_in_batches(db, "job_listings", _LISTING_COLUMNS, "id", ids)
        return {r["id"]: r for r in rows}
    except Exception as e:
        logger.error(f"Loading listings for a claimed batch failed: {e}")
        return {}


def _budget_blocked() -> str | None:
    """The daily LLM budget message if calls are blocked right now, else None.

    Checked before claiming an LLM stage. Budget exhaustion is a "come back
    later", not a defect: items stay pending, keep their attempts, and are
    picked up by a later drain — instead of being written as score-0/archived
    and never re-evaluated.
    """
    from services.ai.provider import BudgetExceededError, _check_budget
    try:
        _check_budget()
        return None
    except BudgetExceededError as e:
        return str(e)
    except Exception:
        return None


def _fail(item: dict, error: str) -> None:
    pipeline.fail(
        item["id"], error,
        attempts=item.get("attempts", 0),
        max_attempts=item.get("max_attempts") or settings.PIPELINE_MAX_ATTEMPTS,
    )


def _drop_orphans(items: list[dict], listings: dict[str, dict]) -> list[dict]:
    """Items whose listing no longer exists can never make progress."""
    alive = []
    for item in items:
        if item.get("job_listing_id") in listings:
            alive.append(item)
        else:
            pipeline.fail(
                item["id"], "job listing missing",
                attempts=settings.PIPELINE_MAX_ATTEMPTS,
                max_attempts=settings.PIPELINE_MAX_ATTEMPTS,
            )
    return alive


# ══════════════════════════════════════════════════════════════
#  STAGES
# ══════════════════════════════════════════════════════════════

async def run_stage_parse(user_id: str, limit: int | None = None, run_id: str = "") -> dict:
    """scraped → parsed. Parses each JD and writes experience back to the listing.

    A parse that comes back empty still advances: scoring works from the raw JD
    text, and blocking here would deny the user a match record over metadata.
    The failure is recorded on the item either way.
    """
    result = {"claimed": 0, "advanced": 0, "failed": 0, "blocked": None}

    blocked = _budget_blocked()
    if blocked:
        result["blocked"] = blocked
        return result

    items = pipeline.claim_batch(pipeline.STAGE_SCRAPED, limit, user_id)
    if not items:
        return result
    result["claimed"] = len(items)

    listings = _load_listings(items)
    items = _drop_orphans(items, listings)
    if not items:
        result["failed"] = result["claimed"]
        return result

    views = [_ListingView(listings[i["job_listing_id"]]) for i in items]
    parsed_jds = await batch_parse_jds([v.jd_text or "" for v in views])

    for item, view, parsed in zip(items, views, parsed_jds):
        try:
            parsed = parsed if isinstance(parsed, dict) else {}
            # Precedence: scraper-set > LLM-parsed > regex over the JD.
            if merge_experience(view, parsed):
                pipeline.update_listing(view.id, pipeline.experience_fields(view))
            pipeline.advance(item["id"], pipeline.STAGE_PARSED, parsed_jd=parsed)
            result["advanced"] += 1
        except Exception as e:
            logger.error(f"Parse stage failed for item {item['id']}: {e}")
            _fail(item, str(e))
            result["failed"] += 1
    return result


async def run_stage_enrich(user_id: str, limit: int | None = None, run_id: str = "") -> dict:
    """parsed → enriched. Attaches HR contact links. Never blocks a job.

    Enrichment is a bonus, not a requirement: whatever happens here, the item
    advances to scoring, matching the non-fatal contract it has always had.
    """
    result = {"claimed": 0, "advanced": 0, "failed": 0, "enriched": 0}

    items = pipeline.claim_batch(pipeline.STAGE_PARSED, limit, user_id)
    if not items:
        return result
    result["claimed"] = len(items)

    listings = _load_listings(items)
    items = _drop_orphans(items, listings)
    if not items:
        result["failed"] = result["claimed"]
        return result

    views = [_ListingView(listings[i["job_listing_id"]]) for i in items]

    if settings.HR_CONTACT_ENRICHMENT_ENABLED:
        try:
            from services.hr_contact import enrich_jobs
            result["enriched"] = await enrich_jobs(views)
        except Exception as e:
            logger.warning(f"HR-contact enrichment failed (non-fatal): {e}")

    for item, view in zip(items, views):
        try:
            fields = pipeline.hr_contact_fields(view)
            if any(v is not None for v in fields.values()):
                pipeline.update_listing(view.id, fields)
        except Exception as e:
            logger.warning(f"HR write-back failed for item {item['id']} (non-fatal): {e}")
        pipeline.advance(item["id"], pipeline.STAGE_ENRICHED)
        result["advanced"] += 1
    return result


async def run_stage_score(user_id: str, limit: int | None = None, run_id: str = "") -> dict:
    """enriched → done. Scores against the profile and writes the match record.

    A scoring failure retries instead of persisting a 0/archived verdict, so an
    LLM outage no longer silently buries a user's jobs at the bottom of the list.
    """
    result = {
        "claimed": 0, "advanced": 0, "failed": 0,
        "matched": 0, "queued": 0, "blocked": None,
    }

    blocked = _budget_blocked()
    if blocked:
        result["blocked"] = blocked
        return result

    user = _load_user(user_id)
    if not user:
        return result

    items = pipeline.claim_batch(pipeline.STAGE_ENRICHED, limit, user_id)
    if not items:
        return result
    result["claimed"] = len(items)

    listings = _load_listings(items)
    items = _drop_orphans(items, listings)
    if not items:
        result["failed"] = result["claimed"]
        return result

    score_inputs = [
        (item.get("parsed_jd") or {}, listings[item["job_listing_id"]].get("jd_text") or "")
        for item in items
    ]
    scores = await batch_score_jobs(user, score_inputs, double_eval_threshold=70)

    for item, listing, score_result in zip(items, [listings[i["job_listing_id"]] for i in items], scores):
        if failed_result(score_result):
            # No verdict — retry later rather than recording a false zero.
            _fail(item, "scoring returned no result (provider failure)")
            result["failed"] += 1
            continue
        try:
            matched, queued = _save_match(user, user_id, item, listing, score_result)
            pipeline.advance(item["id"], pipeline.STAGE_DONE)
            result["advanced"] += 1
            result["matched"] += int(matched)
            result["queued"] += int(queued)
        except Exception as e:
            logger.error(f"Saving match for item {item['id']} failed: {e}")
            _fail(item, str(e))
            result["failed"] += 1
    return result


def _load_user(user_id: str) -> dict | None:
    try:
        res = db.table("users").select("*").eq("id", user_id).single().execute()
        return res.data or None
    except Exception as e:
        logger.error(f"Loading profile {user_id} for scoring failed: {e}")
        return None


def _save_match(user: dict, user_id: str, item: dict, listing: dict, score_result: dict) -> tuple[bool, bool]:
    """Write the match record and queue an auto-apply. Raises on a failed write
    so the caller can retry the item — the listing itself is already safe."""
    score = score_result.get("overall_score", 0)
    tier = score_result.get("tier", "archived")
    job_id = item["job_listing_id"]

    app_data = {
        "user_id": user_id,
        "job_listing_id": job_id,
        "match_score": score,
        "match_tier": tier,
        "match_analysis": {
            "strengths": score_result.get("strengths", []),
            "gaps": score_result.get("gaps", []),
            "recommendations": score_result.get("recommendations", []),
            "summary": score_result.get("summary", ""),
            "score_breakdown": score_result.get("score_breakdown", {}),
            "evaluated_by": score_result.get("_evaluated_by", ""),
            "score_spread": score_result.get("_score_spread"),
            "dual_scores": score_result.get("_scores"),
        },
        "skill_gaps": score_result.get("missing_required_skills", []),
        "missing_skills": score_result.get("missing_nice_skills", []),
        "status": "matched",
    }
    app_res = db.table("job_applications").upsert(
        app_data, on_conflict="user_id,job_listing_id"
    ).execute()
    application_id = app_res.data[0]["id"] if app_res.data else None

    queued = False
    # Only auto-queue when the *portal* supports full automation (Tier A).
    # Tier-B portals stay as matches for assisted apply even at a high score.
    from services.portals import auto_appliable
    platform = item.get("source_platform") or listing.get("source_platform") or ""
    if (
        tier == "auto_apply"
        and user.get("auto_apply_enabled")
        and auto_appliable(platform)
        and application_id
    ):
        try:
            # Idempotent: a retry after a crash between insert and advance must
            # not queue the same application twice.
            existing = db.table("apply_queue").select("id")\
                .eq("application_id", application_id).limit(1).execute()
            if not existing.data:
                db.table("apply_queue").insert({
                    "application_id": application_id,
                    "user_id": user_id,
                    "priority": 10 - (score // 10),
                }).execute()
                db.table("job_applications").update(
                    {"status": "queued"}
                ).eq("id", application_id).execute()
                queued = True
        except Exception as e:
            # The match is saved; queueing is a separate concern and must not
            # send this item back for a re-score (which would re-bill the LLM).
            logger.error(f"Auto-apply queueing failed for application {application_id}: {e}")

    return score >= settings.RECOMMENDED_THRESHOLD, queued


# ══════════════════════════════════════════════════════════════
#  DRAIN
# ══════════════════════════════════════════════════════════════

async def drain(user_id: str, run_id: str = "", limit: int | None = None) -> dict:
    """Run every stage for one user until no claimable work remains.

    Safe to call concurrently with another drain: claims are leased with
    FOR UPDATE SKIP LOCKED, so two callers get disjoint batches.
    """
    totals = {
        "parsed": 0, "enriched": 0, "scored": 0, "failed": 0,
        "matched": 0, "queued": 0, "blocked": None,
    }
    if not pipeline.pipeline_available():
        return totals

    pipeline.release_stale_claims()

    for _ in range(_MAX_DRAIN_ROUNDS):
        worked = 0

        parse_res = await run_stage_parse(user_id, limit, run_id)
        totals["parsed"] += parse_res["advanced"]
        totals["failed"] += parse_res["failed"]
        worked += parse_res["claimed"]
        if parse_res.get("blocked"):
            totals["blocked"] = parse_res["blocked"]

        enrich_res = await run_stage_enrich(user_id, limit, run_id)
        totals["enriched"] += enrich_res["advanced"]
        totals["failed"] += enrich_res["failed"]
        worked += enrich_res["claimed"]

        if run_id and totals["parsed"] and not totals["scored"]:
            progress.set_phase(
                run_id, "scoring",
                f"Scoring {totals['parsed']} job(s) against your profile (dual-LLM double-eval)",
            )
        score_res = await run_stage_score(user_id, limit, run_id)
        totals["scored"] += score_res["advanced"]
        totals["failed"] += score_res["failed"]
        totals["matched"] += score_res["matched"]
        totals["queued"] += score_res["queued"]
        worked += score_res["claimed"]
        if score_res.get("blocked"):
            totals["blocked"] = score_res["blocked"]

        if run_id:
            progress.update_counts(
                run_id,
                evaluated=totals["parsed"],
                matched=totals["matched"],
                queued=totals["queued"],
                saved=totals["scored"],
            )

        if not worked:
            break
        if totals["blocked"]:
            # Budget exhausted — everything still pending waits for the reset.
            break

    if totals["blocked"] and run_id:
        progress.log(run_id, f"AI stages paused — {totals['blocked']}", "error")
    if totals["failed"] and run_id:
        progress.log(
            run_id,
            f"{totals['failed']} job(s) failed a processing stage — the listings are "
            f"stored and will be retried automatically",
            "error",
        )
    return totals


def drain_all_users(limit: int | None = None) -> dict:
    """Finish whatever any run left behind. Entry point for the scheduler.

    This is what makes the pipeline resumable: a run killed mid-stage leaves its
    items in the queue, and the next tick picks them up — no re-scraping, no user
    action.
    """
    summary = {"users": 0, "scored": 0, "matched": 0, "failed": 0}
    if not pipeline.pipeline_available():
        return summary

    released = pipeline.release_stale_claims()
    if released:
        logger.info(f"Pipeline: released {released} stale claim(s) from an interrupted run")

    user_ids = pipeline.users_with_work()
    if not user_ids:
        return summary

    logger.info(f"Pipeline drain: {len(user_ids)} user(s) with pending work")
    for user_id in user_ids:
        try:
            totals = asyncio.run(drain(user_id, limit=limit))
        except Exception as e:
            logger.error(f"Pipeline drain failed for {user_id}: {e}")
            continue
        summary["users"] += 1
        summary["scored"] += totals["scored"]
        summary["matched"] += totals["matched"]
        summary["failed"] += totals["failed"]
        if totals["scored"] or totals["failed"]:
            logger.info(
                f"Pipeline drain for {user_id}: {totals['scored']} scored, "
                f"{totals['matched']} matched, {totals['failed']} failed"
            )
        # A drain that finished work for a user means their tracker is stale.
        if totals["scored"]:
            try:
                from services.job_tracker import update_tracker
                update_tracker(user_id)
            except Exception as e:
                logger.warning(f"Job tracker update failed (non-fatal): {e}")
    return summary
