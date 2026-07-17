"""
Himalayas scraper — remote-jobs board with a free, keyless JSON API.
https://himalayas.app/jobs/api

The API has no keyword parameter, so the query is matched client-side against
title/description (same approach as the ATS aggregator). locationRestrictions
is honored so India users only see jobs open to them; seniority maps onto
experience_level.
"""
import re

from loguru import logger
from scrapers.api_base import APIBaseScraper
from models.job import ExperienceLevel, JobListingCreate, Platform

_HTML = re.compile(r"<[^>]+>")
_STOPWORDS = {"the", "and", "for", "with", "job", "jobs", "developer", "engineer", "role"}

_LEVELS = {
    "entry": ExperienceLevel.entry, "junior": ExperienceLevel.entry,
    "mid": ExperienceLevel.mid, "senior": ExperienceLevel.senior,
    "lead": ExperienceLevel.lead, "principal": ExperienceLevel.principal,
    "manager": ExperienceLevel.lead,
}


class HimalayasScraper(APIBaseScraper):
    platform = Platform.himalayas
    requires_key = False
    regions = {"global", "india"}
    rate_limit_per_minute = 20
    API_URL = "https://himalayas.app/jobs/api"

    # The API caps at 20 jobs per page (verified live 2026-07-16) — paginate.
    _PAGE_SIZE = 20
    _MAX_PAGES = 5

    async def search_jobs(self, query: str, location: str = "", max_results: int = 50,
                          credentials=None, region: str = "india") -> list[JobListingCreate]:
        jobs: list[JobListingCreate] = []
        tokens = [t for t in re.split(r"[^a-z0-9.+#]+", query.lower()) if len(t) >= 3 and t not in _STOPWORDS]

        items: list[dict] = []
        for page in range(self._MAX_PAGES):
            data = await self._get_json(
                self.API_URL, params={"limit": self._PAGE_SIZE, "offset": page * self._PAGE_SIZE}
            )
            batch = (data or {}).get("jobs", [])
            items.extend(batch)
            if len(batch) < self._PAGE_SIZE:
                break

        for item in items:
            url = item.get("applicationLink") or item.get("guid") or ""
            if not self._is_new(url):
                continue
            restrictions = [str(r).lower() for r in (item.get("locationRestrictions") or [])]
            if region == "india" and restrictions and "india" not in restrictions:
                continue
            jd = self._clean_text(_HTML.sub(" ", item.get("description") or item.get("excerpt") or ""))
            if tokens and not any(t in f"{item.get('title', '')} {jd}".lower() for t in tokens):
                continue
            seniority = " ".join(str(s) for s in (item.get("seniority") or [])).lower()
            level = next((v for k, v in _LEVELS.items() if k in seniority), None)
            salary_min, salary_max = item.get("minSalary"), item.get("maxSalary")
            jobs.append(JobListingCreate(
                title=item.get("title") or "Role",
                company=item.get("companyName") or "Company (via Himalayas)",
                company_logo_url=item.get("companyLogo"),
                location=", ".join(str(r) for r in (item.get("locationRestrictions") or [])) or "Remote",
                work_mode="remote",
                is_remote_friendly=True,
                experience_level=level,
                salary_min=int(salary_min) if salary_min else None,
                salary_max=int(salary_max) if salary_max else None,
                salary_currency="USD",
                jd_text=jd or item.get("title", ""),
                source_platform=self.platform,
                source_url=url,
                apply_url=url,
                posted_at=self.parse_posted_at(item.get("pubDate")),
            ))
            if len(jobs) >= max_results:
                break

        logger.info(f"Himalayas: returning {len(jobs)} jobs for '{query}' (region={region})")
        return jobs
