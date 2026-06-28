"""Application tracking router."""
from auth import get_user_id
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Body

from typing import Optional
from loguru import logger
from database import get_db
from models.application import ApplicationUpdate, ApplicationStatus
from services.ai_service import generate_interview_prep, draft_answer_for_user, rephrase_answer, generate_cover_letter
from services import application_service
from services.ranking import filter_and_rank, recency_bucket, BUCKET_LABELS

router = APIRouter(prefix="/applications", tags=["applications"])

db = get_db()


@router.get("/")
async def list_applications(
    user_id: str = Depends(get_user_id),
    status: Optional[str] = Query(None),
    tier: Optional[str] = Query(None),
    is_starred: Optional[bool] = Query(None),
    min_score: int = Query(40),
    show_archived: bool = Query(False),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    try:
        user_res = db.table("users").select("skills").eq("id", user_id).single().execute()
        user_skills = set(user_res.data.get("skills") or []) if user_res.data else set()

        q = db.table("application_details").select("*").eq("user_id", user_id)
        if status:
            q = q.eq("status", status)
        if tier:
            q = q.eq("match_tier", tier)
        if is_starred is not None:
            q = q.eq("is_starred", is_starred)

        try:
            result = q.order("job_posted_at", desc=True).limit(300).execute()
        except Exception:
            result = q.order("created_at", desc=True).limit(300).execute()
        rows = result.data or []

        ranked = filter_and_rank(rows, user_skills, min_score, show_archived)
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
            {"id": "matched", "title": "Matched", "statuses": ["discovered", "matched", "queued"]},
            {"id": "applied", "title": "Applied", "statuses": ["applying", "applied"]},
            {"id": "in_progress", "title": "In Progress", "statuses": ["under_review", "assessment"]},
            {"id": "interviews", "title": "Interviews", "statuses": ["interview_scheduled", "technical_round", "hr_round"]},
            {"id": "offers", "title": "Offers", "statuses": ["offer_received", "accepted"]},
            {"id": "closed", "title": "Closed", "statuses": ["rejected", "withdrawn"]},
        ]

        pipeline = []
        for col in columns:
            col_apps = [a for a in apps if a.get("status") in col["statuses"]]
            col_apps.sort(key=lambda a: (a.get("recency_bucket", 3), -a.get("match_score", 0)))
            pipeline.append({**col, "applications": col_apps, "count": len(col_apps)})

        stats = {
            "total_applied": sum(1 for a in apps if a.get("status") in ["applied", "under_review", "assessment", "interview_scheduled", "technical_round", "hr_round", "offer_received", "accepted", "rejected"]),
            "total_matched": sum(1 for a in apps if a.get("status") in ["matched", "queued"]),
            "active_interviews": sum(1 for a in apps if a.get("status") in ["interview_scheduled", "technical_round", "hr_round"]),
            "offers": sum(1 for a in apps if a.get("status") in ["offer_received", "accepted"]),
            "avg_match_score": round(sum(a.get("match_score", 0) for a in apps) / len(apps), 1) if apps else 0,
        }
        return {"pipeline": pipeline, "stats": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Approval Queue (Recommended tier — 60-79%) ──────────────────────────────
# Must be defined before /{app_id} to avoid FastAPI treating the literal path as an ID.

@router.get("/pending-approval")
async def get_pending_approval(
    user_id: str = Depends(get_user_id),
    limit: int = Query(20, le=50),
):
    """Return recommended-tier jobs waiting for user approval before applying."""
    result = (
        db.table("application_details")
        .select("*")
        .eq("user_id", user_id)
        .eq("match_tier", "recommended")
        .eq("status", "matched")
        .order("match_score", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


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
    form data). Returns {needs_input: [...]} if profile fields are missing."""
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


@router.post("/{app_id}/apply")
async def apply(app_id: str, overrides: dict = Body(default={}), user_id: str = Depends(get_user_id)):
    """Default apply = assisted-apply prepare (no fragile auto-submit)."""
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
    """User approves a recommended job — queue it for auto-apply."""
    from workers.application_bot import apply_single_job
    app_res = db.table("job_applications").select("*").eq("id", app_id).eq("user_id", user_id).single().execute()
    if not app_res.data:
        raise HTTPException(status_code=404, detail="Application not found")
    queue_res = db.table("apply_queue").insert({"application_id": app_id, "user_id": user_id, "priority": 8}).execute()
    db.table("job_applications").update({"status": "queued"}).eq("id", app_id).execute()
    background_tasks.add_task(apply_single_job, queue_res.data[0]["id"])
    return {"success": True, "message": "Approved and queued for application"}


@router.post("/{app_id}/dismiss")
async def dismiss_application(app_id: str, user_id: str = Depends(get_user_id)):
    """User dismisses a recommended job — mark as withdrawn so it doesn't reappear."""
    result = db.table("job_applications").update({"status": "withdrawn"}).eq("id", app_id).eq("user_id", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Application not found")
    return {"success": True}
