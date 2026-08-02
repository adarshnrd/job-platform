"""In-process job scheduler — replaces Celery + Redis.

Uses APScheduler's BackgroundScheduler with a thread pool executor.
Discovery and apply tasks use asyncio.run() internally, so they run in
threads (not on the FastAPI event loop). Lightweight tasks (notifications,
health checks) run in threads too for simplicity.

Started/stopped via the FastAPI lifespan in main.py.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger
from config import settings


scheduler = BackgroundScheduler(
    timezone="Asia/Kolkata",
    job_defaults={
        "coalesce": True,
        "max_instances": 1,
        "misfire_grace_time": 300,
    },
)


def _run_discovery_all_users():
    """Discover jobs for every user who hasn't opted out of scheduled discovery.

    `auto_discovery_enabled` defaults TRUE (see migration 07); a user can turn it
    off to stop the background cron from spending LLM quota on their behalf while
    still browsing/discovering manually.
    """
    from database import get_supabase_admin
    from workers.job_discovery import resolve_region, run_discovery_for_user

    try:
        db = get_supabase_admin()
        try:
            users = db.table("users").select(
                "id, preferred_locations, auto_discovery_enabled, discovery_region"
            ).execute()
        except Exception:
            # Pre-migration fallback: columns may not exist yet.
            users = db.table("users").select("id, preferred_locations").execute()

        for user in (users.data or []):
            if user.get("auto_discovery_enabled") is False:
                continue
            user_id = user["id"]
            region = resolve_region(user)
            try:
                run_discovery_for_user(user_id, region, trigger="scheduled")
            except Exception as e:
                logger.error(f"Scheduled discovery failed for {user_id}: {e}")
    except Exception as e:
        logger.error(f"Scheduled discovery-all failed: {e}")


def _drain_pipeline_queue():
    """Finish post-scrape AI stages for jobs any run left behind.

    This is what makes discovery resumable: a run killed mid-parse/score (crash,
    restart, `--reload`) leaves its work in job_pipeline_items, and this tick
    completes it — no re-scraping, no user action. It runs regardless of
    DISCOVERY_SCHEDULER_ENABLED: that flag gates *starting* new scrapes, not
    finishing work already scraped.
    """
    from workers.pipeline_worker import drain_all_users
    try:
        drain_all_users()
    except Exception as e:
        logger.error(f"Pipeline drain failed: {e}")


def _process_apply_queue():
    """Drain the pending apply queue with rate-limited delays between applications.

    Groups items by (user, platform), checks daily caps, and adds randomized
    human-like delays between submissions to avoid triggering anti-bot detection.
    Also re-queues rate_limited items whose cap has reset (new day).
    """
    import time
    from collections import defaultdict
    from datetime import datetime, timezone

    from database import get_supabase_admin
    from workers.application_bot import apply_single_job
    from services import telemetry
    from services.rate_limiter import rate_limiter

    try:
        db = get_supabase_admin()

        # Re-queue rate_limited items (daily cap may have reset)
        try:
            db.table("apply_queue").update(
                {"status": "pending", "error_msg": None}
            ).eq("status", "rate_limited").execute()
        except Exception:
            pass

        pending = (
            db.table("apply_queue")
            .select("id, user_id, application_id")
            .eq("status", "pending")
            .order("priority")
            .order("created_at")
            .limit(20)
            .execute()
        )
        items = pending.data or []
        if not items:
            return

        # Look up platform for each item to enforce per-platform limits
        app_ids = [item["application_id"] for item in items]
        apps = (
            db.table("application_details")
            .select("id, source_platform")
            .in_("id", app_ids)
            .execute()
        )
        platform_map = {a["id"]: a.get("source_platform", "") for a in (apps.data or [])}

        logger.info(f"Processing {len(items)} pending apply queue items (rate-limited)")
        applied_count = 0
        batch_started = datetime.now(timezone.utc).isoformat()
        user_counts: dict[str, dict] = defaultdict(
            lambda: {"attempted": 0, "applied": 0, "rate_limited": 0, "failed": 0}
        )

        for item in items:
            platform = platform_map.get(item["application_id"], "")
            user_id = item["user_id"]
            user_counts[user_id]["attempted"] += 1

            allowed, reason = rate_limiter.can_apply(user_id, platform)
            if not allowed:
                logger.info(f"Skipping {item['id'][:8]}…: {reason}")
                user_counts[user_id]["rate_limited"] += 1
                db.table("apply_queue").update({
                    "status": "rate_limited",
                    "error_msg": reason,
                }).eq("id", item["id"]).execute()
                continue

            try:
                apply_single_job(item["id"])
                applied_count += 1
                user_counts[user_id]["applied"] += 1
            except Exception as e:
                user_counts[user_id]["failed"] += 1
                logger.error(f"Apply queue item {item['id']} failed: {e}")

            # Randomized delay before next application
            delay = rate_limiter.get_delay_seconds(platform)
            remaining = rate_limiter.remaining_today(user_id, platform)
            logger.info(
                f"Rate limiter: {remaining} applications remaining today "
                f"for {platform}, waiting {delay:.0f}s"
            )
            time.sleep(delay)

        logger.info(f"Apply queue batch done: {applied_count}/{len(items)} processed")

        batch_finished = datetime.now(timezone.utc).isoformat()
        for user_id, counts in user_counts.items():
            telemetry.record_apply_run(user_id, batch_started, batch_finished, counts)

    except Exception as e:
        logger.error(f"Apply queue drain failed: {e}")


def _send_follow_up_reminders():
    """Send follow-up reminders for stale applications."""
    from workers.notification_worker import send_follow_up_reminders_task
    try:
        send_follow_up_reminders_task()
    except Exception as e:
        logger.error(f"Scheduled follow-up reminders failed: {e}")


def _send_weekly_digest():
    """Send weekly pipeline summary."""
    from workers.notification_worker import send_weekly_digest_task
    try:
        send_weekly_digest_task()
    except Exception as e:
        logger.error(f"Scheduled weekly digest failed: {e}")


def _run_session_health_checks():
    """Validate active browser sessions."""
    from workers.session_health import run_session_health_checks
    try:
        run_session_health_checks()
    except Exception as e:
        logger.error(f"Scheduled session health check failed: {e}")


def _run_listing_revalidation():
    """Mark dead/expired job listings inactive."""
    from workers.listing_validator import run_listing_revalidation
    try:
        run_listing_revalidation()
    except Exception as e:
        logger.error(f"Scheduled listing revalidation failed: {e}")


def _run_stuck_application_recovery():
    """Reset applications orphaned mid-apply by a crash/restart."""
    from workers.application_bot import recover_stuck_applications
    try:
        recover_stuck_applications()
    except Exception as e:
        logger.error(f"Scheduled stuck-application recovery failed: {e}")


def start_scheduler():
    """Register all scheduled jobs and start the scheduler."""
    if scheduler.running:
        return

    # Automatic discovery cron is opt-in (DISCOVERY_SCHEDULER_ENABLED, default
    # False) so a restart/redeploy never starts scraping job platforms on its
    # own. Manual discovery from the UI (POST /jobs/discover) is unaffected —
    # it runs via BackgroundTasks, not this scheduler, regardless of this flag.
    if settings.DISCOVERY_SCHEDULER_ENABLED:
        scheduler.add_job(
            _run_discovery_all_users,
            CronTrigger(hour=f"*/{settings.DISCOVERY_INTERVAL_HOURS}"),
            id="discover_jobs",
            name="Job discovery for all users",
            replace_existing=True,
        )
        logger.info(f"Automatic discovery cron ARMED — every {settings.DISCOVERY_INTERVAL_HOURS}h")
    else:
        logger.info(
            "Automatic discovery cron DISABLED (DISCOVERY_SCHEDULER_ENABLED=false) — "
            "manual discovery from the UI still works normally."
        )

    # Always armed — see _drain_pipeline_queue. Without it, jobs scraped by an
    # interrupted run would sit staged and unscored until the next manual run.
    scheduler.add_job(
        _drain_pipeline_queue,
        IntervalTrigger(minutes=settings.PIPELINE_DRAIN_INTERVAL_MINUTES),
        id="pipeline_drain",
        name="Drain discovery processing queue",
        replace_existing=True,
    )

    scheduler.add_job(
        _process_apply_queue,
        IntervalTrigger(minutes=30),
        id="process_apply_queue",
        name="Process auto-apply queue",
        replace_existing=True,
    )

    scheduler.add_job(
        _send_follow_up_reminders,
        CronTrigger(hour=9, minute=0),
        id="follow_up_reminders",
        name="Follow-up reminders (daily 9 AM)",
        replace_existing=True,
    )

    scheduler.add_job(
        _send_weekly_digest,
        CronTrigger(day_of_week="mon", hour=8, minute=0),
        id="weekly_digest",
        name="Weekly digest (Monday 8 AM)",
        replace_existing=True,
    )

    scheduler.add_job(
        _run_session_health_checks,
        CronTrigger(hour=f"*/{settings.SESSION_HEALTH_CHECK_HOURS}"),
        id="session_health",
        name="Session health checks",
        replace_existing=True,
    )

    scheduler.add_job(
        _run_listing_revalidation,
        CronTrigger(hour=f"*/{settings.LISTING_REVALIDATION_HOURS}"),
        id="listing_revalidation",
        name="Revalidate active job listings",
        replace_existing=True,
    )

    scheduler.add_job(
        _run_stuck_application_recovery,
        IntervalTrigger(minutes=settings.STUCK_RECOVERY_INTERVAL_MINUTES),
        id="stuck_recovery",
        name="Recover stuck applications",
        replace_existing=True,
    )

    scheduler.start()
    jobs = scheduler.get_jobs()
    logger.info(f"Scheduler started with {len(jobs)} jobs:")
    for job in jobs:
        logger.info(f"  → {job.name} (next run: {job.next_run_time})")


def stop_scheduler():
    """Gracefully shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
