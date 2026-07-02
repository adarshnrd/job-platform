"""
Remotive scraper — public JSON API for remote jobs (no key, global).
https://remotive.com/api/remote-jobs
"""
import re
from loguru import logger
from scrapers.api_base import APIBaseScraper
from models.job import JobListingCreate, Platform


class RemotiveScraper(APIBaseScraper):
    platform = Platform.remotive
    requires_key = False
    regions = {"global", "remote", "india"}  # remote roles are open to India too
    rate_limit_per_minute = 10
    API_URL = "https://remotive.com/api/remote-jobs"

    async def search_jobs(self, query: str, location: str = "", max_results: int = 50, credentials=None) -> list[JobListingCreate]:
        jobs: list[JobListingCreate] = []
        data = await self._get_json(self.API_URL, params={"search": query, "limit": max_results})
        if not data:
            return jobs

        for item in data.get("jobs", []):
            url = item.get("url") or ""
            if not self._is_new(url):
                continue

            jd_html = item.get("description") or ""
            jd_text = self._clean_text(re.sub(r"<[^>]+>", " ", jd_html))

            jobs.append(JobListingCreate(
                title=item.get("title", "Remote Role"),
                company=item.get("company_name", "Unknown"),
                company_logo_url=item.get("company_logo_url") or item.get("company_logo"),
                location=item.get("candidate_required_location") or "Remote",
                work_mode="remote",
                is_remote_friendly=True,
                salary_min=None,
                salary_max=None,
                jd_text=jd_text or item.get("title", ""),
                jd_html=jd_html,
                required_skills=list(item.get("tags") or [])[:15],
                source_platform=self.platform,
                source_url=url,
                apply_url=url,
                source_job_id=str(item.get("id", "")),
                posted_at=self.parse_posted_at(item.get("publication_date")),
            ))
            if len(jobs) >= max_results:
                break

        logger.info(f"Remotive: returning {len(jobs)} jobs for '{query}'")
        return jobs
