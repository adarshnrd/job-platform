"""
iimjobs scraper — management/senior roles for India (Info Edge platform family,
shares mechanics with Hirist). Server-rendered listing pages scraped via Playwright.
"""
import asyncio
from datetime import datetime
from typing import Optional
from loguru import logger
from scrapers.base import BaseScraper
from models.job import JobListingCreate, Platform


class IimjobsScraper(BaseScraper):
    platform = Platform.iimjobs
    rate_limit_per_minute = 8
    BASE_URL = "https://www.iimjobs.com"

    async def search_jobs(self, query: str, location: str = "India", max_results: int = 50) -> list[JobListingCreate]:
        jobs: list[JobListingCreate] = []
        try:
            page = await self._context.new_page()
            search_url = f"{self.BASE_URL}/search/{query.replace(' ', '-')}-jobs"
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            await page.wait_for_selector(".job-card, [class*='jobCard'], [data-job-id], article", timeout=15000)
            cards = await page.query_selector_all(".job-card, [class*='jobCard'], [data-job-id], article")

            for card in cards[:max_results]:
                try:
                    job = await self._extract_card_data(card)
                    if job and job.source_url not in self._seen_urls:
                        self._seen_urls.add(job.source_url)
                        jobs.append(job)
                        await self.rate_limiter.acquire()
                except Exception as e:
                    logger.debug(f"iimjobs card extraction failed: {e}")
                    continue
            await page.close()
        except Exception as e:
            logger.error(f"iimjobs search failed for '{query}': {e}")
        return jobs

    async def _extract_card_data(self, card) -> Optional[JobListingCreate]:
        title = await card.query_selector("h2, h3, [class*='title']")
        company = await card.query_selector("[class*='company'], .company-name")
        location_el = await card.query_selector("[class*='location'], .location")
        link = await card.query_selector("a")
        if not title or not link:
            return None

        title_text = (await title.inner_text()).strip()
        company_text = (await company.inner_text()).strip() if company else "Company (via iimjobs)"
        location_text = (await location_el.inner_text()).strip() if location_el else "India"
        href = await link.get_attribute("href") or ""
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
            jd_el = await page.query_selector("[class*='description'], .job-description, .jd")
            if jd_el:
                job.jd_text = (await jd_el.inner_text()).strip()
            skills = await page.query_selector_all("[class*='skill'], .skill-tag")
            if skills:
                job.required_skills = [(await s.inner_text()).strip() for s in skills]
            await page.close()
        except Exception as e:
            logger.debug(f"iimjobs detail fetch failed: {e}")
        return job
