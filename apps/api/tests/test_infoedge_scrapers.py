"""Offline parsing tests for the Info Edge gladiator scrapers (Hirist, iimjobs)."""
import json
from pathlib import Path

import pytest

from scrapers.hirist import HiristScraper
from scrapers.iimjobs import IimjobsScraper

FIXTURE = Path(__file__).parent / "fixtures" / "hirist_search.json"


@pytest.fixture
def payload():
    return json.loads(FIXTURE.read_text())


async def _run(monkeypatch, scraper, pages):
    calls = iter(pages)

    async def fake_get(url, params=None, headers=None):
        assert url.endswith("/job/search")
        assert params["query"] and "page" in params
        return next(calls, {"data": [], "hasMore": False})

    async def noop():
        return None

    monkeypatch.setattr(scraper, "_get_json", fake_get)
    monkeypatch.setattr(scraper.rate_limiter, "acquire", noop)
    return scraper


def test_fixture_contract(payload):
    """Guards against upstream field renames in the gladiator API."""
    assert payload["data"], "fixture should contain jobs"
    j = payload["data"][0]
    for key in ("title", "jobDetailUrl", "locations", "tags", "min", "max", "createdTime"):
        assert key in j, f"gladiator API dropped field '{key}'"


def test_host_config():
    assert HiristScraper().GLADIATOR_HOST == "gladiator.hirist.tech"
    assert IimjobsScraper().GLADIATOR_HOST == "gladiator.iimjobs.com"
    assert HiristScraper().platform.value == "hirist"
    assert IimjobsScraper().platform.value == "iimjobs"


@pytest.mark.asyncio
async def test_maps_core_fields(monkeypatch, payload):
    scraper = await _run(monkeypatch, HiristScraper(), [{**payload, "hasMore": False}])
    jobs = await scraper.search_jobs("node", "Bangalore", max_results=10)

    assert len(jobs) == len(payload["data"])
    j = jobs[0]
    src = payload["data"][0]
    assert j.source_platform.value == "hirist"
    assert j.source_url == src["jobDetailUrl"]
    assert j.title and " - " not in j.title.split(" ")[0]  # company stripped off the front
    assert isinstance(j.required_skills, list) and j.required_skills  # tags → skills
    assert j.location and j.location != "India"  # locations[].name mapped
    if src.get("createdTime"):
        assert j.posted_at is not None and j.posted_at.year >= 2020  # ms→dt, not epoch-seconds garbage


@pytest.mark.asyncio
async def test_company_split_from_title(monkeypatch):
    page = {"hasMore": False, "data": [{
        "id": 1, "title": "NetApp - Full Stack Engineer - Node.js",
        "jobdesignation": "Full Stack Engineer", "jobDetailUrl": "https://www.hirist.tech/j/x-1",
        "locations": [{"id": 3, "name": "Bangalore"}], "tags": [{"name": "Node.js"}],
        "min": 5, "max": 8, "createdTime": 1781634600000,
    }]}
    scraper = await _run(monkeypatch, HiristScraper(), [page])
    jobs = await scraper.search_jobs("node", "Bangalore", max_results=5)
    assert jobs[0].company == "NetApp"
    assert jobs[0].title == "Full Stack Engineer - Node.js"


@pytest.mark.asyncio
async def test_confidential_company_fallback(monkeypatch):
    page = {"hasMore": False, "data": [{
        "id": 2, "title": "Confidential - Backend Lead", "jobDetailUrl": "https://www.hirist.tech/j/y-2",
        "locations": [{"name": "Pune"}], "tags": [], "min": 6, "max": 10,
        "confidential": 1, "createdTime": 1781634600000,
    }]}
    scraper = await _run(monkeypatch, HiristScraper(), [page])
    jobs = await scraper.search_jobs("backend", "Pune", max_results=5)
    assert "confidential" in jobs[0].company.lower()


@pytest.mark.asyncio
async def test_hidden_salary_never_emitted(monkeypatch):
    page = {"hasMore": False, "data": [{
        "id": 3, "title": "Acme - Dev", "jobDetailUrl": "https://www.hirist.tech/j/z-3",
        "locations": [{"name": "Noida"}], "tags": [], "min": 3, "max": 5,
        "hideSal": 1, "minSal": 1500000, "maxSal": 2500000, "createdTime": 1781634600000,
    }]}
    scraper = await _run(monkeypatch, HiristScraper(), [page])
    jobs = await scraper.search_jobs("dev", "Noida", max_results=5)
    assert jobs[0].salary_min is None and jobs[0].salary_max is None


@pytest.mark.asyncio
async def test_pagination_stops_on_has_more_false(monkeypatch, payload):
    # hasMore False after page 0 → only one API call's worth of jobs.
    scraper = await _run(monkeypatch, HiristScraper(), [{**payload, "hasMore": False}, {**payload, "hasMore": False}])
    jobs = await scraper.search_jobs("node", "Bangalore", max_results=50)
    assert len(jobs) == len(payload["data"])  # did not page again


@pytest.mark.asyncio
async def test_empty_yields_nothing(monkeypatch):
    scraper = await _run(monkeypatch, IimjobsScraper(), [{"data": [], "hasMore": False}])
    jobs = await scraper.search_jobs("nothing", "Nowhere", max_results=5)
    assert jobs == []
