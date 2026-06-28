"""
Base scraper class — all platform scrapers inherit from this.
Provides Playwright browser management, rate limiting, and retry logic.
"""
import asyncio
import hashlib
import random
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from config import settings
from models.job import JobListingCreate, Platform


class ScraperError(Exception):
    pass


class RateLimiter:
    def __init__(self, max_per_minute: int):
        self.max_per_minute = max_per_minute
        self.requests: list[float] = []

    async def acquire(self):
        now = time.time()
        self.requests = [r for r in self.requests if now - r < 60]
        if len(self.requests) >= self.max_per_minute:
            sleep_time = 60 - (now - self.requests[0]) + random.uniform(1, 3)
            logger.debug(f"Rate limit hit, sleeping {sleep_time:.1f}s")
            await asyncio.sleep(sleep_time)
        self.requests.append(time.time())


def job_url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


class BaseScraper(ABC):
    platform: Platform
    rate_limit_per_minute: int = 10

    def __init__(self):
        self.rate_limiter = RateLimiter(self.rate_limit_per_minute)
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._seen_urls: set = set()

    async def __aenter__(self):
        await self._start_browser()
        return self

    async def __aexit__(self, *args):
        await self._stop_browser()

    async def _start_browser(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=settings.PLAYWRIGHT_HEADLESS,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--window-size=1366,768",
            ]
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
            java_script_enabled=True,
            locale="en-US",
        )
        # Stealth: remove webdriver property
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            window.chrome = {runtime: {}};
        """)

    async def _stop_browser(self):
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if hasattr(self, '_playwright'):
            await self._playwright.stop()

    async def new_page(self) -> Page:
        page = await self._context.new_page()
        page.set_default_timeout(settings.BROWSER_TIMEOUT_MS)
        return page

    async def goto_with_retry(self, page: Page, url: str, wait_for: str = "networkidle"):
        await self.rate_limiter.acquire()
        await asyncio.sleep(random.uniform(0.5, 2.0))  # Human-like delay
        await page.goto(url, wait_until=wait_for, timeout=settings.BROWSER_TIMEOUT_MS)

    async def human_type(self, page: Page, selector: str, text: str):
        """Type text character by character with random delays."""
        await page.click(selector)
        await page.fill(selector, "")
        for char in text:
            await page.type(selector, char, delay=random.randint(50, 150))
        await asyncio.sleep(random.uniform(0.3, 0.8))

    def is_seen(self, url: str) -> bool:
        h = job_url_hash(url)
        if h in self._seen_urls:
            return True
        self._seen_urls.add(h)
        return False

    @abstractmethod
    async def search_jobs(
        self,
        query: str,
        location: str = "",
        max_results: int = 50,
        credentials: Optional[dict] = None
    ) -> list[JobListingCreate]:
        """Search for jobs and return structured listings."""
        pass

    @abstractmethod
    async def get_job_details(self, page: Page, job_url: str) -> dict:
        """Fetch full JD and metadata for a single job URL."""
        pass

    def _clean_text(self, text: str) -> str:
        """Clean scraped text."""
        if not text:
            return ""
        import re
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    @staticmethod
    def parse_relative_date(text: str) -> datetime | None:
        """Parse 'Posted X days/hours ago', 'Just now', 'Today', etc. into a datetime."""
        if not text:
            return None
        text = text.lower().strip()
        now = datetime.utcnow()

        if "just now" in text or "moment" in text:
            return now
        if text in ("today", "just posted"):
            return now

        import re as _re
        m = _re.search(r"(\d+)\s*(second|minute|hour|day|week|month)", text)
        if not m:
            return None

        n = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("second"):
            return now - timedelta(seconds=n)
        if unit.startswith("minute"):
            return now - timedelta(minutes=n)
        if unit.startswith("hour"):
            return now - timedelta(hours=n)
        if unit.startswith("day"):
            return now - timedelta(days=n)
        if unit.startswith("week"):
            return now - timedelta(weeks=n)
        if unit.startswith("month"):
            return now - timedelta(days=n * 30)
        return None
