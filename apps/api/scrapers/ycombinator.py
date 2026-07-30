"""
Y Combinator "Work at a Startup" — vetted YC-funded startup roles, global.

Low volume, high signal. Applying needs a YC account (handled by the
ycombinator session adapter); discovery is public.

The board is a client-rendered SPA, so this is a Playwright source. Job links
must be matched on shape, not just on containing "/jobs/": the page also links
category pages like `/jobs/l/software-engineer`, and treating those as listings
was producing phantom jobs titled "Engineering" and "Design". Real listings are
`/jobs/{id}-{slug}` under a card container.
"""
from __future__ import annotations

import asyncio
import re
from typing import Optional

from loguru import logger
from playwright.async_api import Page

from models.job import JobListingCreate, JobType, Platform, WorkMode
from scrapers.base import BaseScraper

BASE_URL = "https://www.workatastartup.com"
# A real listing path is /jobs/<numeric id>[-slug]; /jobs/l/... is a category.
_JOB_PATH_RE = re.compile(r"^/jobs/(\d+)(?:-|$)")

_JOB_TYPES: dict[str, JobType] = {
    "intern": JobType.internship, "contract": JobType.contract,
    "part-time": JobType.part_time, "part time": JobType.part_time,
}


class YCombinatorScraper(BaseScraper):
    platform = Platform.ycombinator
    # Each JD needs its own page load, and discovery runs several query×location
    # pairs per source, so the per-request budget dominates run time. YC is a
    # small, tolerant board; 8/min made a single search take ~2 minutes.
    rate_limit_per_minute = 20

    MAX_SCROLLS = 3
    DETAIL_FETCH_LIMIT = 6   # JD fetches per search — the board omits JD text

    async def search_jobs(
        self,
        query: str,
        location: str = "",
        max_results: int = 50,
        credentials: Optional[dict] = None,
        region: str = "global",
    ) -> list[JobListingCreate]:
        jobs: list[JobListingCreate] = []
        page = await self.new_page()
        try:
            url = f"{BASE_URL}/jobs?query={query.replace(' ', '%20')}" if query else f"{BASE_URL}/jobs"
            await self.goto_with_retry(page, url, wait_for="domcontentloaded")
            await asyncio.sleep(4)  # SPA — let the list render

            try:
                await page.wait_for_selector('a[href^="/jobs/"]', timeout=20000)
            except Exception:
                logger.info(f"YC: no listings rendered for '{query}'")
                return jobs

            for _ in range(self.MAX_SCROLLS):
                if len(await self._job_links(page)) >= max_results:
                    break
                await page.mouse.wheel(0, 4000)
                await asyncio.sleep(1.5)

            for link in await self._job_links(page):
                try:
                    job = await self._extract(link)
                except Exception as e:
                    logger.debug(f"YC card extraction failed: {e}")
                    continue
                if job:
                    jobs.append(job)
                    if len(jobs) >= max_results:
                        break

            await self._enrich_descriptions(page, jobs)
        except Exception as e:
            logger.error(f"YC search failed for '{query}': {e}")
        finally:
            await page.close()

        logger.info(f"YC: returning {len(jobs)} jobs for '{query}'")
        return jobs

    @staticmethod
    async def _job_links(page: Page) -> list:
        """Anchors that point at an actual listing, not a category page."""
        out = []
        for link in await page.query_selector_all('a[href^="/jobs/"]'):
            href = await link.get_attribute("href") or ""
            if _JOB_PATH_RE.match(href.split("?")[0]):
                out.append(link)
        return out

    async def _extract(self, link) -> Optional[JobListingCreate]:
        href = (await link.get_attribute("href") or "").split("?")[0]
        match = _JOB_PATH_RE.match(href)
        if not match:
            return None
        url = f"{BASE_URL}{href}"
        if self.is_seen(url):
            return None

        title = self._clean_text(await link.inner_text())
        # The company name and meta line live on the surrounding card, not the
        # title anchor, so walk up to the card container for the rest.
        card = await link.evaluate_handle(
            "el => el.closest('div.bg-beige-lighter') || el.closest('[class*=job]') || el.parentElement"
        )
        card_text = ""
        try:
            element = card.as_element()
            if element:
                card_text = await element.inner_text()
        except Exception:
            pass

        lines = [line.strip() for line in card_text.split("\n") if line.strip()]
        company = self._company_from(lines, title)
        blob = card_text.lower()
        remote = "remote" in blob

        return JobListingCreate(
            title=title or "Role (via YC)",
            company=self._clean_text(company),
            location=self._location_from(lines) or ("Remote" if remote else "Not specified"),
            work_mode=WorkMode.remote if remote else None,
            is_remote_friendly=remote,
            job_type=self.match_terms(blob, _JOB_TYPES, JobType.full_time),
            salary_currency="USD",
            jd_text=self._clean_text(card_text) or f"{title} at a Y Combinator startup.",
            source_platform=self.platform,
            source_url=url,
            apply_url=url,
            source_job_id=match.group(1),
        )

    def _company_from(self, lines: list[str], title: str) -> str:
        """The employer, stripped of YC card decoration.

        Cards render the company as "OneSignal (S11)•Engage customers…" — batch
        tag plus tagline. Both must go, or the title+company dedup fingerprint
        drifts whenever a startup edits its tagline.
        """
        raw = next((ln for ln in lines if ln and ln != title), "")
        if not raw:
            return "YC Startup"
        name = raw.split("•")[0]                       # drop the tagline
        name = re.sub(r"\((?:[WSFXwsfx]\d{2}|IK\d{2})\)", "", name)  # drop the batch tag
        return self._clean_text(name).strip(" -–—,") or "YC Startup"

    @staticmethod
    def _location_from(lines: list[str]) -> str:
        for line in lines:
            if re.search(r"remote|hybrid|,\s*[A-Z]{2}\b|San Francisco|New York|London", line):
                return line
        return ""

    async def _enrich_descriptions(self, page: Page, jobs: list[JobListingCreate]) -> None:
        """Pull the real JD for the first N listings — cards carry only a blurb."""
        for job in jobs[: self.DETAIL_FETCH_LIMIT]:
            try:
                details = await self.get_job_details(page, job.source_url)
                if len(details.get("jd_text", "")) > len(job.jd_text):
                    job.jd_text = details["jd_text"]
            except Exception as e:
                logger.debug(f"YC detail fetch failed for {job.source_url}: {e}")

    async def get_job_details(self, page: Page, job_url: str) -> dict:
        """Full JD from a listing page.

        YC renders the copy as a series of `div.prose` blocks (company blurb,
        role, requirements) with no description/main wrapper to anchor on, so
        they are collected and joined in document order.
        """
        try:
            await self.goto_with_retry(page, job_url, wait_for="domcontentloaded")
            await asyncio.sleep(2)
            blocks = await page.query_selector_all("div.prose, [class*='prose']")
            parts = [await b.inner_text() for b in blocks]
            jd = "\n\n".join(p.strip() for p in parts if p and p.strip())
            if not jd:
                body = await page.query_selector("body")
                jd = await body.inner_text() if body else ""
            return {"jd_text": self._clean_text(jd)[:8000]}
        except Exception as e:
            logger.debug(f"YC detail fetch failed for {job_url}: {e}")
            return {"jd_text": ""}
