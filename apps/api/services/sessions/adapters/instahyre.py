"""Instahyre session adapter — authenticated 1-click apply."""
from services.sessions.adapters.simple_apply import SimpleApplyAdapter


class InstahyreAdapter(SimpleApplyAdapter):
    platform_name = "instahyre"
    display_name = "Instahyre"
    icon = "instahyre"
    login_url = "https://www.instahyre.com/login/"
    default_session_lifetime_days = 30

    cookie_domain = "instahyre.com"
    post_login_patterns = ["instahyre.com/candidate", "instahyre.com/opportunities"]
    validate_url = "https://www.instahyre.com/candidate/opportunities/"
    apply_button_selectors = [
        'button:has-text("Apply")',
        'button:has-text("I\'m interested")',
        'button[class*="apply"]',
    ]
