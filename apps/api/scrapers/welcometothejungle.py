"""
Welcome to the Jungle — European job board (formerly Otta in the UK), global.

Hybrid source: a real browser to get past the bot wall, then plain HTTP through
that browser's cookie jar for the bulk work.

Three routes were probed on 2026-07-27 before settling here:
  • The board renders results client-side, so there is no server-rendered
    listing HTML to parse.
  • `/api/v1/search/jobs` is an Algolia proxy that demands the full set of
    internal Algolia parameters and answers 500 to anything it dislikes.
  • The public sitemap plus each listing's schema.org JobPosting is stable,
    keyless and complete — but the site sits behind an AWS WAF that starts
    serving a JS challenge (HTTP 202, `gokuProps`) after a burst of plain
    httpx requests, and the block does not age out on its own.

So: Playwright loads one page to solve the challenge, which banks an
`aws-waf-token` cookie in the browser context, and every subsequent sitemap and
detail fetch goes through `context.request` — same cookies, no rendering cost.
Verified to turn 202-challenge responses into clean 200s.

What keeps the source affordable is the slug: WTTJ job URLs embed the role title
and city (`.../jobs/senior-data-engineer_london_tunrhzym`), so queries and
locations are matched against the URL and only surviving listings are fetched.
Only `/en/` listings are considered — WTTJ is French-origin and its sitemap is
majority-French, which the scoring pipeline cannot read.
"""
from __future__ import annotations

import asyncio
import gzip
import re
from typing import Optional

from loguru import logger
from playwright.async_api import Page

from models.job import JobListingCreate, Platform
from scrapers.base import BaseScraper
from scrapers.jsonld import parse_job_posting

BASE_URL = "https://www.welcometothejungle.com"
SITEMAP_INDEX = f"{BASE_URL}/sitemaps/index.xml.gz"
# Fallback warm-up target. A *listing* page is what actually triggers the WAF
# challenge script and banks the token — the /en/jobs landing page loads without
# issuing one, leaving every later fetch challenged.
WARMUP_URL = f"{BASE_URL}/en/companies"

_LOC_RE = re.compile(r"<loc>([^<]+)</loc>")
_JOB_URL_RE = re.compile(r"/en/companies/([^/]+)/jobs/([^/?#]+)")
_STOPWORDS = {
    "the", "and", "for", "with", "job", "jobs", "role", "roles", "developer",
    "engineer", "senior", "junior", "remote",
}


