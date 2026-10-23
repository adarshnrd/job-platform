"""
Sabbar — Saudi Arabian job board (sabbar.com), MENA region.

Probed 2026-10-17: robots.txt allows crawling and publishes sitemaps. The
English job sitemap lists ~16k detail URLs shaped like
`/en/jobs/c-{city}-r-{role-slug}/id-{uuid}`, and every detail page carries a
schema.org JobPosting (no HTML selectors involved).

The catalogue is mostly sales/HR/other non-tech roles, so the slug is the
filter: the sitemap is loaded once per scraper instance (one instance spans a
run), URLs are shortlisted by tech terms in the role slug, ranked by city and
query match, and only the top DETAIL_FETCH_LIMIT detail pages are fetched.
About a quarter of the English sitemap's slugs are Arabic (percent-encoded), so
URLs are unquoted before matching and ARABIC_ROLE_TERMS from services.geo.mena
shortlists the tech ones. The `/ar/` sitemap itself is a later phase.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import unquote

from loguru import logger

from models.job import JobListingCreate, Platform
from scrapers import jsonld
from scrapers.api_base import APIBaseScraper
from scrapers.mena_common import compile_slug_terms, listing_fields, query_tokens, slug_has_any
from services.geo import mena

SITEMAP_URL = "https://sabbar.com/en/jobs/sitemaps/job-details.xml"
# Matched against the UNQUOTED url: Arabic slugs arrive percent-encoded, and a
# role slug can even contain "/" ("...-قدم-/-سباحة").
_URL_RE = re.compile(r"/en/jobs/c-([^/]+)-r-(.+?)/id-([0-9a-f-]{36})")
_ENTRY_RE = re.compile(r"<url>\s*<loc>([^<]+)</loc>(?:\s*<lastmod>([^<]+)</lastmod>)?")
_SITEMAP_LOC_RE = re.compile(r"<sitemap>\s*<loc>([^<]+)</loc>")

# Hyphen-anchored terms ("it-", "-ai") are whole slug tokens, the rest are
# substrings — see mena_common.compile_slug_terms for why ("it-" in "credit-").
SABBAR_TECH_SLUGS = (
    "software", "developer", "programmer", "full-stack", "fullstack", "backend", "back-end",
    "frontend", "front-end", "devops", "data-engineer", "data-scientist", "data-analyst",
    "machine-learning", "ai-", "-ai", "mobile", "android", "-ios-", "flutter", "web-",
    "cloud", "cyber", "security-engineer", "qa-", "test-automation", "-sre-", "it-",
    "odoo", "sap-", "oracle-", "salesforce", "-erp-", "system-admin", "network-engineer",
    "solution-architect", "technical-lead", "tech-lead", "product-manager",
)
_TECH_PATTERNS = compile_slug_terms(SABBAR_TECH_SLUGS)
# Arabic role terms are whole hyphen-delimited slug tokens (multi-word terms are
# joined with "-" like the slugs), with an optional feminine "ة". A bare
# substring would also fire inside "ومطور" ("and developer") of unrelated titles.
_ARABIC_TECH_PATTERNS = [
    re.compile(rf"(?:^|-){re.escape(term.replace(' ', '-'))}ة?(?:-|$)")
    for term in mena.ARABIC_ROLE_TERMS.values()
]
_NOT_TECH_AR = ("مطور-عقاري", "مطور-عقارات", "مطور-اعمال", "مطور-أعمال")
# "developer" also matches these non-software roles.
_NOT_TECH = ("business-developer", "sales-developer", "real-estate", "property-developer")


class SabbarScraper(APIBaseScraper):
    platform = Platform.sabbar
    requires_key = False
    regions = {"mena"}
    rate_limit_per_minute = 20
    DETAIL_FETCH_LIMIT = 15
    COUNTRY = "SA"

    HTML_HEADERS = {"Accept": "text/html,application/xhtml+xml"}
    XML_HEADERS = {"Accept": "application/xml,text/xml"}
    MAX_CHILD_SITEMAPS = 5

    def __init__(self):
        super().__init__()
        self._entries: Optional[list[tuple[str, str, str, str]]] = None  # (url, city, role, lastmod)

    async def search_jobs(
        self,
        query: str,
        location: str = "",
        max_results: int = 50,
        credentials: Optional[dict] = None,
        region: str = "mena",
    ) -> list[JobListingCreate]:
        # A Saudi board must not answer a "Dubai" search.
        if location and mena.is_mena(location) and mena.country_of(location) != self.COUNTRY:
            return []

        entries = await self._load_entries()
        picked = self._candidates(entries, query, location)
        jobs: list[JobListingCreate] = []
        for url, city, _role, _lastmod in picked[: self.DETAIL_FETCH_LIMIT]:
            if len(jobs) >= max_results:
                break
            if not self._is_new(url):
                continue
            html = await self._get_text(url, headers=self.HTML_HEADERS)
            job = self._to_listing(html, url, city) if html else None
            if job:
                jobs.append(job)

        logger.info(f"Sabbar: returning {len(jobs)} jobs for '{query}' in '{location}'")
        return jobs

    # ── sitemap ──
    async def _load_entries(self) -> list[tuple[str, str, str, str]]:
        """Parse the English sitemap once per instance (failure is cached too so
        a broken run does not re-download 7 MB per search)."""
        if self._entries is not None:
            return self._entries
        entries: list[tuple[str, str, str, str]] = []
        xml = await self._get_text(SITEMAP_URL, headers=self.XML_HEADERS)
        if xml and "<sitemapindex" in xml:
            children = _SITEMAP_LOC_RE.findall(xml)[: self.MAX_CHILD_SITEMAPS]
            for child in children:
                part = await self._get_text(child, headers=self.XML_HEADERS)
                entries.extend(self._parse_sitemap(part or ""))
        elif xml:
            entries = self._parse_sitemap(xml)
        self._entries = entries
        logger.debug(f"Sabbar: {len(entries)} sitemap URLs")
        return entries

    @staticmethod
    def _parse_sitemap(xml: str) -> list[tuple[str, str, str, str]]:
        out = []
        for url, lastmod in _ENTRY_RE.findall(xml):
            m = _URL_RE.search(unquote(url))
            if m:
                # The original (still encoded) URL is what gets fetched.
                out.append((url.strip(), m.group(1), m.group(2), lastmod or ""))
        return out

    # ── shortlisting ──
    @staticmethod
    def _city_token(location: str) -> str:
        """Slug form of a KSA city in `location` ("Al Khobar" -> "al-khobar"),
        or "" for a country-level search."""
        if mena.country_of(location) != "SA":
            return ""
        first = location.split(",")[0].strip()
        c = mena.MENA_COUNTRIES["SA"]
        if first.lower() in {a.lower() for a in c["aliases"]} or first.lower() == c["name"].lower():
            return ""
        return re.sub(r"[^a-z0-9]+", "-", first.lower()).strip("-")

    def _candidates(self, entries, query: str, location: str):
        tokens = query_tokens(query)
        city = self._city_token(location)
        scored = []
        for entry in entries:
            _url, city_slug, role_slug, lastmod = entry
            if any(bad in role_slug for bad in (*_NOT_TECH, *_NOT_TECH_AR)):
                continue
            if not (slug_has_any(role_slug, _TECH_PATTERNS) or slug_has_any(role_slug, _ARABIC_TECH_PATTERNS)):
                continue
            query_match = sum(1 for t in tokens if t in role_slug)
            city_match = 1 if city and (city_slug == city or city in city_slug) else 0
            scored.append(((city_match, query_match, lastmod), entry))
        scored.sort(key=lambda s: s[0], reverse=True)
        return [e for _, e in scored]

    # ── detail ──
    def _to_listing(self, html: str, url: str, city_slug: str) -> Optional[JobListingCreate]:
        posting = jsonld.find_job_posting(html)
        if not posting:
            return None
        city = city_slug.replace("-", " ").title()
        fields = listing_fields(
            posting, self.COUNTRY, location_fallback=city, company_fallback="Company (via Sabbar)"
        )
        if not fields:
            return None

        m = _URL_RE.search(unquote(url))
        uuid = m.group(3) if m else None
        identifier = posting.get("identifier")
        job_id = (identifier.get("value") if isinstance(identifier, dict) else None) or uuid

        try:
            return JobListingCreate(
                **fields,
                source_platform=self.platform,
                source_url=url,
                apply_url=url,
                source_job_id=str(job_id) if job_id else None,
            )
        except Exception as e:
            logger.debug(f"Sabbar: listing build failed for {url}: {e}")
            return None
