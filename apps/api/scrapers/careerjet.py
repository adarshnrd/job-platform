"""
Careerjet scraper — job-search aggregator API with strong India coverage.
https://www.careerjet.com/partners/api/ · locale en_IN.

Needs a free affiliate id (CAREERJET_AFFID) from partners.careerjet.com.
Dormant until it is set — same pattern as Adzuna/Jooble/JSearch.

MENA: Careerjet runs careerjet.ae / .com.sa / .com.eg / .com.kw, so a mena
search picks the locale by the searched country. The `en_AE`-style codes are
NOT verified against the live API (docs/mena/PHASE_2_REGIONAL_BOARDS.md §2.7);
an error or empty answer is logged once per locale and returns [].
"""
import re

from loguru import logger
from scrapers.api_base import APIBaseScraper
from models.job import JobListingCreate, Platform
from config import settings
from scrapers.mena_common import currency_from
from services.geo import mena

_REGION_LOCALE = {"india": "en_IN", "global": "en_GB", "mena": "en_AE"}
# mena: locale per searched country (unverified guesses, see module docstring).
_MENA_LOCALES = {"AE": "en_AE", "SA": "en_SA", "EG": "en_EG", "KW": "en_KW", "QA": "en_QA"}


def locale_for(region: str, location: str = "") -> str:
    if region == "mena":
        return _MENA_LOCALES.get(mena.country_of(location), _REGION_LOCALE["mena"])
    return _REGION_LOCALE.get(region, "en_IN")
_HTML = re.compile(r"<[^>]+>")


class CareerjetScraper(APIBaseScraper):
    platform = Platform.careerjet
    requires_key = True
    regions = {"india", "global", "mena"}
    rate_limit_per_minute = 20
    API_URL = "https://public.api.careerjet.net/search"

    _warned_locales: set = set()  # log a bad MENA locale once per process, not per search

    @staticmethod
    def has_key() -> bool:
        return bool(settings.CAREERJET_AFFID)

    async def search_jobs(self, query: str, location: str = "", max_results: int = 50, credentials=None, region: str = "india") -> list[JobListingCreate]:
        jobs: list[JobListingCreate] = []
        if not self.has_key():
            logger.info("Careerjet skipped — CAREERJET_AFFID not set")
            return jobs

        data = await self._get_json(self.API_URL, params={
            "keywords": query,
            "location": location if region in ("india", "mena") else "",
            "affid": settings.CAREERJET_AFFID,
            "user_ip": "11.22.33.44",
            "user_agent": "Mozilla/5.0 (compatible; JobPlatformBot/1.0)",
            "locale_code": locale_for(region, location),
            "pagesize": min(max_results, 99),
            "sort": "date",
        })
        if not data or data.get("type") != "JOBS":
            if region == "mena":
                locale = locale_for(region, location)
                if locale not in self._warned_locales:
                    self._warned_locales.add(locale)
                    logger.warning(f"Careerjet: locale {locale} gave no JOBS answer ({(data or {}).get('type')})")
            return jobs

        for item in data.get("jobs", []):
            url = item.get("url") or ""
            if not self._is_new(url):
                continue
            salary_min = item.get("salary_min")
            salary_max = item.get("salary_max")
            jobs.append(JobListingCreate(
                title=item.get("title", "Role"),
                company=item.get("company") or "Company (via Careerjet)",
                location=item.get("locations") or (location if region == "mena" and location else "India"),
                salary_min=int(salary_min) if salary_min else None,
                salary_max=int(salary_max) if salary_max else None,
                salary_currency=(
                    currency_from(item.get("locations"), location) if region == "mena"
                    # Global runs use the en_GB locale; salary_currency must be a str.
                    else ("INR" if region == "india" else "GBP")
                ),
                jd_text=self._clean_text(_HTML.sub(" ", item.get("description", ""))) or item.get("title", ""),
                required_skills=[],
                source_platform=self.platform,
                source_url=url,
                apply_url=url,
                posted_at=self.parse_posted_at(item.get("date")),
            ))
            if len(jobs) >= max_results:
                break

        logger.info(f"Careerjet: returning {len(jobs)} jobs for '{query}' (region={region})")
        return jobs
