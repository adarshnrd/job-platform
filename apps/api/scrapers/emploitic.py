"""
Emploitic — Algerian job board (emploitic.com), MENA region.

Probed 2026-10-17: robots.txt disallows only `/partenaires/` (never touched
here). The search page is a Next.js page whose `__NEXT_DATA__` JSON carries
`props.pageProps.searchResult = {data, totalPages, currentPage, total}`, and each
`data[]` item already holds the FULL job description, so no detail fetches are
needed — a search costs 1-3 requests.

Verified field shapes (fixture: tests/fixtures/emploitic_search.html):
  • `location[]`, `contractType[]`, `experienceYears[]`, `jobLevel[]`,
    `company.sector` are objects whose human label is `label` (French).
  • `company.name` / `company.alias`; anonymous postings set `isAnonymous: true`
    and carry only `company.sector`.
  • Pagination is `&page=N` (`currentPage` echoes it), 20 items per page.
  • The job URL is `/entreprises/{company.alias}/offres-d-emploi/{sector-slug}/{alias}`
    (anonymous: `/offres-d-emploi/{sector-slug}/{alias}`). A bare
    `/offres-d-emploi/{alias}` 308-redirects to a search page, so the URL is
    taken from the page's JSON-LD ItemList when present and rebuilt from the
    sector label otherwise.
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Optional

from loguru import logger

from models.job import JobListingCreate, JobType, Platform, WorkMode
from scrapers import jsonld
from scrapers.api_base import APIBaseScraper
from scrapers.mena_common import merge_experience_labels, scrub_contacts, with_country
from services.geo import mena

BASE_URL = "https://emploitic.com"
SEARCH_URL = f"{BASE_URL}/offres-d-emploi"
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)

_WORK_MODES = {"onsite": WorkMode.onsite, "hybrid": WorkMode.hybrid, "remote": WorkMode.remote}
_CONTRACTS: dict[str, JobType] = {
    "cdi": JobType.full_time,
    "cdd": JobType.contract, "mission": JobType.contract, "intérim": JobType.contract,
    "interim": JobType.contract, "consultant": JobType.contract,
    "stage": JobType.internship, "alternance": JobType.internship,
    "freelance": JobType.freelance, "temps partiel": JobType.part_time,
}


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _label(items) -> str:
    """First label of an [{label: ...}] list."""
    for it in items or []:
        if isinstance(it, dict) and it.get("label"):
            return str(it["label"]).strip()
    return ""


class EmploiticScraper(APIBaseScraper):
    platform = Platform.emploitic
    requires_key = False
    regions = {"mena"}
    rate_limit_per_minute = 20
    MAX_PAGES = 3
    COUNTRY = "DZ"
    HTML_HEADERS = {"Accept": "text/html,application/xhtml+xml"}

    async def search_jobs(
        self,
        query: str,
        location: str = "",
        max_results: int = 50,
        credentials: Optional[dict] = None,
        region: str = "mena",
    ) -> list[JobListingCreate]:
        # An Algerian board must not answer a "Dubai" search.
        if location and mena.is_mena(location) and mena.country_of(location) != self.COUNTRY:
            return []

        jobs: list[JobListingCreate] = []
        for page in range(1, self.MAX_PAGES + 1):
            if len(jobs) >= max_results:
                break
            params = {"search": query}
            if page > 1:
                params["page"] = page
            html = await self._get_text(SEARCH_URL, params=params, headers=self.HTML_HEADERS)
            result = self._search_result(html)
            if not result:
                break
            urls = self._ld_urls(html)
            for item in result.get("data") or []:
                job = self._to_listing(item, urls)
                if job:
                    jobs.append(job)
                    if len(jobs) >= max_results:
                        break
            if page >= (result.get("totalPages") or 1):
                break

        logger.info(f"Emploitic: returning {len(jobs)} jobs for '{query}'")
        return jobs

    # ── parsing ──
    @staticmethod
    def _search_result(html: Optional[str]) -> Optional[dict]:
        m = _NEXT_DATA.search(html or "")
        if not m:
            return None
        try:
            data = json.loads(m.group(1))
            return data["props"]["pageProps"]["searchResult"]
        except (ValueError, KeyError, TypeError):
            return None

    @staticmethod
    def _ld_urls(html: Optional[str]) -> dict[str, str]:
        """alias -> canonical job URL from the page's SearchResultsPage ItemList."""
        out: dict[str, str] = {}
        for obj in jsonld.iter_ld_blocks(html or ""):
            entity = obj.get("mainEntity") if isinstance(obj.get("mainEntity"), dict) else {}
            for el in entity.get("itemListElement") or []:
                url = el.get("url") if isinstance(el, dict) else None
                if isinstance(url, str) and url:
                    out[url.rstrip("/").rsplit("/", 1)[-1]] = url
        return out

    @staticmethod
    def _job_url(item: dict, ld_urls: dict[str, str]) -> Optional[str]:
        alias = item.get("alias")
        if not alias:
            return None
        if alias in ld_urls:
            return ld_urls[alias]
        company = item.get("company") or {}
        sector = _slug(_label([company.get("sector")]))
        if not sector:
            return None
        prefix = f"/entreprises/{company['alias']}" if company.get("alias") and not item.get("isAnonymous") else ""
        return f"{BASE_URL}{prefix}/offres-d-emploi/{sector}/{alias}"

    def _to_listing(self, item: dict, ld_urls: dict[str, str]) -> Optional[JobListingCreate]:
        url = self._job_url(item, ld_urls)
        if not url or not self._is_new(url):
            return None

        company = item.get("company") or {}
        name = (company.get("name") or "").strip()
        if item.get("isAnonymous") or not name:
            name = "Confidential (via Emploitic)"

        title = jsonld.strip_html(item.get("title")) or "Role"
        place = _label(item.get("location"))
        location = with_country(place, self.COUNTRY)
        work_mode = _WORK_MODES.get(str(item.get("workMode") or "").lower())

        contract = " ".join(
            str(c.get("label")) for c in (item.get("contractType") or []) if isinstance(c, dict)
        )
        min_exp, max_exp = merge_experience_labels(
            [str(e.get("label")) for e in (item.get("experienceYears") or []) if isinstance(e, dict)]
        )
        skip = {title.lower(), name.lower()}
        tags = [t for t in (item.get("tags") or []) if isinstance(t, str) and t.lower() not in skip]

        return JobListingCreate(
            title=title,
            company=name,
            company_industry=_label([company.get("sector")]) or None,
            location=location,
            work_mode=work_mode,
            is_remote_friendly=work_mode is WorkMode.remote,
            job_type=self.match_terms(contract, _CONTRACTS, JobType.full_time),
            min_experience=min_exp,
            max_experience=max_exp,
            salary_currency="DZD",
            required_skills=tags[:12],
            jd_text=scrub_contacts(jsonld.strip_html(item.get("description"))) or title,
            source_platform=self.platform,
            source_url=url,
            apply_url=url,
            source_job_id=str(item.get("id")) if item.get("id") else None,
            posted_at=self.parse_posted_at(item.get("publishedAt")),
        )
