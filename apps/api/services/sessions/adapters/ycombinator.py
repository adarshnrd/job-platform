"""Y Combinator (Work at a Startup) session adapter — authenticated intro-form apply."""
from services.sessions.adapters.simple_apply import SimpleApplyAdapter


class YCombinatorAdapter(SimpleApplyAdapter):
    platform_name = "ycombinator"
    display_name = "Y Combinator"
    icon = "ycombinator"
    login_url = "https://www.workatastartup.com/login"
    default_session_lifetime_days = 30

    cookie_domain = "workatastartup.com"
    post_login_patterns = ["workatastartup.com/jobs", "workatastartup.com/profile", "workatastartup.com/dashboard"]
    validate_url = "https://www.workatastartup.com/profile"
    apply_button_selectors = [
        'button:has-text("Apply")',
        'button:has-text("Contact")',
        'a:has-text("Apply")',
    ]
    success_selectors = [
        'div:has-text("message sent")',
        'div:has-text("Application sent")',
        'div:has-text("You have applied")',
    ]