class WelcomeToTheJungleScraper(BaseScraper):
    platform = Platform.welcometothejungle
    rate_limit_per_minute = 30

    SHARD_LIMIT = 3          # sitemap shards scanned (≈2600 listings each)
    MAX_DETAIL_FETCHES = 20  # detail pages per search
    # The WAF tolerates a short burst then re-challenges, so fetches stay
    # near-serial and lean on re-warming rather than parallelism for throughput.
    DETAIL_CONCURRENCY = 2

    def __init__(self):
        super().__init__()
        self._job_urls: list[str] = []
        self._warmed = False
        # Serializes re-warming: without it, every in-flight fetch that hits a
        # challenge would kick off its own browser page load. `_warm_generation`
        # lets a waiter notice the token was already refreshed while it queued.
        self._warm_lock = asyncio.Lock()
        self._warm_generation = 0

    async def search_jobs(
        self,
        query: str,
        location: str = "",
        max_results: int = 30,
        credentials: Optional[dict] = None,
        region: str = "global",
    ) -> list[JobListingCreate]:
        try:
            # The sitemaps are static CDN objects and answer without a WAF
            # token, so shortlist first and warm up on a real listing — only a
            # listing page triggers the challenge script that mints the cookie.
            urls = await self._candidate_urls(query, location)
        except Exception as e:
            logger.error(f"WTTJ search failed for '{query}': {e}")
            return []

        if not urls:
            logger.info(f"WTTJ: no slug matches for '{query}' in '{location}'")
            return []

        if not await self._warm_up(target=urls[0]):
            return []

        jobs: list[JobListingCreate] = []
        semaphore = asyncio.Semaphore(self.DETAIL_CONCURRENCY)

        async def fetch(url: str):
            async with semaphore:
                return await self._fetch_listing(url)

        results = await asyncio.gather(
            *(fetch(u) for u in urls[: self.MAX_DETAIL_FETCHES]), return_exceptions=True
        )
        for result in results:
            if isinstance(result, JobListingCreate):
                jobs.append(result)
                if len(jobs) >= max_results:
                    break

        logger.info(
            f"WTTJ: returning {len(jobs)} jobs for '{query}' "
            f"({len(urls)} slug matches, {min(len(urls), self.MAX_DETAIL_FETCHES)} fetched)"
        )
        return jobs

    # ── WAF ──
    async def _warm_up(
        self, seen_generation: Optional[int] = None, target: Optional[str] = None
    ) -> bool:
        """Load a page in the browser so the WAF banks its cookie.

        Without this, every `context.request` fetch comes back as a 202 JS
        challenge with no JobPosting in it. The token also expires mid-run, so
        challenged callers re-solve it by passing the generation they saw; if
        another coroutine already refreshed while they queued on the lock, the
        generation has moved on and this returns without a second page load.
        """
        async with self._warm_lock:
            if seen_generation is None and self._warmed:
                return True
            if seen_generation is not None and seen_generation != self._warm_generation:
                return True  # someone else refreshed the token while we waited
            page = await self.new_page()
            try:
                await self.goto_with_retry(page, target or WARMUP_URL, wait_for="domcontentloaded")
                await asyncio.sleep(4)  # let the challenge script run and set the cookie
                names = {c["name"] for c in await self._context.cookies()}
                self._warm_generation += 1
                if "aws-waf-token" not in names:
                    logger.warning("WTTJ: WAF token not issued — skipping run rather than burning fetches")
                    self._warmed = False
                    return False
                self._warmed = True
                return True
            except Exception as e:
                logger.error(f"WTTJ warm-up failed: {e}")
                return False
            finally:
                await page.close()

    async def _fetch_text(self, url: str, binary: bool = False):
        """GET through the browser context so the WAF cookie travels with it.

        A 202 means the WAF re-armed its JS challenge mid-run. Re-warming in the
        browser mints a fresh token; one retry then usually succeeds.
        """
        for attempt in range(2):
            await self.rate_limiter.acquire()
            generation = self._warm_generation
            resp = await self._context.request.get(
                url,
                headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
            )
            if resp.status == 200:
                return await resp.body() if binary else await resp.text()
            if resp.status == 202 and attempt == 0:
                if not await self._warm_up(seen_generation=generation, target=url):
                    raise RuntimeError("HTTP 202 (WAF challenge, re-warm failed)")
                continue
            raise RuntimeError(f"HTTP {resp.status}")
        raise RuntimeError("HTTP 202 (WAF challenge persisted after re-warm)")

    # ── sitemap ──
    async def _load_job_urls(self) -> list[str]:
        if self._job_urls:
            return self._job_urls
        try:
            index = await self._fetch_text(SITEMAP_INDEX, binary=True)
        except Exception as e:
            logger.warning(f"WTTJ: sitemap index fetch failed: {e}")
            return []

        shards = [u for u in _LOC_RE.findall(self._maybe_gunzip(index)) if "job-listings" in u]
        if not shards:
            logger.warning("WTTJ: sitemap index carried no job-listing shards")
            return []

        urls: list[str] = []
        for shard in shards[: self.SHARD_LIMIT]:
            try:
                raw = await self._fetch_text(shard, binary=True)
            except Exception as e:
                logger.debug(f"WTTJ: shard fetch failed for {shard}: {e}")
                continue
            urls.extend(u for u in _LOC_RE.findall(self._maybe_gunzip(raw)) if "/en/companies/" in u)

        self._job_urls = urls
        logger.debug(f"WTTJ: {len(urls)} English listings from {min(len(shards), self.SHARD_LIMIT)} shard(s)")
        return urls

    @staticmethod
    def _maybe_gunzip(raw: bytes) -> str:
        """Sitemaps are .gz, but the CDN sometimes decompresses them in transit."""
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", errors="ignore")

    async def _candidate_urls(self, query: str, location: str) -> list[str]:
        """URLs whose slug matches the query (and city, when one is given).

        Slug matching is what keeps this source cheap — it avoids fetching
        detail pages for listings that cannot match.
        """
        urls = await self._load_job_urls()
        if not urls:
            return []

        tokens = [
            t for t in re.split(r"[^a-z0-9+#]+", (query or "").lower())
            if len(t) >= 3 and t not in _STOPWORDS
        ]
        city = re.sub(r"[^a-z]", "", (location or "").split(",")[0].lower())

        matches: list[str] = []
        for url in urls:
            m = _JOB_URL_RE.search(url)
            if not m:
                continue
            slug = m.group(2).lower()
            if tokens and not any(t in slug for t in tokens):
                continue
            if city and len(city) >= 3 and city not in slug.replace("-", ""):
                continue
            matches.append(url)
        return matches

    # ── detail ──
    async def _fetch_listing(self, url: str) -> Optional[JobListingCreate]:
        if self.is_seen(url):
            return None
        try:
            html = await self._fetch_text(url)
        except Exception as e:
            logger.debug(f"WTTJ: detail fetch failed for {url}: {e}")
            return None

        posting = parse_job_posting(html)
        if not posting or not posting.get("title"):
            return None

        company = posting.pop("company", None) or self._company_from_url(url)
        # Only trust salary when the posting labelled its currency — an
        # unlabelled number on a multi-country board is worse than none.
        if not posting.get("salary_currency"):
            for key in ("salary_min", "salary_max", "salary_currency"):
                posting.pop(key, None)

        fields: dict = {
            "company": company,
            "location": "Not specified",
            "jd_text": posting.get("title", ""),
            "salary_currency": "EUR",
            "source_platform": self.platform,
            "source_url": url,
            "apply_url": url,
            "source_job_id": url.rstrip("/").split("_")[-1] or None,
        }
        fields.update(posting)
        try:
            return JobListingCreate(**fields)
        except Exception as e:
            logger.debug(f"WTTJ: listing build failed for {url}: {e}")
            return None

    @staticmethod
    def _company_from_url(url: str) -> str:
        m = _JOB_URL_RE.search(url)
        slug = m.group(1) if m else ""
        return slug.replace("-", " ").title() if slug else "Company (via WTTJ)"

    async def get_job_details(self, page: Page, job_url: str) -> dict:
        try:
            html = await self._fetch_text(job_url)
            return parse_job_posting(html) or {"jd_text": ""}
        except Exception as e:
            logger.debug(f"WTTJ detail fetch failed for {job_url}: {e}")
            return {"jd_text": ""}
