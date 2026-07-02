"""
Interview Prep & Career Analysis — interview preparation, skill gaps, follow-ups.
"""
import json
from loguru import logger
from services.ai.provider import _call_llm, parse_json_response as _parse_json_response


def generate_interview_prep(user_profile: dict, job: dict, match_analysis: dict) -> dict:
    system = """You are an expert interview coach. Generate practical, specific interview preparation material.
Respond with valid JSON only."""

    prompt = f"""Generate interview prep for:

CANDIDATE: {user_profile.get('full_name')} — {user_profile.get('headline')}
Skills: {', '.join(user_profile.get('skills', [])[:30])}

ROLE: {job.get('title')} at {job.get('company')}
Required Skills: {', '.join(job.get('required_skills', [])[:15])}
JD: {job.get('jd_text', '')[:2000]}

MATCH GAPS: {', '.join(match_analysis.get('gaps', []))}

Return JSON:
{{
  "technical_questions": [
    {{"question": "Q", "ideal_answer": "A", "difficulty": "easy|medium|hard", "topic": "topic"}}
  ],
  "behavioral_questions": [
    {{"question": "Q", "ideal_answer": "STAR format answer", "competency": "competency"}}
  ],
  "system_design_questions": [
    {{"question": "Q", "approach": "How to approach", "key_points": ["p1"]}}
  ],
  "coding_challenges": [
    {{"title": "T", "description": "D", "hints": ["h1"], "topics": ["t1"]}}
  ],
  "company_research": {{
    "known_products": ["p1"],
    "culture_notes": "...",
    "recent_news": "...",
    "interview_style": "...",
    "questions_to_ask": ["q1", "q2", "q3"]
  }},
  "key_talking_points": ["point1", "point2", "point3"],
  "preparation_plan": "Day-by-day prep plan as markdown",
  "salary_negotiation": {{
    "target_range": "...",
    "anchor_strategy": "...",
    "talking_points": ["t1", "t2"]
  }}
}}"""

    try:
        raw = _call_llm(system, prompt, max_tokens=3000, task_type="reasoning")
        return _parse_json_response(raw)
    except Exception as e:
        logger.error(f"Interview prep generation failed: {e}")
        return {
            "technical_questions": [], "behavioral_questions": [],
            "system_design_questions": [], "coding_challenges": [],
            "company_research": {}, "key_talking_points": [],
            "preparation_plan": "", "salary_negotiation": {},
        }


def analyze_skill_gaps(user_profile: dict, recent_jds: list[dict]) -> dict:
    system = "You are a career development AI. Analyze skill gaps and give actionable advice. JSON only."

    all_required: dict = {}
    for jd in recent_jds:
        for skill in jd.get("required_skills", []):
            all_required[skill] = all_required.get(skill, 0) + 1

    top_market_skills = sorted(all_required.items(), key=lambda x: -x[1])[:30]

    prompt = f"""Analyze skill gaps for this candidate based on {len(recent_jds)} recent job listings:

CANDIDATE SKILLS: {', '.join(user_profile.get('skills', []))}
EXPERIENCE: {user_profile.get('experience_years')} years
CAREER GOALS: {user_profile.get('career_goals', 'Not specified')}

TOP MARKET SKILLS (skill: demand count):
{json.dumps(dict(top_market_skills), indent=2)}

Return JSON:
{{
  "missing_skills": [
    {{
      "skill": "skill name",
      "demand_score": 1-100,
      "salary_impact_percent": number,
      "difficulty": "easy|medium|hard",
      "time_to_learn_weeks": number,
      "resources": [
        {{"type": "course|cert|project|book", "name": "name", "url": "url", "free": boolean}}
      ],
      "why_important": "brief explanation"
    }}
  ],
  "trending_skills": ["skill1", "skill2"],
  "market_insights": {{
    "hottest_tech_stack": "...",
    "declining_skills": ["s1"],
    "salary_trends": "...",
    "hiring_trend": "..."
  }},
  "priority_recommendations": [
    {{"action": "specific action", "impact": "high|medium|low", "timeline": "X weeks"}}
  ]
}}"""

    try:
        raw = _call_llm(system, prompt, max_tokens=2000, task_type="reasoning")
        return _parse_json_response(raw)
    except Exception as e:
        logger.error(f"Skill gap analysis failed: {e}")
        return {"missing_skills": [], "trending_skills": [], "market_insights": {}, "priority_recommendations": []}


def generate_follow_up_email(user_profile: dict, job: dict, days_since_applied: int) -> dict:
    system = """You are an expert career coach. Write concise, professional follow-up emails.
Keep them under 150 words. Be polite, specific, and end with a clear call to action. Return JSON only."""

    prompt = f"""Write a follow-up email for this job application:

CANDIDATE: {user_profile.get('full_name')} — {user_profile.get('headline', '')}
JOB: {job.get('title')} at {job.get('company')}
DAYS SINCE APPLIED: {days_since_applied}

Return JSON:
{{
  "subject": "Follow-up: [Job Title] Application — [Candidate Name]",
  "body": "Full email body in plain text (no HTML). Under 150 words. Polite, specific, professional.",
  "tone": "professional"
}}"""

    try:
        raw = _call_llm(system, prompt, max_tokens=400)
        return _parse_json_response(raw)
    except Exception as e:
        logger.error(f"Follow-up email generation failed: {e}")
        return {
            "subject": f"Follow-up: {job.get('title')} Application — {user_profile.get('full_name')}",
            "body": f"Hi,\n\nI applied for the {job.get('title')} role at {job.get('company')} {days_since_applied} days ago and wanted to follow up. I remain very interested and would love to discuss next steps.\n\nBest,\n{user_profile.get('full_name')}",
            "tone": "professional",
        }
