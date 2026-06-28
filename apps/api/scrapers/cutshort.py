"""
Cutshort scraper — curated startup & tech job marketplace in India.
"""
import asyncio
from datetime import datetime
from typing import Optional
from loguru import logger
from scrapers.base import BaseScraper
from models.job import JobListingCreate, Platform


class CutshortScraper(BaseScraper):
    platform = Platform.cutshort
    rate_limit_per_minute = 8
    BASE_URL = "https://cutshort.io"

    async def search_jobs(self, query: str, location: str = "India", max_results: int = 50) -> list[JobListingCreate]:
        jobs: list[JobListingCreate] = []
        try:
            page = await self._context.new_page()
            search_url = f"{self.BASE_URL}/jobs?q={query.replace(' ', '+')}"
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            await page.wait_for_selector("[class*='job'], .opportunity", timeout=15000)
            cards = await page.query_selector_all("[class*='JobCard'], [class*='job-card'], .opportunity")

            for card in cards[:max_results]:
                try:
                    job = await self._extract_card_data(card, page)
                    if job and job.source_url not in self._seen_urls:
                        self._seen_urls.add(job.source_url)
                        jobs.append(job)
                        await self.rate_limiter.acquire()
                except Exception as e:
                    logger.debug(f"Cutshort card error: {e}")
                    continue

            await page.close()
        except Exception as e:
            logger.error(f"Cutshort search failed for '{query}': {e}")
        return jobs

    async def _extract_card_data(self, card, page) -> Optional[JobListingCreate]:
        title_el = await card.query_selector("h3, h4, [class*='title'], [class*='role']")
        company_el = await card.query_selector("[class*='company'], [class*='startup']")
        location_el = await card.query_selector("[class*='location'], [class*='city']")
        link_el = await card.query_selector("a")

        if not title_el or not link_el:
            return None

        title = (await title_el.inner_text()).strip()
        company = (await company_el.inner_text()).strip() if company_el else "Unknown Startup"
        location = (await location_el.inner_text()).strip() if location_el else "India"
        href = await link_el.get_attribute("href") or ""
        url = href if href.startswith("http") else f"{self.BASE_URL}{href}"

        return JobListingCreate(
            title=title,
            company=company,
            location=location,
            source_platform=self.platform,
            source_url=url,
            apply_url=url,
            jd_text=f"{title} at {company}",
            discovered_at=datetime.utcnow(),
        )

    async def get_job_details(self, job: JobListingCreate) -> JobListingCreate:
        try:
            page = await self._context.new_page()
            await page.goto(job.source_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1.5)
            jd_el = await page.query_selector("[class*='description'], [class*='about']")
            if jd_el:
                job.jd_text = (await jd_el.inner_text()).strip()
            skills = await page.query_selector_all("[class*='skill'], [class*='tag']")
            if skills:
                job.required_skills = [(await s.inner_text()).strip() for s in skills[:15]]
            await page.close()
        except Exception as e:
            logger.debug(f"Cutshort detail fetch failed: {e}")
        return job
