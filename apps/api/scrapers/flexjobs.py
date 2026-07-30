"""
FlexJobs — curated remote/flexible roles, global.

FlexJobs is a paid board: full listings, employer names and apply links sit
behind a subscription. Two consequences shape this scraper.

First, access. Plain HTTP is refused outright (ERR_HTTP2_PROTOCOL_ERROR) and
headless Chrome is blocked; a headed window loads normally (verified
2026-07-27), so `requires_headed` is set.

Second, scope. Only the free `/publicjobs/{slug}-{uuid}` tier is scraped — the
listings FlexJobs itself publishes openly. Paywalled results are deliberately
not touched: scraping them would need the user's paid session and would breach
the terms they agreed to. So this source yields a modest number of genuinely
public roles rather than the full catalogue, and it is registered
non-discoverable by default (opt in via preferred_platforms).

Employer names are withheld on most public listings — FlexJobs is the
intermediary — so `company` falls back to a source-labelled placeholder rather
than a guess.
"""
from __future__ import annotations

import asyncio
import re
from typing import Optional

from loguru import logger
from playwright.async_api import Page

from models.job import JobListingCreate, JobType, Platform, WorkMode
from scrapers.base import BaseScraper
from scrapers.jsonld import parse_job_posting

BASE_URL = "https://www.flexjobs.com"
# /publicjobs/senior-software-engineer-<uuid>
_JOB_HREF_RE = re.compile(
    r"^/publicjobs/(.+?)-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)

_JOB_TYPES: dict[str, JobType] = {
    "intern": JobType.internship, "internship": JobType.internship,
    "contract": JobType.contract, "contractor": JobType.contract,
    "freelance": JobType.freelance,
    "part-time": JobType.part_time, "part time": JobType.part_time,
}


class FlexJobsScraper(BaseScraper):
    platform = Platform.flexjobs
    rate_limit_per_minute = 6
    # Headless Chrome is blocked; plain HTTP is refused at the protocol level.
    requires_headed = True

    MAX_PAGES = 2
    DETAIL_FETCH_LIMIT = 8
    # Many `/publicjobs/` links on the search page point at listings FlexJobs has
    # already removed (HTTP 410), leaving nothing but the title. Scoring those
    # would spend LLM budget for a meaningless number, so they are dropped.
    MIN_JD_CHARS = 120

    async def search_jobs(
        self,
        query: str,
        location: str = "",
        max_results: int = 20,
        credentials: Optional[dict] = None,
        region: str = "global",
    ) -> list[JobListingCreate]:
        jobs: list[JobListingCreate] = []
        page = await self.new_page()
        try:
            for page_num in range(1, self.MAX_PAGES + 1):
                if len(jobs) >= max_results:
                    break
                url = f"{BASE_URL}/search?search={query.replace(' ', '+')}"
                if page_num > 1:
                    url += f"&page={page_num}"
                await self.goto_with_retry(page, url, wait_for="domcontentloaded")
                # Public listings are appended late and below the fold; a short
                # wait alone reliably finds none.
                await asyncio.sleep(7)
                for _ in range(2):
                    await page.mouse.wheel(0, 3000)
                    await asyncio.sleep(2)

                hrefs = await self._job_hrefs(page)
                if not hrefs:
                    logger.info(f"FlexJobs: no public listings on page {page_num} for '{query}'")
                    break

                for href in hrefs:
                    job = self._from_href(href)
                    if job:
                        jobs.append(job)
                        if len(jobs) >= max_results:
                            break

            await self._enrich_descriptions(page, jobs)
        except Exception as e:
            logger.error(f"FlexJobs search failed for '{query}': {e}")
        finally:
            await page.close()

        usable = [j for j in jobs if len(j.jd_text) >= self.MIN_JD_CHARS]
        if len(usable) < len(jobs):
            logger.info(
                f"FlexJobs: dropped {len(jobs) - len(usable)}/{len(jobs)} listings with no JD "
                "(public links commonly resolve to removed postings)"
            )
        logger.info(f"FlexJobs: returning {len(usable)} public jobs for '{query}'")
        return usable

    @staticmethod
    async def _job_hrefs(page: Page) -> list[str]:
        seen, out = set(), []
        for link in await page.query_selector_all('a[href*="/publicjobs/"]'):
            href = (await link.get_attribute("href") or "").split("?")[0]
            if _JOB_HREF_RE.match(href) and href not in seen:
                seen.add(href)
                out.append(href)
        return out

    def _from_href(self, href: str) -> Optional[JobListingCreate]:
        match = _JOB_HREF_RE.match(href)
        if not match:
            return None
        slug, job_id = match.groups()
        url = f"{BASE_URL}{href}"
        if self.is_seen(url):
            return None

        title = re.sub(r"\s+", " ", slug.replace("-", " ")).strip().title()
        return JobListingCreate(
            title=title,
            # FlexJobs withholds the employer on public listings — see module docstring.
            company="Company (via FlexJobs)",
            location="Remote",
            work_mode=WorkMode.remote,
            is_remote_friendly=True,
            job_type=self.match_terms(slug.replace("-", " "), _JOB_TYPES, JobType.full_time),
            salary_currency="USD",
            jd_text=title,  # replaced by the detail pass below
            source_platform=self.platform,
            source_url=url,
            apply_url=url,
            source_job_id=job_id,
        )

    async def _enrich_descriptions(self, page: Page, jobs: list[JobListingCreate]) -> None:
        for job in jobs[: self.DETAIL_FETCH_LIMIT]:
            try:
                details = await self.get_job_details(page, job.source_url)
            except Exception as e:
                logger.debug(f"FlexJobs detail failed for {job.source_url}: {e}")
                continue
            if len(details.get("jd_text") or "") > len(job.jd_text):
                job.jd_text = details["jd_text"]
            for field in ("company", "location", "posted_at", "salary_min", "salary_max"):
                if details.get(field):
                    setattr(job, field, details[field])

    async def get_job_details(self, page: Page, job_url: str) -> dict:
        await self.goto_with_retry(page, job_url, wait_for="domcontentloaded")
        await asyncio.sleep(2)
        html = await page.content()
        posting = parse_job_posting(html)
        if posting and posting.get("jd_text"):
            return posting
        body = await page.query_selector("[class*='description'], main, article")
        jd = await body.inner_text() if body else ""
        return {"jd_text": self._clean_text(jd)[:8000]}
