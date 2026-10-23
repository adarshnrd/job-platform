"""MENA eligibility on the remote boards (docs/mena/PHASE_2_REGIONAL_BOARDS.md §2.6)
and MENA routing for the keyed aggregators (§2.7, dormant without keys).

Each remote board gets a two-item response: one restricted to the United States
and one open to EMEA/worldwide. A `mena` run keeps only the second; india/global
behaviour is asserted unchanged."""
import asyncio

import pytest

from models.job import Platform
from scrapers.himalayas import HimalayasScraper
from scrapers.jobicy import JobicyScraper
from scrapers.remoteok import RemoteOKScraper
from scrapers.remotive import RemotiveScraper
from workers.job_discovery import SOURCE_REGISTRY, select_sources


def _search(scraper, payload, *args, **kwargs):
    """Run scraper.search_jobs with `_get_json` answering `payload`."""
    async def fake_get(url, params=None, headers=None):
        return payload

    scraper._get_json = fake_get
    return asyncio.run(scraper.search_jobs(*args, **kwargs))


# ── Himalayas ──
HIMALAYAS = {"jobs": [
    {"title": "Python Developer", "companyName": "UsCo", "locationRestrictions": ["United States"],
     "applicationLink": "https://himalayas.app/j/us", "description": "python backend", "pubDate": "2026-10-10T00:00:00Z"},
    {"title": "Python Engineer", "companyName": "EmeaCo", "locationRestrictions": ["EMEA"],
     "applicationLink": "https://himalayas.app/j/emea", "description": "python backend", "pubDate": "2026-10-10T00:00:00Z"},
    {"title": "Python Dev", "companyName": "OpenCo", "locationRestrictions": [],
     "applicationLink": "https://himalayas.app/j/open", "description": "python", "pubDate": "2026-10-10T00:00:00Z"},
]}


def test_himalayas_mena_keeps_emea_and_unrestricted_only():
    jobs = _search(HimalayasScraper(), HIMALAYAS, "python", region="mena")
    assert [j.company for j in jobs] == ["EmeaCo", "OpenCo"]
    assert all(j.salary_currency == "USD" for j in jobs)        # never the INR model default


def test_himalayas_global_unchanged():
    assert len(_search(HimalayasScraper(), HIMALAYAS, "python", region="global")) == 3


def test_himalayas_india_unchanged():
    # Only unrestricted rows survive for India (no "india" restriction anywhere).
    assert [j.company for j in _search(HimalayasScraper(), HIMALAYAS, "python", region="india")] == ["OpenCo"]


# ── Jobicy ──
JOBICY = {"jobs": [
    {"jobTitle": "Backend Dev", "companyName": "UsCo", "url": "https://jobicy.com/j/us", "jobGeo": "USA",
     "jobDescription": "x", "pubDate": "2026-10-10 10:00:00"},
    {"jobTitle": "Backend Dev", "companyName": "WorldCo", "url": "https://jobicy.com/j/ww", "jobGeo": "Anywhere",
     "jobDescription": "x", "pubDate": "2026-10-10 10:00:00"},
    {"jobTitle": "Backend Dev", "companyName": "EmeaCo", "url": "https://jobicy.com/j/emea", "jobGeo": "EMEA",
     "jobDescription": "x", "pubDate": "2026-10-10 10:00:00"},
]}


def test_jobicy_mena_filters_by_geo():
    jobs = _search(JobicyScraper(), JOBICY, "backend", region="mena")
    assert [j.company for j in jobs] == ["WorldCo", "EmeaCo"]
    assert all(j.salary_currency for j in jobs) and all(j.salary_currency != "INR" for j in jobs)


def test_jobicy_global_unchanged():
    assert len(_search(JobicyScraper(), JOBICY, "backend", region="global")) == 3


# ── RemoteOK ──
REMOTEOK = [
    {"legal": "notice"},
    {"slug": "us-1", "id": "1", "position": "Python Developer", "company": "UsCo", "location": "United States",
     "tags": ["python"], "url": "https://remoteok.com/remote-jobs/us-1", "epoch": 1760000000},
    {"slug": "ww-2", "id": "2", "position": "Python Developer", "company": "WorldCo", "location": "",
     "tags": ["python"], "url": "https://remoteok.com/remote-jobs/ww-2", "epoch": 1760000000},
    {"slug": "me-3", "id": "3", "position": "Python Developer", "company": "GulfCo", "location": "Dubai",
     "tags": ["python"], "url": "https://remoteok.com/remote-jobs/me-3", "epoch": 1760000000},
]


