"""
Experience extraction — pulls "years of experience required" out of JD text.

Two entry points:
  • extract_experience(text)   — regex-only, zero-cost parse of a JD/title.
  • merge_experience(job, parsed) — fills a JobListingCreate's experience
    fields in place, with precedence:
        1. scraper-set values (structured, most reliable — Naukri/TimesJobs/…)
        2. LLM-parsed values from services/ai/job_analysis.parse_job_description
        3. regex over jd_text (this module)

Recall-first like the prefilter: a wrong "unspecified" is fine, a wrong
"12+ years" on a fresher role is not — every number is sanity-capped and
must appear near an experience keyword.
"""
import re
from typing import Optional

from models.job import ExperienceLevel, JobListingCreate

# Years mentioned in JDs above this are noise ("company founded 25 years ago").
_MAX_SANE_YEARS = 40

_YEARS = r"(?:years?|yrs?\.?)"

# Ordered: ranges first so "3-5 years" never half-matches as "5 years".
_RANGE_RE = re.compile(
    rf"(\d{{1,2}})\s*(?:-|–|—|to)\s*\+?(\d{{1,2}})\s*\+?\s*{_YEARS}", re.IGNORECASE
)
_PLUS_RE = re.compile(rf"(\d{{1,2}})\s*\+\s*{_YEARS}", re.IGNORECASE)
_MINIMUM_RE = re.compile(
    rf"(?:minimum|min\.?|at\s+least|atleast|more\s+than|over)\s+(?:of\s+)?(\d{{1,2}})\s*\+?\s*{_YEARS}",
    re.IGNORECASE,
)
_BARE_RE = re.compile(rf"(\d{{1,2}})\s*{_YEARS}", re.IGNORECASE)

# A bare "N years" only counts when experience is mentioned nearby —
# rejects "25 years in business", "2 years warranty", etc.
_CONTEXT_RE = re.compile(r"experience|exp\b|work(?:ing)?\s+in|relevant|hands[- ]on", re.IGNORECASE)
_CONTEXT_WINDOW = 60

_FRESHER_RE = re.compile(
    r"\bfreshers?\b|\bentry[- ]level\b|\bno\s+(?:prior\s+)?experience\s+(?:required|needed|necessary)\b",
    re.IGNORECASE,
)


def _has_context(text: str, start: int, end: int) -> bool:
    lo = max(0, start - _CONTEXT_WINDOW)
    hi = min(len(text), end + _CONTEXT_WINDOW)
    return bool(_CONTEXT_RE.search(text[lo:hi]))


def _sane(n: int) -> Optional[int]:
    return n if 0 <= n <= _MAX_SANE_YEARS else None


def extract_experience(jd_text: str, title: str = "") -> tuple[Optional[int], Optional[int]]:
    """Return (min_years, max_years) stated in a JD, or (None, None).

    Takes the first contextual mention — JDs lead with the overall
    requirement ("2-4 years experience...") before per-skill asides.
    """
    text = f"{title}\n{jd_text or ''}" if title else (jd_text or "")
    if not text.strip():
        return None, None

    candidates: list[tuple[int, Optional[int], Optional[int]]] = []  # (pos, min, max)

    for m in _RANGE_RE.finditer(text):
        lo, hi = _sane(int(m.group(1))), _sane(int(m.group(2)))
        if lo is None or hi is None:
            continue
        if hi < lo:
            lo, hi = hi, lo
        if _has_context(text, m.start(), m.end()):
            candidates.append((m.start(), lo, hi))

    for m in _MINIMUM_RE.finditer(text):
        lo = _sane(int(m.group(1)))
        if lo is not None and _has_context(text, m.start(), m.end()):
            candidates.append((m.start(), lo, None))

    for m in _PLUS_RE.finditer(text):
        lo = _sane(int(m.group(1)))
        if lo is not None and _has_context(text, m.start(), m.end()):
            candidates.append((m.start(), lo, None))

    if not candidates:
        # Bare "N years" needs context too, and is the weakest signal.
        for m in _BARE_RE.finditer(text):
            lo = _sane(int(m.group(1)))
            if lo is not None and _has_context(text, m.start(), m.end()):
                candidates.append((m.start(), lo, None))

    if candidates:
        candidates.sort(key=lambda c: c[0])
        _, lo, hi = candidates[0]
        return lo, hi

    if _FRESHER_RE.search(text):
        return 0, None
    return None, None


def _coerce_years(value) -> Optional[int]:
    """LLMs return ints, floats, numeric strings, or junk — normalize."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return _sane(int(float(value)))
    except (TypeError, ValueError):
        return None


def _coerce_level(value) -> Optional[ExperienceLevel]:
    if not value or not isinstance(value, str):
        return None
    try:
        return ExperienceLevel(value.strip().lower())
    except ValueError:
        return None


def merge_experience(job: JobListingCreate, parsed: Optional[dict] = None) -> bool:
    """Fill job.min_experience / max_experience / experience_level in place.

    Scraper-set fields are never overwritten. Returns True if anything was set.
    """
    parsed = parsed or {}
    changed = False

    if job.min_experience is None and job.max_experience is None:
        lo = _coerce_years(parsed.get("min_experience"))
        hi = _coerce_years(parsed.get("max_experience"))
        if lo is None and hi is None:
            lo, hi = extract_experience(job.jd_text, job.title)
        if lo is not None and hi is not None and hi < lo:
            lo, hi = hi, lo
        if lo is not None or hi is not None:
            job.min_experience = lo
            job.max_experience = hi
            changed = True

    if job.experience_level is None:
        level = _coerce_level(parsed.get("experience_level"))
        if level is not None:
            job.experience_level = level
            changed = True

    return changed
