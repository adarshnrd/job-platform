"""Offline parsing test for the TimesJobs API scraper (recorded fixture)."""
import json
from pathlib import Path

import pytest

from scrapers.timesjobs import TimesJobsScraper

FIXTURE = Path(__file__).parent / "fixtures" / "timesjobs_search.json"


@pytest.fixture
def payload():
    return json.loads(FIXTURE.read_text())


async def _run_with_stub(monkeypatch, payload, pages):
    """Drive search_jobs with _post_json stubbed to return `pages` in order."""
    scraper = TimesJobsScraper()
    calls = iter(pages)

    async def fake_post(url, json_body=None, headers=None):
        assert url == TimesJobsScraper.API_URL
        assert json_body["keyword"] and "page" in json_body
        return next(calls, {"jobs": []})

    monkeypatch.setattr(scraper, "_post_json", fake_post)

    async def noop():
        return None
    monkeypatch.setattr(scraper.rate_limiter, "acquire", noop)
    return scraper


def test_parses_recorded_response(payload):
    """Fixture shape is the contract — guards against upstream field renames."""
    assert payload["jobs"], "fixture should contain jobs"
    j = payload["jobs"][0]
    for key in ("title", "company", "location", "jobDetailUrl", "description", "skills"):
        assert key in j, f"TimesJobs API dropped field '{key}'"


@pytest.mark.asyncio
async def test_maps_fields_from_fixture(monkeypatch, payload):
    scraper = await _run_with_stub(monkeypatch, payload, [payload])
    jobs = await scraper.search_jobs("Node.js", "Bangalore", max_results=3)

    assert len(jobs) == len(payload["jobs"])
    first = jobs[0]
    src = payload["jobs"][0]
    assert first.title == src["title"].strip()
    assert first.source_platform.value == "timesjobs"
    assert first.source_url == src["jobDetailUrl"]
    assert first.apply_url == src["jobDetailUrl"]
    assert first.jd_text  # description mapped, HTML stripped
    assert "<" not in first.jd_text
    assert isinstance(first.required_skills, list)


@pytest.mark.asyncio
async def test_dedupes_repeated_urls(monkeypatch, payload):
    # Same page returned twice → second page's dupes are dropped.
    scraper = await _run_with_stub(monkeypatch, payload, [payload, payload])
    jobs = await scraper.search_jobs("Node.js", "Bangalore", max_results=50)
    urls = [j.source_url for j in jobs]
    assert len(urls) == len(set(urls))


@pytest.mark.asyncio
async def test_never_emits_placeholder_salary(monkeypatch):
    # API uses -1 for "unspecified" — must map to None, never a bogus figure.
    page = {"total": 1, "page": 1, "totalPages": 1, "jobs": [{
        "title": "Backend Engineer", "company": "Acme", "location": "Pune",
        "jobDetailUrl": "https://www.timesjobs.com/job-detail/x-1", "description": "Build APIs",
        "skills": "Node.js, TypeScript", "lowSalary": -1, "highSalary": -1,
        "experienceFrom": -1, "experienceTo": -1, "jobId": "1",
    }]}
    scraper = await _run_with_stub(monkeypatch, page, [page])
    jobs = await scraper.search_jobs("backend", "Pune", max_results=5)
    assert len(jobs) == 1
    j = jobs[0]
    assert j.salary_min is None and j.salary_max is None
    assert j.min_experience is None and j.max_experience is None
    assert j.required_skills == ["Node.js", "TypeScript"]


@pytest.mark.asyncio
async def test_empty_response_yields_nothing(monkeypatch):
    scraper = await _run_with_stub(monkeypatch, {}, [{"jobs": []}])
    jobs = await scraper.search_jobs("nothing", "Nowhere", max_results=5)
    assert jobs == []
