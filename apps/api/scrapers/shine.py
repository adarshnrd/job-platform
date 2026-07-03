"""Shine.com scraper — India job board, server-rendered search results."""
import asyncio
from datetime import datetime
from typing import Optional
from loguru import logger
from scrapers.base import BaseScraper
from models.job import JobListingCreate, Platform


class ShineScraper(BaseScraper):
    platform = Platform.shine
    rate_limit_per_minute = 10
    BASE_URL = "https://www.shine.com"

    async def search_jobs(self, query: str, location: str = "India", max_results: int = 50) -> list[JobListingCreate]:
        jobs: list[JobListingCreate] = []
        try:
            page = await self._context.new_page()
            slug = query.replace(" ", "-").lower()
            loc = location.replace(" ", "-").lower()
            search_url = f"{self.BASE_URL}/job-search/{slug}-jobs-in-{loc}"
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            await page.wait_for_selector("[class*='jobCard'], .search_listing, [data-jobid]", timeout=15000)
            cards = await page.query_selector_all("[class*='jobCard'], .search_listing, [data-jobid]")

            for card in cards[:max_results]:
                try:
                    job = await self._extract_card_data(card)
                    if job and job.source_url not in self._seen_urls:
                        self._seen_urls.add(job.source_url)
                        jobs.append(job)
                        await self.rate_limiter.acquire()
                except Exception as e:
                    logger.debug(f"Shine card extraction failed: {e}")
                    continue
            await page.close()
        except Exception as e:
            logger.error(f"Shine search failed for '{query}': {e}")
        return jobs

    async def _extract_card_data(self, card) -> Optional[JobListingCreate]:
        title = await card.query_selector("h2 a, h3 a, [class*='jobCardTitle'] a, a[class*='title']")
        company = await card.query_selector("[class*='company'], .cName")
        location_el = await card.query_selector("[class*='location'], .loc")
        if not title:
            return None

        title_text = (await title.inner_text()).strip()
        company_text = (await company.inner_text()).strip() if company else "Company (via Shine)"
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
            jd_el = await page.query_selector("[class*='jobDescription'], .job_description, [class*='description']")
            if jd_el:
                job.jd_text = (await jd_el.inner_text()).strip()
            skills = await page.query_selector_all("[class*='skill'], .skillTag")
            if skills:
                job.required_skills = [(await s.inner_text()).strip() for s in skills]
            await page.close()
        except Exception as e:
            logger.debug(f"Shine detail fetch failed: {e}")
        return job
