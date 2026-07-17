"""Offline tests for HR-contact enrichment (services/hr_contact.py).

Key guarantee under test: with NO provider key set, `hr_email` is never
populated (no guessing) — only the keyless LinkedIn people-search link appears.
A keyed provider is simulated by patching `_PROVIDERS`; no network is touched.
"""
from urllib.parse import parse_qs, urlparse

import pytest

from models.job import JobListingCreate, Platform
from services import hr_contact
from services.hr_contact import (
    HRContact,
    clean_company,
    domain_from,
    enrich_contact,
    enrich_jobs,
    linkedin_people_search_url,
)


def _job(company="Acme", url="https://boards.greenhouse.io/acme/jobs/1", **kw):
    return JobListingCreate(
        title=kw.pop("title", "Backend Engineer"),
        company=company,
        jd_text=kw.pop("jd_text", "Build things"),
        source_platform=Platform.company_portal,
        source_url=url,
        **kw,
    )


# ── company/URL helpers ──
def test_clean_company_strips_suffixes_and_aggregator():
    assert clean_company("Postman, Inc.") == "Postman"
    assert clean_company("Razorpay Software Private Limited") == "Razorpay"
    assert clean_company("Acme (via Careerjet)") == "Acme"
    assert clean_company("  Groww  ") == "Groww"


def test_linkedin_search_url_is_a_search_link():
    url = linkedin_people_search_url("Postman, Inc.")
    parsed = urlparse(url)
    assert parsed.netloc == "www.linkedin.com"
    assert parsed.path == "/search/results/people/"
    kw = parse_qs(parsed.query)["keywords"][0]
    assert "Postman" in kw and "Inc" not in kw
    assert "recruiter" in kw.lower()


def test_domain_from_skips_ats_hosts_and_extracts_company():
    # ATS / aggregator hosts are NOT the employer's mail domain → None.
    assert domain_from("https://boards.greenhouse.io/acme/jobs/1") is None
    assert domain_from("https://jobs.lever.co/meesho/abc") is None
    assert domain_from(None, "https://www.linkedin.com/jobs/view/1") is None
    # A real company site resolves (www. stripped).
    assert domain_from("https://www.postman.com/careers") == "postman.com"
    # First usable candidate wins; ATS apply_url is skipped in favour of website.
    assert domain_from("https://boards.greenhouse.io/x", "https://acme.io") == "acme.io"


# ── verified-only email guarantee ──
@pytest.mark.asyncio
async def test_keyless_never_guesses_email(monkeypatch):
    # No provider keys → no providers active.
    monkeypatch.setattr(hr_contact, "_PROVIDERS", [])
    contact = await enrich_contact("Acme", domain="acme.io")
    assert contact.hr_email is None          # never guessed
    assert contact.hr_linkedin_url is None
    assert contact.confidence is None
    assert contact.source == "search"
    assert contact.hr_linkedin_search_url and "linkedin.com/search" in contact.hr_linkedin_search_url


@pytest.mark.asyncio
async def test_real_providers_are_dormant_without_keys(monkeypatch):
    for name in ("HUNTER_API_KEY", "APOLLO_API_KEY", "PROXYCURL_API_KEY"):
        monkeypatch.setattr(hr_contact.settings, name, "")
    assert hr_contact._active_providers() == []


# ── verified provider merges in ──
class _FakeProvider(hr_contact._Provider):
    name = "hunter"

    def __init__(self, contact):
        self._contact = contact
        self.calls = 0

    def has_key(self):
        return True

    async def lookup(self, company, domain, jd_text):
        self.calls += 1
        return self._contact


@pytest.mark.asyncio
async def test_verified_provider_populates_contact(monkeypatch):
    fake = _FakeProvider(HRContact(
        hr_name="Priya R", hr_email="priya@acme.io",
        hr_linkedin_url="https://www.linkedin.com/in/priya", source="hunter", confidence=92,
    ))
    monkeypatch.setattr(hr_contact, "_PROVIDERS", [fake])
    contact = await enrich_contact("Acme", domain="acme.io")
    assert contact.hr_email == "priya@acme.io"
    assert contact.hr_linkedin_url == "https://www.linkedin.com/in/priya"
    assert contact.hr_name == "Priya R"
    assert contact.source == "hunter"
    assert contact.confidence == 92
    # The keyless search link is still available as a fallback path.
    assert contact.hr_linkedin_search_url


@pytest.mark.asyncio
async def test_provider_failure_is_non_fatal(monkeypatch):
    class _Boom(hr_contact._Provider):
        name = "hunter"

        def has_key(self):
            return True

        async def lookup(self, *a):
            raise RuntimeError("api down")

    monkeypatch.setattr(hr_contact, "_PROVIDERS", [_Boom()])
    contact = await enrich_contact("Acme", domain="acme.io")
    assert contact.hr_email is None
    assert contact.source == "search"  # degraded to the keyless link, no crash


# ── batch enrichment over listings ──
@pytest.mark.asyncio
async def test_enrich_jobs_sets_fields_and_caches_per_company(monkeypatch):
    monkeypatch.setattr(hr_contact, "_PROVIDERS", [])  # keyless
    calls: list[str] = []

    real_enrich = hr_contact.enrich_contact

    async def counting_enrich(company, **kw):
        calls.append(company)
        return await real_enrich(company, **kw)

    monkeypatch.setattr(hr_contact, "enrich_contact", counting_enrich)

    jobs = [
        _job(company="Acme", url="https://x/1"),
        _job(company="Acme, Inc.", url="https://x/2"),   # same employer, different URL
        _job(company="Globex", url="https://x/3"),
    ]
    n = await enrich_jobs(jobs)

    assert n == 3  # each got a search link
    # One lookup per normalized company → Acme collapsed with "Acme, Inc.".
    assert len(calls) == 2
    for job in jobs:
        assert job.hr_contact_source == "search"
        assert job.hr_linkedin_search_url and "linkedin.com/search" in job.hr_linkedin_search_url
        assert job.hr_email is None


@pytest.mark.asyncio
async def test_enrich_jobs_empty_is_noop():
    assert await enrich_jobs([]) == 0
