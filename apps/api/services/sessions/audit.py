"""Immutable audit log for session lifecycle events.

Every session operation (create, validate, expire, revoke, use) is logged
to session_audit_events. Audit writes are fire-and-forget — they never
block the main workflow on failure.
"""

from loguru import logger
from database import get_db

VALID_EVENT_TYPES = {
    "session_created",
    "session_renewed",
    "session_validated",
    "validation_failed",
    "session_expired",
    "session_invalidated",
    "session_revoked",
    "reauth_required",
    "reauth_completed",
    "application_attempted",
    "application_succeeded",
    "application_failed",
}


class AuditLogger:
    """Fire-and-forget audit logger for session events."""

    def __init__(self):
        self._db = get_db()

    def log(
        self,
        event_type: str,
        user_id: str,
        platform: str,
        session_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        if event_type not in VALID_EVENT_TYPES:
            logger.warning(f"Unknown audit event type: {event_type}")
            return

        try:
            self._db.table("session_audit_events").insert({
                "user_id": user_id,
                "session_id": session_id,
                "platform": platform,
                "event_type": event_type,
                "metadata": metadata or {},
            }).execute()
        except Exception as e:
            logger.warning(f"Audit log write failed ({event_type}): {e}")

    def get_events(
        self,
        user_id: str,
        platform: str | None = None,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Retrieve audit events for a user. Returns newest first."""
        try:
            q = (
                self._db.table("session_audit_events")
                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(limit)
            )
            if platform:
                q = q.eq("platform", platform)
            if session_id:
                q = q.eq("session_id", session_id)
            result = q.execute()
            return result.data or []
        except Exception as e:
            logger.warning(f"Audit log read failed: {e}")
            return []
