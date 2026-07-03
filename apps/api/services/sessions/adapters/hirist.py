"""Hirist session adapter — authenticated 1-click apply (Info Edge tech-jobs board)."""
from services.sessions.adapters.simple_apply import SimpleApplyAdapter


class HiristAdapter(SimpleApplyAdapter):
    platform_name = "hirist"
    display_name = "Hirist"
    icon = "hirist"
    login_url = "https://www.hirist.tech/login"
    default_session_lifetime_days = 21

    cookie_domain = "hirist.tech"
    post_login_patterns = ["hirist.tech/job", "hirist.tech/dashboard", "hirist.tech/profile"]
    validate_url = "https://www.hirist.tech/profile"
    apply_button_selectors = [
        'button:has-text("Apply")',
        'a:has-text("Apply")',
        'button[class*="apply"]',
    ]
