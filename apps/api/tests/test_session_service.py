"""
Tests for session service helpers, adapter registry, audit, and exceptions.

Mocks heavy deps (loguru, database, config, playwright) so tests run locally.
"""
import sys
import os
from unittest.mock import MagicMock
from datetime import datetime, timezone, timedelta

mock_config = MagicMock()
mock_config.settings = MagicMock(
    SESSION_ENCRYPTION_KEY="test-key",
    SESSION_ENCRYPTION_KEY_VERSION=1,
    PLAYWRIGHT_HEADLESS=True,
)
sys.modules.setdefault("loguru", MagicMock())
sys.modules.setdefault("database", MagicMock())
sys.modules.setdefault("config", mock_config)
sys.modules.setdefault("playwright", MagicMock())
sys.modules.setdefault("playwright.async_api", MagicMock())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestSessionServiceHelpers:
    """Tests for pure helper methods that don't need DB."""

    def test_mask_email_standard(self):
        from services.sessions.service import SessionService
        assert SessionService._mask_email("adarshvasu90@gmail.com") == "ada****@gmail.com"

    def test_mask_email_short_local(self):
        from services.sessions.service import SessionService
        assert SessionService._mask_email("ab@test.com") == "a****@test.com"

    def test_mask_email_no_at(self):
        from services.sessions.service import SessionService
        assert SessionService._mask_email("username") == "use****"

    def test_compute_health_active_far_expiry(self):
        from services.sessions.service import SessionService
        session = {
            "status": "active",
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=20)).isoformat(),
        }
        assert SessionService._compute_health(session) == "green"

    def test_compute_health_active_near_expiry(self):
        from services.sessions.service import SessionService
        session = {
            "status": "active",
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
        }
        assert SessionService._compute_health(session) == "yellow"

    def test_compute_health_expired_status(self):
        from services.sessions.service import SessionService
        session = {
            "status": "expired",
            "expires_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        }
        assert SessionService._compute_health(session) == "red"

    def test_compute_health_no_expires_at(self):
        from services.sessions.service import SessionService
        session = {"status": "active", "expires_at": None}
        assert SessionService._compute_health(session) == "red"

    def test_compute_health_invalid_status(self):
        from services.sessions.service import SessionService
        session = {"status": "invalid", "expires_at": "2030-01-01T00:00:00+00:00"}
        assert SessionService._compute_health(session) == "red"

    def test_success_rate_no_attempts(self):
        from services.sessions.service import SessionService
        session = {"success_count": 0, "failure_count": 0}
        assert SessionService._success_rate(session) == 1.0

    def test_success_rate_mixed(self):
        from services.sessions.service import SessionService
        session = {"success_count": 7, "failure_count": 3}
        assert SessionService._success_rate(session) == 0.7

    def test_success_rate_all_failures(self):
        from services.sessions.service import SessionService
        session = {"success_count": 0, "failure_count": 5}
        assert SessionService._success_rate(session) == 0.0


class TestAdapterRegistry:
    """Tests for the adapter registry."""

    def test_linkedin_adapter_registered(self):
        from services.sessions.adapters.registry import ADAPTERS, get_adapter
        assert "linkedin" in ADAPTERS
        adapter = get_adapter("linkedin")
        assert adapter is not None

    def test_naukri_adapter_registered(self):
        from services.sessions.adapters.registry import ADAPTERS, get_adapter
        assert "naukri" in ADAPTERS
        adapter = get_adapter("naukri")
        assert adapter is not None

    def test_unknown_platform_returns_none(self):
        from services.sessions.adapters.registry import get_adapter
        assert get_adapter("fakejobboard") is None

    def test_platform_meta_has_all_fields(self):
        from services.sessions.adapters.registry import PLATFORM_META
        required_fields = {"display_name", "login_url", "default_session_lifetime_days"}
        for name, meta in PLATFORM_META.items():
            missing = required_fields - set(meta.keys())
            assert not missing, f"Platform {name} missing fields: {missing}"

    def test_list_platforms_includes_all(self):
        from services.sessions.adapters.registry import list_platforms, PLATFORM_META
        platforms = list_platforms()
        assert len(platforms) == len(PLATFORM_META)
        names = {p["platform"] for p in platforms}
        assert "linkedin" in names
        assert "naukri" in names
        assert "indeed" in names

    def test_list_platforms_has_adapter_flag(self):
        from services.sessions.adapters.registry import list_platforms
        platforms = list_platforms()
        linkedin = next(p for p in platforms if p["platform"] == "linkedin")
        indeed = next(p for p in platforms if p["platform"] == "indeed")
        assert linkedin["has_adapter"] is True
        assert indeed["has_adapter"] is False


class TestExceptions:
    """Tests for exception hierarchy."""

    def test_session_not_found_carries_context(self):
        from services.sessions.exceptions import SessionNotFoundError
        err = SessionNotFoundError("No session", platform="linkedin", user_id="abc")
        assert err.platform == "linkedin"
        assert err.user_id == "abc"

    def test_session_expired_is_session_error(self):
        from services.sessions.exceptions import SessionExpiredError, SessionError
        err = SessionExpiredError("expired", platform="naukri", user_id="xyz")
        assert isinstance(err, SessionError)

    def test_encryption_error(self):
        from services.sessions.exceptions import EncryptionError, SessionError
        err = EncryptionError("bad key")
        assert isinstance(err, SessionError)
