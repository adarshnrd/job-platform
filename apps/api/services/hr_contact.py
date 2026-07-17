"""
HR-contact enrichment — attach a hiring contact to each discovered job listing.

The job sources (ATS boards, LinkedIn, Naukri, aggregator APIs) never carry a
recruiter's email or LinkedIn URL, so contact data has to be *enriched* from a
third party. This module does that with two guarantees that matter for a
job-application product:

  1. Verified-only email. ``hr_email`` is populated ONLY by an enrichment
     provider that returns a real address — we never guess ``first.last@company``
     patterns and pass them off as real. An inaccurate address sent to an
     employer damages the user's application, so a guess is worse than a blank.
  2. ToS-safe LinkedIn. With no provider key we emit a LinkedIn *people-search
     deep-link* (a URL the user clicks), never a scraped profile. A licensed
     people API (Apollo/Proxycurl) upgrades that to a concrete profile URL.

Providers are optional and gated by an API key — exactly like the keyed job
sources (Adzuna/Jooble/Careerjet): absent key → provider is skipped and the
listing still gets the keyless search link. Set ``HUNTER_API_KEY`` /
``APOLLO_API_KEY`` / ``PROXYCURL_API_KEY`` to light up verified data.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote_plus, urlparse

import httpx
from loguru import logger

from config import settings

_HTTP_TIMEOUT = 15.0
_ENRICH_CONCURRENCY = 4

# ATS / aggregator hosts whose domain is NOT the employer's — never use them for
# an email-domain lookup (e.g. a Greenhouse board host is not the company's mail
# domain). Matched against the host and its parent domains.
_NON_COMPANY_HOSTS = {
    "greenhouse.io", "boards.greenhouse.io", "job-boards.greenhouse.io",
    "lever.co", "jobs.lever.co", "ashbyhq.com", "jobs.ashbyhq.com",
    "linkedin.com", "indeed.com", "naukri.com", "glassdoor.com", "shine.com",
    "remoteok.com", "remotive.com", "themuse.com", "ycombinator.com",
    "workatastartup.com", "adzuna.com", "jooble.org", "timesjobs.com",
    "hirist.tech", "iimjobs.com", "careerjet.com", "monster.com",
}

# Trailing legal / descriptor suffixes stripped so "Postman, Inc." → "Postman"
# for search keywords and provider lookups.
_LEGAL_SUFFIX = re.compile(
    r"[,.]?\s+(inc|llc|ltd|pvt|private|limited|corp|corporation|technologies|"
    r"technology|labs|software|systems|solutions|services|gmbh|co)\.?$",
    re.IGNORECASE,
)
_VIA_AGGREGATOR = re.compile(r"\s*\(via [^)]+\)\s*$", re.IGNORECASE)


@dataclass
class HRContact:
    """The contact attached to a listing. Email is verified-only; the search URL
    is always present (keyless). ``source`` records provenance so the UI can show
    verified data differently from a "go search" link."""
    hr_name: Optional[str] = None
    hr_email: Optional[str] = None                 # verified only — never a guess
    hr_linkedin_url: Optional[str] = None          # concrete profile (provider only)
    hr_linkedin_search_url: Optional[str] = None   # keyless people-search deep-link
    source: Optional[str] = None                   # 'hunter'|'apollo'|'proxycurl'|'search'
    confidence: Optional[int] = None               # 0..100 for verified data, else None

    def has_any(self) -> bool:
        return bool(self.hr_email or self.hr_linkedin_url or self.hr_linkedin_search_url)


def clean_company(company: str) -> str:
    """Normalize a company name for search keywords / provider lookups."""
    c = _VIA_AGGREGATOR.sub("", (company or "").strip()).strip()
    prev = None
    while prev != c:
        prev = c
        c = _LEGAL_SUFFIX.sub("", c).strip()
    return c


def linkedin_people_search_url(company: str) -> str:
    """A LinkedIn people-search deep-link for recruiters/HR at ``company``.

    This is a search URL the user clicks — NOT a scrape and NOT a claim about a
    specific person. Always available (no key, no network)."""
    keywords = f"{clean_company(company)} recruiter OR talent OR HR"
    return "https://www.linkedin.com/search/results/people/?keywords=" + quote_plus(keywords)


def domain_from(*candidates: Optional[str]) -> Optional[str]:
    """Best-effort employer mail domain from a company website / apply URL.

    Returns None for ATS/aggregator hosts — their host is not the employer's
    domain, so it must not be used for an email lookup."""
    for raw in candidates:
        if not raw:
            continue
        parsed = urlparse(raw if "//" in raw else f"//{raw}", scheme="https")
        host = parsed.netloc.lower().split("@")[-1].split(":")[0]
        if host.startswith("www."):
            host = host[4:]
        if not host or "." not in host:
            continue
        if any(host == h or host.endswith("." + h) for h in _NON_COMPANY_HOSTS):
            continue
        return host
    return None


# ══════════════════════════════════════════════════════════════
#  PROVIDERS (verified data — each gated by its own API key)
# ══════════════════════════════════════════════════════════════
class _Provider:
    """Base provider. ``has_key`` False → skipped entirely (never called)."""
    name = "base"

    def has_key(self) -> bool:
        return False

    async def lookup(self, company: str, domain: Optional[str], jd_text: Optional[str]) -> Optional[HRContact]:
        return None


class HunterProvider(_Provider):
    """Hunter.io domain-search — real addresses discovered for a domain, filtered
    to HR/executive and a minimum confidence. Needs the employer's mail domain."""
    name = "hunter"
    MIN_CONFIDENCE = 50

    def has_key(self) -> bool:
        return bool(settings.HUNTER_API_KEY)

    async def lookup(self, company, domain, jd_text):
        if not domain:
            return None
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(
                "https://api.hunter.io/v2/domain-search",
                params={
                    "domain": domain,
                    "department": "hr,executive",
                    "limit": 10,
                    "api_key": settings.HUNTER_API_KEY,
                },
            )
            resp.raise_for_status()
            data = resp.json() or {}
        emails = ((data.get("data") or {}).get("emails")) or []
        best = None
        for e in emails:
            conf = e.get("confidence") or 0
            if e.get("value") and conf >= self.MIN_CONFIDENCE:
                if best is None or conf > (best.get("confidence") or 0):
                    best = e
        if not best:
            return None
        name = " ".join(x for x in (best.get("first_name"), best.get("last_name")) if x) or None
        return HRContact(
            hr_name=name,
            hr_email=best.get("value"),
            hr_linkedin_url=best.get("linkedin"),
            source=self.name,
            confidence=best.get("confidence"),
        )


