"""
AI Career Copilot — conversational career assistant.
Handles: resume review, cover letter, career advice, interview simulation,
salary negotiation, LinkedIn profile tips, course recommendations.
"""
from auth import get_user_id
from fastapi import APIRouter, Depends, HTTPException

from pydantic import BaseModel
from typing import Optional
from loguru import logger
from database import get_db
from services.ai_service import call_llm

router = APIRouter(prefix="/copilot", tags=["copilot"])

db = get_db()


class ChatMessage(BaseModel):
    message: str
    context: Optional[str] = None  # "resume_review" | "cover_letter" | "interview" | "salary" | "general"
    job_title: Optional[str] = None
    company: Optional[str] = None
    history: list[dict] = []


COPILOT_SYSTEM = """You are an elite AI Career Copilot for a job application platform. You are a world-class career coach, resume expert, and interview preparation specialist with 20+ years of experience in talent acquisition.

Your capabilities:
- Resume review and improvement with specific, actionable feedback
- Cover letter generation tailored to specific roles
- Career path guidance and planning
- Interview preparation with realistic mock questions and coaching
- Salary negotiation strategies with specific numbers and scripts
- LinkedIn profile optimization
- Skill gap analysis with course/certification recommendations
- Industry insights and market intelligence

Your style:
- Be direct, specific, and actionable — avoid vague platitudes
- Use data points, industry benchmarks, and real examples
- Format responses with clear structure when helpful (use markdown)
- Be encouraging but honest about areas needing improvement
- For Indian market: reference FAANG India, unicorn startups, service companies (TCS/Infosys/Wipro) salary ranges

Always remember: you're helping users land their dream job. Every response should move them closer to that goal."""


@router.post("/chat")
async def chat(msg: ChatMessage, user_id: str = Depends(get_user_id)):
    """Process a chat message and return AI response."""
    try:
        # Load user profile for context
        user_res = db.table("users").select(
            "full_name,headline,skills,tech_stack,experience_years,career_goals,expected_salary_min,expected_salary_max,location"
        ).eq("id", user_id).maybe_single().execute()
        user = (user_res.data if user_res else None) or {}

        # Build user context block
        user_ctx = f"""User Profile:
- Name: {user.get('full_name', 'User')}
- Headline: {user.get('headline', 'Not set')}
- Skills: {', '.join(user.get('skills') or [])}
- Experience: {user.get('experience_years', 0)} years
- Career Goals: {user.get('career_goals', 'Not set')}
- Expected Salary: ₹{user.get('expected_salary_min', 0)}–{user.get('expected_salary_max', 0)} LPA
- Location: {user.get('location', 'Not set')}"""

        if msg.context == "cover_letter" and msg.job_title:
            user_ctx += f"\n\nGenerating cover letter for: {msg.job_title} at {msg.company or 'Company'}"

        if msg.context == "interview" and msg.job_title:
            user_ctx += f"\n\nInterview prep for: {msg.job_title} at {msg.company or 'Company'}"

        # Build conversation history
        history_text = ""
        for h in msg.history[-6:]:  # Last 6 turns for context
            role = "User" if h.get("role") == "user" else "Copilot"
            history_text += f"\n{role}: {h.get('content', '')}"

        user_prompt = f"""{user_ctx}

{f"Recent conversation:{history_text}" if history_text else ""}

User message: {msg.message}"""

        response = call_llm(COPILOT_SYSTEM, user_prompt, max_tokens=1500)
        return {"response": response, "context": msg.context}

    except Exception as e:
        logger.error(f"Copilot chat error for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate-cover-letter")
async def generate_cover_letter(
    payload: dict,
    user_id: str = Depends(get_user_id)
):
    """Generate a tailored cover letter for a specific job application."""
    try:
        app_id = payload.get("application_id")
        if not app_id:
            raise HTTPException(status_code=400, detail="application_id required")

        # Load application details
        app_res = db.table("application_details").select("*").eq("id", app_id).eq("user_id", user_id).single().execute()
        user_res = db.table("users").select("*").eq("id", user_id).single().execute()
        if not app_res.data or not user_res.data:
            raise HTTPException(status_code=404)

        app = app_res.data
        user = user_res.data

        system = "You are an expert cover letter writer. Generate professional, personalized cover letters that get interviews."
        prompt = f"""Generate a compelling cover letter for this application:

Job: {app.get('job_title')} at {app.get('job_company')}
Location: {app.get('job_location')}
Match Score: {app.get('match_score')}%

Candidate Profile:
- Name: {user.get('full_name')}
- Experience: {user.get('experience_years')} years
- Skills: {', '.join((user.get('skills') or [])[:10])}
- Career Goals: {user.get('career_goals', '')}

Job Description (first 1000 chars):
{(app.get('jd_text') or '')[:1000]}

Match Analysis:
{app.get('match_analysis', {})}

Write a 3-paragraph cover letter that:
1. Opens with genuine enthusiasm for this specific role
2. Highlights 2-3 most relevant experiences/skills with brief examples
3. Closes with a confident call to action

Keep it under 250 words. Professional but warm tone. No generic filler."""

        letter = call_llm(system, prompt, max_tokens=800)

        # Save to application
        db.table("job_applications").update({"cover_letter": letter}).eq("id", app_id).execute()

        return {"cover_letter": letter}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cover letter generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze-resume")
