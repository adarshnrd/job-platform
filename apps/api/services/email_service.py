"""Email notification service using Resend API."""

import resend
from datetime import datetime
from config import get_settings

settings = get_settings()
resend.api_key = settings.RESEND_API_KEY


def _html_wrapper(title: str, body: str, cta_text: str = "", cta_url: str = "") -> str:
    cta_block = f"""
    <div style="margin: 32px 0; text-align: center;">
      <a href="{cta_url}" style="
        background: #00E5CC; color: #070B18; text-decoration: none;
        padding: 12px 28px; border-radius: 6px; font-weight: 600;
        font-family: 'Outfit', sans-serif; font-size: 14px; display: inline-block;
      ">{cta_text}</a>
    </div>""" if cta_text and cta_url else ""

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600&display=swap" rel="stylesheet">
</head>
<body style="margin:0; padding:0; background:#F0F4F8;">
  <div style="max-width:580px; margin:40px auto; background:#070B18; border-radius:12px; overflow:hidden; font-family:'Outfit',sans-serif;">
    <div style="padding:24px 32px; border-bottom:1px solid #1C2333;">
      <span style="color:#00E5CC; font-weight:700; font-size:15px; letter-spacing:0.05em;">JOBPLATFORM AI</span>
    </div>
    <div style="padding:32px;">
      <h1 style="color:#F7F6F3; font-size:22px; font-weight:600; margin:0 0 16px;">{title}</h1>
      <div style="color:#94A3B8; font-size:14px; line-height:1.7;">{body}</div>
      {cta_block}
    </div>
    <div style="padding:20px 32px; border-top:1px solid #1C2333;">
      <p style="color:#475569; font-size:12px; margin:0;">
        You're receiving this because you have job automation enabled. 
        <a href="#" style="color:#00E5CC;">Manage preferences</a>
      </p>
    </div>
  </div>
</body>
</html>"""


async def send_application_submitted(
    to_email: str,
    candidate_name: str,
    job_title: str,
    company: str,
    match_score: int,
    confirmation_id: str = "",
    dashboard_url: str = "https://jobplatform.ai/dashboard"
) -> bool:
    try:
        body = f"""
        <p>Hi {candidate_name},</p>
        <p>Your application has been submitted automatically.</p>
        <table style="width:100%; border-collapse:collapse; margin:20px 0;">
          <tr>
            <td style="padding:10px; border:1px solid #1C2333; color:#94A3B8;">Position</td>
            <td style="padding:10px; border:1px solid #1C2333; color:#F7F6F3; font-weight:500;">{job_title}</td>
          </tr>
          <tr>
            <td style="padding:10px; border:1px solid #1C2333; color:#94A3B8;">Company</td>
            <td style="padding:10px; border:1px solid #1C2333; color:#F7F6F3; font-weight:500;">{company}</td>
          </tr>
          <tr>
            <td style="padding:10px; border:1px solid #1C2333; color:#94A3B8;">Match Score</td>
            <td style="padding:10px; border:1px solid #1C2333; color:#00E5CC; font-weight:600;">{match_score}%</td>
          </tr>
          {f'<tr><td style="padding:10px; border:1px solid #1C2333; color:#94A3B8;">Confirmation</td><td style="padding:10px; border:1px solid #1C2333; color:#F7F6F3;">{confirmation_id}</td></tr>' if confirmation_id else ""}
        </table>
        <p>Track your application status in the dashboard. Good luck!</p>
        """
        resend.Emails.send({
            "from": f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>",
            "to": to_email,
            "subject": f"✅ Applied to {job_title} at {company} ({match_score}% match)",
            "html": _html_wrapper(
                "Application Submitted",
                body,
                "View in Dashboard",
                dashboard_url
            )
        })
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False


async def send_new_match_alert(
    to_email: str,
    candidate_name: str,
    jobs: list[dict],
    dashboard_url: str = "https://jobplatform.ai/jobs"
) -> bool:
    try:
        jobs_html = "".join([
            f"""<div style="border:1px solid #1C2333; border-radius:8px; padding:16px; margin:12px 0;">
              <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                <div>
                  <p style="color:#F7F6F3; font-weight:600; margin:0 0 4px;">{j.get('title')}</p>
                  <p style="color:#94A3B8; margin:0 0 8px; font-size:13px;">{j.get('company')} · {j.get('location', 'Remote')}</p>
                </div>
                <span style="background:#00E5CC20; color:#00E5CC; padding:4px 10px; border-radius:4px; font-size:13px; font-weight:600;">{j.get('match_score')}%</span>
              </div>
              <div style="display:flex; gap:8px; flex-wrap:wrap;">
                {"".join([f'<span style="background:#1C2333; color:#94A3B8; padding:3px 8px; border-radius:4px; font-size:11px;">{skill}</span>' for skill in j.get('matched_skills', [])[:4]])}
              </div>
            </div>""" for j in jobs[:5]
        ])

        body = f"""
        <p>Hi {candidate_name},</p>
        <p>We found <strong style="color:#F7F6F3;">{len(jobs)} new job matches</strong> for you. High matches have been or will be applied to automatically.</p>
        {jobs_html}
        """
        resend.Emails.send({
            "from": f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>",
            "to": to_email,
            "subject": f"🎯 {len(jobs)} new job matches found",
            "html": _html_wrapper("New Job Matches", body, "View All Matches", dashboard_url)
        })
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False


async def send_weekly_digest(
    to_email: str,
    candidate_name: str,
    stats: dict,
    dashboard_url: str = "https://jobplatform.ai/analytics"
) -> bool:
    try:
        body = f"""
        <p>Hi {candidate_name}, here's your weekly job search summary:</p>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin:20px 0;">
          <div style="background:#1C2333; border-radius:8px; padding:16px; text-align:center;">
            <div style="color:#00E5CC; font-size:28px; font-weight:700;">{stats.get('applications_this_week', 0)}</div>
            <div style="color:#94A3B8; font-size:12px; margin-top:4px;">Applications</div>
          </div>
          <div style="background:#1C2333; border-radius:8px; padding:16px; text-align:center;">
            <div style="color:#F7F6F3; font-size:28px; font-weight:700;">{stats.get('responses_this_week', 0)}</div>
            <div style="color:#94A3B8; font-size:12px; margin-top:4px;">Responses</div>
          </div>
          <div style="background:#1C2333; border-radius:8px; padding:16px; text-align:center;">
            <div style="color:#F59E0B; font-size:28px; font-weight:700;">{stats.get('interviews_scheduled', 0)}</div>
            <div style="color:#94A3B8; font-size:12px; margin-top:4px;">Interviews</div>
          </div>
          <div style="background:#1C2333; border-radius:8px; padding:16px; text-align:center;">
            <div style="color:#10B981; font-size:28px; font-weight:700;">{stats.get('offers', 0)}</div>
            <div style="color:#94A3B8; font-size:12px; margin-top:4px;">Offers</div>
          </div>
        </div>
        <p style="color:#94A3B8;">Total pipeline: <strong style="color:#F7F6F3;">{stats.get('total_active', 0)} active applications</strong></p>
        """
        resend.Emails.send({
            "from": f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>",
            "to": to_email,
            "subject": f"📊 Weekly Digest — {stats.get('applications_this_week', 0)} apps, {stats.get('interviews_scheduled', 0)} interviews",
            "html": _html_wrapper("Weekly Report", body, "View Full Analytics", dashboard_url)
        })
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False
