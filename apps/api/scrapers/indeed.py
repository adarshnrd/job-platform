"""Indeed job scraper using Publisher API + Playwright fallback."""
import asyncio
from typing import Optional
from loguru import logger
from playwright.async_api import Page
from scrapers.base import BaseScraper
from models.job import JobListingCreate, Platform


class IndeedScraper(BaseScraper):
    platform = Platform.indeed
    rate_limit_per_minute = 20
    BASE_URL = "https://www.indeed.com"
    INDIA_URL = "https://in.indeed.com"

    async def search_jobs(
        self, query: str, location: str = "India",
        max_results: int = 50, credentials: Optional[dict] = None
    ) -> list[JobListingCreate]:
        return await self._scrape_jobs(query, location, max_results)

    async def _scrape_jobs(self, query: str, location: str, max_results: int) -> list[JobListingCreate]:
        jobs = []
        page = await self.new_page()
        try:
            q = query.replace(" ", "+")
            loc = location.replace(" ", "+")
            url = f"{self.INDIA_URL}/jobs?q={q}&l={loc}&sort=date&fromage=7&limit=50"
            await self.goto_with_retry(page, url)
            await asyncio.sleep(2)

            job_cards = await page.query_selector_all(".job_seen_beacon, .tapItem, [data-testid='slider_item']")
            logger.info(f"Indeed: found {len(job_cards)} job cards")

            for card in job_cards[:max_results]:
                try:
                    title_el = await card.query_selector("h2.jobTitle a, .jcs-JobTitle")
                    company_el = await card.query_selector("[data-testid='company-name'], .companyName")
                    location_el = await card.query_selector("[data-testid='text-location'], .companyLocation")
                    salary_el = await card.query_selector("[data-testid='attribute_snippet_testid'], .salary-snippet")
                    date_el = await card.query_selector(".date, [data-testid='myJobsStateDate'], span.css-qvloho")

                    title = await title_el.inner_text() if title_el else None
                    job_url = await title_el.get_attribute("href") if title_el else None
                    company = await company_el.inner_text() if company_el else "Unknown"
                    location_text = await location_el.inner_text() if location_el else ""
                    salary_text = await salary_el.inner_text() if salary_el else ""

                    posted_at = None
                    if date_el:
                        date_text = await date_el.inner_text()
                        posted_at = self.parse_relative_date(date_text)

                    if not title or not job_url:
                        continue

                    if not job_url.startswith("http"):
                        job_url = f"{self.INDIA_URL}{job_url}"

                    if self.is_seen(job_url):
                        continue

                    detail_page = await self.new_page()
                    try:
                        details = await self.get_job_details(detail_page, job_url)
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
                        posted_at=posted_at,
                    ))
                except Exception as e:
                    logger.debug(f"Indeed card error: {e}")
                    continue
        except Exception as e:
            logger.error(f"Indeed search failed: {e}")
        finally:
            await page.close()
        return jobs

    async def get_job_details(self, page: Page, job_url: str) -> dict:
        try:
            await self.goto_with_retry(page, job_url, wait_for="domcontentloaded")
            await asyncio.sleep(1)
            desc_el = await page.query_selector("#jobDescriptionText, .jobsearch-jobDescriptionText")
            jd_text = await desc_el.inner_text() if desc_el else ""
            jd_html = await desc_el.inner_html() if desc_el else ""
            return {"jd_text": self._clean_text(jd_text), "jd_html": jd_html, "required_skills": []}
        except Exception as e:
            logger.error(f"Indeed detail fetch failed: {e}")
            return {"jd_text": ""}
