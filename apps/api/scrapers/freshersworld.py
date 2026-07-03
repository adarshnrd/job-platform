"""
Freshersworld scraper — entry-level/fresher roles for India. Server-rendered.

Note: this source is entry-level heavy. Discovery gates it by experience/opt-in
(see SOURCE_REGISTRY) so it doesn't flood senior candidates with junior roles.
"""
import asyncio
from datetime import datetime
from typing import Optional
from loguru import logger
from scrapers.base import BaseScraper
from models.job import JobListingCreate, Platform


class FreshersworldScraper(BaseScraper):
    platform = Platform.freshersworld
    rate_limit_per_minute = 10
    BASE_URL = "https://www.freshersworld.com"

    async def search_jobs(self, query: str, location: str = "India", max_results: int = 50) -> list[JobListingCreate]:
        jobs: list[JobListingCreate] = []
        try:
            page = await self._context.new_page()
            slug = query.replace(" ", "-").lower()
            search_url = f"{self.BASE_URL}/jobs/jobsearch/{slug}"
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            await page.wait_for_selector(".job-container, [class*='job-listing'], .joblist", timeout=15000)
            cards = await page.query_selector_all(".job-container, [class*='job-listing'], .joblist")

            for card in cards[:max_results]:
                try:
                    job = await self._extract_card_data(card)
                    if job and job.source_url not in self._seen_urls:
                        self._seen_urls.add(job.source_url)
                        jobs.append(job)
                        await self.rate_limiter.acquire()
                except Exception as e:
                    logger.debug(f"Freshersworld card extraction failed: {e}")
                    continue
            await page.close()
        except Exception as e:
            logger.error(f"Freshersworld search failed for '{query}': {e}")
        return jobs

    async def _extract_card_data(self, card) -> Optional[JobListingCreate]:
        title = await card.query_selector(".job-title a, h3 a, [class*='title'] a")
        company = await card.query_selector(".company-name, [class*='company']")
        location_el = await card.query_selector(".location, [class*='location']")
        if not title:
            return None

        title_text = (await title.inner_text()).strip()
        company_text = (await company.inner_text()).strip() if company else "Company (via Freshersworld)"
        location_text = (await location_el.inner_text()).strip() if location_el else "India"
        href = await title.get_attribute("href") or ""
        url = href if href.startswith("http") else f"{self.BASE_URL}{href}"

        return JobListingCreate(
            title=title_text, company=company_text, location=location_text,
            source_platform=self.platform, source_url=url, apply_url=url,
            jd_text=f"{title_text} at {company_text} — {location_text}",
            discovered_at=datetime.utcnow(),
        )

    async def get_job_details(self, job: JobListingCreate) -> JobListingCreate:
        try:
            page = await self._context.new_page()
            await page.goto(job.source_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1.5)
            jd_el = await page.query_selector(".job-description, [class*='description'], .jd-content")
            if jd_el:
                job.jd_text = (await jd_el.inner_text()).strip()
            await page.close()
        except Exception as e:
            logger.debug(f"Freshersworld detail fetch failed: {e}")
        return job