async def analyze_resume(payload: dict, user_id: str = Depends(get_user_id)):
    """AI analysis of the user's primary resume."""
    try:
        resume_res = db.table("resumes").select("*").eq("user_id", user_id).eq("is_primary", True).maybe_single().execute()
        user_res = db.table("users").select("*").eq("id", user_id).single().execute()

        if not user_res.data:
            raise HTTPException(status_code=404)

        user = user_res.data
        resume = resume_res.data or {}
        parsed = resume.get("parsed_data", {}) or {}

        system = "You are a professional resume reviewer and ATS optimization expert."
        prompt = f"""Analyze this candidate's resume and provide detailed, actionable feedback:

Candidate: {user.get('full_name')}
Experience: {user.get('experience_years')} years
Skills: {', '.join((user.get('skills') or [])[:15])}
Tech Stack: {user.get('tech_stack', {})}
Current ATS Score: {resume.get('ats_score', 'Not calculated')}
Resume Name: {resume.get('name', 'Primary Resume')}

Target: {user.get('career_goals', 'Software Engineering roles')}

Provide feedback in these sections:
1. **ATS Score Estimate** (0-100) with reasoning
2. **Strengths** (2-3 bullet points)
3. **Critical Improvements** (3-5 specific, actionable changes)
4. **Keyword Gaps** (skills/keywords to add based on typical JDs)
5. **Format & Structure** (specific formatting recommendations)
6. **Quick Wins** (changes that take <30 minutes but have big impact)

Be specific and direct. Reference real industry expectations."""

        analysis = call_llm(system, prompt, max_tokens=1200)
        return {"analysis": analysis}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/career-suggestions")
async def career_suggestions(user_id: str = Depends(get_user_id)):
    """Generate personalized career growth suggestions."""
    try:
        user_res = db.table("users").select("*").eq("id", user_id).single().execute()
        apps_res = db.table("job_applications").select("match_score,status,skill_gaps").eq("user_id", user_id).order("created_at", desc=True).limit(20).execute()

        if not user_res.data:
            raise HTTPException(status_code=404)

        user = user_res.data
        apps = apps_res.data or []

        all_gaps = []
        for a in apps:
            gaps = a.get("skill_gaps") or []
            all_gaps.extend(gaps)

        gap_freq: dict[str, int] = {}
        for g in all_gaps:
            gap_freq[g] = gap_freq.get(g, 0) + 1
        top_gaps = sorted(gap_freq.items(), key=lambda x: -x[1])[:8]

        system = "You are a career development expert and skills strategist."
        prompt = f"""Generate personalized career growth recommendations for this professional:

Profile:
- Skills: {', '.join((user.get('skills') or [])[:15])}
- Experience: {user.get('experience_years')} years
- Goals: {user.get('career_goals', 'Advance in tech')}
- Location: {user.get('location', 'India')}

Most frequent skill gaps from job applications: {top_gaps}
Total applications reviewed: {len(apps)}
Average match score: {round(sum(a.get('match_score', 0) for a in apps) / max(len(apps), 1), 1)}%

Provide:
1. **Top 3 High-ROI Skills to Learn** — with specific courses/resources and time estimate
2. **Certifications That Move the Needle** — industry-recognized, salary-impacting certs
3. **Portfolio Projects to Build** — 2-3 specific projects that demonstrate in-demand skills
4. **30-Day Action Plan** — concrete weekly tasks
5. **Salary Unlock** — what these skills could add to your package (in LPA)"""

        suggestions = call_llm(system, prompt, max_tokens=1200)
        return {"suggestions": suggestions, "top_skill_gaps": top_gaps[:5]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