def test_remoteok_mena_empty_location_counts_as_worldwide():
    jobs = _search(RemoteOKScraper(), REMOTEOK, "python", region="mena")
    assert [j.company for j in jobs] == ["WorldCo", "GulfCo"]
    assert all(j.salary_currency == "USD" for j in jobs)


def test_remoteok_global_unchanged():
    assert len(_search(RemoteOKScraper(), REMOTEOK, "python", region="global")) == 3


# ── Remotive ──
REMOTIVE = {"jobs": [
    {"id": 1, "title": "Python Developer", "company_name": "UsCo", "url": "https://remotive.com/j/1",
     "candidate_required_location": "USA Only", "description": "<p>x</p>", "publication_date": "2026-10-10T00:00:00"},
    {"id": 2, "title": "Python Developer", "company_name": "WorldCo", "url": "https://remotive.com/j/2",
     "candidate_required_location": "Worldwide", "description": "<p>x</p>", "publication_date": "2026-10-10T00:00:00"},
]}


def test_remotive_mena_keeps_worldwide_only():
    jobs = _search(RemotiveScraper(), REMOTIVE, "python", region="mena")
    assert [j.company for j in jobs] == ["WorldCo"]
    assert jobs[0].salary_currency == "USD"


def test_remotive_without_region_still_works_and_keeps_everything():
    assert len(_search(RemotiveScraper(), REMOTIVE, "python")) == 2           # old call shape
    assert len(_search(RemotiveScraper(), REMOTIVE, "python", region="global")) == 2


def test_remotive_accepts_region_so_discovery_passes_it():
    import inspect
    assert "region" in inspect.signature(RemotiveScraper.search_jobs).parameters


# ── registration ──
@pytest.mark.parametrize("name", ["himalayas", "jobicy", "remoteok", "remotive"])
def test_remote_boards_serve_mena_everywhere(name):
    src = SOURCE_REGISTRY[name]
    assert "mena" in src.regions and "mena" in src.cls.regions
    assert name in {s.name for s in select_sources("mena", [])}


# ══════════════════════════════════════════════════════════════
#  Keyed aggregators (dormant until keys exist; routing only)
# ══════════════════════════════════════════════════════════════
from scrapers import careerjet as cj_mod
from scrapers import jooble as jooble_mod
from scrapers import jsearch as js_mod
from scrapers.adzuna import AdzunaScraper
from scrapers.careerjet import CareerjetScraper, locale_for
from scrapers.jooble import JoobleScraper
from scrapers.jsearch import JSearchScraper


@pytest.mark.parametrize("location,locale", [
    ("Dubai", "en_AE"), ("Saudi Arabia", "en_SA"), ("Riyadh", "en_SA"), ("Cairo, Egypt", "en_EG"),
    ("Kuwait", "en_KW"), ("Doha", "en_QA"), ("Beirut", "en_AE"), ("", "en_AE"),
])
def test_careerjet_mena_locale_per_country(location, locale):
    assert locale_for("mena", location) == locale


def test_careerjet_other_regions_keep_their_locale():
    assert locale_for("india", "Pune") == "en_IN"
    assert locale_for("global", "London") == "en_GB"


def test_careerjet_mena_sends_location_and_uses_local_currency(monkeypatch):
    monkeypatch.setattr(cj_mod.settings, "CAREERJET_AFFID", "affid")
    seen = {}

    async def fake_get(url, params=None, headers=None):
        seen.update(params)
        return {"type": "JOBS", "jobs": [{
            "title": "Software Engineer", "company": "Acme", "locations": "Riyadh",
            "url": "https://www.careerjet.com.sa/jobad/1", "description": "<b>x</b>", "date": "2026-10-10",
        }]}

    scraper = CareerjetScraper()
    scraper._get_json = fake_get
    jobs = asyncio.run(scraper.search_jobs("software engineer", "Saudi Arabia", region="mena"))
    assert seen["locale_code"] == "en_SA" and seen["location"] == "Saudi Arabia"
    assert jobs[0].salary_currency == "SAR"


