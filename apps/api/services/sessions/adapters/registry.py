"""Platform adapter registry.

New platforms: import the adapter class and add one entry to ADAPTERS.
Frontend auto-discovers supported platforms via GET /sessions/platforms.
"""

from services.sessions.adapters.base import BaseSessionAdapter
from services.sessions.adapters.linkedin import LinkedInAdapter
from services.sessions.adapters.naukri import NaukriAdapter
from services.sessions.adapters.instahyre import InstahyreAdapter
from services.sessions.adapters.foundit import FounditAdapter
from services.sessions.adapters.hirist import HiristAdapter
from services.sessions.adapters.cutshort import CutshortAdapter

ADAPTERS: dict[str, type[BaseSessionAdapter]] = {
    "linkedin": LinkedInAdapter,
    "naukri": NaukriAdapter,
    "instahyre": InstahyreAdapter,
    "foundit": FounditAdapter,
    "hirist": HiristAdapter,
    "cutshort": CutshortAdapter,
}

PLATFORM_META: dict[str, dict] = {
    "linkedin": {
        "display_name": "LinkedIn",
        "icon": "linkedin",
        "login_url": "https://www.linkedin.com/login",
        "default_session_lifetime_days": 30,
        "description": "Easy Apply and direct applications",
    },
    "naukri": {
        "display_name": "Naukri",
        "icon": "naukri",
        "login_url": "https://www.naukri.com/nlogin/login",
        "default_session_lifetime_days": 14,
        "description": "India's largest job portal",
    },
    "indeed": {
        "display_name": "Indeed",
        "icon": "indeed",
        "login_url": "https://secure.indeed.com/account/login",
        "default_session_lifetime_days": 30,
        "description": "Global job search engine",
    },
    "instahyre": {
        "display_name": "Instahyre",
        "icon": "instahyre",
        "login_url": "https://www.instahyre.com/login/",
        "default_session_lifetime_days": 30,
        "description": "Curated tech roles — 1-click apply",
    },
    "foundit": {
        "display_name": "Foundit",
        "icon": "foundit",
        "login_url": "https://www.foundit.in/seeker/login",
        "default_session_lifetime_days": 30,
        "description": "Formerly Monster India",
    },
    "hirist": {
        "display_name": "Hirist",
        "icon": "hirist",
        "login_url": "https://www.hirist.tech/login",
        "default_session_lifetime_days": 21,
        "description": "Tech-focused Indian job board",
    },
    "cutshort": {
        "display_name": "Cutshort",
        "icon": "cutshort",
        "login_url": "https://cutshort.io/login",
        "default_session_lifetime_days": 30,
        "description": "AI-matched startup roles (assessments handled manually)",
    },
}


def register_adapter(platform: str, adapter_class: type[BaseSessionAdapter]) -> None:
    ADAPTERS[platform] = adapter_class


def get_adapter(platform: str) -> BaseSessionAdapter | None:
    adapter_class = ADAPTERS.get(platform)
    if adapter_class is None:
        return None
    return adapter_class()


def list_platforms() -> list[dict]:
    """List all platforms with metadata + whether an adapter is registered."""
    platforms = []
    for name, meta in PLATFORM_META.items():
        platforms.append({
            "platform": name,
            "has_adapter": name in ADAPTERS,
            **meta,
        })
    return platforms
