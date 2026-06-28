"""
AI Service — Multi-provider parallel evaluation engine.

Routes LLM calls across Groq, NVIDIA, and optionally Anthropic using
task-based intelligent routing, async concurrency, automatic failover,
double-evaluation for top candidates, and per-call token tracking.

Works with just Groq and/or NVIDIA (free tier). Anthropic is optional.
"""
import asyncio
import json
import re
import time
from collections import defaultdict
from datetime import date
from itertools import cycle
from typing import Optional
from loguru import logger
import httpx
from config import settings


# ══════════════════════════════════════════════════════════════
#  PROVIDER REGISTRY
# ══════════════════════════════════════════════════════════════

_PROVIDERS = {
    "groq": {
        "api": "openai",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "key": lambda: settings.GROQ_API_KEY,
        "model": lambda: settings.GROQ_MODEL,
        "rpm": 30,
        "cost_per_1k_input": 0.0,
        "cost_per_1k_output": 0.0,
    },
    "nvidia": {
        "api": "openai",
        "url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "key": lambda: settings.NVIDIA_API_KEY,
        "model": lambda: settings.NVIDIA_MODEL,
        "rpm": 20,
        "cost_per_1k_input": 0.0,
        "cost_per_1k_output": 0.0,
    },
    "anthropic": {
        "api": "anthropic",
        "url": "https://api.anthropic.com/v1/messages",
        "key": lambda: settings.ANTHROPIC_API_KEY,
        "model": lambda: settings.ANTHROPIC_MODEL,
        "rpm": 50,
        "cost_per_1k_input": 0.003,
        "cost_per_1k_output": 0.015,
    },
}

# Task-based routing: maps task types to ordered provider preferences.
# Falls through to whatever is available if preferred providers are absent.
TASK_ROUTING = {
    "json_extract": ["groq", "nvidia"],
    "freeform": ["groq", "nvidia"],
    "reasoning": ["anthropic", "groq", "nvidia"],
    "scoring": ["groq", "nvidia"],
    "conversation": ["groq", "nvidia", "anthropic"],
}


def _available_providers() -> list[str]:
    """Return provider names that have valid API keys."""
    available = []
    for name, cfg in _PROVIDERS.items():
        try:
            key = cfg["key"]()
            if key and key.strip() and not key.startswith("your_"):
                available.append(name)
        except Exception:
            pass
    return available


_provider_cycle = None
_call_counts: dict[str, list[float]] = {}


def _next_provider(task_type: str | None = None) -> str:
    """Pick the best provider for a task type, with rate-limit awareness."""
    global _provider_cycle
    available = _available_providers()
    if not available:
        raise RuntimeError("No AI providers configured. Set GROQ_API_KEY or NVIDIA_API_KEY in .env")

    if task_type and task_type in TASK_ROUTING:
        preferred = [p for p in TASK_ROUTING[task_type] if p in available]
        if preferred:
            now = time.time()
            for name in preferred:
                if name not in _call_counts:
                    _call_counts[name] = []
                _call_counts[name] = [t for t in _call_counts[name] if now - t < 60]
                rpm = _PROVIDERS[name].get("rpm", 20)
                if len(_call_counts[name]) < rpm:
                    _call_counts[name].append(now)
                    return name
            return preferred[0]

    if len(available) == 1:
        return available[0]

    if _provider_cycle is None:
        _provider_cycle = cycle(available)

    now = time.time()
    for _ in range(len(available)):
        name = next(_provider_cycle)
        if name not in _call_counts:
            _call_counts[name] = []
        _call_counts[name] = [t for t in _call_counts[name] if now - t < 60]
        rpm = _PROVIDERS[name].get("rpm", 20)
        if len(_call_counts[name]) < rpm:
            _call_counts[name].append(now)
            return name

    return min(available, key=lambda n: len(_call_counts.get(n, [])))


# ══════════════════════════════════════════════════════════════
#  TOKEN / COST TRACKING
# ══════════════════════════════════════════════════════════════

_daily_usage: dict[str, dict] = defaultdict(lambda: {
    "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0,
})


def _track_usage(provider: str, input_tokens: int, output_tokens: int):
    """Accumulate daily token usage per provider."""
    today = date.today().isoformat()
    key = f"{today}:{provider}"
    _daily_usage[key]["calls"] += 1
    _daily_usage[key]["input_tokens"] += input_tokens
    _daily_usage[key]["output_tokens"] += output_tokens
    cfg = _PROVIDERS.get(provider, {})
    cost = (input_tokens / 1000 * cfg.get("cost_per_1k_input", 0)
            + output_tokens / 1000 * cfg.get("cost_per_1k_output", 0))
    _daily_usage[key]["cost"] += cost


