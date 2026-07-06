"""
TimesJobs scraper — public JSON search API.

TimesJobs migrated to a Next.js SPA; the old server-rendered `job-bx` markup is
gone. The SPA is backed by an unauthenticated JSON API (tjapi.timesjobs.com)
that returns fully structured listings, so this runs browserless via httpx.
"""
import re
from loguru import logger
from scrapers.api_base import APIBaseScraper
from models.job import JobListingCreate, Platform


class TimesJobsScraper(APIBaseScraper):
    platform = Platform.timesjobs
    requires_key = False
    regions = {"india"}
    rate_limit_per_minute = 20
    API_URL = "https://tjapi.timesjobs.com/search/api/v1/search/jobs/list"
    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://www.timesjobs.com",
        "Referer": "https://www.timesjobs.com/",
    }

    async def search_jobs(self, query: str, location: str = "India", max_results: int = 50, credentials=None) -> list[JobListingCreate]:
        jobs: list[JobListingCreate] = []
        page = 1
        page_size = 25
        loc = "" if location.lower() in ("india", "") else location

        while len(jobs) < max_results and page <= 4:
            body = {
                "keyword": query, "location": loc, "experience": "",
                "page": str(page), "size": str(page_size),
                "jobFunctions": [], "company": "", "industry": "",
                "functionAreaId": "", "jobFunction": "",
            }
            data = await self._post_json(self.API_URL, json_body=body)
            items = (data or {}).get("jobs") or []
            if not items:
                break

            for item in items:
                job = self._to_listing(item)
                if job and self._is_new(job.source_url):
                    jobs.append(job)
                    if len(jobs) >= max_results:
                        break

            if page >= (data or {}).get("totalPages", 1):
                break
            page += 1

        logger.info(f"TimesJobs: returning {len(jobs)} jobs for '{query}'")
        return jobs

    def _to_listing(self, item: dict):
        url = item.get("jobDetailUrl") or ""
        title = (item.get("title") or "").strip()
        if not url or not title:
            return None

        desc = self._clean_text(re.sub(r"<[^>]+>", " ", item.get("description") or ""))
        skills = [s.strip() for s in (item.get("skills") or "").split(",") if s.strip()]

        # Salary and experience: the API uses -1 for "unspecified" — never emit
        # a fabricated 0/-1; leave None when absent.
        low, high = item.get("lowSalary"), item.get("highSalary")
        salary_min = low if isinstance(low, (int, float)) and low > 0 else None
        salary_max = high if isinstance(high, (int, float)) and high > 0 else None
        exp_from, exp_to = item.get("experienceFrom"), item.get("experienceTo")

        return JobListingCreate(
            title=title,
            company=(item.get("company") or "Company (via TimesJobs)").strip(),
            company_logo_url=item.get("companyLogo"),
            location=(item.get("location") or "India").strip(),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=item.get("currency") or "INR",
            min_experience=exp_from if isinstance(exp_from, (int, float)) and exp_from >= 0 else None,
            max_experience=exp_to if isinstance(exp_to, (int, float)) and exp_to > 0 else None,
            jd_text=desc or title,
            required_skills=skills[:20],
            source_platform=self.platform,
            source_url=url,
            apply_url=url,
            source_job_id=str(item.get("jobId") or item.get("loginId") or ""),
            posted_at=self.parse_posted_at(item.get("postDate")),
        )
