"""
Notification service — email delivery via Resend + in-app notifications via Supabase.
"""
import resend
from loguru import logger
from config import settings
from database import get_db
from datetime import datetime

resend.api_key = settings.RESEND_API_KEY
db = get_db()


EMAIL_TEMPLATES = {
    "application_submitted": {
        "subject": "✅ Application Submitted — {job_title} at {company}",
        "body": """
<h2>Application Submitted Successfully</h2>
<p>Great news! Your application for <strong>{job_title}</strong> at <strong>{company}</strong> has been automatically submitted.</p>
<table>
  <tr><td><strong>Position:</strong></td><td>{job_title}</td></tr>
  <tr><td><strong>Company:</strong></td><td>{company}</td></tr>
  <tr><td><strong>Platform:</strong></td><td>{platform}</td></tr>
  <tr><td><strong>Match Score:</strong></td><td>{match_score}%</td></tr>
  <tr><td><strong>Applied At:</strong></td><td>{applied_at}</td></tr>
  {confirmation_row}
</table>
<p>We'll notify you of any updates. <a href="{dashboard_url}">Track your application →</a></p>
"""
    },
    "job_match": {
        "subject": "🎯 {count} New Job Match{plural} — {match_score}%+ fit",
        "body": """
<h2>New Jobs Matched to Your Profile</h2>
<p>We found <strong>{count}</strong> new job{plural} matching your profile at <strong>{match_score}%+</strong>:</p>
{job_list}
<p><a href="{dashboard_url}/jobs">View all matches →</a></p>
"""
    },
    "follow_up_reminder": {
        "subject": "⏰ Follow-up Reminder — {job_title} at {company}",
        "body": """
<h2>Time to Follow Up</h2>
<p>It's been {days} days since you applied to <strong>{job_title}</strong> at <strong>{company}</strong>.</p>
<p>Consider sending a follow-up email to check on your application status.</p>
<p><a href="{application_url}">View Application →</a></p>
"""
    },
    "offer_received": {
        "subject": "🎉 Offer Received — {job_title} at {company}!",
        "body": """
<h2>Congratulations! You've received an offer!</h2>
<p><strong>{company}</strong> has extended an offer for <strong>{job_title}</strong>.</p>
{offer_details}
<p><a href="{application_url}">Review & Respond →</a></p>
"""
    },
    "weekly_digest": {
        "subject": "📊 Your Weekly Job Search Summary",
        "body": """
<h2>Weekly Summary</h2>
<table>
  <tr><td>Applications Submitted</td><td><strong>{applied}</strong></td></tr>
  <tr><td>Under Review</td><td><strong>{under_review}</strong></td></tr>
  <tr><td>Interviews Scheduled</td><td><strong>{interviews}</strong></td></tr>
  <tr><td>Offers Received</td><td><strong>{offers}</strong></td></tr>
  <tr><td>New Matches</td><td><strong>{new_matches}</strong></td></tr>
</table>
{top_matches}
<p><a href="{dashboard_url}">Open Dashboard →</a></p>
"""
    },
    "session_expired": {
        "subject": "🔒 {platform} session expired — auto-apply paused",
        "body": """
<h2>Session Expired</h2>
<p>Your <strong>{platform}</strong> session has expired. Automatic job applications for {platform} are <strong>paused</strong> until you reconnect.</p>
<p>This is normal — job board sessions expire periodically for security. Just log back in to resume auto-apply.</p>
<p style="margin-top: 20px;">
  <a href="{settings_url}" style="background: #f59e0b; color: #000; padding: 10px 20px; border-radius: 8px; text-decoration: none; font-weight: 600;">Reconnect {platform} →</a>
</p>
<p style="font-size: 13px; color: #666; margin-top: 16px;">No passwords are stored. You'll log in through your browser and we capture the session cookies securely.</p>
"""
    }
}


def _send_email(to: str, subject: str, html: str) -> bool:
    """Send an email via Resend."""
    try:
        resend.Emails.send({
            "from": f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>",
            "to": [to],
            "subject": subject,
            "html": _wrap_email(html),
        })
        return True
    except Exception as e:
        logger.error(f"Email send failed to {to}: {e}")
        return False


