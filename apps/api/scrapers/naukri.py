"""Naukri.com job scraper."""
import asyncio
import re
from typing import Optional
from loguru import logger
from playwright.async_api import Page
from scrapers.base import BaseScraper
from models.job import JobListingCreate, Platform


class NaukriScraper(BaseScraper):
    platform = Platform.naukri
    rate_limit_per_minute = 15
    requires_headed = True  # Akamai serves "Access Denied" to every headless browser
    BASE_URL = "https://www.naukri.com"

    async def search_jobs(
        self, query: str, location: str = "India",
        max_results: int = 50, credentials: Optional[dict] = None
    ) -> list[JobListingCreate]:
        jobs = []
        page = await self.new_page()
        try:
            # Naukri search URL format
            q = query.lower().replace(" ", "-")
            loc = location.lower().replace(" ", "-")
            search_url = f"{self.BASE_URL}/{q}-jobs-in-{loc}?Experience=0&jobAge=7"
            await self.goto_with_retry(page, search_url)
            await asyncio.sleep(2)

            for scroll in range(3):
                await page.keyboard.press("End")
                await asyncio.sleep(1.5)

            job_cards = await page.query_selector_all(".jobTuple, article.jobTupleHeader, .srp-jobtuple-wrapper")
            logger.info(f"Naukri: found {len(job_cards)} job cards")

            for card in job_cards[:max_results]:
                try:
                    title_el = await card.query_selector("a.title, a.jobTitle")
                    company_el = await card.query_selector(".companyName a, .comp-name")
                    location_el = await card.query_selector(".location, li.location")
                    salary_el = await card.query_selector(".salary, .sal")
                    exp_el = await card.query_selector(".experience, .exp")

                    title = await title_el.inner_text() if title_el else None
                    url = await title_el.get_attribute("href") if title_el else None
                    company = await company_el.inner_text() if company_el else "Unknown"
                    location_text = await location_el.inner_text() if location_el else ""
                    salary_text = await salary_el.inner_text() if salary_el else ""
                    exp_text = await exp_el.inner_text() if exp_el else ""

                    if not title or not url:
                        continue
                    if self.is_seen(url):
                        continue

                    # Parse salary
                    salary_min, salary_max = self._parse_naukri_salary(salary_text)
                    min_exp, max_exp = self._parse_experience(exp_text)

                    detail_page = await self.new_page()
                    try:
                        details = await self.get_job_details(detail_page, url)
                    finally:
                        await detail_page.close()

                    jobs.append(JobListingCreate(
                        title=self._clean_text(title),
                        company=self._clean_text(company),
                        location=self._clean_text(location_text),
                        salary_min=salary_min,
                        salary_max=salary_max,
                        salary_currency="INR",
                        min_experience=min_exp,
                        max_experience=max_exp,
                        source_platform=self.platform,
                        source_url=url,
                        apply_url=url,
                        jd_text=details.get("jd_text", ""),
                        jd_html=details.get("jd_html", ""),
                        required_skills=details.get("required_skills", []),
                        posted_at=details.get("posted_at"),
                    ))
                except Exception as e:
                    logger.debug(f"Naukri card error: {e}")
                    continue

        except Exception as e:
            logger.error(f"Naukri search failed: {e}")
        finally:
            await page.close()

        logger.info(f"Naukri: returning {len(jobs)} jobs")
        return jobs

    async def get_job_details(self, page: Page, job_url: str) -> dict:
        try:
            await self.goto_with_retry(page, job_url, wait_for="domcontentloaded")
            await asyncio.sleep(1)

            desc_el = await page.query_selector(".job-desc, #job_description, .job-description")
            skills_els = await page.query_selector_all(".key-skill span, .tags-gt span")
            date_el = await page.query_selector(".posted-date, .date-class, [class*='postDate'], [class*='post-date']")

            jd_text = await desc_el.inner_text() if desc_el else ""
            jd_html = await desc_el.inner_html() if desc_el else ""

            posted_at = None
            if date_el:
                date_text = await date_el.inner_text()
                posted_at = self.parse_relative_date(date_text)

            skills = []
            for sk in skills_els:
                text = await sk.inner_text()
                if text.strip():
                    skills.append(text.strip())

            return {
                "jd_text": self._clean_text(jd_text),
                "jd_html": jd_html,
                "required_skills": skills[:30],
                "posted_at": posted_at,
            }
        except Exception as e:
            logger.error(f"Naukri detail fetch failed: {e}")
            return {"jd_text": ""}

    def _parse_naukri_salary(self, text: str) -> tuple:
        if not text:
            return None, None
        nums = re.findall(r'\d+\.?\d*', text)
        if len(nums) >= 2:
            return int(float(nums[0]) * 100000), int(float(nums[1]) * 100000)
        elif len(nums) == 1:
            return int(float(nums[0]) * 100000), None
        return None, None

    def _parse_experience(self, text: str) -> tuple:
        if not text:
            return None, None
        nums = re.findall(r'\d+', text)
        if len(nums) >= 2:
            return int(nums[0]), int(nums[1])
        elif len(nums) == 1:
            return int(nums[0]), int(nums[0]) + 2
        return None, None
