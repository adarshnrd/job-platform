"""Wellfound (AngelList) job scraper — startup-focused jobs."""
import asyncio
import re
from typing import Optional
from loguru import logger
from playwright.async_api import Page
from scrapers.base import BaseScraper
from models.job import JobListingCreate, Platform, WorkMode, JobType


class WellfoundScraper(BaseScraper):
    platform = Platform.wellfound
    rate_limit_per_minute = 8
    BASE_URL = "https://wellfound.com"

    async def search_jobs(
        self,
        query: str,
        location: str = "Remote",
        max_results: int = 30,
        credentials: Optional[dict] = None,
    ) -> list[JobListingCreate]:
        jobs = []
        page = await self.new_page()

        try:
            encoded_query = query.replace(" ", "%20")
            search_url = f"{self.BASE_URL}/jobs?q={encoded_query}&location={location.replace(' ', '%20')}"
            await self.goto_with_retry(page, search_url, wait_for="domcontentloaded")
            await asyncio.sleep(3)

            # Scroll to load more results
            for _ in range(min(max_results // 10, 4)):
                await page.keyboard.press("End")
                await asyncio.sleep(2)

            # Wellfound job cards
            job_cards = await page.query_selector_all('[class*="JobListing"], [data-test="JobSearchResults"] > div, .styles_jobListing__')
            if not job_cards:
                # Try alternative selectors
                job_cards = await page.query_selector_all('div[class*="job-listing"], li[class*="listing"]')

            logger.info(f"Wellfound: found {len(job_cards)} job cards for '{query}'")

            for card in job_cards[:max_results]:
                try:
                    job_data = await self._extract_card_data(page, card)
                    if job_data and job_data.get("source_url") and not self.is_seen(job_data["source_url"]):
                        full_data = await self._get_job_details_from_card(card, job_data)
                        job_data.update(full_data)
                        jobs.append(JobListingCreate(**job_data))
                except Exception as e:
                    logger.debug(f"Wellfound card error: {e}")
                    continue

        except Exception as e:
            logger.error(f"Wellfound search failed: {e}")
        finally:
            await page.close()

        logger.info(f"Wellfound: returning {len(jobs)} jobs for '{query}'")
        return jobs

    async def _extract_card_data(self, page: Page, card) -> Optional[dict]:
        try:
            # Extract title
            title_el = await card.query_selector('h2, [class*="title"], [class*="jobTitle"], a[href*="/jobs/"]')
            title = await title_el.inner_text() if title_el else None

            # Extract company
            company_el = await card.query_selector('[class*="company"], [class*="startup-link"], h3')
            company = await company_el.inner_text() if company_el else "Unknown"

            # Extract location
            location_el = await card.query_selector('[class*="location"], [class*="remote"]')
            location = await location_el.inner_text() if location_el else ""

            # Extract URL
            link_el = await card.query_selector('a[href*="/jobs/"]')
            href = await link_el.get_attribute("href") if link_el else None

            if not title or not href:
                return None

            url = href if href.startswith("http") else f"{self.BASE_URL}{href}"
            url = url.split("?")[0]

            return {
                "title": self._clean_text(title),
                "company": self._clean_text(company),
                "location": self._clean_text(location),
                "source_platform": self.platform,
                "source_url": url,
                "apply_url": url,
                "jd_text": "",
                "is_remote_friendly": "remote" in location.lower(),
            }
        except Exception as e:
            logger.debug(f"Wellfound card parse error: {e}")
            return None

    async def _get_job_details_from_card(self, card, existing_data: dict) -> dict:
        """Try to extract JD text from the card itself (Wellfound shows partial JD inline)."""
        try:
            desc_el = await card.query_selector('[class*="description"], [class*="jobDescription"], p')
            jd_text = await desc_el.inner_text() if desc_el else ""

            # Check for salary info
            salary_el = await card.query_selector('[class*="salary"], [class*="compensation"]')
            salary_text = await salary_el.inner_text() if salary_el else ""

            if salary_text:
                jd_text = f"Compensation: {salary_text}\n\n{jd_text}"

            return {"jd_text": self._clean_text(jd_text) or f"Job at {existing_data.get('company', '')}. Apply on Wellfound."}
        except Exception:
            return {"jd_text": f"Job at {existing_data.get('company', '')}. Apply on Wellfound."}

    async def get_job_details(self, page: Page, job_url: str) -> dict:
        try:
            await self.goto_with_retry(page, job_url, wait_for="domcontentloaded")
            await asyncio.sleep(2)

            desc_el = await page.query_selector('[class*="description"], [class*="jobDescription"], .job-description, article')
            title_el = await page.query_selector('h1')
            company_el = await page.query_selector('[class*="company-name"], [class*="startup-name"]')
            salary_el = await page.query_selector('[class*="salary"], [class*="compensation"]')

            jd_text = await desc_el.inner_text() if desc_el else ""
            title = await title_el.inner_text() if title_el else ""
            company = await company_el.inner_text() if company_el else ""
            salary = await salary_el.inner_text() if salary_el else ""

            if salary:
                jd_text = f"Compensation: {salary}\n\n{jd_text}"

            return {
                "title": self._clean_text(title) or "Unknown",
                "company": self._clean_text(company) or "Unknown",
                "jd_text": self._clean_text(jd_text),
                "is_remote_friendly": True,
            }
        except Exception as e:
            logger.error(f"Wellfound job detail failed for {job_url}: {e}")
            return {"jd_text": ""}
