"""
We Work Remotely — remote-only board, global.

The HTML board is Cloudflare-fronted, but the per-category RSS feeds are public
and complete, so this stays an HTTP source. Feeds are fetched concurrently and
merged; each carries the full JD in its <description>, so no detail fetch is
needed.

Titles follow "Company: Role Title" (older items use "Company | Role"), which
is the only place the employer name appears in the feed.
"""
from __future__ import annotations

import asyncio
import html as html_lib
import re
import xml.etree.ElementTree as ET
from typing import Optional

from loguru import logger

from models.job import JobListingCreate, JobType, Platform, WorkMode
from scrapers.api_base import APIBaseScraper

BASE = "https://weworkremotely.com"
RSS_FEEDS = (
    f"{BASE}/categories/remote-programming-jobs.rss",
    f"{BASE}/categories/remote-devops-sysadmin-jobs.rss",
    f"{BASE}/categories/remote-design-jobs.rss",
    f"{BASE}/categories/remote-product-jobs.rss",
    f"{BASE}/categories/remote-customer-support-jobs.rss",
    f"{BASE}/categories/remote-sales-and-marketing-jobs.rss",
    f"{BASE}/categories/remote-management-and-finance-jobs.rss",
    f"{BASE}/remote-jobs.rss",
)

_HTML = re.compile(r"<[^>]+>")
_STOPWORDS = {"the", "and", "for", "with", "job", "jobs", "role", "roles"}
_JOB_TYPES: dict[str, JobType] = {
    "contract": JobType.contract, "contractor": JobType.contract,
    "freelance": JobType.freelance,
    "part-time": JobType.part_time, "part time": JobType.part_time,
    "internship": JobType.internship, "intern": JobType.internship,
}


class WeWorkRemotelyScraper(APIBaseScraper):
    platform = Platform.weworkremotely
    requires_key = False
    regions = {"global"}
    rate_limit_per_minute = 12

    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (compatible; JobPlatformBot/1.0)",
        "Accept": "application/rss+xml, application/xml, text/xml",
    }

    async def search_jobs(
        self,
        query: str,
        location: str = "Remote",
        max_results: int = 50,
        credentials: Optional[dict] = None,
        region: str = "global",
    ) -> list[JobListingCreate]:
        tokens = [
            t for t in re.split(r"[^a-z0-9.+#]+", (query or "").lower())
            if len(t) >= 2 and t not in _STOPWORDS
        ]

        feeds = await asyncio.gather(
            *(self._fetch_feed(url) for url in RSS_FEEDS), return_exceptions=True
        )

        jobs: list[JobListingCreate] = []
        for feed in feeds:
            if not isinstance(feed, str) or not feed:
                continue
            try:
                root = ET.fromstring(feed)
            except ET.ParseError as e:
                logger.debug(f"WWR: feed parse failed: {e}")
                continue

            for item in root.findall(".//item"):
                job = self._to_listing(item, tokens)
                if job:
                    jobs.append(job)
                    if len(jobs) >= max_results:
                        logger.info(f"WWR: returning {len(jobs)} jobs for '{query}'")
                        return jobs

        logger.info(f"WWR: returning {len(jobs)} jobs for '{query}'")
        return jobs

    async def _fetch_feed(self, url: str) -> str:
        await self.rate_limiter.acquire()
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            logger.debug(f"WWR: feed fetch failed for {url}: {e}")
            return ""

    def _to_listing(self, item: ET.Element, tokens: list[str]) -> Optional[JobListingCreate]:
        def text_of(tag: str) -> str:
            el = item.find(tag)
            return (el.text or "").strip() if el is not None and el.text else ""

        raw_title = text_of("title")
        url = text_of("link")
        if not raw_title or not url:
            return None

        description = html_lib.unescape(text_of("description"))
        jd = self._clean_text(_HTML.sub(" ", description))

        if tokens and not any(t in f"{raw_title} {jd}".lower() for t in tokens):
            return None
        if not self._is_new(url):
            return None

        company, title = self._split_title(raw_title)
        blob = f"{raw_title} {jd}".lower()

        return JobListingCreate(
            title=title,
            company=company,
            location=text_of("region") or "Worldwide",
            work_mode=WorkMode.remote,
            is_remote_friendly=True,
            job_type=self.match_terms(blob, _JOB_TYPES, JobType.full_time),
            salary_currency="USD",
            jd_text=jd or f"{title} at {company}.",
            source_platform=self.platform,
            source_url=url,
            apply_url=url,
            source_job_id=url.rstrip("/").split("/")[-1] or None,
            posted_at=self._parse_pubdate(text_of("pubDate")),
        )

    @staticmethod
    def _split_title(raw: str) -> tuple[str, str]:
        """"Company: Role" (current) or "Company | Role" (older items)."""
        for sep in (":", "|"):
            if sep in raw:
                company, _, role = raw.partition(sep)
                company, role = company.strip(), role.strip()
                if company and role:
                    return company, role
        return "Company (via WWR)", raw.strip()

    @staticmethod
    def _parse_pubdate(value: str):
        """RSS pubDate is RFC-822, which the base ISO/epoch parser can't read."""
        if not value:
            return None
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(value).replace(tzinfo=None)
        except Exception:
            return None
