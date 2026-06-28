"""
The Muse scraper — public JSON API (no key, global, supports location filter).
https://www.themuse.com/api/public/jobs
This is the primary keyless India-capable API source (location=India).
"""
import re
from datetime import datetime
from loguru import logger
from scrapers.api_base import APIBaseScraper
from models.job import JobListingCreate, Platform


class TheMuseScraper(APIBaseScraper):
    platform = Platform.themuse
    requires_key = False
    regions = {"global", "india", "remote"}
    rate_limit_per_minute = 20
    API_URL = "https://www.themuse.com/api/public/jobs"

    async def search_jobs(self, query: str, location: str = "", max_results: int = 50, credentials=None) -> list[JobListingCreate]:
        jobs: list[JobListingCreate] = []
        keywords = [k for k in query.lower().split() if k]

        params = {"page": 1}
        # The Muse expects city names; map common India searches sensibly.
        if location:
            loc = location.strip()
            if loc.lower() in ("india", "in"):
                params["location"] = "Bangalore, India"
            else:
                params["location"] = loc

        for page in range(1, 4):
            params["page"] = page
            data = await self._get_json(self.API_URL, params=params)
            if not data or not data.get("results"):
                break

            for item in data["results"]:
                title = (item.get("name") or "")
                if keywords and not any(kw in title.lower() for kw in keywords):
                    continue

                refs = item.get("refs") or {}
                url = refs.get("landing_page") or ""
                if not self._is_new(url):
                    continue

                company = (item.get("company") or {}).get("name", "Unknown")
                locs = item.get("locations") or []
                location_text = ", ".join(l.get("name", "") for l in locs) or location
                is_remote = any("remote" in (l.get("name", "").lower()) for l in locs)

                jd_html = item.get("contents") or ""
                jd_text = self._clean_text(re.sub(r"<[^>]+>", " ", jd_html))

                levels = item.get("levels") or []
                level_name = levels[0].get("name", "") if levels else ""

                jobs.append(JobListingCreate(
                    title=title or "Role",
                    company=company,
                    location=location_text,
                    work_mode="remote" if is_remote else None,
                    is_remote_friendly=is_remote,
                    jd_text=jd_text or title,
                    jd_html=jd_html,
                    required_skills=[],
                    source_platform=self.platform,
                    source_url=url,
                    apply_url=url,
                    source_job_id=str(item.get("id", "")),
                    experience_level=self._map_level(level_name),
                    posted_at=self.parse_posted_at(item.get("publication_date")),
                ))
                if len(jobs) >= max_results:
                    break
            if len(jobs) >= max_results:
                break

        logger.info(f"TheMuse: returning {len(jobs)} jobs for '{query}' (location={location})")
        return jobs

    @staticmethod
    def _map_level(name: str):
        n = (name or "").lower()
        if "senior" in n:
            return "senior"
        if "entry" in n or "junior" in n:
            return "entry"
        if "mid" in n:
            return "mid"
        if "management" in n or "lead" in n:
            return "lead"
        return None
