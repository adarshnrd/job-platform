"""Session health monitoring — validation, expiry detection, notifications.

Runs on a schedule via Celery Beat and on-demand before each automation task.
"""

from datetime import datetime, timezone, timedelta
from loguru import logger
from database import get_db
from services.sessions.encryption import EncryptionService
from services.sessions.audit import AuditLogger
from services.sessions.adapters.registry import get_adapter
from services.sessions.exceptions import SessionInvalidError


class SessionHealthService:
    def __init__(self, encryption: EncryptionService, audit: AuditLogger):
        self._db = get_db()
        self._encryption = encryption
        self._audit = audit

    async def validate_session(self, session_id: str) -> bool:
        """Validate a single session by calling the platform adapter's
        validate_cookies method. Updates DB and logs result.

        Returns True if valid, False if invalid/expired.
        """
        result = (
            self._db.table("platform_sessions")
            .select("*")
            .eq("id", session_id)
            .maybe_single()
            .execute()
        )
        if not (result and result.data):
            return False

        session = result.data

        if session["status"] != "active":
            return False

        if self._is_expired(session):
            self._mark_expired(session)
            return False

        adapter = get_adapter(session["platform"])
        if adapter is None:
            logger.warning(f"No adapter for platform {session['platform']}")
            return False

        try:
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
        except Exception as e:
            logger.error(f"Failed to decrypt session {session_id}: {e}")
            self._mark_invalid(session, f"Decryption failed: {e}")
            return False

        try:
            vr = await adapter.validate_cookies(cookies, metadata)
        except Exception as e:
            logger.error(f"Validation call failed for {session_id}: {e}")
            self._audit.log(
                "validation_failed", session["user_id"], session["platform"],
                session_id=session_id,
                metadata={"error": str(e)},
            )
            return False

        now = datetime.now(timezone.utc).isoformat()
        if vr.valid:
            self._db.table("platform_sessions").update({
                "last_validated_at": now,
            }).eq("id", session_id).execute()
            self._audit.log(
                "session_validated", session["user_id"], session["platform"],
                session_id=session_id,
            )
            return True
        else:
            self._mark_invalid(session, vr.reason)
            return False

    def check_expiry(self, session_id: str) -> bool:
        """Quick plaintext check — no network call, no decryption."""
        result = (
            self._db.table("platform_sessions")
            .select("status, expires_at")
            .eq("id", session_id)
            .maybe_single()
            .execute()
        )
        if not (result and result.data):
            return True
        return self._is_expired(result.data)

    async def run_scheduled_health_checks(self) -> dict:
        """Validate all active sessions not checked in the last 12 hours.
        Called by Celery Beat every 6 hours.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()

        result = (
            self._db.table("platform_sessions")
            .select("id, user_id, platform")
            .eq("status", "active")
            .or_(f"last_validated_at.is.null,last_validated_at.lt.{cutoff}")
            .execute()
        )
        sessions = result.data or []
        stats = {"checked": 0, "valid": 0, "invalid": 0, "errors": 0}

        for session in sessions:
            stats["checked"] += 1
            try:
                is_valid = await self.validate_session(session["id"])
                if is_valid:
                    stats["valid"] += 1
                else:
                    stats["invalid"] += 1
                    self._send_reauth_notification(session["user_id"], session["platform"])
            except Exception as e:
                stats["errors"] += 1
                logger.error(f"Health check error for session {session['id']}: {e}")

        logger.info(f"Session health check complete: {stats}")
        return stats

    def _is_expired(self, session: dict) -> bool:
        if session.get("status") in ("expired", "invalid", "revoked"):
            return True
        expires_at = session.get("expires_at")
        if not expires_at:
            return True
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return expires_at <= datetime.now(timezone.utc)

    def _mark_expired(self, session: dict) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._db.table("platform_sessions").update({
            "status": "expired",
            "invalidated_at": now,
            "invalidation_reason": "Session TTL exceeded",
        }).eq("id", session["id"]).execute()
        self._audit.log(
            "session_expired", session["user_id"], session["platform"],
            session_id=session["id"],
        )
        self._send_reauth_notification(session["user_id"], session["platform"])

    def _mark_invalid(self, session: dict, reason: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._db.table("platform_sessions").update({
            "status": "invalid",
            "invalidated_at": now,
            "invalidation_reason": reason[:500],
        }).eq("id", session["id"]).execute()
        self._audit.log(
            "session_invalidated", session["user_id"], session["platform"],
            session_id=session["id"],
            metadata={"reason": reason[:500]},
        )
        self._send_reauth_notification(session["user_id"], session["platform"])

    def _send_reauth_notification(self, user_id: str, platform: str) -> None:
        """Send in-app + email notification that the session needs refresh."""
        try:
            user_res = self._db.table("users").select("email").eq("id", user_id).maybe_single().execute()
            user_email = user_res.data.get("email", "") if (user_res and user_res.data) else ""

            from services.notification_service import notify_session_expired
            notify_session_expired(user_id, user_email, platform)
        except Exception as e:
            logger.warning(f"Failed to send reauth notification: {e}")
            try:
                self._db.table("notifications").insert({
                    "user_id": user_id,
                    "type": "session_expired",
                    "title": f"{platform.title()} session expired",
                    "body": f"Your {platform.title()} session has expired. Auto-apply is paused for {platform.title()} jobs. Please re-authenticate.",
                    "action_url": "/settings",
                    "payload": {"platform": platform, "action": "reauth"},
                }).execute()
            except Exception:
                pass
