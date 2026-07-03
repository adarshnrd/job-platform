"""
Application Bot Worker
Processes the apply_queue table and submits applications via session-based auth.
Uses SessionService.get_authenticated_context() instead of stored credentials.
Enforces per-platform rate limits with randomized human-like delays.
"""
import asyncio
from loguru import logger
from database import get_db
from services.ai import generate_cover_letter
from services.sessions.service import SessionService
from services.sessions.adapters.registry import get_adapter
from services.sessions.exceptions import (
    SessionNotFoundError,
    SessionExpiredError,
    SessionInvalidError,
)
from services.rate_limiter import rate_limiter
import tempfile, os

db = get_db()
session_service = SessionService()


def check_already_applied(user_id: str, job_listing_id: str) -> dict | None:
    """Check if the user has already applied to this job.

    Returns the existing application record if found, None otherwise.
    """
    try:
        result = (
            db.table("job_applications")
            .select("id, status, applied_at, application_id, applied_url")
            .eq("user_id", user_id)
            .eq("job_listing_id", job_listing_id)
            .eq("status", "applied")
            .maybe_single()
            .execute()
        )
        return result.data if result.data else None
    except Exception as e:
        logger.warning(f"Duplicate check failed: {e}")
        return None


def check_already_applied_by_url(user_id: str, source_url: str) -> dict | None:
    """Check if the user has already applied via this job URL.

    Uses the application_details view to match by source_url.
    """
    try:
        result = (
            db.table("application_details")
            .select("id, status, applied_at, application_id, applied_url, source_url, apply_url")
            .eq("user_id", user_id)
            .eq("source_url", source_url)
            .eq("status", "applied")
            .maybe_single()
            .execute()
        )
        return result.data if result.data else None
    except Exception as e:
        logger.warning(f"URL-based duplicate check failed: {e}")
        return None


def recover_stuck_applications() -> dict:
    """Reset applications orphaned mid-apply by a crash/restart.

    A row left in 'applying' with no applied_at past the timeout means the bot
    died between marking it in-progress and recording a result. Return it to
    'matched' and its queue item to 'pending' so it retries cleanly.
    """
    from datetime import datetime, timezone, timedelta
    from config import settings

    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=settings.STUCK_APPLYING_TIMEOUT_MINUTES)
    ).isoformat()
    recovered = 0
    try:
        stuck = (
            db.table("job_applications")
            .select("id, updated_at")
            .eq("status", "applying")
            .is_("applied_at", "null")
            .lt("updated_at", cutoff)
            .execute()
        )
        for app in (stuck.data or []):
            db.table("job_applications").update({"status": "matched"}).eq("id", app["id"]).execute()
            db.table("apply_queue").update(
                {"status": "pending", "error_msg": "Recovered from stuck 'applying' state"}
            ).eq("application_id", app["id"]).eq("status", "running").execute()
            recovered += 1
        if recovered:
            logger.warning(f"Recovered {recovered} stuck application(s) from 'applying' state")
    except Exception as e:
        logger.error(f"Stuck-application recovery failed: {e}")
    return {"recovered": recovered}


def apply_single_job(queue_item_id: str):
    """Apply to a single job. Called directly via FastAPI BackgroundTasks."""
    try:
        result = asyncio.run(_apply_job_async(queue_item_id))
        return result
    except Exception as e:
        logger.error(f"Application failed for queue item {queue_item_id}: {e}")
        db.table("apply_queue").update({
            "status": "failed",
            "error_msg": str(e)[:500],
        }).eq("id", queue_item_id).execute()


