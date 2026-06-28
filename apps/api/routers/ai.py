"""AI features router — skill gaps, cover letters, career copilot."""
from auth import get_user_id
from fastapi import APIRouter, Depends, HTTPException

from pydantic import BaseModel
from database import get_db
from services.ai_service import analyze_skill_gaps, generate_cover_letter, call_llm, get_usage_stats
from config import settings

router = APIRouter(prefix="/ai", tags=["ai"])

db = get_db()


@router.get("/skill-gaps")
async def get_skill_gaps(user_id: str = Depends(get_user_id)):
    """Analyze skill gaps based on recently discovered jobs."""
    user_res = db.table("users").select("*").eq("id", user_id).single().execute()
    if not user_res.data:
        raise HTTPException(status_code=404)

    # Get recent job listings for market analysis
    recent_jobs = db.table("job_listings").select("required_skills,nice_to_have_skills").eq("is_active", True).order("discovered_at", desc=True).limit(100).execute()
    jds = [{"required_skills": j.get("required_skills", []), "nice_to_have_skills": j.get("nice_to_have_skills", [])} for j in (recent_jobs.data or [])]

    analysis = analyze_skill_gaps(user_res.data, jds)
    return analysis


class CopilotMessage(BaseModel):
    message: str
    context: str = "general"  # general | resume | interview | salary


@router.post("/copilot")
async def career_copilot(body: CopilotMessage, user_id: str = Depends(get_user_id)):
    """AI career copilot — answer career questions."""
    user_res = db.table("users").select("*").eq("id", user_id).single().execute()
    user = user_res.data or {}

    system = f"""You are an expert AI career coach helping a job seeker.
User profile: {user.get('headline', 'Software Developer')}, {user.get('experience_years', 0)} years experience.
Skills: {', '.join(user.get('skills', [])[:20])}.
Location: {user.get('location', 'India')}.
Be concise, practical, and encouraging. Use markdown formatting."""

    response = call_llm(system, body.message, max_tokens=800, task_type="conversation")
    return {"response": response}


@router.get("/usage")
async def ai_usage_stats(user_id: str = Depends(get_user_id)):
    """Return today's AI provider usage (calls, tokens, estimated cost)."""
    return get_usage_stats()


class CoverLetterRequest(BaseModel):
    job_listing_id: str
    resume_id: str | None = None


@router.post("/cover-letter")
async def generate_cover_letter_endpoint(body: CoverLetterRequest, user_id: str = Depends(get_user_id)):
    user_res = db.table("users").select("*").eq("id", user_id).single().execute()
    job_res = db.table("job_listings").select("*").eq("id", body.job_listing_id).single().execute()
    if not user_res.data or not job_res.data:
        raise HTTPException(status_code=404)

    resume_summary = ""
    if body.resume_id:
        res = db.table("resumes").select("parsed_data").eq("id", body.resume_id).single().execute()
        if res.data:
            resume_summary = res.data.get("parsed_data", {}).get("summary", "")

    letter = generate_cover_letter(user_res.data, job_res.data, resume_summary)
    return {"cover_letter": letter}
