"""
ReKrute — Moroccan job board (rekrute.com), MENA region.

Discovery uses the public sitemap, not the `/offres.html?query=` search page.
Probed 2026-10-17: the spec assumed robots.txt has no disallows, but the real
file has no `*` group at all and names `Disallow: /offres.html` (and
`/fr/offres.html`) for the AI/search crawlers it lists (ClaudeBot, GPTBot,
Bingbot, ...). A generic bot is technically unrestricted, yet the site clearly
does not want automated traffic on the search page, so the safe option is taken:
`/sitemap.xml` (declared in robots.txt, ~1.9k active `offre-emploi-*.html`
URLs) plus the individual offer pages, which every group allows.

Offer slugs read `offre-emploi-{title}-recrutement-{company}-{city}-{id}`, so
the slug shortlists by tech terms and city without fetching anything; only the
top DETAIL_FETCH_LIMIT offers are fetched. Each offer page has a JobPosting
JSON-LD (some pages emit raw newlines inside `description`, which the shared
parser now tolerates) and a server-rendered body whose `<h3 class="jo-secTitle">`
sections ("Poste :", "Profil recherché :") hold the actual job text.

ReKrute also lists Tunisia and Algeria; those are kept, other countries dropped.
"""
from __future__ import annotations

import html as htmllib
import re
from typing import Optional

from loguru import logger

from models.job import JobListingCreate, Platform
from scrapers import jsonld
from scrapers.api_base import APIBaseScraper
from scrapers.mena_common import (
    compile_slug_terms, listing_fields, parse_experience_fr, query_tokens, scrub_contacts, slug_has_any,
)
from services.geo import mena

SITEMAP_URL = "https://www.rekrute.com/sitemap.xml"
BASE_URL = "https://www.rekrute.com"
_OFFER_RE = re.compile(
    r"<loc>(https://www\.rekrute\.com/offre-emploi-([a-z0-9-]+)-(\d+)\.html)</loc>"
)
# A section body runs to the next heading or to the spacer/CTA blocks that close
# the job text (what follows is the apply bar, navigation and login dialogs).
_SECTION_RE = re.compile(
    r'<h3[^>]*class="jo-secTitle"[^>]*>(.*?)</h3>(.*?)'
    r'(?=<h3[\s>]|<div[^>]*class="jo-(?:blockSpacer|testCta|applyBar)|\Z)',
    re.S | re.I,
)
_META_DESC = re.compile(r'<meta name="description" content="([^"]*)"', re.I)
# Sections that describe the job itself (not the employer's marketing text).
_JOB_SECTIONS = ("poste", "profil", "mission", "contexte", "traits", "description")

ACCEPTED_COUNTRIES = {"MA", "TN", "DZ"}

# Hyphen-anchored terms are whole slug tokens (see mena_common.compile_slug_terms).
REKRUTE_TECH_SLUGS = (
    "developpeur", "developpeuse", "developer", "software", "logiciel", "full-stack",
    "fullstack", "backend", "back-end", "frontend", "front-end", "devops", "data-",
    "-data", "big-data", "machine-learning", "intelligence-artificielle", "-ia-", "-ia",
    "mobile", "android", "-ios-", "flutter", "react", "angular", "-java-", "python",
    "-php-", "-net-", "cloud", "cyber", "securite-informatique", "testeur", "-qa-",
    "-sre-", "informatique", "-it-", "-si-", "-sap-", "oracle", "salesforce", "-erp-",
    "administrateur-systeme", "administrateur-reseau", "ingenieur-reseau", "ingenieur-systeme",
    "ingenieur-logiciel", "architecte-si", "architecte-solution", "architecte-technique",
    "chef-de-projet-it", "chef-de-projet-informatique", "chef-de-projet-digital",
    "product-owner", "scrum-master", "tech-lead", "-web-", "webmaster",
)
_TECH_PATTERNS = compile_slug_terms(REKRUTE_TECH_SLUGS)
_NOT_TECH = ("developpeur-commercial", "developpeur-des-ventes", "developpeur-immobilier",
             "business-developer", "developpeur-business")

# English query words -> the French slug/title vocabulary the board uses.
_EN_FR = {
    "developer": "developpeur", "engineer": "ingenieur", "software": "logiciel",
    "frontend": "front", "backend": "back", "manager": "responsable",
    "analyst": "analyste", "tester": "testeur", "architect": "architecte",
}


def extract_jd(html: str) -> str:
    """Job text from an offer page.

    Order of preference: the "Poste :" / "Profil recherché :" (and similar)
    sections of the page body, then the JSON-LD description, then the meta
    description. Employer-marketing sections ("ENTREPRISE", "Culture de
    l'entreprise") are skipped on purpose: they would drown the actual role.
    """
    chunks = []
    for heading, body in _SECTION_RE.findall(html):
        title = jsonld.strip_html(heading).lower()
        if any(title.startswith(s) for s in _JOB_SECTIONS):
            text = jsonld.strip_html(body)
            if text:
                chunks.append(f"{jsonld.strip_html(heading).rstrip(' :')}: {text}")
    if chunks:
        return "\n".join(chunks)
    posting = jsonld.find_job_posting(html)
    if posting and posting.get("description"):
        return jsonld.strip_html(posting["description"])
    m = _META_DESC.search(html)
    return htmllib.unescape(m.group(1)).strip() if m else ""


