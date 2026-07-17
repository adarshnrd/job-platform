"""Offline tests for experience extraction (services/experience.py).

Key guarantees under test: stated ranges/minimums are parsed from JD text,
numbers without experience context are ignored (recall-first: better to say
"unspecified" than invent a requirement), scraper-set values are never
overwritten by the merge, and LLM junk is coerced or dropped.
"""
import pytest

from models.job import ExperienceLevel, JobListingCreate, Platform
from services.experience import extract_experience, merge_experience


def _job(jd_text="Build things", **kw):
    return JobListingCreate(
        title=kw.pop("title", "Backend Engineer"),
        company=kw.pop("company", "Acme"),
        jd_text=jd_text,
        source_platform=Platform.remoteok,
        source_url=kw.pop("source_url", "https://remoteok.com/jobs/1"),
        **kw,
    )


# ── extract_experience: pattern matrix ──
@pytest.mark.parametrize("text,expected", [
    ("We need 3-5 years of experience in Python.", (3, 5)),
    ("Requires 3–5 yrs experience.", (3, 5)),               # en dash
    ("2 to 4 years of relevant experience.", (2, 4)),
    ("5+ years experience with Django.", (5, None)),
    ("Minimum 4 years of experience required.", (4, None)),
    ("At least 2 yrs hands-on experience.", (2, None)),
    ("Experience: 7 years working in DevOps.", (7, None)),
    ("Exp: 1-3 yrs.", (1, 3)),
    ("Freshers are welcome to apply.", (0, None)),
    ("This is an entry-level position.", (0, None)),
    ("No prior experience required.", (0, None)),
])
def test_extract_patterns(text, expected):
    assert extract_experience(text) == expected


# ── extract_experience: guards ──
def test_no_experience_mentioned():
    assert extract_experience("Great team, competitive salary, remote work.") == (None, None)


def test_years_without_context_ignored():
    # "years" with no experience keyword nearby — company age, warranty, etc.
    assert extract_experience("Founded 25 years ago, we ship hardware with a 2 years warranty.") == (None, None)


def test_insane_numbers_rejected():
    assert extract_experience("60 years of experience required.") == (None, None)


def test_reversed_range_swapped():
    assert extract_experience("5-3 years experience") == (3, 5)


def test_first_contextual_mention_wins():
    text = "You have 2-4 years of experience overall. Bonus: 8+ years with COBOL."
    assert extract_experience(text) == (2, 4)


def test_title_is_searched_too():
    assert extract_experience("Great role.", title="Backend Engineer (3-6 years exp)") == (3, 6)


def test_empty_input():
    assert extract_experience("") == (None, None)
    assert extract_experience(None) == (None, None)


# ── merge_experience: precedence ──
def test_scraper_values_never_overwritten():
    job = _job(min_experience=2, max_experience=4)
    merge_experience(job, {"min_experience": 9, "max_experience": 12})
    assert (job.min_experience, job.max_experience) == (2, 4)


def test_llm_values_used_when_scraper_empty():
    job = _job()
    assert merge_experience(job, {"min_experience": 3, "max_experience": 6, "experience_level": "senior"})
    assert (job.min_experience, job.max_experience) == (3, 6)
    assert job.experience_level == ExperienceLevel.senior


def test_regex_fallback_when_llm_empty():
    job = _job(jd_text="We want someone with 4+ years of experience in Go.")
    assert merge_experience(job, {"min_experience": None, "max_experience": None})
    assert (job.min_experience, job.max_experience) == (4, None)


def test_llm_junk_coerced_or_dropped():
    job = _job(jd_text="Minimum 2 years experience.")
    # Numeric strings coerce; junk falls through to the regex.
    merge_experience(job, {"min_experience": "3", "max_experience": "five"})
    assert job.min_experience == 3

    job2 = _job(jd_text="Minimum 2 years experience.")
    merge_experience(job2, {"min_experience": "unknown", "max_experience": None})
    assert job2.min_experience == 2  # regex fallback


def test_invalid_level_dropped():
    job = _job()
    merge_experience(job, {"experience_level": "rockstar"})
    assert job.experience_level is None


def test_llm_reversed_range_swapped():
    job = _job()
    merge_experience(job, {"min_experience": 8, "max_experience": 5})
    assert (job.min_experience, job.max_experience) == (5, 8)


def test_nothing_to_merge_returns_false():
    job = _job(jd_text="Nice team.")
    assert merge_experience(job, {}) is False
    assert job.min_experience is None
