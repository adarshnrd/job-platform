"""
Keejob — Tunisian job board (keejob.com), MENA region.

Probed 2026-10-17: robots.txt disallows `/api/`, `/recruiter/*`, per-job
`/postuler/`, `/print/` and a few account paths. This scraper only touches the
public search page (`/offres-emploi/?keywords=`) and public detail pages
(`/offres-emploi/{id}/{slug}/`) — never `/api/` and never an apply/print path.

Search results are server-rendered HTML; every card appears twice (image link
and title link) and links carry `?source=search`, so ids are de-duplicated and
the query string stripped. Pagination is `&page=N` (verified; page 1 held 15
distinct jobs, page 2 five more). Each detail page carries a schema.org
JobPosting with salary (monthly -> annualized), location and remote flag.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import quote

from loguru import logger

from models.job import JobListingCreate, Platform
from scrapers import jsonld
from scrapers.api_base import APIBaseScraper
from scrapers.mena_common import listing_fields, query_tokens
from services.geo import mena

BASE_URL = "https://www.keejob.com"
LIST_URL = f"{BASE_URL}/offres-emploi/"
_LINK_RE = re.compile(r'href="(/offres-emploi/(\d+)/([^"/?]+)/)')
# robots.txt-disallowed action sub-paths that look like /offres-emploi/{id}/{x}/.
_RESERVED_SLUGS = {"postuler", "postuler-externe", "print", "favorites-top"}


class KeejobScraper(APIBaseScraper):
    platform = Platform.keejob
    requires_key = False
    regions = {"mena"}
    rate_limit_per_minute = 20
    DETAIL_FETCH_LIMIT = 12
    MAX_PAGES = 2
    COUNTRY = "TN"
    HTML_HEADERS = {"Accept": "text/html,application/xhtml+xml"}

    async def search_jobs(
        self,
        query: str,
        location: str = "",
        max_results: int = 50,
        credentials: Optional[dict] = None,
        region: str = "mena",
    ) -> list[JobListingCreate]:
        # A Tunisian board must not answer a "Dubai" search.
        if location and mena.is_mena(location) and mena.country_of(location) != self.COUNTRY:
            return []

        limit = min(self.DETAIL_FETCH_LIMIT, max_results)
        paths: dict[str, str] = {}
        for keywords in self._query_variants(query):
            for page in range(1, self.MAX_PAGES + 1):
                if len(paths) >= limit:
                    break
                url = f"{LIST_URL}?keywords={quote(keywords)}" + (f"&page={page}" if page > 1 else "")
                html = await self._get_text(url, headers=self.HTML_HEADERS)
                found = self.extract_job_paths(html or "")
                if not found:
                    break
                for job_id, path in found.items():
                    paths.setdefault(job_id, path)
            if paths:
                break

        jobs: list[JobListingCreate] = []
        for job_id, path in list(paths.items())[:limit]:
            url = f"{BASE_URL}{path}"
            if not self._is_new(url):
                continue
            html = await self._get_text(url, headers=self.HTML_HEADERS)
            job = self._to_listing(html, url, job_id) if html else None
            if job:
                jobs.append(job)

        logger.info(f"Keejob: returning {len(jobs)} jobs for '{query}'")
        return jobs

    MAX_QUERY_VARIANTS = 3

    @classmethod
    def _query_variants(cls, query: str) -> list[str]:
        """The full query first, then single words. Keejob ANDs every word, so an
        English "software engineer" matches nothing on a French board while
        "software" alone does; single words are tried only when the full query
        came back empty, longest first, at most MAX_QUERY_VARIANTS requests."""
        variants = [query]
        words = sorted(set(query_tokens(query)), key=len, reverse=True)
        if len(words) > 1:
            variants += words
        return variants[: cls.MAX_QUERY_VARIANTS]

    @staticmethod
    def extract_job_paths(html: str) -> dict[str, str]:
        """id -> canonical path (no query string), in page order."""
        out: dict[str, str] = {}
        for path, job_id, slug in _LINK_RE.findall(html):
            if slug not in _RESERVED_SLUGS:
                out.setdefault(job_id, path)
        return out

    def _to_listing(self, html: str, url: str, job_id: str) -> Optional[JobListingCreate]:
        posting = jsonld.find_job_posting(html)
        if not posting:
            return None
        # A bare "Remote" location names no place, so it falls back to the country.
        fields = listing_fields(
            posting, self.COUNTRY, generic_locations=("Remote",), company_fallback="Company (via Keejob)"
        )
        if not fields:
            return None

        identifier = posting.get("identifier")
        job_id = (identifier.get("value") if isinstance(identifier, dict) else None) or job_id

        try:
            return JobListingCreate(
                **fields,
                source_platform=self.platform,
                source_url=url,
                apply_url=url,
                source_job_id=str(job_id),
            )
        except Exception as e:
            logger.debug(f"Keejob: listing build failed for {url}: {e}")
            return None
