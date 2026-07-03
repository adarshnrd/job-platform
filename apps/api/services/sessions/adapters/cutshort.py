"""Cutshort session adapter — authenticated apply with an assessment guard.

Cutshort frequently gates applications behind a skills assessment/evaluation.
Those must never be auto-answered — the adapter detects them and aborts so the
application is surfaced for manual handling instead.
"""
from services.sessions.adapters.simple_apply import SimpleApplyAdapter


class CutshortAdapter(SimpleApplyAdapter):
    platform_name = "cutshort"
    display_name = "Cutshort"
    icon = "cutshort"
    login_url = "https://cutshort.io/login"
    default_session_lifetime_days = 30

    cookie_domain = "cutshort.io"
    post_login_patterns = ["cutshort.io/candidate", "cutshort.io/jobs", "cutshort.io/dashboard"]
    validate_url = "https://cutshort.io/candidate/dashboard"
    apply_button_selectors = [
        'button:has-text("Apply")',
        'button:has-text("I\'m interested")',
        'button[class*="apply"]',
    ]

    _ASSESSMENT_MARKERS = [
        'text=/assessment/i',
        'text=/evaluation/i',
        'text=/take the test/i',
        'text=/skill test/i',
        'button:has-text("Start Assessment")',
    ]

    async def _pre_apply_block(self, page) -> str | None:
        if await self._any_visible(page, self._ASSESSMENT_MARKERS, timeout=1500):
            return "Cutshort assessment required — needs manual completion"
        return None
