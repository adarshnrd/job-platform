"""
Content Generation — cover letters, screening answers, resume tailoring.
"""
import re
from loguru import logger
from services.ai.provider import _call_llm, parse_json_response as _parse_json_response

# Sentinel the AI must return when it lacks the real data to answer truthfully.
NEEDS_INFO_TOKEN = "[NEEDS_INFO]"

_ANSWER_BLOCK_RE = re.compile(r"<ANSWER>(.*?)</ANSWER>", re.DOTALL)
_ANSWER_OPEN_RE = re.compile(r"<ANSWER>(.*)", re.DOTALL)
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_QUOTED_BLOCK_RE = re.compile(r'["“”]([^"“”]{60,})["“”]', re.DOTALL)


def _extract_answer(raw: str) -> str:
    """Pull the final answer out of an LLM response that may include
    chain-of-thought, <think> blocks, echoed prompts, or truncated <ANSWER> tags."""
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
    s = s.strip()
    s = re.sub(r"</?ANSWER>", "", s)
    s = re.sub(r"</?think>", "", s, flags=re.IGNORECASE)
    s = s.strip().strip('"').strip("“").strip("”").strip()
    return s


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
        return _extract_answer(_call_llm(system, prompt, max_tokens=2000, prefer=["groq"]))
    except Exception as e:
        logger.error(f"Cover letter generation failed: {e}")
        return ""


def answer_screening_question(question: str, user_profile: dict, job: dict, question_type: str = "text") -> str:
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
        ans = _call_llm(system, prompt, max_tokens=800, prefer=["groq"]).strip()
        return ans if NEEDS_INFO_TOKEN in ans else _extract_answer(ans)
    except Exception as e:
        logger.error(f"Screening answer failed: {e}")
        return f"{NEEDS_INFO_TOKEN} could not generate answer"


def draft_answer_for_user(question: str, user_profile: dict, job: dict, resume_summary: str = "") -> str:
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
        return _extract_answer(_call_llm(system, prompt, max_tokens=2000, prefer=["groq"]))
    except Exception as e:
        logger.error(f"Draft answer failed: {e}")
        raise


def rephrase_answer(question: str, user_answer: str, user_profile: dict, job: dict) -> str:
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
