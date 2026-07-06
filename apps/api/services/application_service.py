"""
Assisted-Apply service — prepares a complete application package, records a full
audit trail, and tracks submission status. Works for every job source (including
API-sourced jobs that have only an external apply link).

Resilient to pre-migration DB state: writes to new tracking columns/tables are
attempted but degrade gracefully if 03_application_tracking.sql hasn't been run.
"""
from datetime import datetime, timezone
from loguru import logger
from database import get_db
from services.ai import generate_cover_letter, answer_screening_question, NEEDS_INFO_TOKEN

db = get_db()

# Fields that BLOCK an application if missing — never guessed or defaulted.
REQUIRED_PROFILE_FIELDS = [
    ("full_name", "Full name"),
    ("email", "Email"),
    ("phone", "Phone number"),
    ("location", "Current location"),
    ("experience_years", "Total years of experience"),
    ("expected_salary_min", "Expected salary"),
    ("work_authorization", "Work authorization"),
    ("notice_period_days", "Notice period (days)"),
]

# Common screening questions we pre-draft answers for.
COMMON_SCREENING_QUESTIONS = [
    "Why are you interested in this role?",
    "What is your notice period / availability to start?",
    "What are your salary expectations?",
    "Are you authorized to work in this location?",
    "Why are you a good fit for this position?",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_event(application_id: str, user_id: str, event_type: str, message: str = "", metadata: dict | None = None):
    """Append to the application audit trail. Skips silently if the table is absent."""
    try:
        db.table("application_events").insert({
            "application_id": application_id,
            "user_id": user_id,
            "event_type": event_type,
            "message": message,
            "metadata": metadata or {},
        }).execute()
    except Exception as e:
        logger.warning(f"application_events insert skipped ({event_type}): {e}")


def _update_application(app_id: str, fields: dict, legacy_only: dict):
    """
    Update job_applications with the full tracking fields; if the new columns
    don't exist yet (pre-migration), retry with only the legacy columns.
    """
    try:
        db.table("job_applications").update(fields).eq("id", app_id).execute()
    except Exception as e:
        if "could not find" in str(e).lower() or "column" in str(e).lower():
            logger.warning(f"Tracking columns missing — applying legacy update only. Run 03_application_tracking.sql. ({e})")
            try:
                db.table("job_applications").update(legacy_only).eq("id", app_id).execute()
            except Exception as e2:
                logger.error(f"Legacy application update failed: {e2}")
        else:
            logger.error(f"Application update failed: {e}")


def _missing_profile_fields(user: dict) -> list[dict]:
    missing = []
    for key, label in REQUIRED_PROFILE_FIELDS:
        val = user.get(key)
        if val in (None, "", 0, []):
            missing.append({"field": key, "label": label})
    return missing


def _missing_skill_experience(user: dict, job_skills: list[str]) -> list[dict]:
    """Require per-skill years for the user's skills that this job actually asks for.
    Stored in users.tech_stack JSONB as {skill: years}. Never guessed."""
    skill_exp = user.get("tech_stack") or {}
    user_skills = {s.lower(): s for s in (user.get("skills") or [])}
    job_skill_set = {s.lower() for s in (job_skills or [])}

    # Skills the candidate has that this job requires — the relevant ones to quantify.
    relevant = [orig for low, orig in user_skills.items() if low in job_skill_set]
    # Fall back to the user's top skills if the job lists none we recognize.
    if not relevant:
        relevant = (user.get("skills") or [])[:5]

    missing = []
    for skill in relevant:
        yrs = skill_exp.get(skill)
        if yrs in (None, "", 0):
            missing.append({"field": f"skill_exp::{skill}", "label": f"Years of experience with {skill}"})
    return missing


def prepare_application(user_id: str, application_id: str, overrides: dict | None = None) -> dict:
    """
    Build the full assisted-apply package: pick resume, write cover letter, draft
    screening answers, assemble form data + snapshots, persist, and log events.
    Returns the package, or {"needs_input": [...]} when profile fields are missing.
    """
    overrides = overrides or {}

    app_res = db.table("application_details").select("*").eq("id", application_id).eq("user_id", user_id).maybe_single().execute()
    if not (app_res and app_res.data):
        return {"error": "Application not found", "status_code": 404}
    app = app_res.data

    user_res = db.table("users").select("*").eq("id", user_id).maybe_single().execute()
    if not (user_res and user_res.data):
        return {"error": "User profile not found", "status_code": 404}
    user = dict(user_res.data)
    user["tech_stack"] = dict(user.get("tech_stack") or {})

    # Apply any per-job overrides on top of the stored profile (for this run).
    # skill_exp::<skill> overrides route into tech_stack; answer::<q> are handled later.
    for k, v in overrides.items():
        if k == "resume_id" or v in (None, ""):
            continue
        if k.startswith("skill_exp::"):
            user["tech_stack"][k.split("::", 1)[1]] = v
        elif not k.startswith("answer::"):
            user[k] = v

    job = {
        "title": app.get("job_title"),
        "company": app.get("job_company"),
        "location": app.get("job_location"),
        "required_skills": app.get("job_required_skills", []),
        "jd_text": app.get("jd_text", ""),
    }

    # 1) Required-field check — prompt for any missing profile field OR per-skill
    #    years of experience. Nothing is ever guessed or defaulted.
    missing = _missing_profile_fields(user)
    missing += _missing_skill_experience(user, job["required_skills"])
    if missing:
        log_event(application_id, user_id, "prepare_blocked",
                  f"Missing {len(missing)} field(s) — asking the user, not guessing",
                  {"missing": [m["field"] for m in missing]})
        return {"needs_input": missing, "submission_status": "not_started"}

    # 2) Resolve resume (override → primary → most recent).
    resume = _resolve_resume(user_id, overrides.get("resume_id"))
    if not resume:
        return {"needs_input": [{"field": "resume", "label": "Upload a resume first"}],
                "submission_status": "not_started"}

    # 3) Cover letter (uses only real data — see ai_service anti-fabrication rules).
    resume_summary = (resume.get("parsed_data") or {}).get("summary", "")
    cover_letter = generate_cover_letter(user, job, resume_summary)
    log_event(application_id, user_id, "cover_letter_generated", "AI cover letter drafted (real data only)")

    # 4) Draft screening answers — answer once, reuse forever:
    #    user override → saved Answer Bank answer → AI draft. If the AI flags
    #    missing info, collect it from the user instead of fabricating; any
    #    answer the user provides is banked so no application asks it again.
    from services.questions import QuestionService
    question_service = QuestionService()

    drafted_answers = []
    answer_gaps = []
    for q in COMMON_SCREENING_QUESTIONS:
        # If the user supplied this answer (via a prior needs_input round), use it
        # verbatim and persist it to the Answer Bank for every future application.
        user_answer = overrides.get(f"answer::{q}")
        if user_answer not in (None, ""):
            drafted_answers.append({"question": q, "answer": user_answer, "source": "user"})
            try:
                question_service.create_manual(user_id, q, user_answer)
            except Exception as e:
                logger.warning(f"Answer Bank save skipped for '{q}': {e}")
            continue

        # Reuse a previously banked answer (exact or fuzzy match) — don't re-ask.
        try:
            banked = question_service.find_banked(user_id, q)
        except Exception as e:
            logger.debug(f"Answer Bank lookup skipped for '{q}': {e}")
            banked = None
        if banked and banked.get("value") not in (None, ""):
            drafted_answers.append({"question": q, "answer": banked["value"], "source": "bank"})
            try:
                question_service.record_usage(user_id, banked["question_id"])
            except Exception:
                pass
            continue

        try:
            ans = answer_screening_question(q, user, job)
        except Exception as e:
            logger.warning(f"Screening answer failed for '{q}': {e}")
            ans = f"{NEEDS_INFO_TOKEN} could not generate answer"
        if NEEDS_INFO_TOKEN in ans:
            need = ans.replace(NEEDS_INFO_TOKEN, "").strip() or q
            answer_gaps.append({"field": f"answer::{q}", "label": f"Answer needed: {q}", "hint": need})
        drafted_answers.append({"question": q, "answer": ans})

    if answer_gaps:
        log_event(application_id, user_id, "prepare_blocked",
                  f"AI needs {len(answer_gaps)} answer(s) it cannot truthfully provide",
                  {"gaps": [g["field"] for g in answer_gaps]})
        return {"needs_input": answer_gaps, "submission_status": "not_started",
                "note": "Some questions need your input — the assistant will not invent answers."}

    log_event(application_id, user_id, "answers_drafted", f"Drafted {len(drafted_answers)} screening answers from real data")

    # 5) Assemble snapshots + form data.
    form_data = {
        "full_name": user.get("full_name"),
        "email": user.get("email"),
        "phone": user.get("phone"),
        "location": user.get("location"),
        "work_authorization": user.get("work_authorization"),
        "willing_to_relocate": user.get("willing_to_relocate"),
        "notice_period_days": user.get("notice_period_days"),
        "expected_salary_min": user.get("expected_salary_min"),
        "expected_salary_max": user.get("expected_salary_max"),
        "years_experience": user.get("experience_years"),
        "skill_experience": user.get("tech_stack") or {},
        "linkedin_url": user.get("linkedin_url"),
        "github_url": user.get("github_url"),
        "portfolio_url": user.get("portfolio_url"),
    }
    resume_snapshot = {
        "resume_id": resume.get("id"),
        "name": resume.get("name"),
        "file_url": resume.get("file_url"),
        "version": resume.get("version", 1),
    }
    job_snapshot = {
        "title": app.get("job_title"),
        "company": app.get("job_company"),
        "location": app.get("job_location"),
        "source_platform": app.get("source_platform"),
        "source_url": app.get("source_url"),
        "apply_url": app.get("apply_url") or app.get("source_url"),
        "salary_min": app.get("salary_min"),
        "salary_max": app.get("salary_max"),
        "salary_currency": app.get("salary_currency"),
        "captured_at": _now(),
    }

    full_fields = {
        "resume_id": resume.get("id"),
        "cover_letter": cover_letter,
        "submission_status": "ready",
        "submission_method": "assisted",
        "form_data": form_data,
        "submitted_responses": {"screening_answers": drafted_answers},
        "resume_snapshot": resume_snapshot,
        "job_snapshot": job_snapshot,
        "prepared_at": _now(),
    }
    legacy = {"resume_id": resume.get("id"), "cover_letter": cover_letter}
    _update_application(application_id, full_fields, legacy)
    log_event(application_id, user_id, "prepared", "Application package ready to submit")

    return {
        "submission_status": "ready",
        "apply_url": job_snapshot["apply_url"],
        "cover_letter": cover_letter,
        "screening_answers": drafted_answers,
        "form_data": form_data,
        "resume": resume_snapshot,
        "job": job_snapshot,
    }


def load_answer_context(user_id: str, application_id: str) -> dict | None:
    """Load the user profile + job context + resume summary needed to draft or
    rephrase a single screening answer. Returns None if app/user not found."""
    app_res = db.table("application_details").select("*").eq("id", application_id).eq("user_id", user_id).maybe_single().execute()
    if not (app_res and app_res.data):
        return None
    app = app_res.data

    user_res = db.table("users").select("*").eq("id", user_id).maybe_single().execute()
    if not (user_res and user_res.data):
        return None
    user = dict(user_res.data)

    resume = _resolve_resume(user_id, None)
    resume_summary = ((resume or {}).get("parsed_data") or {}).get("summary", "")

    job = {
        "title": app.get("job_title"),
        "company": app.get("job_company"),
        "location": app.get("job_location"),
        "required_skills": app.get("job_required_skills", []),
        "jd_text": app.get("jd_text", ""),
    }
    return {"user": user, "job": job, "resume_summary": resume_summary}


def _resolve_resume(user_id: str, resume_id: str | None) -> dict | None:
    try:
        if resume_id:
            r = db.table("resumes").select("*").eq("id", resume_id).eq("user_id", user_id).maybe_single().execute()
            if r and r.data:
                return r.data
        r = db.table("resumes").select("*").eq("user_id", user_id).eq("is_primary", True).maybe_single().execute()
        if r and r.data:
            return r.data
        r = db.table("resumes").select("*").eq("user_id", user_id).eq("is_active", True).order("created_at", desc=True).limit(1).execute()
        return r.data[0] if r and r.data else None
    except Exception as e:
        logger.warning(f"Resume resolution failed: {e}")
        return None


def mark_opened(user_id: str, application_id: str) -> dict:
    _update_application(application_id,
                        {"submission_status": "opened"},
                        {})
    log_event(application_id, user_id, "opened_external", "Opened the external application page")
    return {"submission_status": "opened"}


def confirm_submitted(user_id: str, application_id: str, confirmation_id: str | None = None) -> dict:
    full = {
        "status": "applied",
        "submission_status": "submitted",
        "submission_method": "assisted",
        "applied_via": "assisted",
        "applied_at": _now(),
    }
    if confirmation_id:
        full["application_id"] = confirmation_id
    legacy = {"status": "applied", "applied_via": "assisted", "applied_at": _now()}
    _update_application(application_id, full, legacy)
    log_event(application_id, user_id, "submitted", "User confirmed the application was submitted",
              {"confirmation_id": confirmation_id})
    return {"status": "applied", "submission_status": "submitted"}


def mark_failed(user_id: str, application_id: str, reason: str) -> dict:
    full = {
        "status": "matched",  # revert the funnel status so it's actionable again
        "submission_status": "failed",
        "failure_reason": reason,
    }
    legacy = {"status": "matched", "rejection_reason": reason}
    _update_application(application_id, full, legacy)
    log_event(application_id, user_id, "failed", reason or "Application could not be submitted")
    return {"submission_status": "failed", "failure_reason": reason}


def get_events(user_id: str, application_id: str) -> list[dict]:
    """Return the ordered audit trail for an application."""
    try:
        res = db.table("application_events").select("*").eq("application_id", application_id).eq("user_id", user_id).order("created_at", desc=False).execute()
        return res.data or []
    except Exception as e:
        logger.warning(f"application_events fetch skipped: {e}")
        return []
