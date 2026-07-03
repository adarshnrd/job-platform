"""
Question matcher — maps a detected question to a known answer source.

Resolution order (cheapest first):
  1. profile-field classifier  — rules/keywords → a users table column
  2. exact hash match          — same normalized text seen before
  3. trigram similarity        — pg_trgm via the find_similar_question RPC
The LLM equivalence tie-break described in the roadmap is intentionally deferred;
trigram + profile rules resolve the vast majority at single-user scale, and
staying LLM-free keeps this deterministic and unit-testable.
"""
from __future__ import annotations

import re

from loguru import logger

from services.questions.schema import normalize_question, hash_question


# ── Profile-field classification ─────────────────────────────────────────────
# Each rule maps a question category to (a) the users column that answers it
# live and (b) keyword/regex patterns that identify it. Ordered by specificity.
#
# category, profile_field, patterns
_PROFILE_RULES: list[tuple[str, str | None, list[str]]] = [
    ("notice_period", "notice_period_days",
     [r"notice period", r"how soon can you (join|start)", r"availability to (join|start)",
      r"when can you (join|start)"]),
    ("salary", "expected_salary_min",
     [r"expected (ctc|salary|compensation)", r"salary expectation", r"desired salary",
      r"expected pay"]),
    ("salary_current", "current_salary",
     [r"current (ctc|salary|compensation)", r"present (ctc|salary)"]),
    ("work_auth", "work_authorization",
     [r"work authoriz", r"work authoris", r"authorized to work", r"authorised to work",
      r"right to work", r"visa status", r"require sponsorship", r"need sponsorship"]),
    ("relocation", "willing_to_relocate",
     [r"reloc", r"willing to move"]),
    ("experience", "experience_years",
     [r"total (years )?(of )?experience", r"years of experience", r"how many years.*experience",
      r"overall experience"]),
    ("contact_phone", "phone",
     [r"phone", r"mobile", r"contact number"]),
    ("contact_email", "email",
     [r"email address", r"your email"]),
    ("location", "location",
     [r"current location", r"your location", r"where are you (based|located)",
      r"current city"]),
    ("linkedin", "linkedin_url",
     [r"linkedin (profile|url)"]),
    ("github", "github_url",
     [r"github (profile|url)"]),
    ("portfolio", "portfolio_url",
     [r"portfolio (url|link)", r"website url"]),
    ("full_name", "full_name",
     [r"full name", r"your name", r"first name", r"last name"]),
]

_COMPILED_RULES = [
    (cat, field, [re.compile(p) for p in pats])
    for cat, field, pats in _PROFILE_RULES
]

# Essay/opinion questions: job-specific, AI-drafted, never banked.
_ESSAY_PATTERNS = [re.compile(p) for p in [
    r"why (do you|are you|this|would you)", r"tell us about", r"describe (a|your|why)",
    r"cover letter", r"what (makes|motivates)", r"your motivation", r"why should we",
    r"a few (words|lines)", r"in your own words",
]]

# Skill-experience: "years of experience with <skill>" → users.tech_stack lookup.
_SKILL_EXP_RE = re.compile(
    r"(?:years?|experience)\s+(?:of\s+)?(?:experience\s+)?(?:with|in|using)\s+([a-z0-9+.# \-]{2,40})"
)


def classify_profile_field(text: str) -> tuple[str, str | None]:
    """Return (category, profile_field) if the question maps to a profile column.

    profile_field is None for categories we recognize but don't store as a single
    column (none currently) — callers treat a non-None profile_field as "resolve live".
    Returns ("custom", None) when unmatched.
    """
    norm = normalize_question(text)
    for category, field, patterns in _COMPILED_RULES:
        if any(p.search(norm) for p in patterns):
            return category, field
    return "custom", None


def is_essay_question(text: str) -> bool:
    norm = normalize_question(text)
    return any(p.search(norm) for p in _ESSAY_PATTERNS)


def extract_skill(text: str) -> str | None:
    """Pull the skill name out of a 'years with <skill>' style question."""
    m = _SKILL_EXP_RE.search((text or "").lower())
    if not m:
        return None
    skill = m.group(1).strip().rstrip("?.")
    # Drop trailing filler words.
    skill = re.sub(r"\b(do you have|have you|the|a|an)\b", "", skill).strip()
    return skill or None


def find_banked_answer(db, user_id: str, text: str) -> dict | None:
    """Look up a saved answer for this question via exact hash then trigram.

    Returns a dict {question_id, value, question_type, category} or None.
    """
    qhash = hash_question(text)
    norm = normalize_question(text)

    # 1. Exact hash match.
    try:
        exact = (
            db.table("question_bank")
            .select("id, question_type, category")
            .eq("user_id", user_id)
            .eq("question_hash", qhash)
            .limit(1)
            .execute()
        )
        if exact.data:
            q = exact.data[0]
            ans = _active_answer(db, user_id, q["id"])
            if ans is not None:
                return {"question_id": q["id"], "value": ans,
                        "question_type": q["question_type"], "category": q["category"]}
    except Exception as e:
        logger.debug(f"Answer-bank exact lookup skipped: {e}")

    # 2. Trigram similarity via RPC.
    try:
        sim = db.rpc("find_similar_question", {
            "p_user_id": user_id, "p_norm": norm, "p_threshold": 0.6, "p_limit": 3,
        }).execute()
        for cand in (sim.data or []):
            ans = _active_answer(db, user_id, cand["id"])
            if ans is not None:
                return {"question_id": cand["id"], "value": ans,
                        "question_type": cand.get("question_type", "text"),
                        "category": cand.get("category", "custom")}
    except Exception as e:
        logger.debug(f"Answer-bank trigram lookup skipped: {e}")

    return None


def _active_answer(db, user_id: str, question_id: str) -> str | None:
    """Return the active answer value for a banked question, or None."""
    try:
        res = (
            db.table("user_answers")
            .select("answer, is_active")
            .eq("user_id", user_id)
            .eq("question_id", question_id)
            .eq("is_active", True)
            .maybe_single()
            .execute()
        )
        if res and res.data:
            answer = res.data.get("answer") or {}
            val = answer.get("value") if isinstance(answer, dict) else answer
            if val not in (None, ""):
                return str(val)
    except Exception as e:
        logger.debug(f"Active-answer lookup skipped: {e}")
    return None
