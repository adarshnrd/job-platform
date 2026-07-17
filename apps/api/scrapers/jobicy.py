"""
Jobicy scraper — curated remote-jobs board with a free, keyless JSON API.
https://jobicy.com/jobs-rss-feed · GET /api/v2/remote-jobs

Quality lean: listings are hand-curated (no aggregator spam) and carry a
jobLevel field that maps straight onto our experience_level enum. Roles are
remote-first; geo-restricted ones are filtered so India users only see jobs
they can actually take.
"""
import re

from loguru import logger
from scrapers.api_base import APIBaseScraper
from models.job import ExperienceLevel, JobListingCreate, Platform

_HTML = re.compile(r"<[^>]+>")

# jobLevel → experience_level. Jobicy uses free-ish labels ("Senior", "Any").
_LEVELS = {
    "intern": ExperienceLevel.entry, "junior": ExperienceLevel.entry,
    "entry": ExperienceLevel.entry, "mid": ExperienceLevel.mid,
    "senior": ExperienceLevel.senior, "lead": ExperienceLevel.lead,
    "manager": ExperienceLevel.lead, "expert": ExperienceLevel.principal,
}

# jobGeo values an India-region user can take.
_INDIA_OK = ("anywhere", "worldwide", "india", "apac", "asia", "emea")


class JobicyScraper(APIBaseScraper):
    platform = Platform.jobicy
    requires_key = False
    regions = {"global", "india"}
    rate_limit_per_minute = 20
    API_URL = "https://jobicy.com/api/v2/remote-jobs"

    async def search_jobs(self, query: str, location: str = "", max_results: int = 50,
                          credentials=None, region: str = "india") -> list[JobListingCreate]:
        jobs: list[JobListingCreate] = []
        data = await self._get_json(self.API_URL, params={"count": min(max_results, 50), "tag": query})
        for item in (data or {}).get("jobs", []):
            url = item.get("url") or ""
            if not self._is_new(url):
                continue
            geo = (item.get("jobGeo") or "").lower()
            if region == "india" and geo and not any(tok in geo for tok in _INDIA_OK):
                continue
            level_raw = (item.get("jobLevel") or "").lower()
            level = next((v for k, v in _LEVELS.items() if k in level_raw), None)
            jd = self._clean_text(_HTML.sub(" ", item.get("jobDescription") or item.get("jobExcerpt") or ""))
            salary_min, salary_max = item.get("annualSalaryMin"), item.get("annualSalaryMax")
            jobs.append(JobListingCreate(
                title=item.get("jobTitle") or "Role",
                company=item.get("companyName") or "Company (via Jobicy)",
                company_logo_url=item.get("companyLogo"),
                location=item.get("jobGeo") or "Remote",
                work_mode="remote",
                is_remote_friendly=True,
                experience_level=level,
                salary_min=int(salary_min) if salary_min else None,
                salary_max=int(salary_max) if salary_max else None,
                salary_currency=item.get("salaryCurrency") or "USD",
                jd_text=jd or item.get("jobTitle", ""),
                source_platform=self.platform,
                source_url=url,
                apply_url=url,
                posted_at=self.parse_posted_at(item.get("pubDate")),
            ))
            if len(jobs) >= max_results:
                break

        logger.info(f"Jobicy: returning {len(jobs)} jobs for '{query}' (region={region})")
        return jobs
