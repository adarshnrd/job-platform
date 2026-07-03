"""iimjobs session adapter — authenticated 1-click apply (Info Edge platform family)."""
from services.sessions.adapters.simple_apply import SimpleApplyAdapter


class IimjobsAdapter(SimpleApplyAdapter):
    platform_name = "iimjobs"
    display_name = "iimjobs"
    icon = "iimjobs"
    login_url = "https://www.iimjobs.com/login"
    default_session_lifetime_days = 21

    cookie_domain = "iimjobs.com"
    post_login_patterns = ["iimjobs.com/dashboard", "iimjobs.com/profile", "iimjobs.com/job"]
    validate_url = "https://www.iimjobs.com/profile"
    apply_button_selectors = [
        'button:has-text("Apply")',
        'a:has-text("Apply")',
        'button[class*="apply"]',
    ]