async def _apply_job_async(queue_item_id: str):
    """Core application submission logic using session-based authentication."""
    queue_res = db.table("apply_queue").select("*").eq("id", queue_item_id).single().execute()
    if not queue_res.data:
        return {"success": False, "error": "Queue item not found"}

    queue_item = queue_res.data
    application_id = queue_item["application_id"]
    user_id = queue_item["user_id"]

    app_res = db.table("application_details").select("*").eq("id", application_id).single().execute()
    if not app_res.data:
        return {"success": False, "error": "Application not found"}

    app = app_res.data
    platform = app.get("source_platform", "")

    # ── Duplicate detection ──────────────────────────────────────────────
    existing = check_already_applied(user_id, app.get("job_listing_id", ""))
    if existing:
        logger.info(
            f"Already applied to {app.get('job_title')} at {app.get('job_company')} "
            f"(application {existing['id'][:8]}…) — skipping"
        )
        db.table("apply_queue").update({
            "status": "completed",
            "completed_at": "now()",
            "error_msg": "Already applied — skipped duplicate",
        }).eq("id", queue_item_id).execute()
        return {
            "success": True,
            "skipped": True,
            "reason": "already_applied",
            "existing_application_id": existing["id"],
            "applied_url": existing.get("applied_url"),
        }

    # ── Listing liveness preflight ───────────────────────────────────────
    # Don't spend a rate-limit slot on a job that has already closed.
    from services.listing_validator import validate_listing, mark_expired
    source_url = app.get("source_url", "")
    if source_url:
        is_live, live_reason = await validate_listing(source_url, platform)
        if not is_live:
            logger.info(f"Skipping apply — listing no longer live: {live_reason}")
            mark_expired(app.get("job_listing_id", ""), live_reason)
            db.table("job_applications").update({"status": "matched"}).eq("id", application_id).execute()
            db.table("apply_queue").update({
                "status": "failed",
                "error_msg": f"Listing expired: {live_reason}"[:500],
            }).eq("id", queue_item_id).execute()
            return {"success": False, "error": f"Listing expired: {live_reason}", "expired": True}

    # ── Rate limit check ─────────────────────────────────────────────────
    allowed, reason = rate_limiter.can_apply(user_id, platform)
    if not allowed:
        logger.warning(f"Rate limited: {reason}")
        # Reschedule for tomorrow by pushing next_attempt_at
        db.table("apply_queue").update({
            "status": "rate_limited",
            "error_msg": reason,
        }).eq("id", queue_item_id).execute()
        return {"success": False, "error": reason, "rate_limited": True}

    # ── Wait for minimum delay since last application ────────────────────
    wait_seconds = rate_limiter.seconds_until_ready(user_id, platform)
    if wait_seconds > 0:
        logger.info(f"Rate limiter: waiting {wait_seconds:.0f}s before applying on {platform}")
        await asyncio.sleep(wait_seconds)

    db.table("apply_queue").update({
        "status": "running",
        "attempts": queue_item["attempts"] + 1
    }).eq("id", queue_item_id).execute()

    db.table("job_applications").update({
        "status": "applying"
    }).eq("id", application_id).execute()

    user_res = db.table("users").select("*").eq("id", user_id).single().execute()
    if not user_res.data:
        return {"success": False, "error": "User not found"}

    user = user_res.data

    resume_path = await _download_resume(user_id)

    job_data = {
        "title": app.get("job_title"),
        "company": app.get("job_company"),
        "required_skills": app.get("job_required_skills", []),
        "jd_text": app.get("jd_text", ""),
    }
    resume_summary = ""
    resume_res = db.table("resumes").select("*").eq("user_id", user_id).eq("is_primary", True).maybe_single().execute()
    if resume_res and resume_res.data:
        parsed = resume_res.data.get("parsed_data", {})
        resume_summary = parsed.get("summary", "")

    cover_letter = generate_cover_letter(user, job_data, resume_summary)

    # Answer Bank resolver: fills every question it can from the profile/bank/AI,
    # and appends any genuinely unknown question to `pending_tracker` so we can
    # pause the application instead of submitting incomplete or guessed answers.
    from services.questions import build_question_resolver, QuestionService
    question_service = QuestionService()
    pending_tracker: list[dict] = []
    screening_answerer = build_question_resolver(
        user_id, user=user, job_data=job_data, application_id=application_id,
        platform=platform, pending_tracker=pending_tracker, service=question_service,
    )

    result = {"success": False, "error": "Unsupported platform"}

    try:
        adapter = get_adapter(platform)
        if adapter:
            result = await _apply_with_session(
                user_id, platform, adapter, app, user,
                resume_path, cover_letter, screening_answerer,
            )
        elif platform == "":
            result = await _apply_generic_portal(
                app, user, resume_path, cover_letter, screening_answerer,
            )
        else:
            result = {"success": False, "error": f"No adapter for platform: {platform}"}

    except (SessionNotFoundError, SessionExpiredError, SessionInvalidError) as e:
        logger.warning(f"Session auth failed for {platform}: {e}")
        result = {
            "success": False,
            "error": f"Session authentication failed: {e}. Please reconnect your {platform.title()} account.",
            "is_auth_failure": True,
        }
    finally:
        if resume_path and os.path.exists(resume_path):
            os.unlink(resume_path)

    # ── Pause for unknown questions ──────────────────────────────────────
    # If the application hit a question we couldn't answer, don't mark it applied
    # or failed — pause it as needs_input and ask the user (their answers are
    # already banked as pending_questions by the resolver).
    if pending_tracker and not result.get("skipped"):
        return _pause_for_input(
            queue_item_id, application_id, user_id, user, app, platform, pending_tracker,
        )

    # ── Record result and rate limit tracking ────────────────────────────
    if result.get("success") and not result.get("skipped"):
        rate_limiter.record_apply(user_id, platform)

    _update_application_result(
        queue_item, queue_item_id, application_id, user_id, user, app, platform, result, cover_letter,
    )

    try:
        from services.job_tracker import update_tracker
        update_tracker(user_id)
    except Exception as e:
        logger.warning(f"Job tracker update failed (non-fatal): {e}")

    return result