def get_usage_stats() -> dict:
    """Return today's usage stats per provider."""
    today = date.today().isoformat()
    stats = {}
    for key, data in _daily_usage.items():
        if key.startswith(today):
            provider = key.split(":", 1)[1]
            stats[provider] = dict(data)
    return {"date": today, "providers": stats}


def _extract_usage(provider: str, data: dict) -> tuple[int, int]:
    """Extract input/output token counts from provider response."""
    usage = data.get("usage", {})
    if _PROVIDERS.get(provider, {}).get("api") == "anthropic":
        return usage.get("input_tokens", 0), usage.get("output_tokens", 0)
    return usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


# ══════════════════════════════════════════════════════════════
#  CORE LLM CALLS
# ══════════════════════════════════════════════════════════════

def _build_request(provider: str, system: str, user: str, max_tokens: int):
    """Build provider-specific request payload and headers."""
    cfg = _PROVIDERS[provider]
    api_key = cfg["key"]()

    if cfg["api"] == "anthropic":
        payload = {
            "model": cfg["model"](),
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": 0.6,
        }
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
    else:
        payload = {
            "model": cfg["model"](),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.6,
            "top_p": 0.95,
            "max_tokens": max_tokens,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
    return cfg["url"], payload, headers


def _extract_text(provider: str, data: dict) -> str:
    """Extract response text from provider-specific response format."""
    cfg = _PROVIDERS.get(provider, {})
    if cfg.get("api") == "anthropic":
        blocks = data.get("content", [])
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
    msg = data["choices"][0]["message"]
    return (msg.get("content") or msg.get("reasoning_content") or "").strip()


def _call_provider(provider: str, system: str, user: str, max_tokens: int = 2000) -> str:
    """Call a specific provider. Returns the response text."""
    url, payload, headers = _build_request(provider, system, user, max_tokens)

    with httpx.Client(timeout=120.0) as http:
        resp = http.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    inp, out = _extract_usage(provider, data)
    _track_usage(provider, inp, out)
    return _extract_text(provider, data)


async def _call_provider_async(provider: str, system: str, user: str, max_tokens: int = 2000) -> str:
    """Async version — for concurrent batch processing."""
    url, payload, headers = _build_request(provider, system, user, max_tokens)

    async with httpx.AsyncClient(timeout=120.0) as http:
        resp = await http.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    inp, out = _extract_usage(provider, data)
    _track_usage(provider, inp, out)
    return _extract_text(provider, data)


def _call_llm(
    system: str,
    user: str,
    max_tokens: int = 2000,
    prefer: list[str] | None = None,
    task_type: str | None = None,
) -> str:
    """Smart single call with task-based routing and failover.

    - task_type: routes to the best provider for the task (see TASK_ROUTING)
    - prefer: explicit provider preference (overrides task_type routing)
    """
    available = _available_providers()
    if prefer:
        ordered = [p for p in prefer if p in available] + [p for p in available if p not in prefer]
        if not ordered:
            raise RuntimeError("No AI providers configured.")
        primary = ordered[0]
    else:
        ordered = available
        primary = _next_provider(task_type)

    try:
        return _call_provider(primary, system, user, max_tokens)
    except Exception as e:
        logger.warning(f"{primary} failed: {e}")
        for fallback in ordered:
            if fallback != primary:
                try:
                    logger.info(f"Falling back to {fallback}")
                    return _call_provider(fallback, system, user, max_tokens)
                except Exception as e2:
                    logger.warning(f"{fallback} also failed: {e2}")
        raise


def call_llm(
    system: str,
    user: str,
    max_tokens: int = 2000,
    prefer: list[str] | None = None,
    task_type: str | None = None,
) -> str:
    """Public API — task-routed LLM call with failover."""
    return _call_llm(system, user, max_tokens, prefer, task_type)


def _parse_json_response(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown fences and reasoning blocks."""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", cleaned).strip()
    match = re.search(r"(\{.*\}|\[.*\])", cleaned, flags=re.DOTALL)
    if match:
        cleaned = match.group(1)
    return json.loads(cleaned)


# ══════════════════════════════════════════════════════════════
#  PARALLEL BATCH PROCESSING ENGINE
# ══════════════════════════════════════════════════════════════

def _is_rate_limit(e: Exception) -> bool:
    return "429" in str(e) or "too many requests" in str(e).lower()


async def _call_with_backoff(provider: str, system: str, prompt: str, max_tokens: int, job_index: int) -> str:
    """Call a provider, retrying on 429 with exponential backoff (free-tier friendly)."""
    delays = [2.0, 4.0, 8.0]  # up to 3 retries on rate-limit
    for attempt, delay in enumerate([0.0, *delays]):
        if delay:
            await asyncio.sleep(delay)
        try:
            return await _call_provider_async(provider, system, prompt, max_tokens)
        except Exception as e:
            if _is_rate_limit(e) and attempt < len(delays):
                logger.debug(f"[Job {job_index}] {provider} 429 — backing off {delays[attempt]}s")
                continue
            raise
    raise RuntimeError("unreachable")


async def _process_single_job(
    provider: str,
    system: str,
    prompt: str,
    max_tokens: int,
    job_index: int,
    semaphore: asyncio.Semaphore,
) -> tuple[int, Optional[dict], str]:
    """Process one job through a provider, with 429 backoff then cross-provider failover."""
    async with semaphore:
        available = _available_providers()
        try:
            raw = await _call_with_backoff(provider, system, prompt, max_tokens, job_index)
            return (job_index, _parse_json_response(raw), provider)
        except Exception as e:
            logger.warning(f"[Job {job_index}] {provider} failed: {e}")
            for fallback in available:
                if fallback != provider:
                    try:
                        raw = await _call_with_backoff(fallback, system, prompt, max_tokens, job_index)
                        return (job_index, _parse_json_response(raw), fallback)
                    except Exception as e2:
                        logger.warning(f"[Job {job_index}] {fallback} fallback also failed: {e2}")
            return (job_index, None, provider)


async def batch_parse_jds(jd_texts: list[str]) -> list[dict]:
    """Parse multiple job descriptions concurrently across both APIs."""
    available = _available_providers()
    if not available:
        return [_empty_jd_parse() for _ in jd_texts]

    provider_pool = cycle(available)
    semaphore = asyncio.Semaphore(4)  # free-tier friendly (Groq ~30/min, NVIDIA ~20/min)

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
    """
    Score multiple jobs concurrently across both APIs.

    jobs: list of (jd_parsed, jd_text) tuples
    double_eval_threshold: jobs scoring above this get re-evaluated by the
                           other API and scores are averaged for confidence.
    """
    available = _available_providers()
    if not available:
        return [_empty_score() for _ in jobs]

    provider_pool = cycle(available)
    semaphore = asyncio.Semaphore(4)  # free-tier friendly (Groq ~30/min, NVIDIA ~20/min)

    system = """You are an expert career AI that evaluates candidate-job fit.
Be honest, precise, and practical. Always respond with valid JSON only."""

    # Phase 1: Score all jobs distributed across providers
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

    # Phase 2: Double-evaluate top matches with the other API
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


def _merge_scores(r1: dict, r2: dict) -> dict:
    """Average scores from two providers for higher confidence."""
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

    strengths = list(dict.fromkeys(r1.get("strengths", []) + r2.get("strengths", [])))
    gaps = list(dict.fromkeys(r1.get("gaps", []) + r2.get("gaps", [])))
    merged["strengths"] = strengths[:5]
    merged["gaps"] = gaps[:5]

    merged = _enforce_tier(merged, avg)
    return merged


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


# ══════════════════════════════════════════════════════════════
#  PROMPT BUILDERS
# ══════════════════════════════════════════════════════════════

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
    user_skills = user_profile.get("skills", [])
    user_experience = user_profile.get("experience_years", 0)
    user_tech = user_profile.get("tech_stack", {})
    user_headline = user_profile.get("headline", "")
    career_goals = user_profile.get("career_goals", "")
    required_skills = jd_parsed.get("required_skills", [])
    nice_skills = jd_parsed.get("nice_to_have_skills", [])

    return f"""Evaluate this candidate-job match and return JSON:

CANDIDATE:
- Skills: {', '.join(user_skills[:50])}
- Tech Stack: {json.dumps(user_tech)}
- Experience: {user_experience} years
- Headline: {user_headline}
- Career Goals: {career_goals}

JOB REQUIREMENTS:
- Title: {jd_parsed.get('title')} at {jd_parsed.get('company')}
- Required Skills: {', '.join(required_skills)}
- Nice-to-have: {', '.join(nice_skills)}
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


# ══════════════════════════════════════════════════════════════
#  SINGLE-CALL WRAPPERS (backward compatible)
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
#  COVER LETTER, INTERVIEW PREP, AND OTHER AI FEATURES
# ══════════════════════════════════════════════════════════════

def generate_cover_letter(user_profile: dict, job: dict, resume_summary: str) -> str:
    system = """You are an expert career coach who writes authentic cover letters.
Write in first person. Be specific and concrete. Avoid clichés. Max 350 words.

ANTI-FABRICATION RULES (strict):
- Use ONLY facts present in the CANDIDATE data / resume summary below.
- NEVER invent employers, projects, metrics, years, titles, or achievements that
  are not explicitly provided. Do not exaggerate numbers.
- It is fine to express genuine interest and connect REAL skills to the role, but
  every concrete claim must trace to provided data. When in doubt, stay general
  rather than inventing specifics."""

    exp = user_profile.get('experience_years')
    exp_str = f"{exp} years" if exp not in (None, 0) else "(not provided — do not state a number)"
    skill_exp = user_profile.get("tech_stack") or {}
    skill_exp_str = ", ".join(f"{k}: {yr}y" for k, yr in skill_exp.items()) or "(not provided)"

    prompt = f"""Write a professional cover letter using ONLY the facts below.

CANDIDATE:
- Name: {user_profile.get('full_name') or '(not provided)'}
- Headline: {user_profile.get('headline') or '(not provided)'}
- Key Skills: {', '.join(user_profile.get('skills', [])[:15]) or '(not provided)'}
- Per-skill experience: {skill_exp_str}
- Total experience: {exp_str}
- Resume Summary (the only source of accomplishments): {resume_summary[:600] or '(not provided)'}

ROLE:
- Job Title: {job.get('title')}
- Company: {job.get('company')}
- Key Requirements: {', '.join(job.get('required_skills', [])[:10])}
- JD Excerpt: {job.get('jd_text', '')[:1500]}

Write 3 short paragraphs: (1) genuine interest in this specific role/company,
(2) connect the candidate's REAL skills/summary to the requirements (no invented
achievements), (3) brief forward-looking close. Return only the letter text."""

    try:
        # Pin to Groq (non-reasoning) so chain-of-thought doesn't leak into the letter.
        return _extract_answer(_call_llm(system, prompt, max_tokens=2000, prefer=["groq"]))
    except Exception as e:
        logger.error(f"Cover letter generation failed: {e}")
        return ""


# Sentinel the AI must return when it lacks the real data to answer truthfully.
NEEDS_INFO_TOKEN = "[NEEDS_INFO]"


def answer_screening_question(question: str, user_profile: dict, job: dict, question_type: str = "text") -> str:
    """Draft an answer using ONLY the candidate's real data. If the data needed
    to answer truthfully is not present, returns the NEEDS_INFO sentinel so the
    caller can ask the user — never fabricates."""
    system = f"""You answer job-application screening questions using ONLY facts explicitly
provided about the candidate. This is a STRICT anti-fabrication task.

ABSOLUTE RULES:
- NEVER invent, assume, estimate, or guess any fact (no made-up numbers, names,
  dates, salaries, locations, years of experience, authorizations, or claims).
- Use ONLY values present in CANDIDATE DATA below. A value shown as null/empty/None
  means it is UNKNOWN — you may not fill it in.
- If answering truthfully requires a fact that is missing/unknown, respond with
  EXACTLY this and nothing else: {NEEDS_INFO_TOKEN} <what specific info is needed>
- Do not be "helpful" by inventing plausible content. Missing data → {NEEDS_INFO_TOKEN}."""

    # Build a data block; show explicit "(not provided)" for anything missing.
    def v(key):
        val = user_profile.get(key)
        return val if val not in (None, "", 0, []) else "(not provided)"

    skill_exp = (user_profile.get("tech_stack") or {})
    skill_exp_str = ", ".join(f"{k}: {yr}y" for k, yr in skill_exp.items()) or "(not provided)"

    prompt = f"""QUESTION: {question}
QUESTION TYPE: {question_type}

CANDIDATE DATA (use only these; "(not provided)" means UNKNOWN — do not fill in):
- Name: {v('full_name')}
- Total years of experience: {v('experience_years')}
- Per-skill experience: {skill_exp_str}
- Skills: {', '.join(user_profile.get('skills', [])[:20]) or '(not provided)'}
- Current salary: {v('current_salary')}
- Expected salary: {v('expected_salary_min')} – {v('expected_salary_max')}
- Notice period (days): {v('notice_period_days')}
- Location: {v('location')}
- Work authorization: {v('work_authorization')}
- Willing to relocate: {v('willing_to_relocate')}

JOB: {job.get('title')} at {job.get('company')}

Answer using ONLY the data above. If a required fact is "(not provided)", output {NEEDS_INFO_TOKEN} and what is needed. Output only the answer text."""

    try:
        # Pin to Groq (non-reasoning) and give enough tokens so the answer (or
        # the NEEDS_INFO sentinel) isn't truncated mid-output.
        ans = _call_llm(system, prompt, max_tokens=800, prefer=["groq"]).strip()
        # NEEDS_INFO must remain intact for the caller's gap-detection; only
        # extract a clean answer when the sentinel isn't present.
        return ans if NEEDS_INFO_TOKEN in ans else _extract_answer(ans)
    except Exception as e:
        logger.error(f"Screening answer failed: {e}")
        return f"{NEEDS_INFO_TOKEN} could not generate answer"


_ANSWER_BLOCK_RE = re.compile(r"<ANSWER>(.*?)</ANSWER>", re.DOTALL)
_ANSWER_OPEN_RE = re.compile(r"<ANSWER>(.*)", re.DOTALL)  # unclosed (truncated) case
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_QUOTED_BLOCK_RE = re.compile(r"[\"“]([^\"“”]{60,})[\"”]", re.DOTALL)


def _extract_answer(raw: str) -> str:
    """Pull the final answer out of an LLM response that may include
    chain-of-thought (reasoning preambles, <think> blocks, echoed prompts, or
    truncated <ANSWER> tags from a token cutoff).

    Order of preference:
      1) Content between <ANSWER>…</ANSWER> markers
      2) Content after a lone <ANSWER> (response was truncated before the close)
      3) Everything after the last "rewrite:" / "answer:" / "final:" marker
      4) The largest quoted block (reasoning models often wrap the answer)
      5) The raw text with <think> blocks and any stray <ANSWER> tag stripped
    """
    text = raw.strip()
    m = _ANSWER_BLOCK_RE.search(text)
    if m:
        return _clean(m.group(1))

    open_only = _ANSWER_OPEN_RE.search(text)
    if open_only:
        return _clean(open_only.group(1))

    stripped = _THINK_BLOCK_RE.sub("", text).strip()

    for marker in ("Final answer:", "FINAL ANSWER:", "Polished:", "Rewrite:",
                   "Potential rewrite:", "Answer:", "Output:"):
        idx = stripped.rfind(marker)
        if idx >= 0:
            tail = stripped[idx + len(marker):].strip()
            if tail:
                return _clean(tail)

    quotes = _QUOTED_BLOCK_RE.findall(stripped)
    if quotes:
        return _clean(max(quotes, key=len))

    return _clean(stripped)


def _clean(s: str) -> str:
    """Final-pass cleanup: strip surrounding quotes, leftover <ANSWER>/<think>
    fragments, and dangling whitespace."""
    s = s.strip()
    s = re.sub(r"</?ANSWER>", "", s)
    s = re.sub(r"</?think>", "", s, flags=re.IGNORECASE)
    s = s.strip().strip('"').strip("“").strip("”").strip()
    return s


def draft_answer_for_user(question: str, user_profile: dict, job: dict, resume_summary: str = "") -> str:
    """Draft a screening-question answer the user can review and edit.

    Differs from answer_screening_question: a bit more permissive — it may reason
    about *fit* and *motivation* by connecting the candidate's real background to
    the role. It still must not invent factual claims (years, salaries, dates,
    certifications, employers) — those come from CANDIDATE DATA only."""
    system = """You draft job-application answers for a candidate to review and edit.

RULES:
- Connect the candidate's REAL background (skills, experience, role history) to the role.
- You may write about motivation/interest/fit by reasoning from their background.
- NEVER invent factual claims: years of experience, salary, dates, employers, certifications,
  authorizations, or specific projects not mentioned in CANDIDATE DATA / RESUME SUMMARY.
- Keep it concise (2–4 sentences), professional, first-person, no clichés.

OUTPUT FORMAT (strict): Put ONLY the final answer between <ANSWER> and </ANSWER> tags.
Any reasoning, restating of the prompt, or preamble OUTSIDE the tags will be discarded.
Example: <ANSWER>I am drawn to this role because…</ANSWER>"""

    def v(key):
        val = user_profile.get(key)
        return val if val not in (None, "", 0, []) else "(not provided)"

    skill_exp = (user_profile.get("tech_stack") or {})
    skill_exp_str = ", ".join(f"{k}: {yr}y" for k, yr in skill_exp.items()) or "(not provided)"

    prompt = f"""QUESTION: {question}

CANDIDATE DATA:
- Name: {v('full_name')}
- Headline: {v('headline')}
- Total years experience: {v('experience_years')}
- Per-skill experience: {skill_exp_str}
- Skills: {', '.join(user_profile.get('skills', [])[:20]) or '(not provided)'}
- Location: {v('location')}
- Notice period (days): {v('notice_period_days')}
- Expected salary: {v('expected_salary_min')} – {v('expected_salary_max')}
- Work authorization: {v('work_authorization')}
- Career goals: {v('career_goals')}

RESUME SUMMARY:
{resume_summary or '(not provided)'}

JOB:
- Title: {job.get('title')}
- Company: {job.get('company')}
- Location: {job.get('location')}
- Required skills: {', '.join(job.get('required_skills') or []) or '(not specified)'}
- JD excerpt: {(job.get('jd_text') or '')[:1200]}

Write the answer."""

    try:
        # Pin to non-reasoning provider (Groq) to avoid chain-of-thought leakage;
        # high token budget so reasoning-model fallback can still finish.
        return _extract_answer(_call_llm(system, prompt, max_tokens=2000, prefer=["groq"]))
    except Exception as e:
        logger.error(f"Draft answer failed: {e}")
        raise


def rephrase_answer(question: str, user_answer: str, user_profile: dict, job: dict) -> str:
    """Polish the user's own answer — clarity, grammar, professionalism — while
    PRESERVING meaning and never adding new factual claims."""
    system = """You polish job-application answers. STRICT rules:

- Improve clarity, grammar, flow, and professional tone.
- Preserve the candidate's MEANING and intent. Do not change what they're saying.
- Do NOT add new factual claims (years, salaries, employers, projects, certifications).
  If the user didn't mention it, you don't either.
- Do NOT remove specifics the user included.
- Keep it the same approximate length (±25%). Stay in first person.

OUTPUT FORMAT (strict): Put ONLY the polished answer between <ANSWER> and </ANSWER> tags.
Any reasoning, restating of the draft, or preamble OUTSIDE the tags will be discarded.
Example: <ANSWER>I am drawn to this role because…</ANSWER>"""

    prompt = f"""QUESTION: {question}

CANDIDATE'S DRAFT:
{user_answer}

CONTEXT (for tone only — do NOT inject these facts unless already in the draft):
- Role: {job.get('title')} at {job.get('company')}
- Candidate name: {user_profile.get('full_name') or '(unspecified)'}

Rewrite the draft."""

    try:
        return _extract_answer(_call_llm(system, prompt, max_tokens=2000, prefer=["groq"]))
    except Exception as e:
        logger.error(f"Rephrase failed: {e}")
        raise


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


def tailor_resume_content(parsed_resume: dict, jd_parsed: dict) -> dict:
    system = "You are an expert resume writer. Tailor resume content to match job requirements. JSON only."

    prompt = f"""Tailor this resume for the job. Suggest specific rewrites:

RESUME:
- Summary: {parsed_resume.get('summary', '')}
- Skills: {', '.join(parsed_resume.get('skills', [])[:30])}
- Experience titles: {[e.get('title') for e in parsed_resume.get('experience', [])[:3]]}
- Top experience descriptions: {[e.get('description', '')[:200] for e in parsed_resume.get('experience', [])[:2]]}

JOB:
- Title: {jd_parsed.get('title')} at {jd_parsed.get('company')}
- Required Skills: {', '.join(jd_parsed.get('required_skills', []))}
- Key Responsibilities: {jd_parsed.get('responsibilities', [])[:5]}

Return JSON:
{{
  "tailored_summary": "Rewritten summary (2-3 sentences) optimized for this role",
  "skills_to_highlight": ["skill1", "skill2"],
  "skills_to_add": ["skill from resume not currently listed"],
  "bullet_rewrites": [
    {{"original": "...", "improved": "...", "reason": "..."}}
  ],
  "keywords_to_include": ["kw1", "kw2"],
  "ats_improvements": ["tip1", "tip2"],
  "estimated_ats_score": 0-100,
  "changes_summary": ["change1", "change2"]
}}"""

    try:
        raw = _call_llm(system, prompt, max_tokens=1500)
        return _parse_json_response(raw)
    except Exception as e:
        logger.error(f"Resume tailoring failed: {e}")
        return {}
