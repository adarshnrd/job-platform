"""
Peerlist — startup/tech job board with a strong India + remote mix.

Cloudflare fronts this board and answers *every* headless request with a 403
"security verification" interstitial, including real Chrome in headless mode.
A headed window gets through cleanly (verified 2026-07-27), so this scraper
sets `requires_headed` and opens a visible browser — the same accommodation
`linkedin`/`naukri` already rely on. With SCRAPER_ALLOW_HEADED=false it will
be blocked and returns nothing rather than pretending otherwise.

Listing URLs carry the structure this needs without a detail fetch:
    /company/{company}/careers/{title-slug}/job{id}
so company and title come from the href and only the JD needs a page visit.
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

BASE_URL = "https://peerlist.io"
_JOB_HREF_RE = re.compile(r"^/company/([^/]+)/careers/([^/]+)/(job[a-z0-9]+)")

_JOB_TYPES: dict[str, JobType] = {
    "intern": JobType.internship, "internship": JobType.internship,
    "contract": JobType.contract, "contractor": JobType.contract,
    "freelance": JobType.freelance,
    "part-time": JobType.part_time, "part time": JobType.part_time,
}


class PeerlistScraper(BaseScraper):
    platform = Platform.peerlist
    rate_limit_per_minute = 8
    # Cloudflare serves a 403 challenge to every headless browser here.
    requires_headed = True

    MAX_SCROLLS = 4
    DETAIL_FETCH_LIMIT = 10
    # A listing whose JD never loaded carries only its title. Scoring that would
    # spend LLM budget to produce a meaningless number and store an unusable row,
    # so such listings are dropped instead of returned.
    MIN_JD_CHARS = 120

    async def search_jobs(
        self,
        query: str,
        location: str = "",
        max_results: int = 30,
        credentials: Optional[dict] = None,
        region: str = "global",
    ) -> list[JobListingCreate]:
        jobs: list[JobListingCreate] = []
        page = await self.new_page()
        try:
            url = f"{BASE_URL}/jobs?q={query.replace(' ', '%20')}" if query else f"{BASE_URL}/jobs"
            await self.goto_with_retry(page, url, wait_for="domcontentloaded")
            await asyncio.sleep(5)  # SPA render + Cloudflare handshake

            if await self._is_challenged(page):
                logger.warning("Peerlist: blocked by the bot wall — needs a headed browser")
                return jobs

            for _ in range(self.MAX_SCROLLS):
                if len(await self._job_hrefs(page)) >= max_results:
                    break
                await page.mouse.wheel(0, 4000)
                await asyncio.sleep(2)

            hrefs = await self._job_hrefs(page)
            logger.info(f"Peerlist: {len(hrefs)} listing links for '{query}'")

            for href in hrefs:
                job = self._from_href(href)
                if job:
                    jobs.append(job)
                    if len(jobs) >= max_results:
                        break

            await self._enrich_descriptions(page, jobs)
        except Exception as e:
            logger.error(f"Peerlist search failed for '{query}': {e}")
        finally:
            await page.close()

        usable = [j for j in jobs if len(j.jd_text) >= self.MIN_JD_CHARS]
        if len(usable) < len(jobs):
            logger.info(
                f"Peerlist: dropped {len(jobs) - len(usable)}/{len(jobs)} listings with no JD "
                "(detail pages are bot-walled even from a headed browser)"
            )
        logger.info(f"Peerlist: returning {len(usable)} jobs for '{query}'")
        return usable

    @staticmethod
    async def _is_challenged(page: Page) -> bool:
        title = (await page.title() or "").lower()
        return "just a moment" in title or "attention required" in title

    @staticmethod
    async def _job_hrefs(page: Page) -> list[str]:
        """Unique listing paths, in page order."""
        seen, out = set(), []
        for link in await page.query_selector_all('a[href*="/careers/"]'):
            href = (await link.get_attribute("href") or "").split("?")[0]
            if _JOB_HREF_RE.match(href) and href not in seen:
                seen.add(href)
                out.append(href)
        return out

    def _from_href(self, href: str) -> Optional[JobListingCreate]:
        match = _JOB_HREF_RE.match(href)
        if not match:
            return None
        company_slug, title_slug, job_id = match.groups()
        url = f"{BASE_URL}{href}"
        if self.is_seen(url):
            return None

        title = self._deslug(title_slug)
        return JobListingCreate(
            title=title,
            company=self._deslug(company_slug),
            location="Not specified",
            job_type=self.match_terms(title_slug.replace("-", " "), _JOB_TYPES, JobType.full_time),
            salary_currency="USD",
            jd_text=title,  # replaced by the detail pass below
            source_platform=self.platform,
            source_url=url,
            apply_url=url,
            source_job_id=job_id,
        )

    @staticmethod
    def _deslug(slug: str) -> str:
        """"senior-software-engineer--trading" → "Senior Software Engineer - Trading".

        A doubled hyphen encodes a literal dash in the original title. Word
        hyphens are split first so the restored dash isn't swallowed by the
        same pass that expands them.
        """
        text = re.sub(r"_[a-z0-9]{2,}$", "", slug)   # drop disambiguating suffixes
        parts = [p.replace("-", " ") for p in text.split("--")]
        return re.sub(r"\s+", " ", " - ".join(parts)).strip().title()

    async def _enrich_descriptions(self, page: Page, jobs: list[JobListingCreate]) -> None:
        for job in jobs[: self.DETAIL_FETCH_LIMIT]:
            try:
                details = await self.get_job_details(page, job.source_url)
            except Exception as e:
                logger.debug(f"Peerlist detail failed for {job.source_url}: {e}")
                continue
            jd = details.get("jd_text") or ""
            if len(jd) > len(job.jd_text):
                job.jd_text = jd
            for field in ("company", "location", "posted_at", "salary_min", "salary_max"):
                if details.get(field):
                    setattr(job, field, details[field])
            if details.get("is_remote_friendly"):
                job.is_remote_friendly = True
                job.work_mode = WorkMode.remote

    async def get_job_details(self, page: Page, job_url: str) -> dict:
        await self.goto_with_retry(page, job_url, wait_for="domcontentloaded")
        await asyncio.sleep(2)
        html = await page.content()
        # Peerlist emits a schema.org JobPosting on listing pages; fall back to
        # the rendered body when a listing predates that.
        posting = parse_job_posting(html)
        if posting and posting.get("jd_text"):
            return posting
        body = await page.query_selector("main, article, [class*='description']")
        jd = await body.inner_text() if body else ""
        return {"jd_text": self._clean_text(jd)[:8000]}
