"""Per-platform rate limiter for job applications.

Enforces daily caps and randomized human-like delays between applications
to avoid triggering anti-automation systems on job portals.
"""

import random
import threading
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from loguru import logger
from config import settings
from database import get_db


@dataclass(frozen=True)
class PlatformLimits:
    max_daily: int
    min_delay_seconds: int
    max_delay_seconds: int


_PLATFORM_LIMITS: dict[str, PlatformLimits] = {
    "linkedin": PlatformLimits(
        max_daily=settings.RATE_LIMIT_LINKEDIN_DAILY,
        min_delay_seconds=settings.RATE_LIMIT_LINKEDIN_MIN_DELAY,
        max_delay_seconds=settings.RATE_LIMIT_LINKEDIN_MAX_DELAY,
    ),
    "naukri": PlatformLimits(
        max_daily=settings.RATE_LIMIT_NAUKRI_DAILY,
        min_delay_seconds=settings.RATE_LIMIT_NAUKRI_MIN_DELAY,
        max_delay_seconds=settings.RATE_LIMIT_NAUKRI_MAX_DELAY,
    ),
}

_DEFAULT_LIMITS = PlatformLimits(
    max_daily=settings.RATE_LIMIT_DEFAULT_DAILY,
    min_delay_seconds=settings.RATE_LIMIT_DEFAULT_MIN_DELAY,
    max_delay_seconds=settings.RATE_LIMIT_DEFAULT_MAX_DELAY,
)


def get_limits(platform: str) -> PlatformLimits:
    return _PLATFORM_LIMITS.get(platform, _DEFAULT_LIMITS)


class RateLimiter:
    """Thread-safe per-platform rate limiter.

    Tracks the last application timestamp per (user, platform) to enforce
    minimum delays, and queries the DB for daily counts to enforce caps.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._last_apply: dict[str, datetime] = {}

    def _key(self, user_id: str, platform: str) -> str:
        return f"{user_id}:{platform}"

    def get_today_count(self, user_id: str, platform: str) -> int:
        """Count applications submitted today for a user on a platform."""
        db = get_db()
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()

        try:
            result = (
                db.table("job_applications")
                .select("id", count="exact")
                .eq("user_id", user_id)
                .eq("status", "applied")
                .eq("applied_via", "auto")
                .gte("applied_at", today_start)
                .execute()
            )

            if result.count is not None:
                return result.count

            # Filter by platform via the job_listings join
            apps = (
                db.table("application_details")
                .select("id")
                .eq("user_id", user_id)
                .eq("status", "applied")
                .eq("applied_via", "auto")
                .eq("source_platform", platform)
                .gte("applied_at", today_start)
                .execute()
            )
            return len(apps.data or [])
        except Exception as e:
            logger.warning(f"Rate limit count query failed: {e}")
            return 0

    def can_apply(self, user_id: str, platform: str) -> tuple[bool, str]:
        """Check if the user can apply on this platform right now.

        Returns (allowed, reason). If not allowed, reason explains why.
        """
        limits = get_limits(platform)
        today_count = self.get_today_count(user_id, platform)

        if today_count >= limits.max_daily:
            return False, (
                f"Daily limit reached for {platform}: "
                f"{today_count}/{limits.max_daily} applications today"
            )

        return True, ""

    def get_delay_seconds(self, platform: str) -> float:
        """Return a randomized delay in seconds for human-like pacing."""
        limits = get_limits(platform)
        delay = random.uniform(limits.min_delay_seconds, limits.max_delay_seconds)
        # Add extra jitter (±15%) to avoid patterns
        jitter = delay * random.uniform(-0.15, 0.15)
        return max(limits.min_delay_seconds, delay + jitter)

    def record_apply(self, user_id: str, platform: str) -> None:
        """Record that an application was just submitted (for delay tracking)."""
        key = self._key(user_id, platform)
        with self._lock:
            self._last_apply[key] = datetime.now(timezone.utc)

    def seconds_until_ready(self, user_id: str, platform: str) -> float:
        """How many seconds until the next application is allowed (delay-wise).

        Returns 0 if enough time has passed since the last application.
        """
        key = self._key(user_id, platform)
        limits = get_limits(platform)

        with self._lock:
            last = self._last_apply.get(key)

        if last is None:
            return 0

        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
        remaining = limits.min_delay_seconds - elapsed
        return max(0, remaining)

    def remaining_today(self, user_id: str, platform: str) -> int:
        """How many more applications are allowed today."""
        limits = get_limits(platform)
        return max(0, limits.max_daily - self.get_today_count(user_id, platform))


# Singleton — shared across the scheduler and API
rate_limiter = RateLimiter()
