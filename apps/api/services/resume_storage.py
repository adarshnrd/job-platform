"""Private Supabase Storage helpers for resume files."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import uuid4

from config import settings
from database import get_supabase_admin

_SIGNED_URL_TTL_SECONDS = 60 * 15


def new_resume_storage_path(user_id: str, filename: str) -> str:
    """Generate an opaque object key; never trust a client filename as a path."""
    suffix = Path(filename).suffix.lower()
    return f"{user_id}/{uuid4().hex}{suffix}"


def storage_path_from_value(value: str | None) -> str | None:
    """Support legacy public URLs while moving the database to object paths."""
    if not value:
        return None

    value = str(value).strip()
    if not value:
        return None
    if not value.startswith(("http://", "https://")):
        return value.lstrip("/")

    path = urlparse(value).path
    bucket = settings.STORAGE_BUCKET_RESUMES
    for marker in (
        f"/storage/v1/object/public/{bucket}/",
        f"/storage/v1/object/sign/{bucket}/",
    ):
        if marker in path:
            return unquote(path.split(marker, 1)[1]).lstrip("/") or None
    return None


def create_signed_resume_url(value: str | None) -> str | None:
    """Return a short-lived URL for a stored resume, never a public URL."""
    storage_path = storage_path_from_value(value)
    if not storage_path:
        return None

    result = (
        get_supabase_admin()
        .storage.from_(settings.STORAGE_BUCKET_RESUMES)
        .create_signed_url(storage_path, _SIGNED_URL_TTL_SECONDS)
    )
    if isinstance(result, dict):
        return result.get("signedURL") or result.get("signedUrl")
    return getattr(result, "signedURL", None) or getattr(result, "signed_url", None)
