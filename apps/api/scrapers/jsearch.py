"""
JSearch scraper — Google-for-Jobs aggregator via RapidAPI (freemium, global).
Aggregates LinkedIn, Indeed, Glassdoor, etc. Needs JSEARCH_RAPIDAPI_KEY.
https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch
Dormant until key is set.
"""
from loguru import logger
from scrapers.api_base import APIBaseScraper
from models.job import JobListingCreate, Platform
from config import settings


class JSearchScraper(APIBaseScraper):
    platform = Platform.jsearch
    requires_key = True
    regions = {"india", "global"}
    rate_limit_per_minute = 15
    BASE_URL = "https://jsearch.p.rapidapi.com/search"

    @staticmethod
    def has_key() -> bool:
        return bool(settings.JSEARCH_RAPIDAPI_KEY)

    async def search_jobs(self, query: str, location: str = "", max_results: int = 50, credentials=None, region: str = "india") -> list[JobListingCreate]:
        jobs: list[JobListingCreate] = []
        if not self.has_key():
            logger.info("JSearch skipped — JSEARCH_RAPIDAPI_KEY not set")
            return jobs

        country = "in" if region == "india" else "us"
        full_query = f"{query} in {location}" if location else query

        headers = {
            "X-RapidAPI-Key": settings.JSEARCH_RAPIDAPI_KEY,
            "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
        }
        data = await self._get_json(
            self.BASE_URL,
            params={"query": full_query, "page": "1", "num_pages": "2", "country": country},
            headers=headers,
        )
        if not data:
            return jobs

        for item in data.get("data", []):
            url = item.get("job_apply_link") or item.get("job_google_link") or ""
            if not self._is_new(url):
                continue

            loc_parts = [item.get("job_city"), item.get("job_state"), item.get("job_country")]
            loc = ", ".join(p for p in loc_parts if p)

            jobs.append(JobListingCreate(
                title=item.get("job_title", "Role"),
                company=item.get("employer_name") or "Unknown",
                company_logo_url=item.get("employer_logo"),
                location=loc,
                work_mode="remote" if item.get("job_is_remote") else None,
                is_remote_friendly=bool(item.get("job_is_remote")),
                salary_min=int(item["job_min_salary"]) if item.get("job_min_salary") else None,
                salary_max=int(item["job_max_salary"]) if item.get("job_max_salary") else None,
                jd_text=self._clean_text(item.get("job_description", "")),
                required_skills=[],
                source_platform=self.platform,
                source_url=url,
                apply_url=url,
                source_job_id=str(item.get("job_id", "")),
                posted_at=self.parse_posted_at(item.get("job_posted_at_datetime_utc")),
            ))
            if len(jobs) >= max_results:
                break

        logger.info(f"JSearch: returning {len(jobs)} jobs for '{query}' (region={region})")
        return jobs
