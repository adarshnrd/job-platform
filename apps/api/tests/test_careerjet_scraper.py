"""Offline tests for the Careerjet scraper (dormant keyed source)."""
import pytest

from scrapers.careerjet import CareerjetScraper


@pytest.mark.asyncio
async def test_dormant_without_affid(monkeypatch):
    monkeypatch.setattr(CareerjetScraper, "has_key", staticmethod(lambda: False))
    scraper = CareerjetScraper()
    jobs = await scraper.search_jobs("node.js", "Bangalore", region="india")
    assert jobs == []


@pytest.mark.asyncio
async def test_parses_response(monkeypatch):
    from scrapers import careerjet as cj_mod
    monkeypatch.setattr(cj_mod.settings, "CAREERJET_AFFID", "test_affid_123")
    payload = {
        "type": "JOBS",
        "jobs": [{
            "title": "Backend Engineer (Node.js)", "company": "Acme",
            "locations": "Bangalore", "salary_min": "1500000", "salary_max": "2500000",
            "url": "https://www.careerjet.co.in/jobad/abc123",
            "description": "Build <b>Node.js</b> services", "date": "2026-07-01",
        }],
    }

    async def fake_get(url, params=None, headers=None):
        assert params["affid"] and params["locale_code"] == "en_IN"
        return payload

    scraper = CareerjetScraper()
    monkeypatch.setattr(scraper, "_get_json", fake_get)

    async def noop():
        return None
    monkeypatch.setattr(scraper.rate_limiter, "acquire", noop)

    jobs = await scraper.search_jobs("node.js", "Bangalore", region="india")
    assert len(jobs) == 1
    j = jobs[0]
    assert j.title == "Backend Engineer (Node.js)"
    assert j.company == "Acme"
    assert j.source_platform.value == "careerjet"
    assert j.salary_min == 1500000 and j.salary_max == 2500000
    assert "<b>" not in j.jd_text  # HTML stripped


@pytest.mark.asyncio
async def test_handles_no_jobs_type(monkeypatch):
    from scrapers import careerjet as cj_mod
    monkeypatch.setattr(cj_mod.settings, "CAREERJET_AFFID", "test_affid_123")

    async def fake_get(url, params=None, headers=None):
        return {"type": "LOCATIONS", "solveLocations": []}  # ambiguous-location response

    scraper = CareerjetScraper()
    monkeypatch.setattr(scraper, "_get_json", fake_get)

    async def noop():
        return None
    monkeypatch.setattr(scraper.rate_limiter, "acquire", noop)

    jobs = await scraper.search_jobs("x", "y", region="india")
    assert jobs == []
