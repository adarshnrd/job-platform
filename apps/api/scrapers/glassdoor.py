"""Glassdoor job scraper using Playwright."""
import asyncio
from loguru import logger
from playwright.async_api import Page
from scrapers.base import BaseScraper
from models.job import JobListingCreate, Platform


class GlassdoorScraper(BaseScraper):
    platform = Platform.glassdoor
    rate_limit_per_minute = 6
    BASE_URL = "https://www.glassdoor.co.in"

    async def search_jobs(
        self, query: str, location: str = "India",
        max_results: int = 50, credentials=None
    ) -> list[JobListingCreate]:
        return await self._scrape_jobs(query, location, max_results)

    async def _scrape_jobs(self, query: str, location: str, max_results: int) -> list[JobListingCreate]:
        jobs = []
        page = await self.new_page()
        try:
            q = query.replace(" ", "-")
            url = f"{self.BASE_URL}/Job/{q}-jobs-SRCH_KO0,{len(q)}.htm"
            await self.goto_with_retry(page, url)
            await asyncio.sleep(3)

            # Dismiss sign-in modal if present
            try:
                close_btn = await page.query_selector("[alt='Close'], button[data-test='close-btn'], .modal_closeIcon")
                if close_btn:
                    await close_btn.click()
                    await asyncio.sleep(1)
            except Exception:
                pass

            job_cards = await page.query_selector_all(
                "li[data-test='jobListing'], [data-jobid], .react-job-listing"
            )
            logger.info(f"Glassdoor: found {len(job_cards)} job cards")

            for card in job_cards[:max_results]:
                try:
                    title_el = await card.query_selector("[data-test='job-title'], .job-title, a[data-test='job-link']")
                    company_el = await card.query_selector("[data-test='employer-name'], .employer-name, .EmployerProfile_compactEmployerName__LE242")
                    location_el = await card.query_selector("[data-test='emp-location'], .location")
                    salary_el = await card.query_selector("[data-test='detailSalary'], .salary-estimate")

                    title = await title_el.inner_text() if title_el else None
                    job_url = await title_el.get_attribute("href") if title_el else None
                    company = await company_el.inner_text() if company_el else "Unknown"
                    location_text = await location_el.inner_text() if location_el else ""
                    salary_text = await salary_el.inner_text() if salary_el else ""

                    if not title or not job_url:
                        continue

                    if not job_url.startswith("http"):
                        job_url = f"{self.BASE_URL}{job_url}"

                    if self.is_seen(job_url):
                        continue

                    detail_page = await self.new_page()
                    try:
                        details = await self._get_details(detail_page, job_url)
                    finally:
                        await detail_page.close()

                    jobs.append(JobListingCreate(
                        title=self._clean_text(title),
                        company=self._clean_text(company),
                        location=self._clean_text(location_text),
                        source_platform=self.platform,
                        source_url=job_url,
                        apply_url=job_url,
                        jd_text=details.get("jd_text", ""),
                        required_skills=details.get("required_skills", []),
                    ))
                except Exception as e:
                    logger.debug(f"Glassdoor card error: {e}")
                    continue
        except Exception as e:
            logger.error(f"Glassdoor search failed: {e}")
        finally:
            await page.close()
        return jobs

    async def _get_details(self, page: Page, url: str) -> dict:
        try:
            await self.goto_with_retry(page, url, wait_for="domcontentloaded")
            await asyncio.sleep(2)
            desc_el = await page.query_selector(
                ".jobDescriptionContent, [data-test='jobDescriptionContent'], .desc, #JobDescriptionContainer"
            )
            jd_text = await desc_el.inner_text() if desc_el else ""
            return {"jd_text": self._clean_text(jd_text), "required_skills": []}
        except Exception as e:
            logger.debug(f"Glassdoor detail error: {e}")
            return {"jd_text": ""}
