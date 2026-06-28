"""
Arbeitnow scraper — public JSON job board API (no key, EU/global remote).
https://www.arbeitnow.com/api/job-board-api
Filters client-side by query keywords (the API has no search param).
"""
import re
from datetime import datetime
from loguru import logger
from scrapers.api_base import APIBaseScraper
from models.job import JobListingCreate, Platform


class ArbeitnowScraper(APIBaseScraper):
    platform = Platform.arbeitnow
    requires_key = False
    regions = {"global", "remote"}
    rate_limit_per_minute = 20
    API_URL = "https://www.arbeitnow.com/api/job-board-api"

    async def search_jobs(self, query: str, location: str = "", max_results: int = 50, credentials=None) -> list[JobListingCreate]:
        jobs: list[JobListingCreate] = []
        keywords = [k for k in query.lower().split() if k]

        # Paginate a few pages (API returns ~100/page).
        for page in range(1, 4):
            data = await self._get_json(self.API_URL, params={"page": page})
            if not data or not data.get("data"):
                break

            for item in data["data"]:
                title = (item.get("title") or "").lower()
                tags = [t.lower() for t in (item.get("tags") or [])]
                combined = title + " " + " ".join(tags)
                if keywords and not any(kw in combined for kw in keywords):
                    continue

                url = item.get("url") or ""
                if not self._is_new(url):
                    continue

                jd_html = item.get("description") or ""
                jd_text = self._clean_text(re.sub(r"<[^>]+>", " ", jd_html))

                jobs.append(JobListingCreate(
                    title=item.get("title", "Role"),
                    company=item.get("company_name", "Unknown"),
                    location=item.get("location") or ("Remote" if item.get("remote") else ""),
                    work_mode="remote" if item.get("remote") else None,
                    is_remote_friendly=bool(item.get("remote")),
                    jd_text=jd_text or item.get("title", ""),
                    jd_html=jd_html,
                    required_skills=list(item.get("tags") or [])[:15],
                    source_platform=self.platform,
                    source_url=url,
                    apply_url=url,
                    source_job_id=item.get("slug", ""),
                    posted_at=self.parse_posted_at(item.get("created_at")),
                ))
                if len(jobs) >= max_results:
                    break
            if len(jobs) >= max_results:
                break

        logger.info(f"Arbeitnow: returning {len(jobs)} jobs for '{query}'")
        return jobs
