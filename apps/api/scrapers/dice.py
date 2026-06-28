"""Dice.com job scraper using their public search API."""
import asyncio
import httpx
from loguru import logger
from scrapers.base import BaseScraper
from models.job import JobListingCreate, Platform


class DiceScraper(BaseScraper):
    platform = Platform.dice
    rate_limit_per_minute = 20
    API_URL = "https://job-search-api.svc.dhigroupinc.com/v1/dice/jobs/search"

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
                "q": query,
                "countryCode2": "US",
                "radius": "30",
                "radiusUnit": "mi",
                "page": 1,
                "pageSize": min(max_results, 50),
                "filters.postedDate": "ONE_DAY",
                "language": "en",
            }
            headers = {
                "x-api-key": "1YAt0R9wBg4WfsF9VB2778F5CHLAPMVH3ITP",
                "User-Agent": "Mozilla/5.0 (compatible; JobSearchBot/1.0)",
            }
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(self.API_URL, params=params, headers=headers)
                if resp.status_code != 200:
                    logger.warning(f"Dice API returned {resp.status_code}")
                    return []
                data = resp.json()

            listings = data.get("data", [])
            logger.info(f"Dice: found {len(listings)} jobs")

            for item in listings[:max_results]:
                try:
                    job_id = item.get("id", "")
                    title = item.get("title", "")
                    company = item.get("advertiser", {}).get("name", "Unknown")
                    location_text = item.get("location", "")
                    description = item.get("jobDescription", "")
                    job_url = f"https://www.dice.com/job-detail/{job_id}"
                    is_remote = item.get("isRemote", False)

                    if not title or not job_id:
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
                        required_skills=item.get("skills", []),
                        is_remote_friendly=is_remote,
                        work_mode="remote" if is_remote else "on-site",
                    ))
                except Exception as e:
                    logger.debug(f"Dice item error: {e}")
                    continue
        except Exception as e:
            logger.error(f"Dice search failed: {e}")
        return jobs