async def _apply_with_session(
    user_id: str,
    platform: str,
    adapter,
    app: dict,
    user: dict,
    resume_path: str | None,
    cover_letter: str,
    screening_answerer,
) -> dict:
    """Apply to a job using the session-based authenticated browser context."""
    async with session_service.get_authenticated_context(user_id, platform) as auth_ctx:
        form_data = {
            "full_name": user.get("full_name", ""),
            "email": user.get("email", ""),
            "phone": user.get("phone", ""),
            "headline": user.get("headline", ""),
            "location": user.get("location", ""),
        }

        adapter_result = await adapter.apply_to_job(
            browser_context=auth_ctx.browser_context,
            application={
                "source_url": app.get("source_url", ""),
                "apply_url": app.get("apply_url", ""),
                "job_title": app.get("job_title", ""),
                "job_company": app.get("job_company", ""),
            },
            form_data=form_data,
            resume_path=resume_path,
            cover_letter=cover_letter,
            screening_answerer=screening_answerer,
        )

        session_service.record_application_result(
            session_id=auth_ctx.session_id,
            success=adapter_result.success,
            is_auth_failure=adapter_result.is_auth_failure,
        )

        session_service.audit.log(
            "application_succeeded" if adapter_result.success else "application_failed",
            user_id, platform,
            session_id=auth_ctx.session_id,
            metadata={
                "job_title": app.get("job_title"),
                "company": app.get("job_company"),
                "confirmation_id": adapter_result.confirmation_id,
                "error": adapter_result.error,
            },
        )

        return {
            "success": adapter_result.success,
            "application_id": adapter_result.confirmation_id,
            "error": adapter_result.error,
            "is_auth_failure": adapter_result.is_auth_failure,
            "already_applied": adapter_result.metadata.get("already_applied", False),
            "applied_url": adapter_result.metadata.get("applied_url"),
        }


async def _apply_generic_portal(app, user, resume_path, cover_letter, screening_answerer):
    """Generic company career portal application using AI form detection."""
    from playwright.async_api import async_playwright

    result = {"success": False, "error": None}
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            apply_url = app.get("apply_url") or app.get("source_url")
            await page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            name_input = await page.query_selector('input[name*="name"], input[placeholder*="name"]')
            email_input = await page.query_selector('input[type="email"], input[name*="email"]')
            phone_input = await page.query_selector('input[type="tel"], input[name*="phone"]')
            file_input = await page.query_selector('input[type="file"]')

            if name_input:
                await name_input.fill(user.get("full_name", ""))
            if email_input:
                await email_input.fill(user.get("email", ""))
            if phone_input:
                await phone_input.fill(user.get("phone", ""))
            if file_input and resume_path:
                await file_input.set_input_files(resume_path)

            submit_btn = await page.query_selector('button[type="submit"], input[type="submit"]')
            if submit_btn:
                await submit_btn.click()
                await asyncio.sleep(2)
                result["success"] = True
                result["applied_url"] = apply_url

            await browser.close()
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Generic portal apply failed: {e}")

    return result


