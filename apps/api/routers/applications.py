"""Application tracking router."""
from auth import get_user_id
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Body

from typing import Optional
from loguru import logger
from database import get_db
from models.application import ApplicationUpdate
from services.ai import generate_interview_prep, draft_answer_for_user, rephrase_answer, generate_cover_letter
from services import application_service
from services.ranking import filter_and_rank, recency_bucket, BUCKET_LABELS

router = APIRouter(prefix="/applications", tags=["applications"])

db = get_db()


# Lifecycle buckets for the Applications page.
# active   — in-flight work the user still acts on
# history  — everything successfully applied (and its aftermath)
# archived — withdrawn, or the listing itself is dead (expired/removed/404)
ACTIVE_STATUSES = {"discovered", "matched", "queued", "applying", "needs_input", "manual_apply"}
HISTORY_STATUSES = {
    "applied", "under_review", "assessment", "interview_scheduled",
    "technical_round", "hr_round", "offer_received", "accepted", "rejected",
}


def _annotate_listing_active(rows: list):
    """Ensure every row has job_is_active. Pre-migration the view lacks the
    column, so look it up from job_listings.is_active (base schema) directly."""
    missing = [r for r in rows if "job_is_active" not in r]
    ids = list({r.get("job_listing_id") for r in missing if r.get("job_listing_id")})
    if not ids:
        return
    try:
        from database import select_in_batches
        listing_rows = select_in_batches(db, "job_listings", "id, is_active", "id", ids)
        by_id = {x["id"]: x.get("is_active") for x in listing_rows}
        for r in missing:
            r["job_is_active"] = by_id.get(r.get("job_listing_id"), True)
    except Exception as e:
        logger.warning(f"Listing-active annotation skipped: {e}")


def _bucket_of(row: dict) -> str:
    status = row.get("status")
    if status in HISTORY_STATUSES:
        return "history"
    if status == "withdrawn" or row.get("job_is_active") is False:
        return "archived"
    return "active"


def _apply_column_sort(rows: list[dict], sort_by: Optional[str], sort_dir: str) -> list[dict]:
    """Explicit column-header sort (tri-state: asc / desc / none).

    Called only when sort_by is set — the caller keeps its own default
    ordering (bucket-appropriate relevance/date) when sort_by is None, which
    is what the third click state ("no sort") falls back to."""
    key_fns = {
        "status": lambda r: (r.get("status") or ""),
        "score": lambda r: (r.get("match_score") if r.get("match_score") is not None else -1),
        "platform": lambda r: (r.get("source_platform") or "").lower(),
        "date": _row_date,
    }
    key_fn = key_fns.get(sort_by)
    if not key_fn:
        return rows
    return sorted(rows, key=key_fn, reverse=(sort_dir == "desc"))


def _row_date(row: dict) -> str:
    """The date this row is keyed on for display and filtering — matches what
    the Date column actually shows: applied date if applied, else discovered."""
    return row.get("applied_at") or row.get("created_at") or ""


def _filter_by_date(rows: list[dict], date_from: Optional[str], date_to: Optional[str]) -> list[dict]:
    if not date_from and not date_to:
        return rows
    from datetime import datetime, timezone

    def parse_bound(s: str, end_of_day: bool) -> datetime:
        d = datetime.fromisoformat(s[:10])
        if end_of_day:
            d = d.replace(hour=23, minute=59, second=59, microsecond=999999)
        return d.replace(tzinfo=timezone.utc)

    lo = parse_bound(date_from, False) if date_from else None
    hi = parse_bound(date_to, True) if date_to else None

    out = []
    for r in rows:
        ts = _row_date(r)
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if lo and dt < lo:
            continue
        if hi and dt > hi:
            continue
        out.append(r)
    return out


