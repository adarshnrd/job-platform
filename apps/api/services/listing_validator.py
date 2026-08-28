"""
Listing validator — determines whether a job listing is still live.

Used in two places:
  1. A scheduled revalidation job (workers/listing_validator.py) that batch-checks
     active listings and marks dead ones inactive.
  2. An apply-time preflight in the application bot, so we never burn a rate-limit
     slot applying to a job that has already closed.

Validation is intentionally conservative: a listing is only marked expired on
*positive* evidence it's gone (404/410, a redirect away from the detail page, or a
known "no longer accepting applications" marker). Network errors, timeouts, and
bot-walls leave the listing untouched — we'd rather keep a maybe-live job than
wrongly hide a good one.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from loguru import logger

from database import get_db

db = get_db()

# Per-platform markers that a listing has closed. Matched case-insensitively
# against the fetched page text. Kept short and high-precision on purpose.
EXPIRY_MARKERS: dict[str, list[str]] = {
    "linkedin": ["no longer accepting applications", "this job is no longer available"],
    "naukri": ["job you are looking for is not available", "this job has expired"],
    "indeed": ["this job has expired", "no longer available"],
    "wellfound": ["this job is no longer active", "no longer accepting applications"],
    "instahyre": ["position has been closed", "no longer accepting"],
    "foundit": ["job has expired", "position is no longer available"],
    "hirist": ["job has expired", "no longer accepting applications"],
    "glassdoor": ["this job is no longer available"],
    "_default": [
        "no longer accepting applications",
        "this job has expired",
        "position has been filled",
        "job posting has been removed",
        "position is no longer available",
    ],
}

# Redirect targets that mean "the detail page is gone" (bounced to a search/home page).
_DEAD_REDIRECT_HINTS = ("/jobs", "/search", "/home", "expired", "notfound", "not-found")

_TIMEOUT = httpx.Timeout(15.0, connect=10.0)
_MAX_REDIRECTS = 3
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    )
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _is_safe_external_url(url: str) -> bool:
    """Reject local, private, and otherwise non-public destinations before fetching."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return False

    try:
        addresses = {ipaddress.ip_address(parsed.hostname)}
    except ValueError:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                parsed.hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
            addresses = {ipaddress.ip_address(info[4][0]) for info in infos}
        except (OSError, ValueError):
            return False

    return bool(addresses) and all(
        not (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        )
        for address in addresses
    )


async def validate_listing(url: str, platform: str = "", client: httpx.AsyncClient | None = None) -> tuple[bool, str]:
    """Check whether a single job listing is still live.

    Returns (is_live, reason). is_live is True unless we have positive evidence
    the listing is gone. `reason` is a short human-readable explanation when dead,
    empty string when live.
    """
    if not url:
        return True, ""  # Nothing to check — don't touch it.

    if not await _is_safe_external_url(url):
        logger.warning(f"Listing validation skipped unsafe URL: {url[:120]}")
        return True, ""

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=False)
    try:
        try:
            final_url = url
            for _ in range(_MAX_REDIRECTS + 1):
                if not await _is_safe_external_url(final_url):
                    logger.warning(f"Listing validation blocked unsafe redirect: {final_url[:120]}")
                    return True, ""
                resp = await client.get(final_url, follow_redirects=False)
                if not resp.is_redirect:
                    break
                location = resp.headers.get("location")
                if not location:
                    break
                final_url = urljoin(final_url, location)
            else:
                return True, ""  # Too many redirects are inconclusive.
        except (httpx.TimeoutException, httpx.TransportError) as e:
            logger.debug(f"Listing check inconclusive ({url[:60]}…): {e}")
            return True, ""  # Inconclusive — leave as-is.

        if resp.status_code in (404, 410):
            return False, f"HTTP {resp.status_code} — listing removed"

        # A redirect that lands somewhere generic usually means the detail page died.
        final = final_url.lower()
        if final != url.lower():
            orig_path = re.sub(r"https?://[^/]+", "", url.lower())
            if orig_path not in final and any(h in final for h in _DEAD_REDIRECT_HINTS):
                # Only trust this if the final URL clearly isn't a job-detail page.
                if not re.search(r"/(job|jobs|jd|viewjob|opening)[-/]?\w", final):
                    return False, "Redirected away from listing — likely expired"

        if resp.status_code >= 500 or resp.status_code == 429:
            return True, ""  # Server error / rate-limited — inconclusive.

        text = resp.text.lower()
        markers = EXPIRY_MARKERS.get(platform.lower(), []) + EXPIRY_MARKERS["_default"]
        for marker in markers:
            if marker in text:
                return False, f"Marked closed on page ('{marker}')"

        return True, ""
    finally:
        if owns_client:
            await client.aclose()


def mark_expired(job_listing_id: str, reason: str) -> None:
    """Flag a listing inactive with an expiry reason. Best-effort."""
    try:
        db.table("job_listings").update({
            "is_active": False,
            "expired_at": _now_iso(),
            "expiry_reason": reason[:200],
            "last_validated_at": _now_iso(),
        }).eq("id", job_listing_id).execute()
        logger.info(f"Listing {job_listing_id[:8]}… marked expired: {reason}")
    except Exception as e:
        # Pre-migration safety: expiry columns may not exist yet.
        if "column" in str(e).lower() or "could not find" in str(e).lower():
            logger.warning("Expiry columns missing — run database/06_listing_validation.sql. Falling back to is_active only.")
            try:
                db.table("job_listings").update({"is_active": False}).eq("id", job_listing_id).execute()
            except Exception as e2:
                logger.error(f"Failed to mark listing inactive: {e2}")
        else:
            logger.error(f"Failed to mark listing expired: {e}")


def touch_validated(job_listing_id: str) -> None:
    """Record that a listing was checked and is still live."""
    try:
        db.table("job_listings").update({"last_validated_at": _now_iso()}).eq("id", job_listing_id).execute()
    except Exception:
        pass  # last_validated_at is best-effort metadata.


async def revalidate_batch(listings: list[dict], concurrency: int = 5) -> dict:
    """Validate a batch of listings with bounded concurrency.

    Each listing dict needs: id, source_url, source_platform.
    Returns {"checked": n, "expired": n, "expired_ids": [...]}.
    """
    sem = asyncio.Semaphore(concurrency)
    expired_ids: list[str] = []

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True) as client:
        async def _check(listing: dict):
            async with sem:
                url = listing.get("source_url") or ""
                platform = listing.get("source_platform") or ""
                is_live, reason = await validate_listing(url, platform, client=client)
                if not is_live:
                    mark_expired(listing["id"], reason)
                    expired_ids.append(listing["id"])
                else:
                    touch_validated(listing["id"])

        await asyncio.gather(*(_check(l) for l in listings), return_exceptions=True)

    return {"checked": len(listings), "expired": len(expired_ids), "expired_ids": expired_ids}