class RekruteScraper(APIBaseScraper):
    platform = Platform.rekrute
    requires_key = False
    regions = {"mena"}
    rate_limit_per_minute = 20
    DETAIL_FETCH_LIMIT = 12
    COUNTRY = "MA"
    HTML_HEADERS = {"Accept": "text/html,application/xhtml+xml"}
    XML_HEADERS = {"Accept": "application/xml,text/xml"}

    def __init__(self):
        super().__init__()
        self._offers: Optional[list[tuple[str, str, int]]] = None  # (url, slug, id)

    async def search_jobs(
        self,
        query: str,
        location: str = "",
        max_results: int = 50,
        credentials: Optional[dict] = None,
        region: str = "mena",
    ) -> list[JobListingCreate]:
        wanted = mena.country_of(location) if location else None
        # Morocco, Tunisia and Algeria only; a Gulf search gets nothing here.
        if wanted and wanted not in ACCEPTED_COUNTRIES:
            return []

        offers = await self._load_offers()
        picked = self._candidates(offers, query, wanted)
        jobs: list[JobListingCreate] = []
        for url, _slug, job_id in picked[: self.DETAIL_FETCH_LIMIT]:
            if len(jobs) >= max_results:
                break
            if not self._is_new(url):
                continue
            html = await self._get_text(url, headers=self.HTML_HEADERS)
            job = self._to_listing(html, url, str(job_id), wanted) if html else None
            if job:
                jobs.append(job)

        logger.info(f"ReKrute: returning {len(jobs)} jobs for '{query}' in '{location}'")
        return jobs

    # ── sitemap ──
    async def _load_offers(self) -> list[tuple[str, str, int]]:
        if self._offers is not None:
            return self._offers
        xml = await self._get_text(SITEMAP_URL, headers=self.XML_HEADERS)
        self._offers = [
            (m.group(1), m.group(2), int(m.group(3))) for m in _OFFER_RE.finditer(xml or "")
        ]
        logger.debug(f"ReKrute: {len(self._offers)} offer URLs in sitemap")
        return self._offers

    @staticmethod
    def _slug_country(slug: str) -> Optional[str]:
        """Country of the city the slug ends with ("...-recrutement-alten-maroc-fes"),
        trying the last 1-3 tokens; None when the city is not one we know."""
        parts = slug.split("-")
        for k in (1, 2, 3):
            iso = mena.country_of(" ".join(parts[-k:]))
            if iso:
                return iso
        return None

    def _candidates(self, offers, query: str, wanted: Optional[str]):
        tokens = query_tokens(query)
        tokens += [_EN_FR[t] for t in tokens if t in _EN_FR]
        scored = []
        for url, slug, job_id in offers:
            if any(bad in slug for bad in _NOT_TECH):
                continue
            if not slug_has_any(slug, _TECH_PATTERNS):
                continue
            iso = self._slug_country(slug)
            # Unknown cities are almost always Moroccan (the bulk of the board),
            # so they only pass for a Morocco search; TN/DZ need a positive match.
            if wanted and iso != wanted and not (iso is None and wanted == self.COUNTRY):
                continue
            city_rank = 1 if (wanted and iso == wanted) else 0
            query_match = sum(1 for t in tokens if t in slug)
            scored.append(((city_rank, query_match, job_id), (url, slug, job_id)))
        scored.sort(key=lambda s: s[0], reverse=True)  # newest ids first within a tier
        return [e for _, e in scored]

    # ── detail ──
    def _to_listing(
        self, html: str, url: str, job_id: str, wanted: Optional[str] = None
    ) -> Optional[JobListingCreate]:
        """`wanted` (ISO-2) drops postings from other countries."""
        posting = jsonld.find_job_posting(html)
        if not posting:
            return None

        # Location: locality + the country the page names (French: "Maroc").
        address = (posting.get("jobLocation") or {}).get("address") if isinstance(posting.get("jobLocation"), dict) else None
        address = address if isinstance(address, dict) else {}
        locality = address.get("addressLocality") or ""
        country_raw = address.get("addressCountry")
        country_raw = country_raw.get("name") if isinstance(country_raw, dict) else (country_raw or "")
        iso = mena.country_of(country_raw) if country_raw else self.COUNTRY
        if iso is None or (wanted and iso != wanted):
            # Non-MENA (ReKrute also lists sub-Saharan Africa) or another country.
            return None

        fields = listing_fields(posting, iso, location=locality, company_fallback="Company (via ReKrute)")
        if not fields:
            return None
        # The page body's Poste/Profil sections beat the JSON-LD description.
        fields["jd_text"] = scrub_contacts(extract_jd(html)) or fields["jd_text"]
        min_exp, max_exp = parse_experience_fr(posting.get("experienceRequirements"))
        try:
            return JobListingCreate(
                **fields,
                min_experience=min_exp,
                max_experience=max_exp,
                source_platform=self.platform,
                source_url=url,
                apply_url=url,
                source_job_id=job_id,
            )
        except Exception as e:
            logger.debug(f"ReKrute: listing build failed for {url}: {e}")
            return None