class ApolloProvider(_Provider):
    """Apollo.io people search — recruiters/HR at the org, with email + LinkedIn.
    Apollo masks locked emails as ``email_not_unlocked@…`` — those are rejected so
    we never store a placeholder as a real address."""
    name = "apollo"
    TITLES = [
        "recruiter", "technical recruiter", "talent acquisition",
        "hr", "human resources", "hiring manager", "people operations",
    ]

    def has_key(self) -> bool:
        return bool(settings.APOLLO_API_KEY)

    async def lookup(self, company, domain, jd_text):
        payload: dict = {"person_titles": self.TITLES, "page": 1, "per_page": 5}
        if domain:
            payload["q_organization_domains"] = domain
        else:
            payload["q_organization_name"] = clean_company(company)
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(
                "https://api.apollo.io/v1/mixed_people/search",
                headers={"X-Api-Key": settings.APOLLO_API_KEY, "Content-Type": "application/json"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json() or {}
        people = data.get("people") or []
        # Prefer a person with a real, unlocked email.
        for p in people:
            email = p.get("email")
            if email and "email_not_unlocked" not in email and "@" in email:
                return HRContact(
                    hr_name=_person_name(p),
                    hr_email=email,
                    hr_linkedin_url=p.get("linkedin_url"),
                    source=self.name,
                    confidence=90,
                )
        # No unlocked email — still surface a concrete LinkedIn profile if present.
        for p in people:
            if p.get("linkedin_url"):
                return HRContact(
                    hr_name=_person_name(p),
                    hr_linkedin_url=p.get("linkedin_url"),
                    source=self.name,
                )
        return None


class ProxycurlProvider(_Provider):
    """Proxycurl role lookup — a licensed API that resolves a company + role to a
    LinkedIn profile URL (no scraping). LinkedIn only, no email."""
    name = "proxycurl"

    def has_key(self) -> bool:
        return bool(settings.PROXYCURL_API_KEY)

    async def lookup(self, company, domain, jd_text):
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(
                "https://nubela.co/proxycurl/api/find/company/role/",
                headers={"Authorization": f"Bearer {settings.PROXYCURL_API_KEY}"},
                params={"role": "recruiter", "company_name": clean_company(company)},
            )
            resp.raise_for_status()
            data = resp.json() or {}
        url = data.get("linkedin_profile_url")
        if not url:
            return None
        return HRContact(hr_linkedin_url=url, source=self.name)


def _person_name(p: dict) -> Optional[str]:
    return p.get("name") or " ".join(
        x for x in (p.get("first_name"), p.get("last_name")) if x
    ) or None


# Order = precedence. Hunter first (verified email), then Apollo (email+LinkedIn),
# then Proxycurl (LinkedIn only). Only key-bearing providers are ever called.
_PROVIDERS: list[_Provider] = [HunterProvider(), ApolloProvider(), ProxycurlProvider()]


def _active_providers() -> list[_Provider]:
    return [p for p in _PROVIDERS if p.has_key()]


# ══════════════════════════════════════════════════════════════
#  ENRICHMENT
# ══════════════════════════════════════════════════════════════
async def enrich_contact(
    company: str,
    *,
    domain: Optional[str] = None,
    jd_text: Optional[str] = None,
) -> HRContact:
    """Best-effort HR contact for a company.

    Keyless → just the LinkedIn people-search deep-link. With provider keys →
    verified email / concrete profile merged in (first provider to return each
    field wins). Email is only ever set from a provider — never guessed."""
    contact = HRContact(
        hr_linkedin_search_url=linkedin_people_search_url(company),
        source="search",
    )
    for provider in _active_providers():
        try:
            res = await provider.lookup(company, domain, jd_text)
        except Exception as e:
            logger.warning(f"HR-contact provider {provider.name} failed for {company!r}: {e}")
            continue
        if not res:
            continue
        if res.hr_name and not contact.hr_name:
            contact.hr_name = res.hr_name
        if res.hr_email and not contact.hr_email:
            contact.hr_email = res.hr_email
        if res.hr_linkedin_url and not contact.hr_linkedin_url:
            contact.hr_linkedin_url = res.hr_linkedin_url
        # Record verified provenance the moment we get any concrete datum.
        if res.hr_email or res.hr_linkedin_url:
            contact.source = res.source or provider.name
            if res.confidence is not None:
                contact.confidence = res.confidence
        if contact.hr_email and contact.hr_linkedin_url:
            break  # fully enriched — stop paying for lookups
    return contact


async def enrich_jobs(jobs: list) -> int:
    """Attach HR-contact fields to each ``JobListingCreate`` in ``jobs``, in place.

    One lookup per employer per run (cached by normalized company name), bounded
    concurrency, fully non-fatal. Returns how many listings received at least a
    contact link."""
    if not jobs:
        return 0

    by_company: dict[str, list[int]] = {}
    for i, job in enumerate(jobs):
        key = clean_company(getattr(job, "company", "") or "").lower()
        by_company.setdefault(key, []).append(i)

    sem = asyncio.Semaphore(_ENRICH_CONCURRENCY)

    async def _one(idxs: list[int]) -> HRContact:
        rep = jobs[idxs[0]]
        domain = domain_from(
            getattr(rep, "company_website", None),
            getattr(rep, "apply_url", None),
            getattr(rep, "source_url", None),
        )
        async with sem:
            return await enrich_contact(rep.company, domain=domain, jd_text=getattr(rep, "jd_text", None))

    items = list(by_company.items())
    results = await asyncio.gather(*[_one(idxs) for _, idxs in items], return_exceptions=True)

    enriched = 0
    for (_, idxs), res in zip(items, results):
        if isinstance(res, Exception) or res is None:
            if isinstance(res, Exception):
                logger.warning(f"HR-contact enrichment error (non-fatal): {res}")
            continue
        for i in idxs:
            job = jobs[i]
            job.hr_name = res.hr_name
            job.hr_email = res.hr_email
            job.hr_linkedin_url = res.hr_linkedin_url
            job.hr_linkedin_search_url = res.hr_linkedin_search_url
            job.hr_contact_source = res.source
            job.hr_contact_confidence = res.confidence
            if res.has_any():
                enriched += 1
    return enriched
