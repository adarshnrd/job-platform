"""Session management exceptions."""


class SessionError(Exception):
    """Base exception for session operations."""

    def __init__(self, message: str, platform: str = "", user_id: str = ""):
        self.platform = platform
        self.user_id = user_id
        super().__init__(message)


class SessionNotFoundError(SessionError):
    """No session exists for this user/platform combination."""
    pass


class SessionExpiredError(SessionError):
    """Session exists but has expired."""
    pass


class SessionInvalidError(SessionError):
    """Session exists but failed validation (cookies rejected by platform)."""
    pass


class HandshakeTimeoutError(SessionError):
    """Browser login handshake timed out (user did not complete login)."""
    pass


class EncryptionError(SessionError):
    """Failed to encrypt or decrypt session data."""
    pass
