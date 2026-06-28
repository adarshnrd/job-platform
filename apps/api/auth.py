"""Shared auth dependency — validates Supabase JWT.

Uses local HS256 verification when SUPABASE_JWT_SECRET is valid (~0ms).
Falls back to Supabase Admin API network call otherwise (~50-100ms).
Auto-detects on first request: tries local verification, if it fails
switches to Supabase API permanently for the session.
"""
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from loguru import logger
from config import settings

security = HTTPBearer()

_auth_mode: str | None = None
_jwt_secret: str | None = None

PLACEHOLDER_SECRETS = {"placeholder", "your_supabase_jwt_secret", "your_jwt_secret", ""}


def _init_auth():
    global _auth_mode, _jwt_secret
    secret = (settings.SUPABASE_JWT_SECRET or "").strip()
    if secret and secret.lower() not in PLACEHOLDER_SECRETS and not secret.startswith("your_"):
        _jwt_secret = secret
        _auth_mode = "local"
        logger.info("Auth: using local JWT verification (fast path)")
    else:
        _auth_mode = "supabase"
        logger.info("Auth: using Supabase API verification (JWT secret not configured)")


def get_user_id(creds: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """Extract and validate user ID from Supabase JWT."""
    global _auth_mode

    if _auth_mode is None:
        _init_auth()

    token = creds.credentials

    if _auth_mode == "local":
        try:
            return _verify_local(token)
        except HTTPException:
            logger.warning("Local JWT verification failed — falling back to Supabase API and switching auth mode")
            _auth_mode = "supabase"
            return _verify_via_supabase(token)

    return _verify_via_supabase(token)


def _verify_local(token: str) -> str:
    """Verify JWT signature locally — no network call."""
    try:
        payload = jwt.decode(
            token,
            _jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token: missing sub claim")
        return user_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail="Invalid token")


def _verify_via_supabase(token: str) -> str:
    """Fallback: validate via Supabase Admin API (network round-trip)."""
    try:
        from database import get_supabase_admin
        admin = get_supabase_admin()
        user = admin.auth.get_user(token)
        if not user or not user.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return user.user.id
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
