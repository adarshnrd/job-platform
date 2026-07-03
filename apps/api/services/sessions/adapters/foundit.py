"""Foundit (formerly Monster India) session adapter — authenticated 1-click apply."""
from services.sessions.adapters.simple_apply import SimpleApplyAdapter


class FounditAdapter(SimpleApplyAdapter):
    platform_name = "foundit"
    display_name = "Foundit"
    icon = "foundit"
    login_url = "https://www.foundit.in/seeker/login"
    default_session_lifetime_days = 30

    cookie_domain = "foundit.in"
    post_login_patterns = ["foundit.in/seeker", "foundit.in/dashboard"]
    validate_url = "https://www.foundit.in/seeker/profile"
    apply_button_selectors = [
        'button:has-text("Apply")',
        'a:has-text("Apply")',
        'button[class*="apply"]',
    ]
