"""ZipRecruiter job scraper using their public job feed API."""
import asyncio
import httpx
from loguru import logger
from scrapers.base import BaseScraper
from models.job import JobListingCreate, Platform


class ZipRecruiterScraper(BaseScraper):
    platform = Platform.ziprecruiter
    rate_limit_per_minute = 15
    API_URL = "https://api.ziprecruiter.com/jobs/v1"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def search_jobs(
        self, query: str, location: str = "Remote",
        max_results: int = 50, credentials=None
    ) -> list[JobListingCreate]:
        return await self._fetch_jobs(query, location, max_results)

    async def _fetch_jobs(self, query: str, location: str, max_results: int) -> list[JobListingCreate]:
        jobs = []
        try:
            params = {
                "search": query,
                "location": location,
                "radius_miles": 50,
                "days_ago": 1,
                "jobs_per_page": min(max_results, 50),
                "page": 1,
            }
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "application/json",
            }
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    "https://www.ziprecruiter.com/api/3/job_search",
                    params=params, headers=headers
                )
                if resp.status_code != 200:
                    logger.warning(f"ZipRecruiter returned {resp.status_code}, trying fallback")
                    return await self._playwright_fallback(query, location, max_results)
                data = resp.json()

            listings = data.get("jobs", [])
            logger.info(f"ZipRecruiter: found {len(listings)} jobs")

            for item in listings[:max_results]:
                try:
                    title = item.get("title", "")
                    company = item.get("hiring_company", {}).get("name", "Unknown")
                    location_text = item.get("location", "")
                    description = item.get("snippet", "") or item.get("job_description", "")
                    job_url = item.get("url", "") or item.get("job_url", "")
                    salary_min = item.get("base_salary_min")
                    salary_max = item.get("base_salary_max")

                    if not title or not job_url:
                        continue
                    if self.is_seen(job_url):
                        continue

                    jobs.append(JobListingCreate(
                        title=self._clean_text(title),
                        company=self._clean_text(company),
                        location=self._clean_text(location_text),
                        source_platform=self.platform,
                        source_url=job_url,
                        apply_url=job_url,
                        jd_text=self._clean_text(description),
                        salary_min=int(salary_min) if salary_min else None,
                        salary_max=int(salary_max) if salary_max else None,
                        salary_currency="USD",
                    ))
                except Exception as e:
                    logger.debug(f"ZipRecruiter item error: {e}")
                    continue
        except Exception as e:
            logger.error(f"ZipRecruiter fetch failed: {e}")
        return jobs

    async def _playwright_fallback(self, query: str, location: str, max_results: int) -> list[JobListingCreate]:
        """Fall back to Playwright if the API is blocked."""
        jobs = []
        await self._start_browser()
        page = await self.new_page()
        try:
            q = query.replace(" ", "+")
            loc = location.replace(" ", "+")
            url = f"https://www.ziprecruiter.com/Jobs/{q}?location={loc}&days=1"
            await self.goto_with_retry(page, url)
            await asyncio.sleep(2)

            cards = await page.query_selector_all(
                "[data-testid='job-card'], article.job_result, .job_content"
            )
            logger.info(f"ZipRecruiter (Playwright): found {len(cards)} cards")

            for card in cards[:max_results]:
                try:
                    title_el = await card.query_selector("h2 a, .job_title, [data-testid='job-title']")
                    company_el = await card.query_selector(".hiring_company_text, [data-testid='job-company']")
                    location_el = await card.query_selector(".location, [data-testid='job-location']")

                    title = await title_el.inner_text() if title_el else None
                    job_url = await title_el.get_attribute("href") if title_el else None
                    company = await company_el.inner_text() if company_el else "Unknown"
                    location_text = await location_el.inner_text() if location_el else ""

                    if not title or not job_url:
                        continue
                    if not job_url.startswith("http"):
                        job_url = f"https://www.ziprecruiter.com{job_url}"
                    if self.is_seen(job_url):
                        continue

                    jobs.append(JobListingCreate(
                        title=self._clean_text(title),
                        company=self._clean_text(company),
                        location=self._clean_text(location_text),
                        source_platform=self.platform,
                        source_url=job_url,
                        apply_url=job_url,
                        jd_text="",
                    ))
                except Exception as e:
                    logger.debug(f"ZipRecruiter card error: {e}")
                    continue
        except Exception as e:
            logger.error(f"ZipRecruiter Playwright fallback failed: {e}")
        finally:
            await page.close()
            await self._stop_browser()
        return jobs
