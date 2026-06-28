"""Scheduled notification tasks — plain functions invoked by APScheduler."""
from datetime import datetime, timedelta
from loguru import logger
from database import get_supabase_admin
from services.notification_service import send_follow_up_reminders, send_weekly_digest
from services.ai_service import generate_follow_up_email


def send_follow_up_reminders_task():
    """Send follow-up reminders for applications with no response for 7 days."""
    try:
        db = get_supabase_admin()
        seven_days_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        stale_apps = db.table("application_details")\
            .select("*")\
            .eq("status", "applied")\
            .lt("applied_at", seven_days_ago)\
            .is_("follow_up_at", "null")\
            .execute()

        by_user: dict = {}
        for app in (stale_apps.data or []):
            uid = app["user_id"]
            by_user.setdefault(uid, []).append(app)

        for user_id, apps in by_user.items():
            user_res = db.table("users").select("*").eq("id", user_id).single().execute()
            if not user_res.data:
                continue
            user = user_res.data
            send_follow_up_reminders(user_id, user["email"], apps)

            for app in apps:
                days_since = (datetime.utcnow() - datetime.fromisoformat(
                    app.get("applied_at", datetime.utcnow().isoformat())
                )).days if app.get("applied_at") else 7
                try:
                    draft = generate_follow_up_email(
                        user_profile=user,
                        job={"title": app.get("job_title"), "company": app.get("job_company")},
                        days_since_applied=days_since,
                    )
                    db.table("notifications").insert({
                        "user_id": user_id,
                        "type": "follow_up_reminder",
                        "title": f"Follow-up draft ready — {app.get('job_title')} at {app.get('job_company')}",
                        "body": draft.get("subject", ""),
                        "payload": {"draft_subject": draft.get("subject"), "draft_body": draft.get("body"), "application_id": str(app["id"])},
                        "action_url": f"/applications/{app['id']}",
                    }).execute()
                except Exception as e:
                    logger.error(f"Follow-up draft generation failed for app {app['id']}: {e}")

                db.table("job_applications").update({
                    "follow_up_at": datetime.utcnow().isoformat()
                }).eq("id", app["id"]).execute()

        logger.info(f"Follow-up reminders processed for {len(by_user)} users")
    except Exception as e:
        logger.error(f"Follow-up reminder task failed: {e}")


def send_weekly_digest_task():
    """Send weekly pipeline summary to all users."""
    try:
        db = get_supabase_admin()
        users = db.table("users").select("id,email").execute()
        for user in (users.data or []):
            user_id = user["id"]
            try:
                one_week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
                apps = db.table("job_applications").select("status")\
                    .eq("user_id", user_id).execute()

                status_counts: dict = {}
                for app in (apps.data or []):
                    s = app["status"]
                    status_counts[s] = status_counts.get(s, 0) + 1

                new_matches = db.table("application_details")\
                    .select("job_title,job_company,match_score")\
                    .eq("user_id", user_id)\
                    .eq("status", "matched")\
                    .gte("created_at", one_week_ago)\
                    .order("match_score", desc=True)\
                    .limit(5).execute()

                stats = {
                    "applied": status_counts.get("applied", 0),
                    "under_review": status_counts.get("under_review", 0),
                    "interviews": status_counts.get("interview_scheduled", 0) + status_counts.get("technical_round", 0) + status_counts.get("hr_round", 0),
                    "offers": status_counts.get("offer_received", 0),
                    "new_matches": len(new_matches.data or []),
                }
                send_weekly_digest(user_id, user["email"], stats, new_matches.data or [])
            except Exception as e:
                logger.error(f"Weekly digest failed for user {user_id}: {e}")

        logger.info(f"Weekly digest sent to {len(users.data or [])} users")
    except Exception as e:
        logger.error(f"Weekly digest task failed: {e}")
