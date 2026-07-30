"""
Foundit (formerly Monster) — via the site's own `/middleware/jobsearch` JSON API.

The public HTML search is Akamai-walled (403 to every headless browser), but the
JSON endpoint its own frontend calls answers fine with an Accept/Referer pair.
That response is *richer* than the rendered page: explicit experience ranges,
salary bounds with currency, skill lists and posting epochs — all fields the
old Playwright scraper had to guess at, and several the job model wants but
most sources never supply.

Foundit runs one deployment per country on its own TLD sharing this API, so a
single scraper covers India plus the APAC markets. Only domains verified to
answer are listed (checked 2026-07-27); foundit.ae / .com.my / .qa did not
respond and are deliberately omitted rather than shipped as dead endpoints.

Full JD text is not in the list response — each listing's detail page carries a
schema.org JobPosting instead. Listings are enriched from it in bounded batches
(DETAIL_FETCH_LIMIT) and fall back to a synthesized summary built from the
structured fields, which already carry most of the scoring signal.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from loguru import logger

from models.job import JobListingCreate, JobType, Platform, WorkMode
from scrapers.api_base import APIBaseScraper
from scrapers.jsonld import parse_job_posting

# region → (domain, default location label, currency). India first: it is this
# deployment's home market and the only one with `india` region coverage.
COUNTRY_SITES: dict[str, tuple[str, str, str]] = {
    "india":     ("www.foundit.in", "India", "INR"),
    "singapore": ("www.foundit.sg", "Singapore", "SGD"),
    "indonesia": ("www.foundit.id", "Indonesia", "IDR"),
    "hongkong":  ("www.foundit.hk", "Hong Kong", "HKD"),
}

# Locations that should route to a non-India Foundit deployment.
_LOCATION_ROUTES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("singapore", "sg"), "singapore"),
    (("indonesia", "jakarta", "bandung", "surabaya"), "indonesia"),
    (("hong kong", "hongkong", "kowloon"), "hongkong"),
)

_EMPLOYMENT_TYPES: dict[str, JobType] = {
    "full time": JobType.full_time, "part time": JobType.part_time,
    "contract": JobType.contract, "freelance": JobType.freelance,
    "internship": JobType.internship, "temporary": JobType.contract,
}


class FounditScraper(APIBaseScraper):
    platform = Platform.foundit
    requires_key = False
    regions = {"india", "global"}
    rate_limit_per_minute = 20

    PAGE_SIZE = 50           # the API returns ~50 real listings per page
    MAX_PAGES = 3
    DETAIL_FETCH_LIMIT = 12  # JD enrichment requests per search — keeps runs bounded

    DEFAULT_HEADERS = {
        # The middleware rejects the bot UA with "content negotiation failed";
        # it needs a browser UA *and* an explicit JSON Accept.
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }

    @staticmethod
    def _site_for(location: str, region: str) -> tuple[str, str, str]:
        """Pick the country deployment for a search. Falls back to India."""
        low = (location or "").lower()
        for needles, key in _LOCATION_ROUTES:
            if any(n in low for n in needles):
                return COUNTRY_SITES[key]
        if region != "india":
            # A global run with an unrecognised city: Singapore is the widest
            # English-language APAC board of the four.
            return COUNTRY_SITES["singapore"]
        return COUNTRY_SITES["india"]

    async def search_jobs(
        self,
        query: str,
        location: str = "",
        max_results: int = 50,
        credentials: Optional[dict] = None,
        region: str = "india",
    ) -> list[JobListingCreate]:
        domain, default_location, currency = self._site_for(location, region)
        jobs: list[JobListingCreate] = []

        for page in range(self.MAX_PAGES):
            if len(jobs) >= max_results:
                break
            data = await self._get_json(
                f"https://{domain}/middleware/jobsearch",
                params={
                    "start": page * self.PAGE_SIZE,
                    "sort": 1,                    # 1 = most recent
                    "limit": self.PAGE_SIZE,
                    "query": query,
                    "locations": location or "",
                },
                headers={"Referer": f"https://{domain}/"},
            )
            response = (data or {}).get("jobSearchResponse") or {}
            items = response.get("data") or []
            # The feed interleaves ad/placeholder objects ({"index","type"}) with
            # real listings — only entries carrying a jobId are jobs.
            listings = [i for i in items if isinstance(i, dict) and i.get("jobId")]
            if not listings:
                break

            for item in listings:
                job = self._to_listing(item, domain, default_location, currency)
                if job:
                    jobs.append(job)
                    if len(jobs) >= max_results:
                        break

            total = ((response.get("meta") or {}).get("paging") or {}).get("total")
            if total is not None and (page + 1) * self.PAGE_SIZE >= total:
                break

        await self._enrich_descriptions(jobs)
        logger.info(f"Foundit: returning {len(jobs)} jobs for '{query}' ({domain})")
        return jobs

    # ── mapping ──
    def _to_listing(
        self, item: dict, domain: str, default_location: str, currency: str
    ) -> Optional[JobListingCreate]:
        if not item.get("isJobActive", True):
            return None
        path = item.get("seoJdUrl") or item.get("jdUrl") or ""
        if not path:
            return None
        url = path if path.startswith("http") else f"https://{domain}{path}"
        if not self._is_new(url):
            return None

        location = self._clean_text(item.get("locations") or "") or default_location
        remote = "remote" in location.lower() or "work from home" in location.lower()

        employment = " ".join(str(e) for e in (item.get("employmentTypes") or []))
        job_type = self.match_terms(employment, _EMPLOYMENT_TYPES, JobType.full_time)

        # Foundit marks confidential pay with hideSalary — the numbers are still
        # in the payload but must not be shown or scored against.
        salary_min = salary_max = None
        if not (item.get("hideSalary") or item.get("jobSalaryConfidential")):
            salary_min = self._salary_value(item.get("minimumSalary"))
            salary_max = self._salary_value(item.get("maximumSalary"))

        min_exp, max_exp = self._experience_range(item)

        return JobListingCreate(
            title=self._clean_text(item.get("title") or "") or "Role",
            company=self._clean_text(item.get("companyName") or "") or "Company (via Foundit)",
            company_logo_url=item.get("companyLogoUrl") or item.get("companyLogo") or None,
            company_industry=", ".join(str(i) for i in (item.get("industries") or [])) or None,
            location=location,
            work_mode=WorkMode.remote if remote else None,
            is_remote_friendly=remote,
            job_type=job_type,
            min_experience=min_exp,
            max_experience=max_exp,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=item.get("currencyCode") or currency,
            required_skills=self._skills(item),
            jd_text=self._synthesize_jd(item, location),
            source_platform=self.platform,
            source_url=url,
            apply_url=url,
            source_job_id=str(item.get("jobId")),
            is_easy_apply=bool(item.get("quickApplyJob")),
            posted_at=self._epoch_ms(item.get("createdAt")),
        )

    @classmethod
    def _experience_range(cls, item: dict) -> tuple[Optional[int], Optional[int]]:
        """(min, max) years, or (None, None) when the board didn't state them.

        The non-India deployments send `{"years": 0}` for both bounds as an
        "unspecified" sentinel. Passing that through as a real 0–0 range would
        be worse than sending nothing: services.experience.merge_experience only
        fills experience when *both* fields are None, so a phantom 0–0 would
        permanently mask the "5+ years" the JD text actually states.
        """
        lo = cls._years(item.get("minimumExperience"))
        hi = cls._years(item.get("maximumExperience"))
        if not lo and not hi:
            return None, None
        return lo, hi

    @staticmethod
    def _years(value) -> Optional[int]:
        if isinstance(value, dict):
            value = value.get("years")
        try:
            n = int(value)
            return n if 0 <= n <= 50 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _salary_value(value) -> Optional[int]:
        if not isinstance(value, dict):
            return None
        try:
            n = int(value.get("absoluteValue") or 0)
            return n or None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _epoch_ms(value):
        """createdAt is milliseconds since epoch; the base helper expects seconds."""
        try:
            return APIBaseScraper.parse_posted_at(int(value) // 1000)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _skills(item: dict) -> list[str]:
        raw = item.get("skills")
        skills = [s.strip() for s in str(raw).split(",")] if isinstance(raw, str) else []
        if not skills:
            skills = [
                str(s.get("value"))
                for s in (item.get("skillsWithSynonyms") or [])
                if isinstance(s, dict) and s.get("value")
            ]
        return [s for s in skills if s][:15]

    def _synthesize_jd(self, item: dict, location: str) -> str:
        """A description built from the structured fields.

        Used as-is when detail enrichment is skipped or fails; the prefilter and
        LLM scorer both read jd_text, so it must carry real signal rather than a
        one-line placeholder.
        """
        bits = [f"{item.get('title', 'Role')} at {item.get('companyName', 'a company')} — {location}."]
        if roles := item.get("roles") or item.get("designations"):
            bits.append(f"Role: {', '.join(str(r) for r in roles)}.")
        if item.get("exp"):
            bits.append(f"Experience: {item['exp']}.")
        if not (item.get("hideSalary") or item.get("jobSalaryConfidential")) and item.get("salary"):
            bits.append(f"Salary: {item['salary']}.")
        if skills := self._skills(item):
            bits.append(f"Skills: {', '.join(skills)}.")
        if industries := item.get("industries"):
            bits.append(f"Industry: {', '.join(str(i) for i in industries)}.")
        if functions := item.get("functions"):
            bits.append(f"Function: {', '.join(str(f) for f in functions)}.")
        return " ".join(bits)

    async def _enrich_descriptions(self, jobs: list[JobListingCreate]) -> None:
        """Replace synthesized JDs with the real one from each detail page.

        Bounded and best-effort: a failure leaves the synthesized text in place.
        """
        targets = jobs[: self.DETAIL_FETCH_LIMIT]
        if not targets:
            return
        results = await asyncio.gather(
            *(self._fetch_description(j.source_url) for j in targets),
            return_exceptions=True,
        )
        enriched = 0
        for job, jd in zip(targets, results):
            if isinstance(jd, str) and len(jd) > len(job.jd_text):
                job.jd_text = jd
                enriched += 1
        if enriched:
            logger.debug(f"Foundit: enriched {enriched}/{len(targets)} JDs from detail pages")

    async def _fetch_description(self, url: str) -> str:
        await self.rate_limiter.acquire()
        try:
            resp = await self._client.get(url, headers={"Accept": "text/html"})
            resp.raise_for_status()
            return (parse_job_posting(resp.text) or {}).get("jd_text", "")
        except Exception as e:
            logger.debug(f"Foundit detail fetch failed for {url}: {e}")
            return ""
