"""Job listings router — search, browse, filter, trigger discovery."""
from auth import get_user_id
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query

from typing import Optional
from loguru import logger
from database import get_db
from models.job import DiscoveryRequest
from services.ai import parse_job_description
from services.ranking import filter_and_rank, paginate
from workers.job_discovery import run_discovery_for_user

router = APIRouter(prefix="/jobs", tags=["jobs"])

db_admin = get_db()


def _build_jobs_query(db, user_id: str, work_mode=None, is_easy_apply=None, platform_filter=None):
    """Build a fresh application_details query with filters.

    Must be called each time because the Supabase query builder is mutable —
    .order() modifies the builder in-place, so a failed attempt poisons it.
    """
    q = db.table("application_details").select("*").eq("user_id", user_id)
    if work_mode:
        q = q.eq("job_work_mode", work_mode)
    if is_easy_apply is not None:
        q = q.eq("is_easy_apply", is_easy_apply)
    if platform_filter:
        q = q.eq("source_platform", platform_filter)
    return q


@router.get("/")
async def list_jobs(
    user_id: str = Depends(get_user_id),
    query: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    work_mode: Optional[str] = Query(None),
    min_score: int = Query(40),
    show_archived: bool = Query(False),
    is_easy_apply: Optional[bool] = Query(None),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
):
    """List jobs with recency-weighted sorting, relevance threshold, and skill rescue."""
    try:
        user_res = db_admin.table("users").select("skills").eq("id", user_id).single().execute()
        user_skills = set(user_res.data.get("skills") or []) if user_res.data else set()

        qkw = dict(work_mode=work_mode, is_easy_apply=is_easy_apply, platform_filter=platform)

        try:
            result = _build_jobs_query(db_admin, user_id, **qkw)\
                .order("job_posted_at", desc=True).limit(300).execute()
        except Exception:
            result = _build_jobs_query(db_admin, user_id, **qkw)\
                .order("created_at", desc=True).limit(300).execute()
        rows = result.data or []

        if query:
            ql = query.lower()
            rows = [r for r in rows if ql in (r.get("job_title") or "").lower() or ql in (r.get("job_company") or "").lower()]

        ranked = filter_and_rank(rows, user_skills, min_score, show_archived)
        return paginate(ranked, offset, limit)
    except Exception as e:
        logger.error(f"List jobs failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{job_id}")
async def get_job(job_id: str, user_id: str = Depends(get_user_id)):
    """Get full job details including match analysis for this user."""
    try:
        app_res = db_admin.table("application_details")\
            .select("*")\
            .eq("job_listing_id", job_id)\
            .eq("user_id", user_id)\
            .maybe_single().execute()

        if app_res and app_res.data:
            return app_res.data

        job_res = db_admin.table("job_listings").select("*").eq("id", job_id).single().execute()
        if not job_res.data:
            raise HTTPException(status_code=404, detail="Job not found")

        return job_res.data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{job_id}/score")
async def score_job(job_id: str, background_tasks: BackgroundTasks, user_id: str = Depends(get_user_id)):
    """Manually trigger AI match scoring for a specific job."""
    try:
        job_res = db_admin.table("job_listings").select("*").eq("id", job_id).single().execute()
        user_res = db_admin.table("users").select("*").eq("id", user_id).single().execute()

        if not job_res.data or not user_res.data:
            raise HTTPException(status_code=404, detail="Job or user not found")

        job = job_res.data
        user = user_res.data

        jd_parsed = parse_job_description(job["jd_text"])
        from services.ai import compute_match_score
        match_result = compute_match_score(user, jd_parsed, job["jd_text"])

        app_data = {
            "user_id": user_id,
            "job_listing_id": job_id,
            "match_score": match_result.get("overall_score", 0),
            "match_tier": match_result.get("tier", "archived"),
            "match_analysis": {
                "strengths": match_result.get("strengths", []),
                "gaps": match_result.get("gaps", []),
                "recommendations": match_result.get("recommendations", []),
                "summary": match_result.get("summary", ""),
                "score_breakdown": match_result.get("score_breakdown", {}),
            },
            "skill_gaps": match_result.get("missing_required_skills", []),
            "missing_skills": match_result.get("missing_nice_skills", []),
            "status": "matched",
        }

        result = db_admin.table("job_applications").upsert(
            app_data, on_conflict="user_id,job_listing_id"
        ).execute()

        return {"success": True, "match_score": match_result.get("overall_score"), "tier": match_result.get("tier"), "analysis": match_result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/discover")
async def trigger_discovery(
    request: DiscoveryRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_user_id)
):
    """Manually trigger job discovery for the current user."""
    background_tasks.add_task(run_discovery_for_user, user_id, request.region)
    return {
        "success": True,
        "region": request.region,
        "message": f"Job discovery started ({request.region}). You'll be notified when complete.",
    }
