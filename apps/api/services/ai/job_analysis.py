"""
Job Analysis — JD parsing, match scoring, batch operations.
"""
import asyncio
import json
from itertools import cycle
from typing import Optional
from loguru import logger
from config import settings
from services.ai.provider import (
    _available_providers,
    _call_llm,
    parse_json_response as _parse_json_response,
    process_single_job as _process_single_job,
)


def _build_jd_parse_prompt(jd_text: str) -> str:
    return f"""Parse this job description and return JSON with these exact keys:
{{
  "title": "Job title",
  "company": "Company name",
  "location": "Location or null",
  "work_mode": "remote|hybrid|onsite|null",
  "job_type": "full_time|part_time|contract|freelance|internship",
  "experience_level": "entry|mid|senior|lead|principal|executive|null",
  "min_experience": integer_or_null,
  "max_experience": integer_or_null,
  "salary_min": integer_or_null,
  "salary_max": integer_or_null,
  "salary_currency": "INR|USD|GBP|EUR",
  "required_skills": ["skill1", "skill2"],
  "nice_to_have_skills": ["skill1", "skill2"],
  "responsibilities": ["item1", "item2"],
  "qualifications": ["item1", "item2"],
  "benefits": ["item1", "item2"],
  "company_size": "startup|small|medium|large|enterprise|null",
  "company_industry": "string or null",
  "is_remote_friendly": boolean,
  "hiring_manager": "name or null",
  "key_technologies": ["tech1", "tech2"]
}}

Job Description:
{jd_text[:8000]}"""


def _build_score_prompt(user_profile: dict, jd_parsed: dict, jd_text: str) -> str:
    user_skills = user_profile.get("skills") or []
    user_experience = user_profile.get("experience_years", 0)
    user_tech = user_profile.get("tech_stack") or {}
    user_headline = user_profile.get("headline", "")
    career_goals = user_profile.get("career_goals", "")
    required_skills = jd_parsed.get("required_skills") or []
    nice_skills = jd_parsed.get("nice_to_have_skills") or []

    return f"""Evaluate this candidate-job match and return JSON:

CANDIDATE:
- Skills: {', '.join(str(s) for s in user_skills[:50])}
- Tech Stack: {json.dumps(user_tech)}
- Experience: {user_experience} years
- Headline: {user_headline}
- Career Goals: {career_goals}

JOB REQUIREMENTS:
- Title: {jd_parsed.get('title')} at {jd_parsed.get('company')}
- Required Skills: {', '.join(str(s) for s in required_skills)}
- Nice-to-have: {', '.join(str(s) for s in nice_skills)}
- Experience Required: {jd_parsed.get('min_experience', 'Not specified')}-{jd_parsed.get('max_experience', 'Not specified')} years
- Level: {jd_parsed.get('experience_level', 'Not specified')}

JD Excerpt:
{jd_text[:3000]}

Return JSON:
{{
  "overall_score": 0-100,
  "score_breakdown": {{
    "skills_match": 0-40,
    "experience_match": 0-30,
    "role_fit": 0-20,
    "culture_location_fit": 0-10
  }},
  "matched_skills": ["skill1"],
  "missing_required_skills": ["skill1"],
  "missing_nice_skills": ["skill1"],
  "strengths": ["strength1", "strength2", "strength3"],
  "gaps": ["gap1", "gap2"],
  "recommendations": ["action1", "action2"],
  "culture_fit": "Brief assessment",
  "growth_potential": "Brief assessment",
  "summary": "2-3 sentence honest summary of fit",
  "tier": "auto_apply|recommended|watchlist|archived"
}}"""


def _empty_jd_parse() -> dict:
    return {
        "title": "Unknown", "company": "Unknown",
        "required_skills": [], "nice_to_have_skills": [],
        "responsibilities": [], "qualifications": [],
        "is_remote_friendly": False,
    }


def _empty_score() -> dict:
    return {
        "overall_score": 0, "tier": "archived",
        "strengths": [], "gaps": [], "recommendations": [],
        "matched_skills": [], "missing_required_skills": [],
        "missing_nice_skills": [], "summary": "Scoring failed",
    }


def _enforce_tier(result: dict, score: int) -> dict:
    if score >= settings.AUTO_APPLY_THRESHOLD:
        result["tier"] = "auto_apply"
    elif score >= settings.RECOMMENDED_THRESHOLD:
        result["tier"] = "recommended"
    elif score >= settings.WATCHLIST_THRESHOLD:
        result["tier"] = "watchlist"
    else:
        result["tier"] = "archived"
    return result


def _merge_scores(r1: dict, r2: dict) -> dict:
    s1 = r1.get("overall_score", 0)
    s2 = r2.get("overall_score", 0)
    avg = round((s1 + s2) / 2)

    breakdown1 = r1.get("score_breakdown", {})
    breakdown2 = r2.get("score_breakdown", {})
    merged_breakdown = {}
    for key in set(list(breakdown1.keys()) + list(breakdown2.keys())):
        v1 = breakdown1.get(key, 0)
        v2 = breakdown2.get(key, 0)
        merged_breakdown[key] = round((v1 + v2) / 2)

    merged = {**r1}
    merged["overall_score"] = avg
    merged["score_breakdown"] = merged_breakdown
    merged["_score_spread"] = abs(s1 - s2)
    merged["_scores"] = {"primary": s1, "secondary": s2}

    strengths = list(dict.fromkeys((r1.get("strengths") or []) + (r2.get("strengths") or [])))
    gaps = list(dict.fromkeys((r1.get("gaps") or []) + (r2.get("gaps") or [])))
    merged["strengths"] = strengths[:5]
    merged["gaps"] = gaps[:5]

    merged = _enforce_tier(merged, avg)
    return merged


