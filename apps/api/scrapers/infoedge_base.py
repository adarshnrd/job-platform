"""
Shared base for Info Edge tech/management boards (Hirist, iimjobs).

Both are React SPAs backed by the same public "gladiator" JSON search API
(gladiator.<site>/job/search?query=...). This runs browserless via httpx and
returns fully structured listings, so subclasses only declare their hosts.
"""
import re
from datetime import datetime
from typing import Optional

from loguru import logger

from scrapers.api_base import APIBaseScraper
from models.job import JobListingCreate


class InfoEdgeGladiatorScraper(APIBaseScraper):
    """Base for gladiator-API boards. Subclasses set SITE_HOST + GLADIATOR_HOST."""
    requires_key = False
    regions = {"india"}
    rate_limit_per_minute = 15

    SITE_HOST: str = ""        # e.g. "www.hirist.tech"
    GLADIATOR_HOST: str = ""   # e.g. "gladiator.hirist.tech"

    @property
    def _api_url(self) -> str:
        return f"https://{self.GLADIATOR_HOST}/job/search"

    @property
    def DEFAULT_HEADERS(self) -> dict:  # noqa: N802 (matches base attr name)
        return {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            "Accept": "application/json",
            "Origin": f"https://{self.SITE_HOST}",
            "Referer": f"https://{self.SITE_HOST}/",
        }

    async def search_jobs(self, query: str, location: str = "India", max_results: int = 50, credentials=None) -> list[JobListingCreate]:
        jobs: list[JobListingCreate] = []
        page = 0
        page_size = 20

        while len(jobs) < max_results and page < 5:
            params = {"query": query, "page": page, "size": page_size, "posting": 0, "industry": ""}
            data = await self._get_json(self._api_url, params=params)
            items = (data or {}).get("data") or []
            if not items:
                break

            for item in items:
                job = self._to_listing(item, location)
                if job and self._is_new(job.source_url):
                    jobs.append(job)
                    if len(jobs) >= max_results:
                        break

            if not (data or {}).get("hasMore"):
                break
            page += 1

        logger.info(f"{self.platform.value}: returning {len(jobs)} jobs for '{query}'")
        return jobs

    def _to_listing(self, item: dict, wanted_location: str) -> Optional[JobListingCreate]:
        url = item.get("jobDetailUrl") or ""
        raw_title = (item.get("title") or "").strip()
        if not url or not raw_title:
            return None

        # Hirist/iimjobs title convention is "Company - Role[- extra]".
        company, title = self._split_company_title(raw_title, item)
        locations = item.get("locations") or item.get("location") or []
        loc_names = [loc.get("name") for loc in locations if isinstance(loc, dict) and loc.get("name")]
        location_text = ", ".join(loc_names) if loc_names else "India"

        skills = [t.get("name") for t in (item.get("tags") or []) if isinstance(t, dict) and t.get("name")]
        designation = item.get("jobdesignation") or title
        jd_text = self._compose_jd(designation, company, location_text, skills, item)

        # Salary hidden unless hideSal is falsy and values are positive.
        min_sal, max_sal = item.get("minSal"), item.get("maxSal")
        hide = item.get("hideSal")
        salary_min = min_sal if not hide and isinstance(min_sal, (int, float)) and min_sal > 0 else None
        salary_max = max_sal if not hide and isinstance(max_sal, (int, float)) and max_sal > 0 else None

        min_exp, max_exp = item.get("min"), item.get("max")

        return JobListingCreate(
            title=title,
            company=company,
            location=location_text,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency="INR",
            min_experience=min_exp if isinstance(min_exp, (int, float)) and min_exp >= 0 else None,
            max_experience=max_exp if isinstance(max_exp, (int, float)) and max_exp > 0 else None,
            jd_text=jd_text,
            required_skills=skills[:20],
            source_platform=self.platform,
            source_url=url,
            apply_url=item.get("applyUrl") or url,
            source_job_id=str(item.get("id") or ""),
            posted_at=_epoch_ms_to_dt(item.get("createdTime")),
        )

    @staticmethod
    def _split_company_title(raw_title: str, item: dict) -> tuple[str, str]:
        parts = [p.strip() for p in raw_title.split(" - ") if p.strip()]
        if len(parts) >= 2 and parts[0].lower() != "confidential":
            return parts[0], " - ".join(parts[1:])
        # Confidential / no delimiter → derive from domain, else generic label.
        domain = item.get("creatorDomainName") or ""
        if domain and "." in domain and item.get("confidential") != 1:
            company = domain.split(".")[0].replace("-", " ").title()
            return company, raw_title
        return "Company (confidential)", raw_title

    @staticmethod
    def _compose_jd(designation: str, company: str, location: str, skills: list, item: dict) -> str:
        exp = ""
        if isinstance(item.get("min"), (int, float)):
            exp = f" Experience: {item.get('min')}-{item.get('max')} years."
        skills_str = f" Key skills: {', '.join(skills[:15])}." if skills else ""
        return re.sub(r"\s+", " ", f"{designation} at {company} — {location}.{exp}{skills_str}").strip()

    async def get_job_details(self, *args, **kwargs) -> dict:
        return {}


def _epoch_ms_to_dt(ms) -> Optional[datetime]:
    try:
        return datetime.utcfromtimestamp(int(ms) / 1000)
    except Exception:
        return None