def test_careerjet_mena_error_answer_returns_empty_and_warns_once(monkeypatch):
    monkeypatch.setattr(cj_mod.settings, "CAREERJET_AFFID", "affid")
    monkeypatch.setattr(CareerjetScraper, "_warned_locales", set())

    async def fake_get(url, params=None, headers=None):
        return {"type": "ERROR", "error": "bad locale"}

    scraper = CareerjetScraper()
    scraper._get_json = fake_get
    assert asyncio.run(scraper.search_jobs("x", "Dubai", region="mena")) == []
    assert asyncio.run(scraper.search_jobs("x", "Dubai", region="mena")) == []
    assert CareerjetScraper._warned_locales == {"en_AE"}


def test_jsearch_mena_country_param_and_currency(monkeypatch):
    monkeypatch.setattr(js_mod.settings, "JSEARCH_RAPIDAPI_KEY", "k")
    seen = {}

    async def fake_get(url, params=None, headers=None):
        seen.update(params)
        return {"data": [{
            "job_title": "Backend Engineer", "employer_name": "Acme", "job_city": "Riyadh",
            "job_state": "Riyadh", "job_country": "SA", "job_apply_link": "https://acme.example/apply/1",
            "job_description": "x", "job_id": "j1",
        }]}

    scraper = JSearchScraper()
    scraper._get_json = fake_get
    jobs = asyncio.run(scraper.search_jobs("backend", "Saudi Arabia", region="mena"))
    assert seen["country"] == "sa" and seen["query"] == "backend in Saudi Arabia"
    assert jobs[0].salary_currency == "SAR"
    assert jobs[0].location.endswith("Saudi Arabia")


def test_jsearch_mena_unknown_location_defaults_to_uae(monkeypatch):
    monkeypatch.setattr(js_mod.settings, "JSEARCH_RAPIDAPI_KEY", "k")
    seen = {}

    async def fake_get(url, params=None, headers=None):
        seen.update(params)
        return {"data": []}

    scraper = JSearchScraper()
    scraper._get_json = fake_get
    asyncio.run(scraper.search_jobs("backend", "Atlantis", region="mena"))
    assert seen["country"] == "ae"


def test_jsearch_india_and_global_country_unchanged(monkeypatch):
    monkeypatch.setattr(js_mod.settings, "JSEARCH_RAPIDAPI_KEY", "k")
    countries = []

    async def fake_get(url, params=None, headers=None):
        countries.append(params["country"])
        return {"data": []}

    scraper = JSearchScraper()
    scraper._get_json = fake_get
    asyncio.run(scraper.search_jobs("backend", "Pune", region="india"))
    asyncio.run(scraper.search_jobs("backend", "London", region="global"))
    assert countries == ["in", "us"]


def test_jooble_mena_passes_location_through_with_local_currency(monkeypatch):
    monkeypatch.setattr(jooble_mod.settings, "JOOBLE_API_KEY", "k")
    bodies = []

    async def fake_post(url, json_body, headers=None):
        bodies.append(json_body)
        return {"jobs": [{"title": "Dev", "company": "Acme", "location": "Doha", "link": "https://j.example/1",
                          "snippet": "x", "id": 1, "updated": "2026-10-10"}]}

    scraper = JoobleScraper()
    scraper._post_json = fake_post
    jobs = asyncio.run(scraper.search_jobs("dev", "Qatar", region="mena"))
    assert bodies[0]["location"] == "Qatar"
    assert jobs[0].salary_currency == "QAR"


@pytest.mark.parametrize("name", ["careerjet", "jsearch", "jooble"])
def test_keyed_sources_serve_mena_but_stay_dormant_without_keys(name, monkeypatch):
    src = SOURCE_REGISTRY[name]
    assert "mena" in src.regions and "mena" in src.cls.regions
    monkeypatch.setattr(src.cls, "has_key", staticmethod(lambda: False))
    assert name not in {s.name for s in select_sources("mena", [])}
    monkeypatch.setattr(src.cls, "has_key", staticmethod(lambda: True))
    assert name in {s.name for s in select_sources("mena", [])}


def test_adzuna_is_not_a_mena_source():
    assert "mena" not in AdzunaScraper.regions and "mena" not in SOURCE_REGISTRY["adzuna"].regions
