"""Session-based authentication for job platform automation.

All automation code accesses browser sessions through SessionService — never
query platform_sessions directly.
"""

from services.sessions.service import SessionService
from services.sessions.health import SessionHealthService
from services.sessions.audit import AuditLogger
from services.sessions.encryption import EncryptionService
from services.sessions.exceptions import (
    SessionError,
    SessionNotFoundError,
    SessionExpiredError,
    SessionInvalidError,
    HandshakeTimeoutError,
)

__all__ = [
    "SessionService",
    "SessionHealthService",
    "AuditLogger",
    "EncryptionService",
    "SessionError",
    "SessionNotFoundError",
    "SessionExpiredError",
    "SessionInvalidError",
    "HandshakeTimeoutError",
]
