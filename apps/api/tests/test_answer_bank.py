"""Unit tests for the Answer Bank matching + resolution logic (no DB required)."""
import pytest

from services.questions.schema import (
    normalize_question, hash_question, infer_type,
    NUMERIC, BOOLEAN, TEXTAREA, TEXT, FormQuestion,
)
from services.questions.matcher import (
    classify_profile_field, is_essay_question, extract_skill,
)
from services.questions.resolver import resolve_question, build_question_resolver
from services.questions.schema import ResolutionStatus, NEEDS_INFO_TOKEN


# ── normalization / hashing ──────────────────────────────────────────────────

def test_normalize_strips_numbers_and_punctuation():
    assert normalize_question("How many years? 5+ years!") == "how many years years"

def test_normalize_collapses_whitespace():
    assert normalize_question("  Notice   period\n days ") == "notice period days"

def test_hash_is_stable_across_number_variants():
    # Same question with different numbers hashes identically (numbers blanked).
    assert hash_question("5+ years with Python") == hash_question("3+ years with Python")

def test_hash_differs_for_different_questions():
    assert hash_question("expected salary") != hash_question("notice period")


# ── type inference ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("How many years of experience do you have?", NUMERIC),
    ("What is your expected CTC?", NUMERIC),
    ("Are you authorized to work in India?", BOOLEAN),
    ("Do you have a valid passport?", BOOLEAN),
    ("Why do you want to work here and what motivates you in your career journey?", TEXTAREA),
    ("Preferred location", TEXT),
])
def test_infer_type(text, expected):
    assert infer_type(text) == expected


# ── profile classification ───────────────────────────────────────────────────

@pytest.mark.parametrize("text,category,field", [
    ("What is your notice period?", "notice_period", "notice_period_days"),
    ("Expected CTC", "salary", "expected_salary_min"),
    ("Are you authorized to work in the US?", "work_auth", "work_authorization"),
    ("Are you willing to relocate?", "relocation", "willing_to_relocate"),
    ("Total years of experience", "experience", "experience_years"),
    ("Your LinkedIn profile URL", "linkedin", "linkedin_url"),
])
def test_classify_profile_field(text, category, field):
    cat, fld = classify_profile_field(text)
    assert cat == category
    assert fld == field

def test_classify_unknown_is_custom():
    assert classify_profile_field("What is your favorite color?") == ("custom", None)


# ── essay + skill extraction ─────────────────────────────────────────────────

def test_is_essay_question():
    assert is_essay_question("Why do you want to join us?")
    assert is_essay_question("Tell us about a challenge you faced")
    assert not is_essay_question("What is your notice period?")

def test_extract_skill():
    assert extract_skill("How many years of experience with Kafka?") == "kafka"
    assert extract_skill("Years of experience in React") == "react"
    assert extract_skill("What is your notice period?") is None


# ── resolution ladder (profile-mapped, no DB writes) ─────────────────────────

def test_resolve_profile_mapped_answered():
    user = {"notice_period_days": 30}
    q = FormQuestion(text="What is your notice period (in days)?")
    res = resolve_question("u1", q, user=user, service=_NoopService())
    assert res.status == ResolutionStatus.ANSWERED
    assert res.value == "30"
    assert res.source == "profile"

def test_resolve_relocation_boolean_formatting():
    user = {"willing_to_relocate": True}
    q = FormQuestion(text="Are you willing to relocate?")
    res = resolve_question("u1", q, user=user, service=_NoopService())
    assert res.answered and res.value == "Yes"

def test_resolve_skill_experience_from_tech_stack():
    user = {"tech_stack": {"Kafka": 4}}
    q = FormQuestion(text="How many years of experience with Kafka?")
    res = resolve_question("u1", q, user=user, service=_NoopService(), allow_ai_essay=False)
    assert res.answered and res.value == "4"

def test_resolve_unknown_pauses():
    user = {"full_name": "Jane"}
    q = FormQuestion(text="What is your favorite programming paradigm and why?")
    # essay disabled so it falls through to needs_input deterministically
    res = resolve_question("u1", q, user=user, service=_NoopService(), allow_ai_essay=False)
    assert res.status == ResolutionStatus.NEEDS_INPUT


def test_build_resolver_callback_returns_needs_info_sentinel():
    user = {"full_name": "Jane"}
    pending = []
    resolver = build_question_resolver(
        "u1", user=user, application_id=None, pending_tracker=pending, service=_NoopService(),
    )
    out = resolver("Describe your favorite side project in detail and why it mattered")
    assert out == NEEDS_INFO_TOKEN
    assert len(pending) == 1

def test_build_resolver_callback_answers_from_profile():
    user = {"notice_period_days": 15}
    pending = []
    resolver = build_question_resolver(
        "u1", user=user, application_id=None, pending_tracker=pending, service=_NoopService(),
    )
    assert resolver("Notice period in days?") == "15"
    assert pending == []


class _NoopService:
    """Stand-in QuestionService that never touches the DB."""
    def upsert_question(self, *a, **k):
        return None
    def add_pending(self, *a, **k):
        return None
    def record_usage(self, *a, **k):
        return None
    def find_banked(self, *a, **k):
        return None
