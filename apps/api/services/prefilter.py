"""
Rule-based relevance prefilter — a cheap gate before the LLM scoring pipeline.

Discovery now pulls from many sources (ATS boards alone carry hundreds of India
roles across sales/finance/marketing/engineering). Parsing and dual-LLM
double-eval scoring every raw job would scale token cost linearly with volume.
This deterministic filter drops jobs that clearly don't match the user's
profile — a "Corporate Sales Manager" for a Node.js engineer — before any LLM
call, protecting the daily budget (services/ai/provider._check_budget).

It is intentionally **recall-first**: it only rejects a job when there is enough
text to judge AND zero overlap with either the user's own keywords or generic
technical-role vocabulary. Borderline jobs are kept — the LLM remains the
precision gate. Disable with DISCOVERY_PREFILTER_ENABLED=false.
"""
import re

from loguru import logger

# Generic technical-role vocabulary. A hit in the *title* keeps the job even if
# the user's exact skills aren't mentioned (short JDs, reworded titles).
TECH_ROLE_WORDS = {
    "engineer", "engineering", "developer", "development", "programmer",
    "architect", "sde", "swe", "backend", "back-end", "frontend", "front-end",
    "fullstack", "full-stack", "full stack", "devops", "sre", "software",
    "programming", "coder", "qa", "sdet", "data", "ml", "ai", "machine learning",
    "platform", "cloud", "infrastructure", "systems", "web", "mobile", "android",
    "ios", "api", "database", "security", "blockchain", "technical", "tech lead",
    "cto", "vp engineering", "staff engineer", "principal engineer",
}

_TOKEN = re.compile(r"[a-z0-9][a-z0-9.+#-]*")
_STOPWORDS = {
    "the", "and", "for", "with", "job", "jobs", "role", "roles", "at", "in",
    "to", "of", "a", "an", "years", "year", "experience", "work", "team",
    "our", "you", "your", "we", "are", "is", "as", "on", "or",
}
# Minimum haystack length before we trust a "no signal" verdict; below this we
# keep the job (too little text to reject safely).
_MIN_JUDGE_LEN = 30


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall((text or "").lower()) if len(t) >= 2 and t not in _STOPWORDS}


def build_user_keywords(user: dict) -> set[str]:
    """The user's *distinctive* vocabulary — skills and tech stack only.

    Deliberately excludes headline/career-goal prose: words like "software" or
    "engineer" appear in almost every tech-company JD (including sales roles at
    those companies), so matching them defeats the filter. Generic technical-role
    coverage is handled separately by TECH_ROLE_WORDS against the *title*. Skill
    terms (NestJS, TypeScript, Kubernetes) are specific enough that an
    off-profile JD won't mention them.
    """
    kw: set[str] = set()

    def add_skill(raw: str):
        # Keep each skill as a whole phrase — never decompose. Splitting
        # "Express.js"→"express" or "Node.js"→"node" injects common English words
        # that match off-profile JDs ("express interest", "node in the network").
        # The tokenizer preserves dots/plus/hash within a token, so "node.js"
        # still matches a JD's "node.js" exactly without matching "node".
        s = str(raw).lower().strip()
        if s:
            kw.add(s)

    for skill in (user.get("skills") or []):
        add_skill(skill)
    ts = user.get("tech_stack")
    if isinstance(ts, dict):
        for v in ts.values():
            for item in (v if isinstance(v, list) else [v]):
                add_skill(item)
    elif isinstance(ts, list):
        for item in ts:
            add_skill(item)

    return {k for k in kw if k and k not in _STOPWORDS}


def is_relevant(job, user_keywords: set[str]) -> bool:
    """Recall-first: keep unless we can confidently say it's off-profile."""
    if not user_keywords:
        return True  # nothing to compare against → don't filter

    title = (getattr(job, "title", "") or "").lower()
    skills = " ".join(getattr(job, "required_skills", None) or []).lower()
    jd = (getattr(job, "jd_text", "") or "").lower()
    haystack = f"{title} {skills} {jd}"

    if len(haystack.strip()) < _MIN_JUDGE_LEN:
        return True  # too little signal to reject

    # 1) generic tech-role word in the title → keep
    if any(w in title for w in TECH_ROLE_WORDS):
        return True
    # 2) any of the user's own keywords anywhere → keep
    hay_tokens = _tokens(haystack)
    for kw in user_keywords:
        if " " in kw or "." in kw or "+" in kw or "#" in kw:
            if kw in haystack:   # phrase / dotted skill (node.js, c++)
                return True
        elif kw in hay_tokens:
            return True
    return False


def prefilter_jobs(jobs: list, user: dict) -> tuple[list, int]:
    """Return (kept_jobs, dropped_count). Order preserved."""
    keywords = build_user_keywords(user)
    if not keywords:
        return jobs, 0
    kept = [j for j in jobs if is_relevant(j, keywords)]
    dropped = len(jobs) - len(kept)
    if dropped:
        logger.info(f"Prefilter: dropped {dropped}/{len(jobs)} off-profile jobs before LLM scoring")
    return kept, dropped
