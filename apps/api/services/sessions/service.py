"""Central session management service.

This is the ONLY entry point automation code uses to access browser sessions.
Never query platform_sessions directly — always go through SessionService.
"""

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import AsyncIterator

from loguru import logger
from playwright.async_api import async_playwright, BrowserContext

from config import settings
from database import get_db
from services.sessions.encryption import EncryptionService
from services.sessions.audit import AuditLogger
from services.sessions.health import SessionHealthService
from services.sessions.adapters.registry import get_adapter, PLATFORM_META
from services.sessions.exceptions import (
    SessionNotFoundError,
    SessionExpiredError,
    SessionInvalidError,
)


class AuthenticatedContext:
    """Wraps a Playwright BrowserContext with session metadata."""

    def __init__(self, browser_context: BrowserContext, session_id: str,
                 platform: str, user_id: str):
        self.browser_context = browser_context
        self.session_id = session_id
        self.platform = platform
        self.user_id = user_id


class SessionService:
    """Public API for session management. All automation code uses this."""

    def __init__(self):
        self._db = get_db()
        master_key = getattr(settings, "SESSION_ENCRYPTION_KEY", "") or "dev-key-change-in-production"
        key_version = getattr(settings, "SESSION_ENCRYPTION_KEY_VERSION", 1)
        self._encryption = EncryptionService(master_key, version=key_version)
        self._audit = AuditLogger()
        self._health = SessionHealthService(self._encryption, self._audit)

    @property
    def encryption(self) -> EncryptionService:
        return self._encryption

    @property
    def audit(self) -> AuditLogger:
        return self._audit

    @property
    def health(self) -> SessionHealthService:
        return self._health

    def store_session(
        self,
        user_id: str,
        platform: str,
        cookies: list[dict],
        metadata: dict,
        platform_username: str | None = None,
        platform_user_id: str | None = None,
    ) -> dict:
        """Encrypt and store a newly captured session.

        If a session already exists for this user/platform, it is replaced.
        """
        cookies_ct, version = self._encryption.encrypt_json(cookies)
        metadata_ct, _ = self._encryption.encrypt_json(metadata)

        lifetime_days = PLATFORM_META.get(platform, {}).get(
            "default_session_lifetime_days", 30
        )
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=lifetime_days)

        masked_username = None
        if platform_username:
            masked_username = self._mask_email(platform_username)

        record = {
            "user_id": user_id,
            "platform": platform,
            "cookies_ciphertext": cookies_ct,
            "metadata_ciphertext": metadata_ct,
            "encryption_version": version,
            "platform_user_id": platform_user_id,
            "platform_username": masked_username,
            "status": "active",
            "captured_at": now.isoformat(),
            "last_validated_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }

        result = (
            self._db.table("platform_sessions")
            .upsert(record, on_conflict="user_id,platform")
            .execute()
        )

        session = result.data[0] if result.data else record
        session_id = session.get("id")

        self._audit.log(
            "session_created", user_id, platform,
            session_id=session_id,
            metadata={"expires_at": expires_at.isoformat()},
        )

        logger.info(f"Session stored for user {user_id[:8]}… on {platform} (expires {expires_at.date()})")
        return session

    def get_status(self, user_id: str, platform: str) -> dict:
        """Get session status for dashboard display. No decryption."""
        result = (
            self._db.table("platform_sessions")
            .select(
                "id, platform, status, platform_username, "
                "captured_at, last_validated_at, last_used_at, expires_at, "
                "use_count, success_count, failure_count"
            )
            .eq("user_id", user_id)
            .eq("platform", platform)
            .maybe_single()
            .execute()
        )

        if not (result and result.data):
            meta = PLATFORM_META.get(platform, {})
            return {
                "platform": platform,
                "display_name": meta.get("display_name", platform.title()),
                "status": "not_connected",
                "health": "red",
            }

        session = result.data
        health = self._compute_health(session)

        return {
            "platform": platform,
            "display_name": PLATFORM_META.get(platform, {}).get("display_name", platform.title()),
            "status": session["status"],
            "masked_username": session.get("platform_username"),
            "captured_at": session.get("captured_at"),
            "expires_at": session.get("expires_at"),
            "last_used_at": session.get("last_used_at"),
            "last_validated_at": session.get("last_validated_at"),
            "use_count": session.get("use_count", 0),
            "success_rate": self._success_rate(session),
            "health": health,
        }

    def list_user_sessions(self, user_id: str) -> list[dict]:
        """All platforms for a user — for dashboard/settings display."""
        result = (
            self._db.table("platform_sessions")
            .select(
                "id, platform, status, platform_username, "
                "captured_at, last_validated_at, last_used_at, expires_at, "
                "use_count, success_count, failure_count"
            )
            .eq("user_id", user_id)
            .execute()
        )

        connected = {s["platform"]: s for s in (result.data or [])}
        sessions = []

        for platform_name, meta in PLATFORM_META.items():
            if platform_name in connected:
                session = connected[platform_name]
                sessions.append({
                    "platform": platform_name,
                    "display_name": meta.get("display_name", platform_name.title()),
                    "status": session["status"],
                    "masked_username": session.get("platform_username"),
                    "captured_at": session.get("captured_at"),
                    "expires_at": session.get("expires_at"),
                    "last_used_at": session.get("last_used_at"),
                    "last_validated_at": session.get("last_validated_at"),
                    "use_count": session.get("use_count", 0),
                    "success_rate": self._success_rate(session),
                    "health": self._compute_health(session),
                })
            else:
                sessions.append({
                    "platform": platform_name,
                    "display_name": meta.get("display_name", platform_name.title()),
                    "status": "not_connected",
                    "health": "red",
                })

        return sessions

    @asynccontextmanager
    async def get_authenticated_context(
        self, user_id: str, platform: str
    ) -> AsyncIterator[AuthenticatedContext]:
        """Yields a Playwright BrowserContext with session cookies loaded.

        Validates the session before returning. Updates last_used_at and
        use_count. Raises SessionExpiredError / SessionInvalidError on failure.
        """
        session = self._load_session_record(user_id, platform)

        if session["status"] != "active":
            raise SessionInvalidError(
                f"Session is {session['status']}",
                platform=platform, user_id=user_id,
            )

        if self._health._is_expired(session):
            self._health._mark_expired(session)
            raise SessionExpiredError(
                "Session has expired", platform=platform, user_id=user_id,
            )

        cookies = self._encryption.decrypt_json(
            session["cookies_ciphertext"],
            session.get("encryption_version"),
        )
        metadata = {}
        if session.get("metadata_ciphertext"):
            metadata = self._encryption.decrypt_json(
                session["metadata_ciphertext"],
                session.get("encryption_version"),
            )

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=settings.PLAYWRIGHT_HEADLESS)
            context = await browser.new_context(
                user_agent=metadata.get("user_agent"),
                viewport=metadata.get("viewport"),
            )
            await context.add_cookies(cookies)

            now = datetime.now(timezone.utc).isoformat()
            self._db.table("platform_sessions").update({
                "last_used_at": now,
                "use_count": session.get("use_count", 0) + 1,
            }).eq("id", session["id"]).execute()

            try:
                yield AuthenticatedContext(
                    browser_context=context,
                    session_id=session["id"],
                    platform=platform,
                    user_id=user_id,
                )
            finally:
                await browser.close()

    def record_application_result(
        self, session_id: str, success: bool, is_auth_failure: bool = False
    ) -> None:
        """Update session usage counters after an application attempt."""
        result = (
            self._db.table("platform_sessions")
            .select("success_count, failure_count, user_id, platform")
            .eq("id", session_id)
            .maybe_single()
            .execute()
        )
        if not (result and result.data):
            return

        session = result.data
        updates: dict = {}
        if success:
            updates["success_count"] = session.get("success_count", 0) + 1
        else:
            updates["failure_count"] = session.get("failure_count", 0) + 1
            if is_auth_failure:
                updates["status"] = "invalid"
                updates["invalidated_at"] = datetime.now(timezone.utc).isoformat()
                updates["invalidation_reason"] = "Auth failure during application"

        self._db.table("platform_sessions").update(updates).eq("id", session_id).execute()

        if is_auth_failure:
            self._audit.log(
                "session_invalidated",
                session["user_id"], session["platform"],
                session_id=session_id,
                metadata={"reason": "Auth failure during application"},
            )
            self._health._send_reauth_notification(session["user_id"], session["platform"])

    def revoke(self, user_id: str, platform: str) -> dict:
        """User-initiated disconnect. Deletes session + logs event."""
        result = (
            self._db.table("platform_sessions")
            .select("id")
            .eq("user_id", user_id)
            .eq("platform", platform)
            .maybe_single()
            .execute()
        )
        session_id = result.data["id"] if (result and result.data) else None

        self._db.table("platform_sessions").delete().eq(
            "user_id", user_id
        ).eq("platform", platform).execute()

        self._audit.log(
            "session_revoked", user_id, platform,
            session_id=session_id,
            metadata={"action": "user_disconnect"},
        )
        logger.info(f"Session revoked for user {user_id[:8]}… on {platform}")
        return {"status": "revoked", "platform": platform}

    # -- Handshake management (browser-login flow) --

    def create_handshake(self, user_id: str, platform: str) -> dict:
        """Start a browser-login flow. Returns handshake token for polling."""
        token = str(uuid.uuid4())
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()

        result = (
            self._db.table("auth_handshakes")
            .insert({
                "handshake_token": token,
                "user_id": user_id,
                "platform": platform,
                "status": "pending",
                "expires_at": expires_at,
            })
            .execute()
        )

        return {
            "handshake_token": token,
            "platform": platform,
            "status": "pending",
            "expires_at": expires_at,
            "poll_url": f"/api/v1/sessions/handshake/{token}",
        }

    def get_handshake_status(self, token: str, user_id: str) -> dict | None:
        """Poll the current state of a handshake."""
        result = (
            self._db.table("auth_handshakes")
            .select("*")
            .eq("handshake_token", token)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        if not (result and result.data):
            return None
        return result.data

    def update_handshake(self, token: str, status: str, **kwargs) -> None:
        """Update handshake status during browser-login flow."""
        updates = {"status": status}
        if status in ("completed", "failed", "timeout"):
            updates["completed_at"] = datetime.now(timezone.utc).isoformat()
        updates.update(kwargs)
        self._db.table("auth_handshakes").update(updates).eq(
            "handshake_token", token
        ).execute()

    # -- Internal helpers --

    def _load_session_record(self, user_id: str, platform: str) -> dict:
        result = (
            self._db.table("platform_sessions")
            .select("*")
            .eq("user_id", user_id)
            .eq("platform", platform)
            .maybe_single()
            .execute()
        )
        if not (result and result.data):
            raise SessionNotFoundError(
                f"No session for {platform}",
                platform=platform, user_id=user_id,
            )
        return result.data

    @staticmethod
    def _mask_email(email: str) -> str:
        if "@" not in email:
            return email[:3] + "****"
        local, domain = email.split("@", 1)
        if len(local) <= 3:
            return local[0] + "****@" + domain
        return local[:3] + "****@" + domain

    @staticmethod
    def _compute_health(session: dict) -> str:
        status = session.get("status", "")
        if status != "active":
            return "red"
        expires_at = session.get("expires_at")
        if not expires_at:
            return "red"
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        remaining = expires_at - datetime.now(timezone.utc)
        if remaining <= timedelta(days=3):
            return "yellow"
        return "green"

    @staticmethod
    def _success_rate(session: dict) -> float:
        total = session.get("success_count", 0) + session.get("failure_count", 0)
        if total == 0:
            return 1.0
        return round(session.get("success_count", 0) / total, 2)
