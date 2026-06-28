"""
Adzuna scraper — structured job API (free key, ~20 countries incl. India/UK/US).
https://developer.adzuna.com/
Needs ADZUNA_APP_ID + ADZUNA_APP_KEY in .env. Dormant until both are set.
"""
from datetime import datetime
from loguru import logger
from scrapers.api_base import APIBaseScraper
from models.job import JobListingCreate, Platform
from config import settings


# Region → Adzuna country codes to query.
_REGION_COUNTRIES = {
    "india": ["in"],
    "global": ["us", "gb", "in"],
}


class AdzunaScraper(APIBaseScraper):
    platform = Platform.adzuna
    requires_key = True
    regions = {"india", "global"}
    rate_limit_per_minute = 25
    BASE_URL = "https://api.adzuna.com/v1/api/jobs"

    @staticmethod
    def has_key() -> bool:
        return bool(settings.ADZUNA_APP_ID and settings.ADZUNA_APP_KEY)

    async def search_jobs(self, query: str, location: str = "", max_results: int = 50, credentials=None, region: str = "india") -> list[JobListingCreate]:
        jobs: list[JobListingCreate] = []
        if not self.has_key():
            logger.info("Adzuna skipped — ADZUNA_APP_ID/APP_KEY not set")
            return jobs

        countries = _REGION_COUNTRIES.get(region, ["in"])
        per_country = max(10, max_results // len(countries))

        for country in countries:
            data = await self._get_json(
                f"{self.BASE_URL}/{country}/search/1",
                params={
                    "app_id": settings.ADZUNA_APP_ID,
                    "app_key": settings.ADZUNA_APP_KEY,
                    "what": query,
                    "where": location if region == "india" else "",
                    "results_per_page": per_country,
                    "content-type": "application/json",
                },
            )
            if not data:
                continue

            for item in data.get("results", []):
                url = item.get("redirect_url") or ""
                if not self._is_new(url):
                    continue

                company = (item.get("company") or {}).get("display_name", "Unknown")
                loc = (item.get("location") or {}).get("display_name", "")

                jobs.append(JobListingCreate(
                    title=item.get("title", "Role"),
                    company=company,
                    location=loc,
                    salary_min=int(item["salary_min"]) if item.get("salary_min") else None,
                    salary_max=int(item["salary_max"]) if item.get("salary_max") else None,
                    salary_currency="INR" if country == "in" else ("GBP" if country == "gb" else "USD"),
                    jd_text=self._clean_text(item.get("description", "")),
                    required_skills=[],
                    source_platform=self.platform,
                    source_url=url,
                    apply_url=url,
                    source_job_id=str(item.get("id", "")),
                    posted_at=self.parse_posted_at(item.get("created")),
                ))
                if len(jobs) >= max_results:
                    break
            if len(jobs) >= max_results:
                break

        logger.info(f"Adzuna: returning {len(jobs)} jobs for '{query}' (region={region})")
        return jobs