def _build_apps_query(db_client, user_id: str, status=None, tier=None, is_starred=None):
    """Build a fresh application_details query with filters.

    Must be called each time because the Supabase query builder is mutable —
    .order() modifies the builder in-place, so a failed attempt poisons it.
    """
    q = db_client.table("application_details").select("*").eq("user_id", user_id)
    if status:
        q = q.eq("status", status)
    if tier:
        q = q.eq("match_tier", tier)
    if is_starred is not None:
        q = q.eq("is_starred", is_starred)
    return q


@router.get("/")
async def list_applications(
    user_id: str = Depends(get_user_id),
    status: Optional[str] = Query(None),
    tier: Optional[str] = Query(None),
    is_starred: Optional[bool] = Query(None),
    min_score: int = Query(50),
    show_archived: bool = Query(False),
    bucket: Optional[str] = Query(None),   # active | history | archived
    sort_by: Optional[str] = Query(None),  # status | score | platform | date | None (bucket default)
    sort_dir: str = Query("asc"),          # asc | desc
    date_from: Optional[str] = Query(None),  # YYYY-MM-DD, inclusive
    date_to: Optional[str] = Query(None),    # YYYY-MM-DD, inclusive
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    try:
        user_res = db.table("users").select("skills").eq("id", user_id).single().execute()
        user_skills = set(user_res.data.get("skills") or []) if user_res.data else set()

        qkw = dict(status=status, tier=tier, is_starred=is_starred)

        try:
            result = _build_apps_query(db, user_id, **qkw)\
                .order("job_posted_at", desc=True).limit(300).execute()
        except Exception:
            result = _build_apps_query(db, user_id, **qkw)\
                .order("created_at", desc=True).limit(300).execute()
        rows = result.data or []
        _annotate_listing_active(rows)
        rows = _filter_by_date(rows, date_from, date_to)

        if bucket in ("active", "history", "archived"):
            groups: dict[str, list] = {"active": [], "history": [], "archived": []}
            for r in rows:
                groups[_bucket_of(r)].append(r)

            if bucket == "active":
                # Score threshold is a hard, user-chosen cutoff here — no skill
                # rescue. Recency ordering still applies to the working queue.
                sel = filter_and_rank(groups["active"], user_skills, min_score, False, rescue=False)
            elif bucket == "history":
                sel = sorted(groups["history"], key=_row_date, reverse=True)
            else:
                sel = sorted(groups["archived"], key=lambda r: (r.get("updated_at") or r.get("created_at") or ""), reverse=True)

            sel = _apply_column_sort(sel, sort_by, sort_dir)

            counts = {
                "active": len(filter_and_rank(list(groups["active"]), user_skills, min_score, False, rescue=False)) if bucket != "active" else len(sel),
                "history": len(groups["history"]),
                "archived": len(groups["archived"]),
            }
            page = sel[offset:offset + limit]
            return {"data": page, "total": len(sel), "offset": offset, "counts": counts}

        ranked = filter_and_rank(rows, user_skills, min_score, show_archived, rescue=False)
        ranked = _apply_column_sort(ranked, sort_by, sort_dir)
        page = ranked[offset:offset + limit]
        return {"data": page, "total": len(ranked), "offset": offset}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pipeline")
async def get_pipeline(user_id: str = Depends(get_user_id)):
    """Get applications grouped by status for the Kanban view, sorted by recency within each column."""
    try:
        result = db.table("application_details").select("*").eq("user_id", user_id).execute()
        apps = result.data or []

        for app in apps:
            bucket = recency_bucket(app)
            app["recency_bucket"] = bucket
            app["recency_label"] = BUCKET_LABELS.get(bucket, "Older")

        columns = [
            {"id": "matched", "title": "Matched", "statuses": ["discovered", "matched", "queued", "manual_apply"]},
            {"id": "applied", "title": "Applied", "statuses": ["applying", "applied"]},
            {"id": "in_progress", "title": "In Progress", "statuses": ["under_review", "assessment"]},
            {"id": "interviews", "title": "Interviews", "statuses": ["interview_scheduled", "technical_round", "hr_round"]},
            {"id": "offers", "title": "Offers", "statuses": ["offer_received", "accepted"]},
            {"id": "closed", "title": "Closed", "statuses": ["rejected", "withdrawn"]},
        ]

        pipeline = []
        for col in columns:
            col_apps = [a for a in apps if a.get("status") in col["statuses"]]
            col_apps.sort(key=lambda a: (a.get("recency_bucket", 3), -(a.get("match_score") or 0)))
            pipeline.append({**col, "applications": col_apps, "count": len(col_apps)})

        stats = {
            "total_applied": sum(1 for a in apps if a.get("status") in ["applied", "under_review", "assessment", "interview_scheduled", "technical_round", "hr_round", "offer_received", "accepted", "rejected"]),
            "total_matched": sum(1 for a in apps if a.get("status") in ["matched", "queued", "manual_apply"]),
            "active_interviews": sum(1 for a in apps if a.get("status") in ["interview_scheduled", "technical_round", "hr_round"]),
            "offers": sum(1 for a in apps if a.get("status") in ["offer_received", "accepted"]),
            "avg_match_score": round(sum((a.get("match_score") or 0) for a in apps) / len(apps), 1) if apps else 0,
        }
        return {"pipeline": pipeline, "stats": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Approval Queue (Recommended tier — 60-79%) ──────────────────────────────
# Must be defined before /{app_id} to avoid FastAPI treating the literal path as an ID.

def _drop_inactive_listings(apps: list) -> list:
    """Filter out apps whose listing is inactive, using job_listings.is_active
    directly. Used when the view lacks job_is_active (06_listing_validation.sql
    not applied) — is_active itself exists in the base schema."""
    ids = list({a.get("job_listing_id") for a in apps if a.get("job_listing_id")})
    if not ids:
        return apps
    try:
        rows = db.table("job_listings").select("id, is_active").in_("id", ids).execute().data or []
        dead = {r["id"] for r in rows if r.get("is_active") is False}
        return [a for a in apps if a.get("job_listing_id") not in dead]
    except Exception as e:
        logger.warning(f"Active-listing fallback filter skipped: {e}")
        return apps


@router.get("/pending-approval")
async def get_pending_approval(
    user_id: str = Depends(get_user_id),
    limit: int = Query(20, le=50),
):
    """Return recommended-tier jobs waiting for user approval before applying.

    Expired listings are excluded — no point asking the user to review a job
    that can no longer be applied to."""
    def _query(active_only: bool):
        q = (
            db.table("application_details")
            .select("*")
            .eq("user_id", user_id)
            .eq("match_tier", "recommended")
            .eq("status", "matched")
        )
        if active_only:
            q = q.eq("job_is_active", True)
        return q.order("match_score", desc=True).limit(limit)

    try:
        result = _query(active_only=True).execute()
        return result.data or []
    except Exception:
        # Pre-migration fallback: job_is_active comes from 06_listing_validation.sql.
        # Filter against job_listings.is_active directly instead.
        logger.warning("job_is_active missing — run database/06_listing_validation.sql; filtering via job_listings")
        result = _query(active_only=False).execute()
        return _drop_inactive_listings(result.data or [])


@router.get("/manual-apply")
async def get_manual_apply(
    user_id: str = Depends(get_user_id),
    limit: int = Query(50, le=100),
):
    """Jobs the bot could not submit automatically — the user applies directly
    via the job link. Includes the last failure reason from the apply queue."""
    def _query(active_only: bool):
        q = (
            db.table("application_details")
            .select("*")
            .eq("user_id", user_id)
            .eq("status", "manual_apply")
        )
        if active_only:
            q = q.eq("job_is_active", True)
        return q.order("match_score", desc=True).limit(limit)

    apps = []
    for active_only in (True, False):
        try:
            apps = _query(active_only).execute().data or []
            if not active_only:
                apps = _drop_inactive_listings(apps)
            break
        except Exception as e:
            if "invalid input value for enum" in str(e).lower():
                # Pre-migration: 'manual_apply' status doesn't exist yet.
                logger.warning("'manual_apply' enum value missing — run database/10_manual_apply.sql")
                return []
            if active_only:
                # job_is_active missing (06_listing_validation.sql) — retry without it.
                continue
            raise

    # Attach the most recent queue error so the UI can say why automation failed.
    if apps:
        try:
            q = (
                db.table("apply_queue")
                .select("application_id, error_msg, created_at")
                .in_("application_id", [a["id"] for a in apps])
                .order("created_at", desc=True)
                .execute()
            )
            reasons: dict[str, str] = {}
            for row in (q.data or []):
                reasons.setdefault(row["application_id"], row.get("error_msg") or "")
            for a in apps:
                a["failure_reason"] = reasons.get(a["id"], "")
        except Exception as e:
            logger.warning(f"Manual-apply reason lookup skipped: {e}")
    return apps


# ─── Rate Limit Status ──────────────────────────────────────────────────────
# Must be defined before /{app_id} to avoid FastAPI treating the literal path as an ID.

@router.get("/rate-limits")
async def get_rate_limits(user_id: str = Depends(get_user_id)):
    """Return current rate limit status per platform."""
    from services.rate_limiter import rate_limiter, get_limits

    platforms = ["linkedin", "naukri", "indeed"]
    result = {}
    for platform in platforms:
        limits = get_limits(platform)
        today_count = rate_limiter.get_today_count(user_id, platform)
        result[platform] = {
            "today_count": today_count,
            "max_daily": limits.max_daily,
            "remaining": max(0, limits.max_daily - today_count),
            "min_delay_seconds": limits.min_delay_seconds,
            "max_delay_seconds": limits.max_delay_seconds,
        }
    return result


@router.get("/check-applied")
async def check_applied(
    user_id: str = Depends(get_user_id),
    job_listing_id: Optional[str] = Query(None),
    source_url: Optional[str] = Query(None),
):
    """Check if the user has already applied to a job. Returns the existing
    application with its applied_url for redirect if found."""
    from workers.application_bot import check_already_applied, check_already_applied_by_url

    if not job_listing_id and not source_url:
        raise HTTPException(status_code=400, detail="Provide job_listing_id or source_url")

    existing = None
    if job_listing_id:
        existing = check_already_applied(user_id, job_listing_id)
    if not existing and source_url:
        existing = check_already_applied_by_url(user_id, source_url)

    if existing:
        return {
            "already_applied": True,
            "application_id": existing["id"],
            "applied_at": existing.get("applied_at"),
            "applied_url": existing.get("applied_url"),
            "source_url": existing.get("source_url"),
            "apply_url": existing.get("apply_url"),
        }
    return {"already_applied": False}


@router.get("/{app_id}")
async def get_application(app_id: str, user_id: str = Depends(get_user_id)):
    result = db.table("application_details").select("*").eq("id", app_id).eq("user_id", user_id).maybe_single().execute()
    if not (result and result.data):
        raise HTTPException(status_code=404, detail="Application not found")
    return result.data


@router.patch("/{app_id}")
async def update_application(app_id: str, update: ApplicationUpdate, user_id: str = Depends(get_user_id)):
    try:
        update_data = {k: v for k, v in update.dict().items() if v is not None}
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")
        result = db.table("job_applications").update(update_data).eq("id", app_id).eq("user_id", user_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Application not found")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{app_id}/star")
async def toggle_star(app_id: str, user_id: str = Depends(get_user_id)):
    app = db.table("job_applications").select("is_starred").eq("id", app_id).eq("user_id", user_id).single().execute()
    if not app.data:
        raise HTTPException(status_code=404)
    new_val = not app.data["is_starred"]
    db.table("job_applications").update({"is_starred": new_val}).eq("id", app_id).execute()
    return {"is_starred": new_val}


# ─── Assisted Apply ───────────────────────────────────────────────────────────

@router.post("/{app_id}/prepare")
async def prepare_application(app_id: str, overrides: dict = Body(default={}), user_id: str = Depends(get_user_id)):
    """Build the assisted-apply package (resume, cover letter, drafted answers,
    form data). Returns {needs_input: [...]} if profile fields are missing.

    Only validate liveness on the FIRST prepare (no overrides): re-prepares after
    the user answers questions shouldn't re-fetch the listing every time."""
    if not overrides:
        await _ensure_listing_live(app_id, user_id)
    result = application_service.prepare_application(user_id, app_id, overrides or {})
    if result.get("error"):
        raise HTTPException(status_code=result.get("status_code", 400), detail=result["error"])
    return result


@router.post("/{app_id}/opened")
async def mark_opened(app_id: str, user_id: str = Depends(get_user_id)):
    """Record that the user opened the external application page."""
    return application_service.mark_opened(user_id, app_id)


@router.post("/{app_id}/confirm-submit")
async def confirm_submit(app_id: str, body: dict = Body(default={}), user_id: str = Depends(get_user_id)):
    """User confirms they submitted the application on the external site."""
    return application_service.confirm_submitted(user_id, app_id, body.get("confirmation_id"))


@router.post("/{app_id}/mark-failed")
async def mark_failed(app_id: str, body: dict = Body(default={}), user_id: str = Depends(get_user_id)):
    """Record that the application could not be submitted, with a reason."""
    reason = body.get("reason") or "Application could not be submitted"
    return application_service.mark_failed(user_id, app_id, reason)


@router.get("/{app_id}/events")
async def get_application_events(app_id: str, user_id: str = Depends(get_user_id)):
    """Return the full audit trail (event timeline) for an application."""
    return application_service.get_events(user_id, app_id)


@router.post("/{app_id}/draft-answer")
async def draft_screening_answer(app_id: str, body: dict = Body(...), user_id: str = Depends(get_user_id)):
    """Generate an AI draft for one screening question using the user's real
    profile + resume + job context. User reviews/edits before submitting."""
    question = (body.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")
    ctx = application_service.load_answer_context(user_id, app_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="Application not found")
    try:
        answer = draft_answer_for_user(question, ctx["user"], ctx["job"], ctx["resume_summary"])
    except Exception as e:
        logger.error(f"draft-answer failed: {e}")
        raise HTTPException(status_code=502, detail="Could not draft an answer — try again.")
    return {"question": question, "answer": answer}


@router.post("/{app_id}/rephrase-answer")
async def rephrase_screening_answer(app_id: str, body: dict = Body(...), user_id: str = Depends(get_user_id)):
    """Polish a user-written screening answer (clarity/grammar/tone) without
    adding new factual claims."""
    question = (body.get("question") or "").strip()
    answer = (body.get("answer") or "").strip()
    if not answer:
        raise HTTPException(status_code=400, detail="answer is required")
    ctx = application_service.load_answer_context(user_id, app_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="Application not found")
    try:
        polished = rephrase_answer(question, answer, ctx["user"], ctx["job"])
    except Exception as e:
        logger.error(f"rephrase-answer failed: {e}")
        raise HTTPException(status_code=502, detail="Could not rephrase — try again.")
    return {"question": question, "answer": polished}


@router.post("/{app_id}/draft-cover-letter")
async def draft_cover_letter(app_id: str, user_id: str = Depends(get_user_id)):
    """Regenerate the cover letter from scratch using the user's real profile +
    resume + job context."""
    ctx = application_service.load_answer_context(user_id, app_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="Application not found")
    try:
        letter = generate_cover_letter(ctx["user"], ctx["job"], ctx["resume_summary"])
    except Exception as e:
        logger.error(f"draft-cover-letter failed: {e}")
        raise HTTPException(status_code=502, detail="Could not draft a cover letter — try again.")
    if not letter:
        raise HTTPException(status_code=502, detail="Could not draft a cover letter — try again.")
    return {"cover_letter": letter}


@router.post("/{app_id}/rephrase-cover-letter")
async def rephrase_cover_letter(app_id: str, body: dict = Body(...), user_id: str = Depends(get_user_id)):
    """Polish the user's edited cover letter (clarity/grammar/tone) without adding
    new factual claims. Re-uses the same rephrase rules as screening answers."""
    text = (body.get("cover_letter") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="cover_letter is required")
    ctx = application_service.load_answer_context(user_id, app_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="Application not found")
    pseudo_question = f"Cover letter for {ctx['job'].get('title')} at {ctx['job'].get('company')}"
    try:
        polished = rephrase_answer(pseudo_question, text, ctx["user"], ctx["job"])
    except Exception as e:
        logger.error(f"rephrase-cover-letter failed: {e}")
        raise HTTPException(status_code=502, detail="Could not rephrase — try again.")
    return {"cover_letter": polished}


async def _ensure_listing_live(app_id: str, user_id: str):
    """Liveness preflight for assisted apply — raises 410 (and marks the listing
    expired) if the posting is gone, so the user never fills a form for a dead job."""
    from services.listing_validator import validate_listing, mark_expired

    app_res = db.table("application_details").select(
        "id, source_platform, source_url, apply_url, job_listing_id"
    ).eq("id", app_id).eq("user_id", user_id).maybe_single().execute()
    if not (app_res and app_res.data):
        return
    a = app_res.data
    check_url = a.get("apply_url") or a.get("source_url") or ""
    if not check_url:
        return
    is_live, reason = await validate_listing(check_url, a.get("source_platform") or "")
    if not is_live:
        mark_expired(a.get("job_listing_id", ""), reason)
        raise HTTPException(
            status_code=410,
            detail=f"This job posting is no longer available ({reason}). It has been removed from your queue.",
        )


@router.post("/{app_id}/apply")
async def apply(app_id: str, overrides: dict = Body(default={}), user_id: str = Depends(get_user_id)):
    """Default apply = assisted-apply prepare (no fragile auto-submit)."""
    await _ensure_listing_live(app_id, user_id)
    result = application_service.prepare_application(user_id, app_id, overrides or {})
    if result.get("error"):
        raise HTTPException(status_code=result.get("status_code", 400), detail=result["error"])
    return result


@router.get("/{app_id}/interview-prep")
async def get_interview_prep(app_id: str, user_id: str = Depends(get_user_id)):
    """Get or generate interview prep content for an application."""
    try:
        # maybe_single() can return None (not a response) when there are zero rows.
        existing = db.table("interview_prep").select("*").eq("application_id", app_id).maybe_single().execute()
        if existing and existing.data:
            return existing.data
    except Exception as e:
        logger.warning(f"interview_prep lookup failed: {e}")

    # Fetch the application + user (maybe_single → tolerate missing rows).
    app_res = db.table("application_details").select("*").eq("id", app_id).eq("user_id", user_id).maybe_single().execute()
    user_res = db.table("users").select("*").eq("id", user_id).maybe_single().execute()
    if not (app_res and app_res.data) or not (user_res and user_res.data):
        raise HTTPException(status_code=404, detail="Application not found")

    app_data = app_res.data
    job = {"title": app_data.get("job_title"), "company": app_data.get("job_company"),
           "required_skills": app_data.get("job_required_skills", []), "jd_text": app_data.get("jd_text", "")}
    match_analysis = app_data.get("match_analysis", {})
    prep_data = generate_interview_prep(user_res.data, job, match_analysis)

    total_q = len(prep_data.get("technical_questions", [])) + len(prep_data.get("behavioral_questions", []))
    try:
        result = db.table("interview_prep").insert({
            "application_id": app_id, "user_id": user_id,
            **prep_data, "total_questions": total_q
        }).execute()
        return result.data[0] if result and result.data else prep_data
    except Exception as e:
        logger.warning(f"interview_prep insert failed (returning generated data): {e}")
        return prep_data


@router.get("/{app_id}/history")
async def get_status_history(app_id: str, user_id: str = Depends(get_user_id)):
    result = db.table("application_status_history").select("*").eq("application_id", app_id).order("changed_at").execute()
    return result.data or []


@router.post("/{app_id}/approve")
async def approve_application(app_id: str, background_tasks: BackgroundTasks, user_id: str = Depends(get_user_id)):
    """User approves a recommended job.

    True bot auto-submit is reserved for Tier-A portals with a registered
    automation adapter. Everything else (Tier B/C, unknown platforms) routes
    to the assisted-apply flow — the frontend opens the prepare/review modal
    and the user submits on the real page themselves.
    """
    from workers.application_bot import apply_single_job
    from services.portals import get_portal
    from services.sessions.adapters.registry import get_adapter
    from services.listing_validator import validate_listing, mark_expired

    app_res = db.table("application_details").select(
        "id, source_platform, source_url, apply_url, job_listing_id"
    ).eq("id", app_id).eq("user_id", user_id).maybe_single().execute()
    if not (app_res and app_res.data):
        raise HTTPException(status_code=404, detail="Application not found")

    platform = app_res.data.get("source_platform") or ""

    # Liveness preflight — validate BEFORE starting any apply flow so the user
    # never fills out an application for a job that's already gone.
    check_url = app_res.data.get("apply_url") or app_res.data.get("source_url") or ""
    if check_url:
        is_live, reason = await validate_listing(check_url, platform)
        if not is_live:
            mark_expired(app_res.data.get("job_listing_id", ""), reason)
            return {
                "success": True,
                "mode": "expired",
                "message": f"This job posting is no longer available ({reason}) — removed from your queue.",
            }

    cap = get_portal(platform)
    bot_capable = bool(cap and cap.tier == "A" and cap.auto_apply and get_adapter(platform))

    if not bot_capable:
        return {
            "success": True,
            "mode": "assisted",
            "message": "This portal can't be auto-submitted — review and submit it yourself.",
        }

    queue_res = db.table("apply_queue").insert({"application_id": app_id, "user_id": user_id, "priority": 8}).execute()
    db.table("job_applications").update({"status": "queued"}).eq("id", app_id).execute()
    background_tasks.add_task(apply_single_job, queue_res.data[0]["id"])
    return {"success": True, "mode": "auto", "message": "Approved and queued for application"}


@router.post("/{app_id}/mark-manual-applied")
async def mark_manual_applied(app_id: str, user_id: str = Depends(get_user_id)):
    """User confirms they applied to a manual-apply job themselves."""
    app_res = db.table("job_applications").select("id").eq("id", app_id).eq("user_id", user_id).maybe_single().execute()
    if not (app_res and app_res.data):
        raise HTTPException(status_code=404, detail="Application not found")
    db.table("job_applications").update({
        "status": "applied",
        "applied_via": "manual",
        "applied_at": "now()",
    }).eq("id", app_id).execute()
    # Close out any stale queue entries so the scheduler never retries it.
    db.table("apply_queue").update({"status": "completed", "completed_at": "now()"})\
        .eq("application_id", app_id).in_("status", ["pending", "failed", "rate_limited"]).execute()
    try:
        application_service.log_event(app_id, user_id, "submitted", "User applied manually via job link")
    except Exception:
        pass
    return {"success": True}


@router.post("/{app_id}/dismiss")
async def dismiss_application(app_id: str, user_id: str = Depends(get_user_id)):
    """User dismisses a recommended job — mark as withdrawn so it doesn't reappear."""
    result = db.table("job_applications").update({"status": "withdrawn"}).eq("id", app_id).eq("user_id", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Application not found")
    return {"success": True}
