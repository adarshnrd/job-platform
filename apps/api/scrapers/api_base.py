"""
APIBaseScraper — base class for HTTP/JSON job sources (no browser).

Modeled on the RemoteOK scraper: overrides the Playwright lifecycle so these
sources run as plain async HTTP calls. Subclasses implement `search_jobs`
and return a list of JobListingCreate.
"""
import asyncio
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse
from loguru import logger
import httpx
from scrapers.base import BaseScraper, RateLimiter

# Cloudflare also injects /cdn-cgi/challenge-platform/.../main.js into perfectly
# normal pages, so that path alone is not evidence of a wall.
_CF_MARKERS = ("cf-chl", "challenge-platform", "just a moment")


def _is_bot_challenge(status: int, text: str) -> bool:
    """True when a response is a Cloudflare interstitial rather than the page.

    The wall is served as 403/503 with a challenge page; a 200 counts only when
    it carries the challenge form token ("cf-chl") or the interstitial title.
    """
    low = text.lower()
    if status in (403, 503):
        return any(m in low for m in _CF_MARKERS)
    return "cf-chl" in low or "<title>just a moment" in low


class APIBaseScraper(BaseScraper):
    """HTTP-only job source. No Chromium — overrides the browser lifecycle."""

    # Subclasses override these.
    requires_key: bool = False          # True → registry skips when key absent
    regions: set[str] = {"global"}      # which regions this source serves
    rate_limit_per_minute: int = 30
    # Opt-in: give every host its own `rate_limit_per_minute` budget instead of
    # one limiter shared by all hosts. For aggregators that fan out across many
    # unrelated hosts (ATS boards), so one slow/busy host doesn't throttle the rest.
    per_host_rate_limit: bool = False
    DEFAULT_HEADERS: dict = {
        "User-Agent": "Mozilla/5.0 (compatible; JobPlatformBot/1.0)",
        "Accept": "application/json",
    }

    def __init__(self):
        self.rate_limiter = RateLimiter(self.rate_limit_per_minute)
        self._host_limiters: dict[str, RateLimiter] = {}
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._seen_urls: set = set()
        self._client: Optional[httpx.AsyncClient] = None

    # ── Lifecycle: HTTP client instead of a browser ──
    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=30.0,
            headers=self.DEFAULT_HEADERS,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Helpers ──
    async def _acquire(self, url: str) -> None:
        """Wait for a rate-limit slot: the shared limiter, or the URL's host's own."""
        if not self.per_host_rate_limit:
            await self.rate_limiter.acquire()
            return
        host = urlparse(url).netloc.lower()
        limiter = self._host_limiters.get(host)
        if limiter is None:
            limiter = self._host_limiters[host] = RateLimiter(self.rate_limit_per_minute)
            self._host_locks[host] = asyncio.Lock()
        # RateLimiter.acquire() isn't safe for concurrent waiters: they would all
        # wake from the same sleep and burst. Serialise per host so the cap holds.
        async with self._host_locks[host]:
            await limiter.acquire()

    async def _get_json(self, url: str, params: Optional[dict] = None, headers: Optional[dict] = None):
        """Rate-limited GET returning parsed JSON, or None on failure."""
        await self._acquire(url)
        try:
            resp = await self._client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"[{self.platform.value}] GET {url} failed: {e}")
            return None

    async def _get_text(self, url: str, params: Optional[dict] = None, headers: Optional[dict] = None) -> Optional[str]:
        """Rate-limited GET returning the body text (HTML/XML), or None on failure.

        A Cloudflare/bot-wall challenge counts as failure: MENA boards that wall
        plain HTTP are partnership-only (docs/mena/README.md §5), never bypassed.
        DEFAULT_HEADERS sends Accept: application/json, so HTML callers should
        pass headers={"Accept": "text/html,application/xhtml+xml"}.
        """
        await self._acquire(url)
        try:
            resp = await self._client.get(url, params=params, headers=headers)
            text = resp.text
            if _is_bot_challenge(resp.status_code, text):
                logger.warning(f"[{self.platform.value}] {url} served a bot challenge — skipping")
                return None
            resp.raise_for_status()
            return text
        except Exception as e:
            logger.warning(f"[{self.platform.value}] GET {url} failed: {e}")
            return None

    async def _post_json(self, url: str, json_body: dict, headers: Optional[dict] = None):
        """Rate-limited POST returning parsed JSON, or None on failure."""
        await self._acquire(url)
        try:
            resp = await self._client.post(url, json=json_body, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"[{self.platform.value}] POST {url} failed: {e}")
            return None

    @staticmethod
    def parse_posted_at(value) -> Optional[datetime]:
        """Parse a source posting date (ISO string or unix epoch) into datetime."""
        if value is None or value == "":
            return None
        try:
            if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
                return datetime.utcfromtimestamp(int(value))
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None

    def _is_new(self, url: str) -> bool:
        """True if this URL hasn't been seen in this run."""
        if not url or url in self._seen_urls:
            return False
        self._seen_urls.add(url)
        return True

    # Detail is always inline in the list response for API sources.
    async def get_job_details(self, *args, **kwargs) -> dict:
        return {}
