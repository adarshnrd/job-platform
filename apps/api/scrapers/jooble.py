"""
Jooble scraper — aggregator API (free key, ~70 countries incl. India).
https://jooble.org/api/about
Needs JOOBLE_API_KEY in .env. Dormant until set.
"""
import re
from loguru import logger
from scrapers.api_base import APIBaseScraper
from models.job import JobListingCreate, Platform
from config import settings


class JoobleScraper(APIBaseScraper):
    platform = Platform.jooble
    requires_key = True
    regions = {"india", "global"}
    rate_limit_per_minute = 20
    BASE_URL = "https://jooble.org/api"

    @staticmethod
    def has_key() -> bool:
        return bool(settings.JOOBLE_API_KEY)

    async def search_jobs(self, query: str, location: str = "", max_results: int = 50, credentials=None, region: str = "india") -> list[JobListingCreate]:
        jobs: list[JobListingCreate] = []
        if not self.has_key():
            logger.info("Jooble skipped — JOOBLE_API_KEY not set")
            return jobs

        where = location or ("India" if region == "india" else "")
        data = await self._post_json(
            f"{self.BASE_URL}/{settings.JOOBLE_API_KEY}",
            json_body={"keywords": query, "location": where, "page": "1"},
        )
        if not data:
            return jobs

        for item in data.get("jobs", []):
            url = item.get("link") or ""
            if not self._is_new(url):
                continue

            jd_html = item.get("snippet") or ""
            jd_text = self._clean_text(re.sub(r"<[^>]+>", " ", jd_html))

            jobs.append(JobListingCreate(
                title=item.get("title", "Role"),
                company=item.get("company") or "Unknown",
                location=item.get("location") or where,
                jd_text=jd_text or item.get("title", ""),
                jd_html=jd_html,
                required_skills=[],
                source_platform=self.platform,
                source_url=url,
                apply_url=url,
                source_job_id=str(item.get("id", "")),
                posted_at=self.parse_posted_at(item.get("updated")),
            ))
            if len(jobs) >= max_results:
                break

        logger.info(f"Jooble: returning {len(jobs)} jobs for '{query}' (region={region})")
        return jobs
