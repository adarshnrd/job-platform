"""LinkedIn job scraper — uses Playwright with stealth."""
import asyncio
from typing import Optional
from loguru import logger
from playwright.async_api import Page
from scrapers.base import BaseScraper
from models.job import JobListingCreate, Platform, JobType


class LinkedInScraper(BaseScraper):
    platform = Platform.linkedin
    rate_limit_per_minute = 10
    BASE_URL = "https://www.linkedin.com"

    async def login(self, page: Page, credentials: dict) -> bool:
        """Log into LinkedIn."""
        try:
            await self.goto_with_retry(page, f"{self.BASE_URL}/login", wait_for="domcontentloaded")
            await self.human_type(page, "#username", credentials["username"])
            await self.human_type(page, "#password", credentials["password"])
            await page.click('[type="submit"]')
            await page.wait_for_url("**/feed/**", timeout=15000)
            logger.info("LinkedIn login successful")
            return True
        except Exception as e:
            logger.error(f"LinkedIn login failed: {e}")
            return False

    async def search_jobs(
        self,
        query: str,
        location: str = "India",
        max_results: int = 50,
        credentials: Optional[dict] = None
    ) -> list[JobListingCreate]:
        jobs = []
        page = await self.new_page()

        try:
            if credentials:
                await self.login(page, credentials)

            # Build search URL (works without login too)
            encoded_query = query.replace(" ", "%20")
            encoded_location = location.replace(" ", "%20")
            search_url = (
                f"{self.BASE_URL}/jobs/search/"
                f"?keywords={encoded_query}&location={encoded_location}"
                f"&f_TPR=r604800&sortBy=DD"  # Last 7 days, sorted by date
            )

            await self.goto_with_retry(page, search_url)
            await asyncio.sleep(2)

            # Scroll to load more
            for _ in range(min(max_results // 10, 5)):
                await page.keyboard.press("End")
                await asyncio.sleep(1.5)

            # Get job cards
            job_cards = await page.query_selector_all(".job-search-card, .base-card")
            logger.info(f"LinkedIn: found {len(job_cards)} job cards")

            for card in job_cards[:max_results]:
                try:
                    job_data = await self._extract_card_data(page, card)
                    if job_data and not self.is_seen(job_data.get("source_url", "")):
                        detail_page = await self.new_page()
                        try:
                            full_data = await self.get_job_details(detail_page, job_data["source_url"])
                            job_data.update(full_data)
                            jobs.append(JobListingCreate(**job_data))
                        finally:
                            await detail_page.close()
                except Exception as e:
                    logger.debug(f"LinkedIn card extraction failed: {e}")
                    continue

        except Exception as e:
            logger.error(f"LinkedIn search failed: {e}")
        finally:
            await page.close()

        logger.info(f"LinkedIn: returning {len(jobs)} jobs for '{query}'")
        return jobs

    async def _extract_card_data(self, page: Page, card) -> Optional[dict]:
        """Extract basic data from a job card."""
        try:
            title_el = await card.query_selector(".base-search-card__title, .job-search-card__title")
            company_el = await card.query_selector(".base-search-card__subtitle, .job-search-card__company-name")
            location_el = await card.query_selector(".job-search-card__location")
            link_el = await card.query_selector("a.base-card__full-link, a[data-tracking-control-name]")
            time_el = await card.query_selector("time, .job-search-card__listdate")

            title = await title_el.inner_text() if title_el else None
            company = await company_el.inner_text() if company_el else None
            location = await location_el.inner_text() if location_el else None
            url = await link_el.get_attribute("href") if link_el else None

            posted_at = None
            if time_el:
                datetime_attr = await time_el.get_attribute("datetime")
                if datetime_attr:
                    try:
                        from datetime import datetime as dt
                        posted_at = dt.fromisoformat(datetime_attr.replace("Z", "+00:00"))
                    except Exception:
                        pass
                if not posted_at:
                    time_text = await time_el.inner_text()
                    posted_at = self.parse_relative_date(time_text)

            if not title or not url:
                return None

            url = url.split("?")[0] if "?" in url else url
            if not url.startswith("http"):
                url = f"{self.BASE_URL}{url}"

            return {
                "title": self._clean_text(title),
                "company": self._clean_text(company or "Unknown"),
                "location": self._clean_text(location or ""),
                "source_platform": self.platform,
                "source_url": url,
                "apply_url": url,
                "jd_text": "",
                "posted_at": posted_at,
            }
        except Exception as e:
            logger.debug(f"Card parse error: {e}")
            return None

    async def get_job_details(self, page: Page, job_url: str) -> dict:
        """Fetch full JD from LinkedIn job page."""
        try:
            await self.goto_with_retry(page, job_url, wait_for="domcontentloaded")
            await asyncio.sleep(1.5)

            # Expand description if "See more" button exists
            try:
                see_more = await page.query_selector(".show-more-less-html__button--more")
                if see_more:
                    await see_more.click()
                    await asyncio.sleep(0.5)
            except:
                pass

            # Extract fields
            desc_el = await page.query_selector(".show-more-less-html__markup, .description__text")
            title_el = await page.query_selector("h1.top-card-layout__title, .job-details-jobs-unified-top-card__job-title")
            company_el = await page.query_selector(".topcard__org-name-link, .job-details-jobs-unified-top-card__company-name")
            seniority_el = await page.query_selector('[class*="seniority-level"]')
            job_type_el = await page.query_selector('[class*="employment-type"]')
            easy_apply_el = await page.query_selector(".jobs-apply-button--top-card, [data-job-id]")

            jd_text = await desc_el.inner_text() if desc_el else ""
            jd_html = await desc_el.inner_html() if desc_el else ""
            title = await title_el.inner_text() if title_el else ""
            company = await company_el.inner_text() if company_el else ""
            seniority = await seniority_el.inner_text() if seniority_el else ""
            job_type_text = await job_type_el.inner_text() if job_type_el else ""

            # Detect Easy Apply
            is_easy_apply = False
            if easy_apply_el:
                button_text = await easy_apply_el.inner_text()
                is_easy_apply = "easy apply" in button_text.lower()

            # Parse job type
            job_type = JobType.full_time
            if "contract" in job_type_text.lower():
                job_type = JobType.contract
            elif "part" in job_type_text.lower():
                job_type = JobType.part_time
            elif "intern" in job_type_text.lower():
                job_type = JobType.internship

            return {
                "title": self._clean_text(title) or "Unknown",
                "company": self._clean_text(company) or "Unknown",
                "jd_text": self._clean_text(jd_text),
                "jd_html": jd_html,
                "is_easy_apply": is_easy_apply,
                "job_type": job_type,
            }
        except Exception as e:
            logger.error(f"LinkedIn job detail fetch failed for {job_url}: {e}")
            return {"jd_text": ""}

    async def apply_easy_apply(
        self,
        page: Page,
        job_url: str,
        user_profile: dict,
        resume_path: str,
        cover_letter_text: str,
        screening_answerer  # callable(question: str) -> str
    ) -> dict:
        """Submit an Easy Apply application on LinkedIn."""
        result = {"success": False, "application_id": None, "error": None}
        try:
            await self.goto_with_retry(page, job_url)
            await asyncio.sleep(2)

            # Click Easy Apply button
            apply_btn = await page.wait_for_selector(".jobs-apply-button", timeout=10000)
            await apply_btn.click()
            await asyncio.sleep(1.5)

            max_steps = 10
            for step in range(max_steps):
                # Upload resume on first step if field present
                resume_input = await page.query_selector('input[type="file"]')
                if resume_input:
                    await resume_input.set_input_files(resume_path)
                    await asyncio.sleep(1)

                # Handle text inputs (screening questions)
                inputs = await page.query_selector_all('input[type="text"], input[type="number"], textarea')
                for inp in inputs:
                    label_el = await inp.query_selector("xpath=preceding-sibling::label | ../label")
                    label = ""
                    if label_el:
                        label = await label_el.inner_text()
                    if label:
                        answer = await screening_answerer(label)
                        if answer:
                            await self.human_type(page, f'#{await inp.get_attribute("id")}', answer)

                # Handle select dropdowns
                selects = await page.query_selector_all("select")
                for sel in selects:
                    options = await sel.query_selector_all("option")
                    if len(options) > 1:
                        await sel.select_option(index=1)  # Select first non-empty option

                # Handle radio buttons (yes/no questions)
                radios = await page.query_selector_all('input[type="radio"]')
                for radio in radios:
                    value = await radio.get_attribute("value")
                    if value and value.lower() in ["yes", "true"]:
                        await radio.click()
                        break

                # Check for Next / Submit button
                next_btn = await page.query_selector('button[aria-label*="Submit"], button[aria-label*="Next"], button[aria-label*="Review"]')
                if not next_btn:
                    next_btn = await page.query_selector('.artdeco-button--primary')

                if next_btn:
                    btn_text = await next_btn.inner_text()
                    await next_btn.click()
                    await asyncio.sleep(2)

                    if "submit" in btn_text.lower():
                        # Success!
                        result["success"] = True
                        logger.info("LinkedIn Easy Apply submitted successfully")
                        break
                else:
                    break

        except Exception as e:
            result["error"] = str(e)
            logger.error(f"LinkedIn Easy Apply failed: {e}")

        return result