# ══════════════════════════════════════════════════════════════
#  SINGLE-CALL WRAPPERS
# ══════════════════════════════════════════════════════════════

def parse_job_description(jd_text: str) -> dict:
    system = """You are an expert recruiter AI that extracts structured data from job descriptions.
Always respond with valid JSON only — no markdown, no prose."""
    try:
        raw = _call_llm(system, _build_jd_parse_prompt(jd_text), max_tokens=1500, task_type="json_extract")
        return _parse_json_response(raw)
    except Exception as e:
        logger.error(f"JD parsing failed: {e}")
        return _empty_jd_parse()


def compute_match_score(user_profile: dict, jd_parsed: dict, jd_text: str) -> dict:
    system = """You are an expert career AI that evaluates candidate-job fit.
Be honest, precise, and practical. Always respond with valid JSON only."""
    try:
        raw = _call_llm(system, _build_score_prompt(user_profile, jd_parsed, jd_text), max_tokens=1500, task_type="scoring")
        result = _parse_json_response(raw)
        return _enforce_tier(result, result.get("overall_score", 0))
    except Exception as e:
        logger.error(f"Match scoring failed: {e}")
        return _empty_score()


# ══════════════════════════════════════════════════════════════
#  BATCH OPERATIONS
# ══════════════════════════════════════════════════════════════

async def batch_parse_jds(jd_texts: list[str]) -> list[dict]:
    available = _available_providers()
    if not available:
        return [_empty_jd_parse() for _ in jd_texts]

    provider_pool = cycle(available)
    semaphore = asyncio.Semaphore(4)

    system = """You are an expert recruiter AI that extracts structured data from job descriptions.
Always respond with valid JSON only — no markdown, no prose."""

    tasks = []
    for i, jd in enumerate(jd_texts):
        prompt = _build_jd_parse_prompt(jd)
        provider = next(provider_pool)
        tasks.append(_process_single_job(provider, system, prompt, 1500, i, semaphore))

    results_raw = await asyncio.gather(*tasks)
    results = [None] * len(jd_texts)
    for idx, result, prov in results_raw:
        results[idx] = result if result else _empty_jd_parse()
        if result:
            logger.debug(f"[JD {idx}] parsed via {prov}")

    return results


async def batch_score_jobs(
    user_profile: dict,
    jobs: list[tuple[dict, str]],
    double_eval_threshold: int = 70,
) -> list[dict]:
    available = _available_providers()
    if not available:
        return [_empty_score() for _ in jobs]

    provider_pool = cycle(available)
    semaphore = asyncio.Semaphore(4)

    system = """You are an expert career AI that evaluates candidate-job fit.
Be honest, precise, and practical. Always respond with valid JSON only."""

    tasks = []
    for i, (jd_parsed, jd_text) in enumerate(jobs):
        prompt = _build_score_prompt(user_profile, jd_parsed, jd_text)
        provider = next(provider_pool)
        tasks.append(_process_single_job(provider, system, prompt, 1500, i, semaphore))

    results_raw = await asyncio.gather(*tasks)

    first_pass: list[tuple[Optional[dict], str]] = [(None, "")] * len(jobs)
    for idx, result, prov in results_raw:
        if result:
            score = result.get("overall_score", 0)
            result = _enforce_tier(result, score)
        first_pass[idx] = (result if result else _empty_score(), prov)

    if len(available) >= 2:
        reeval_tasks = []
        reeval_indices = []
        for i, (result, primary_provider) in enumerate(first_pass):
            if result and result.get("overall_score", 0) >= double_eval_threshold:
                other = [p for p in available if p != primary_provider][0]
                jd_parsed, jd_text = jobs[i]
                prompt = _build_score_prompt(user_profile, jd_parsed, jd_text)
                reeval_tasks.append(_process_single_job(other, system, prompt, 1500, i, semaphore))
                reeval_indices.append(i)

        if reeval_tasks:
            logger.info(f"Double-evaluating {len(reeval_tasks)} top matches for confidence scoring")
            reeval_raw = await asyncio.gather(*reeval_tasks)

            for idx, result2, prov2 in reeval_raw:
                if result2:
                    result1 = first_pass[idx][0]
                    merged = _merge_scores(result1, result2)
                    first_pass[idx] = (merged, f"{first_pass[idx][1]}+{prov2}")

    final = []
    for i, (result, providers_used) in enumerate(first_pass):
        if result is None:
            result = _empty_score()
        result["_evaluated_by"] = providers_used
        final.append(result)

    scored = sum(1 for r in final if r.get("overall_score", 0) > 0)
    logger.info(
        f"Batch scoring complete: {scored}/{len(jobs)} scored, "
        f"{sum(1 for r in final if '+' in r.get('_evaluated_by', ''))} double-evaluated"
    )

    return final