def _pause_for_input(queue_item_id, application_id, user_id, user, app, platform, pending):
    """Pause an application that hit unanswered questions.

    Sets the application to needs_input and the queue item to awaiting_input, then
    notifies the user. The unknown questions were already persisted as
    pending_questions by the resolver — the user answers them in the /answers
    inbox, which re-queues the application automatically.
    """
    count = len(pending)
    preview = "; ".join(p["question"][:60] for p in pending[:3])
    logger.info(f"Application {application_id[:8]}… paused — {count} question(s) need input: {preview}")

    db.table("job_applications").update({"status": "needs_input"}).eq("id", application_id).execute()
    db.table("apply_queue").update({
        "status": "awaiting_input",
        "error_msg": f"Waiting on {count} question(s): {preview}"[:500],
    }).eq("id", queue_item_id).execute()

    try:
        from services.notification_service import notify_input_needed
        notify_input_needed(
            user_id=user_id,
            user_email=user.get("email", ""),
            application={"id": application_id, "question_count": count},
            job={"title": app.get("job_title"), "company": app.get("job_company"), "id": app.get("job_listing_id")},
        )
    except Exception as e:
        logger.debug(f"input_needed notification skipped: {e}")

    try:
        from services.job_tracker import update_tracker
        update_tracker(user_id)
    except Exception:
        pass

    return {"success": False, "needs_input": True, "pending_count": count,
            "message": f"Paused — {count} question(s) need your answer"}


def _update_application_result(
    queue_item, queue_item_id, application_id, user_id, user, app, platform, result, cover_letter,
):
    """Update DB records based on application outcome."""
    from services.notification_service import notify_application_submitted

    if result.get("success"):
        update_data = {
            "status": "applied",
            "applied_at": "now()",
            "applied_via": "auto",
            "cover_letter": cover_letter,
            "application_id": result.get("application_id"),
        }
        if result.get("applied_url"):
            update_data["applied_url"] = result["applied_url"]

        if result.get("already_applied"):
            update_data["applied_via"] = "already_applied"

        db.table("job_applications").update(update_data).eq("id", application_id).execute()

        db.table("apply_queue").update({
            "status": "completed",
            "completed_at": "now()",
        }).eq("id", queue_item_id).execute()

        notify_application_submitted(
            user_id=user_id,
            user_email=user.get("email", ""),
            application={"id": application_id, "match_score": app.get("match_score"), "application_id": result.get("application_id")},
            job={"title": app.get("job_title"), "company": app.get("job_company"), "source_platform": platform, "id": app.get("job_listing_id")},
        )

    else:
        error_msg = result.get("error", "Unknown error")[:500]

        if result.get("rate_limited"):
            db.table("job_applications").update({
                "status": "queued",
            }).eq("id", application_id).execute()
            db.table("apply_queue").update({
                "status": "rate_limited",
                "error_msg": error_msg,
            }).eq("id", queue_item_id).execute()
            return

        db.table("job_applications").update({
            "status": "matched",
        }).eq("id", application_id).execute()

        if result.get("is_auth_failure"):
            error_msg = f"[SESSION_EXPIRED] {error_msg}"

        db.table("apply_queue").update({
            "status": "failed" if queue_item["attempts"] >= 2 else "pending",
            "error_msg": error_msg,
        }).eq("id", queue_item_id).execute()


async def _download_resume(user_id: str) -> str | None:
    """Download user's primary resume to a temp file. Returns path or None."""
    resume_res = db.table("resumes").select("*").eq("user_id", user_id).eq("is_primary", True).maybe_single().execute()
    if not (resume_res and resume_res.data):
        return None

    resume_url = resume_res.data.get("file_url", "")
    if not resume_url:
        return None

    import httpx
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(resume_url)
            if response.status_code == 200:
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                    f.write(response.content)
                    return f.name
    except Exception as e:
        logger.warning(f"Failed to download resume for user {user_id[:8]}…: {e}")
    return None