def _wrap_email(body: str) -> str:
    """Wrap email body in a styled template."""
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color: #1a1a1a; background: #f5f5f5; margin: 0; padding: 20px; }}
  .container {{ max-width: 600px; margin: 0 auto; background: white; border-radius: 12px; overflow: hidden; }}
  .header {{ background: #0f172a; padding: 24px 32px; }}
  .header h1 {{ color: #f59e0b; margin: 0; font-size: 20px; font-weight: 700; letter-spacing: -0.5px; }}
  .content {{ padding: 32px; }}
  h2 {{ margin-top: 0; font-size: 22px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #f0f0f0; font-size: 14px; }}
  a {{ color: #f59e0b; font-weight: 600; }}
  .footer {{ background: #f8f8f8; padding: 20px 32px; font-size: 12px; color: #666; }}
</style>
</head>
<body>
<div class="container">
  <div class="header"><h1>⚡ JobPlatform AI</h1></div>
  <div class="content">{body}</div>
  <div class="footer">
    <p>JobPlatform AI — Your AI-powered career agent</p>
    <p>You're receiving this because you have auto-notifications enabled. 
    <a href="{settings.ALLOWED_ORIGINS[0]}/settings">Manage preferences</a></p>
  </div>
</div>
</body>
</html>"""


def _create_notification(
    user_id: str,
    notif_type: str,
    title: str,
    body: str,
    payload: dict = None,
    action_url: str = None
) -> dict:
    """Insert a notification record into Supabase."""
    try:
        result = db.table("notifications").insert({
            "user_id": user_id,
            "type": notif_type,
            "title": title,
            "body": body,
            "payload": payload or {},
            "action_url": action_url,
        }).execute()
        return result.data[0] if result.data else {}
    except Exception as e:
        logger.error(f"Failed to create notification: {e}")
        return {}


def notify_application_submitted(user_id: str, user_email: str, application: dict, job: dict):
    """Notify user that an application was auto-submitted."""
    confirmation_row = ""
    if application.get("application_id"):
        confirmation_row = f"<tr><td><strong>Confirmation ID:</strong></td><td>{application['application_id']}</td></tr>"

    template = EMAIL_TEMPLATES["application_submitted"]
    subject = template["subject"].format(
        job_title=job.get("title", ""), company=job.get("company", "")
    )
    html = template["body"].format(
        job_title=job.get("title", ""),
        company=job.get("company", ""),
        platform=job.get("source_platform", "").title(),
        match_score=application.get("match_score", 0),
        applied_at=datetime.now().strftime("%B %d, %Y at %I:%M %p"),
        confirmation_row=confirmation_row,
        dashboard_url=settings.ALLOWED_ORIGINS[0]
    )

    _send_email(user_email, subject, html)
    _create_notification(
        user_id=user_id,
        notif_type="application_submitted",
        title=f"Applied to {job.get('title')} at {job.get('company')}",
        body=f"Match score: {application.get('match_score')}%",
        payload={"application_id": str(application.get("id")), "job_id": str(job.get("id"))},
        action_url=f"{settings.ALLOWED_ORIGINS[0]}/applications/{application.get('id')}"
    )
    logger.info(f"Notified {user_email} about application to {job.get('company')}")


def notify_new_matches(user_id: str, user_email: str, matches: list):
    """Notify user about new high-scoring job matches."""
    if not matches:
        return

    job_list_html = "<ul>"
    for m in matches[:5]:
        job_list_html += f"<li><strong>{m.get('title')}</strong> at {m.get('company')} — {m.get('match_score')}% match</li>"
    job_list_html += "</ul>"

    template = EMAIL_TEMPLATES["job_match"]
    count = len(matches)
    subject = template["subject"].format(count=count, plural="es" if count > 1 else "", match_score=min(m.get("match_score", 0) for m in matches))
    html = template["body"].format(
        count=count, plural="s" if count > 1 else "",
        match_score=min(m.get("match_score", 0) for m in matches),
        job_list=job_list_html,
        dashboard_url=settings.ALLOWED_ORIGINS[0]
    )

    _send_email(user_email, subject, html)
    _create_notification(
        user_id=user_id,
        notif_type="job_match",
        title=f"{count} new job match{'es' if count > 1 else ''} found",
        body=f"Best match: {matches[0].get('title')} at {matches[0].get('company')}",
        payload={"count": count, "top_job_id": str(matches[0].get("id"))},
        action_url=f"{settings.ALLOWED_ORIGINS[0]}/jobs"
    )


def send_follow_up_reminders(user_id: str, user_email: str, applications: list):
    """Send follow-up reminders for applications with no response."""
    for app in applications:
        days_since = (datetime.now() - app.get("applied_at")).days
        template = EMAIL_TEMPLATES["follow_up_reminder"]
        subject = template["subject"].format(job_title=app.get("job_title"), company=app.get("job_company"))
        html = template["body"].format(
            days=days_since,
            job_title=app.get("job_title"),
            company=app.get("job_company"),
            application_url=f"{settings.ALLOWED_ORIGINS[0]}/applications/{app['id']}"
        )
        _send_email(user_email, subject, html)
        _create_notification(
            user_id=user_id,
            notif_type="follow_up_reminder",
            title=f"Follow-up reminder: {app.get('job_title')} at {app.get('job_company')}",
            body=f"{days_since} days since application",
            payload={"application_id": str(app["id"])},
            action_url=f"{settings.ALLOWED_ORIGINS[0]}/applications/{app['id']}"
        )


def send_weekly_digest(user_id: str, user_email: str, stats: dict, top_matches: list):
    """Send weekly pipeline digest email."""
    top_html = ""
    if top_matches:
        top_html = "<h3>Top New Matches</h3><ul>"
        for m in top_matches[:3]:
            top_html += f"<li>{m.get('title')} at {m.get('company')} — {m.get('match_score')}%</li>"
        top_html += "</ul>"

    template = EMAIL_TEMPLATES["weekly_digest"]
    subject = template["subject"]
    html = template["body"].format(
        applied=stats.get("applied", 0),
        under_review=stats.get("under_review", 0),
        interviews=stats.get("interviews", 0),
        offers=stats.get("offers", 0),
        new_matches=stats.get("new_matches", 0),
        top_matches=top_html,
        dashboard_url=settings.ALLOWED_ORIGINS[0]
    )
    _send_email(user_email, subject, html)


def notify_session_expired(user_id: str, user_email: str, platform: str):
    """Notify user that a job board session has expired and needs re-login."""
    display_name = platform.title()
    settings_url = f"{settings.ALLOWED_ORIGINS[0]}/settings"

    template = EMAIL_TEMPLATES["session_expired"]
    subject = template["subject"].format(platform=display_name)
    html = template["body"].format(
        platform=display_name,
        settings_url=settings_url,
    )

    _send_email(user_email, subject, html)
    _create_notification(
        user_id=user_id,
        notif_type="session_expired",
        title=f"{display_name} session expired",
        body=f"Your {display_name} session has expired. Auto-apply is paused. Please reconnect.",
        payload={"platform": platform, "action": "reauth"},
        action_url="/settings",
    )
    logger.info(f"Session expiry notification sent to {user_email} for {platform}")
