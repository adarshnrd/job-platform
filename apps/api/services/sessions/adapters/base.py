"""Abstract base class for platform session adapters.

Each supported job board implements this interface. Adapters handle only
platform-specific logic — storage, encryption, and audit are infrastructure
concerns handled by SessionService.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CapturedSession:
    """Result of a successful browser-login capture."""
    cookies: list[dict]
    user_agent: str
    viewport: dict
    platform_username: str | None = None
    platform_user_id: str | None = None
    extra_metadata: dict = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Result of a session cookie validation check."""
    valid: bool
    reason: str = ""
    platform_user_id: str | None = None
    is_auth_failure: bool = False


@dataclass
class ApplicationResult:
    """Result of a job application submission."""
    success: bool
    confirmation_id: str | None = None
    screenshot_url: str | None = None
    error: str | None = None
    is_auth_failure: bool = False
    metadata: dict = field(default_factory=dict)


class BaseSessionAdapter(ABC):
    """Platform-specific session adapter interface.

    To add a new platform:
    1. Subclass this and implement all abstract methods
    2. Register in adapters/registry.py
    3. Add the platform to the `platform` enum in schema.sql if needed
    """

    platform_name: str = ""
    login_url: str = ""
    default_session_lifetime_days: int = 30
    display_name: str = ""
    icon: str = ""

    @abstractmethod
    async def is_login_complete(self, page: Any) -> bool:
        """Check if the user has completed login (URL changed from login page).
        Called repeatedly during browser-login to detect success.

        Args:
            page: Playwright Page object
        """

    @abstractmethod
    async def capture_session(self, page: Any) -> CapturedSession:
        """Capture cookies and metadata after user completes login.
        Called once is_login_complete returns True.

        Args:
            page: Playwright Page object (authenticated)
        """

    @abstractmethod
    async def validate_cookies(self, cookies: list[dict], metadata: dict) -> ValidationResult:
        """Lightweight check that cookies are still authenticated.
        Should complete within 5 seconds — one HTTP request to a known
        authenticated endpoint.

        Args:
            cookies: list of cookie dicts from Playwright
            metadata: dict with user_agent, viewport, etc.
        """

    @abstractmethod
    async def apply_to_job(
        self,
        browser_context: Any,
        application: dict,
        form_data: dict,
        resume_path: str | None = None,
        cover_letter: str | None = None,
        screening_answerer: Any = None,
    ) -> ApplicationResult:
        """Submit one application using an authenticated browser context.

        Args:
            browser_context: Playwright BrowserContext with cookies loaded
            application: dict with job details (source_url, apply_url, etc.)
            form_data: dict with user profile fields for form filling
            resume_path: local path to resume file for upload
            cover_letter: generated cover letter text
            screening_answerer: callback(question: str) -> str for AI answers
        """
