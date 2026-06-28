"""
APIBaseScraper — base class for HTTP/JSON job sources (no browser).

Modeled on the RemoteOK scraper: overrides the Playwright lifecycle so these
sources run as plain async HTTP calls. Subclasses implement `search_jobs`
and return a list of JobListingCreate.
"""
from datetime import datetime
from typing import Optional
from loguru import logger
import httpx
from scrapers.base import BaseScraper, RateLimiter
from models.job import JobListingCreate


class APIBaseScraper(BaseScraper):
    """HTTP-only job source. No Chromium — overrides the browser lifecycle."""

    # Subclasses override these.
    requires_key: bool = False          # True → registry skips when key absent
    regions: set[str] = {"global"}      # which regions this source serves
    rate_limit_per_minute: int = 30
    DEFAULT_HEADERS: dict = {
        "User-Agent": "Mozilla/5.0 (compatible; JobPlatformBot/1.0)",
        "Accept": "application/json",
    }

    def __init__(self):
        self.rate_limiter = RateLimiter(self.rate_limit_per_minute)
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
    async def _get_json(self, url: str, params: Optional[dict] = None, headers: Optional[dict] = None):
        """Rate-limited GET returning parsed JSON, or None on failure."""
        await self.rate_limiter.acquire()
        try:
            resp = await self._client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"[{self.platform.value}] GET {url} failed: {e}")
            return None

    async def _post_json(self, url: str, json_body: dict, headers: Optional[dict] = None):
        """Rate-limited POST returning parsed JSON, or None on failure."""
        await self.rate_limiter.acquire()
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
