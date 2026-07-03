"""
Resolver — turn a detected question into a fill value or a pause.

Resolution ladder (never fabricates a factual answer):
  1. profile-mapped   → live value from the users row
  2. skill-experience → users.tech_stack per-skill years
  3. banked answer    → exact/trigram match in the user's Answer Bank
  4. essay/opinion    → AI draft (job-specific, not banked)
  5. otherwise        → NEEDS_INPUT: persist the question, record it as pending,
                        and return the [NEEDS_INFO] sentinel so the adapter leaves
                        the field blank (which pauses the application).
"""
from __future__ import annotations

from loguru import logger

from services.questions.schema import (
    FormQuestion, Resolution, ResolutionStatus, NEEDS_INFO_TOKEN, infer_type,
)
from services.questions.matcher import (
    classify_profile_field, is_essay_question, extract_skill,
)
from services.questions.service import QuestionService


def _format_profile_value(field: str, user: dict):
    """Render a users column into a form-ready string. Returns None if unset."""
    val = user.get(field)
    if val in (None, "", []):
        return None
    if field == "willing_to_relocate":
        return "Yes" if val else "No"
    if field in ("notice_period_days", "experience_years",
                 "expected_salary_min", "current_salary"):
        return str(val)
    return str(val)


def resolve_question(
    user_id: str,
    q: FormQuestion,
    *,
    user: dict,
    job_data: dict | None = None,
    application_id: str | None = None,
    service: QuestionService | None = None,
    allow_ai_essay: bool = True,
) -> Resolution:
    """Resolve one question. Persists unknown questions + pending rows as a side
    effect so the UI can surface them. Pure lookups (profile/bank) don't write."""
    service = service or QuestionService()
    q.qtype = q.qtype or infer_type(q.text)
    category, profile_field = classify_profile_field(q.text)

    # 1. Skill-experience → tech_stack. Checked before the generic profile
    # mapping so "years of experience with Kafka" resolves per-skill rather than
    # being answered with total years of experience.
    skill = extract_skill(q.text)
    if skill:
        category = "skill_experience"
        profile_field = None  # not the generic experience field
        tech = user.get("tech_stack") or {}
        for k, yrs in tech.items():
            if k.lower() == skill.lower() and yrs not in (None, ""):
                return Resolution(ResolutionStatus.ANSWERED, value=str(yrs),
                                  source="profile", category="skill_experience")

    # 2. Profile-mapped → live value.
    if profile_field:
        value = _format_profile_value(profile_field, user)
        if value is not None:
            return Resolution(ResolutionStatus.ANSWERED, value=value,
                              source="profile", category=category, profile_field=profile_field)
        # Known category but the profile field is empty → ask the user (and point
        # them at the profile). Fall through to needs_input, tagged with category.

    # 3. Banked answer.
    banked = service.find_banked(user_id, q.text)
    if banked:
        service.record_usage(user_id, banked["question_id"])
        return Resolution(ResolutionStatus.ANSWERED, value=str(banked["value"]),
                          source="bank", category=banked.get("category", category),
                          question_id=banked["question_id"])

    # 4. Essay/opinion → AI draft (job-specific; not banked).
    if allow_ai_essay and is_essay_question(q.text):
        draft = _ai_draft(q.text, user, job_data or {})
        if draft and NEEDS_INFO_TOKEN not in draft:
            return Resolution(ResolutionStatus.ANSWERED, value=draft,
                              source="ai_draft", category="essay")

    # 5. Unknown → persist + pause.
    qid = service.upsert_question(user_id, q, application_id=application_id)
    if qid and application_id:
        service.add_pending(user_id, application_id, qid,
                            raw_context={"selector": q.selector, "options": q.options,
                                         "platform": q.platform})
    return Resolution(ResolutionStatus.NEEDS_INPUT, category=category,
                      profile_field=profile_field, question_id=qid)


def _ai_draft(question: str, user: dict, job_data: dict) -> str | None:
    """Draft an essay-style answer with the existing anti-fabrication generator."""
    try:
        from services.ai import answer_screening_question
        return answer_screening_question(question, user, job_data)
    except Exception as e:
        logger.debug(f"Essay draft skipped: {e}")
        return None


def build_question_resolver(
    user_id: str,
    *,
    user: dict,
    job_data: dict | None = None,
    application_id: str | None = None,
    platform: str = "",
    pending_tracker: list | None = None,
    service: QuestionService | None = None,
):
    """Return a synchronous `(question_text) -> str` callback for adapters.

    Matches the existing `screening_answerer` seam: adapters call it with the
    question text and skip filling when the return contains [NEEDS_INFO]. Every
    unknown question is appended to `pending_tracker` so the bot can detect that
    the application must pause.
    """
    service = service or QuestionService()
    pending_tracker = pending_tracker if pending_tracker is not None else []

    def _resolver(question_text: str) -> str:
        if not question_text or not question_text.strip():
            return NEEDS_INFO_TOKEN
        q = FormQuestion(text=question_text.strip(), platform=platform)
        try:
            res = resolve_question(
                user_id, q, user=user, job_data=job_data,
                application_id=application_id, service=service,
            )
        except Exception as e:
            logger.warning(f"Question resolution failed for '{question_text[:50]}': {e}")
            return NEEDS_INFO_TOKEN
        if res.answered:
            return res.value
        pending_tracker.append({
            "question": question_text.strip(),
            "question_id": res.question_id,
            "category": res.category,
        })
        return NEEDS_INFO_TOKEN

    return _resolver
