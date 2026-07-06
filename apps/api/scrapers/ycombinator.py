"""
Y Combinator "Work at a Startup" scraper — high-quality startup roles (global).

Scrapes the public job listings at workatastartup.com. Low volume, high signal.
Applying requires a YC account (handled by the ycombinator session adapter).
"""
import asyncio
from datetime import datetime
from typing import Optional
from loguru import logger
from scrapers.base import BaseScraper
from models.job import JobListingCreate, Platform, WorkMode


class YCombinatorScraper(BaseScraper):
    platform = Platform.ycombinator
    rate_limit_per_minute = 8
    BASE_URL = "https://www.workatastartup.com"

    async def search_jobs(self, query: str, location: str = "", max_results: int = 50) -> list[JobListingCreate]:
        jobs: list[JobListingCreate] = []
        try:
            page = await self._context.new_page()
            search_url = f"{self.BASE_URL}/jobs?query={query.replace(' ', '%20')}"
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)  # SPA — give the job list time to render

            await page.wait_for_selector("[class*='job'], .directory-list a, a[href*='/jobs/']", timeout=15000)
            cards = await page.query_selector_all("a[href*='/jobs/']")

            seen_local = set()
            for card in cards[:max_results * 2]:
                try:
                    job = await self._extract_card_data(card)
                    if job and job.source_url not in self._seen_urls and job.source_url not in seen_local:
                        seen_local.add(job.source_url)
                        self._seen_urls.add(job.source_url)
                        jobs.append(job)
                        if len(jobs) >= max_results:
                            break
                        await self.rate_limiter.acquire()
                except Exception as e:
                    logger.debug(f"YC card extraction failed: {e}")
                    continue
            await page.close()
        except Exception as e:
            logger.error(f"YC search failed for '{query}': {e}")
        return jobs

    async def _extract_card_data(self, card) -> Optional[JobListingCreate]:
        href = await card.get_attribute("href") or ""
        if "/jobs/" not in href:
            return None
        text = (await card.inner_text()).strip()
        if not text:
            return None
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        title_text = lines[0] if lines else "Role (via YC)"
        company_text = lines[1] if len(lines) > 1 else "YC Startup"
        url = href if href.startswith("http") else f"{self.BASE_URL}{href}"

        return JobListingCreate(
            title=title_text, company=company_text, location="Remote / On-site",
            work_mode=WorkMode.remote,
            source_platform=self.platform, source_url=url, apply_url=url,
            salary_currency="USD",
            jd_text=f"{title_text} at {company_text} (Y Combinator startup)",
            is_remote_friendly=True,
            discovered_at=datetime.utcnow(),
        )

    async def get_job_details(self, job: JobListingCreate) -> JobListingCreate:
        try:
            page = await self._context.new_page()
            await page.goto(job.source_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
            jd_el = await page.query_selector("[class*='description'], .job-details, main")
            if jd_el:
                job.jd_text = (await jd_el.inner_text()).strip()[:5000]
            await page.close()
        except Exception as e:
            logger.debug(f"YC detail fetch failed: {e}")
        return job
