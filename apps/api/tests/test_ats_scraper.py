"""Offline tests for the ATS-direct aggregator (Greenhouse/Lever/Ashby)."""
import json
from pathlib import Path

import pytest

from scrapers.ats import ATSAggregatorScraper

FX = Path(__file__).parent / "fixtures"


@pytest.fixture
def greenhouse():
    return json.loads((FX / "greenhouse_groww.json").read_text())


@pytest.fixture
def lever():
    return json.loads((FX / "lever_meesho.json").read_text())


def test_greenhouse_contract(greenhouse):
    j = greenhouse["jobs"][0]
    for k in ("title", "location", "absolute_url", "content", "updated_at"):
        assert k in j, f"Greenhouse dropped '{k}'"


def test_lever_contract(lever):
    j = lever[0]
    for k in ("text", "categories", "hostedUrl", "createdAt"):
        assert k in j, f"Lever dropped '{k}'"


def test_greenhouse_normalization(greenhouse):
    s = ATSAggregatorScraper()
    norm = s._norm_greenhouse(greenhouse["jobs"][0], "Groww")
    assert norm["company"] == "Groww"
    assert norm["title"]
    assert norm["source_url"].startswith("http")
    assert "<" not in norm["jd_text"]  # HTML stripped
    assert s._is_india(norm)  # groww fixture jobs are India


def test_lever_normalization(lever):
    s = ATSAggregatorScraper()
    norm = s._norm_lever(lever[0], "Meesho")
    assert norm["company"] == "Meesho"
    assert norm["title"]
    assert norm["source_url"].startswith("http")
    assert norm["posted_at"] is not None and norm["posted_at"].year >= 2020  # epoch ms → dt


@pytest.mark.asyncio
async def test_search_filters_by_query_and_location(monkeypatch, greenhouse, lever):
    s = ATSAggregatorScraper()
    # Preload the cache directly with normalized jobs (skip network).
    jobs = [s._norm_greenhouse(j, "Groww") for j in greenhouse["jobs"]]
    jobs += [s._norm_lever(j, "Meesho") for j in lever]
    s._all_jobs = [j for j in jobs if s._is_india(j)]

    async def noop():
        return None
    monkeypatch.setattr(s.rate_limiter, "acquire", noop)

    # A generic query returns India jobs with real fields.
    out = await s.search_jobs("manager", "India", max_results=10)
    assert out, "expected some matches for a common query"
    j = out[0]
    assert j.source_platform.value == "company_portal"
    assert j.source_url.startswith("http")
    assert j.company in ("Groww", "Meesho")


@pytest.mark.asyncio
async def test_query_with_no_matches_returns_empty(monkeypatch, greenhouse):
    s = ATSAggregatorScraper()
    s._all_jobs = [s._norm_greenhouse(j, "Groww") for j in greenhouse["jobs"]]

    async def noop():
        return None
    monkeypatch.setattr(s.rate_limiter, "acquire", noop)

    out = await s.search_jobs("zxqwynevermatch", "India", max_results=10)
    assert out == []


@pytest.mark.asyncio
async def test_dedupes_within_run(monkeypatch, greenhouse):
    s = ATSAggregatorScraper()
    s._all_jobs = [s._norm_greenhouse(j, "Groww") for j in greenhouse["jobs"]]

    async def noop():
        return None
    monkeypatch.setattr(s.rate_limiter, "acquire", noop)

    first = await s.search_jobs("associate", "India", max_results=10)
    second = await s.search_jobs("associate", "India", max_results=10)  # same query again
    assert first and second == []  # already-seen URLs not re-emitted


@pytest.mark.asyncio
async def test_region_controls_whether_overseas_roles_are_kept(monkeypatch):
    """India seed companies also post abroad; a global run wants exactly those."""
    s = ATSAggregatorScraper()
    s._all_jobs = [
        {"title": "Backend Engineer", "location": "Bangalore, India",
         "source_url": "https://boards.test/in-1", "company": "Groww",
         "jd_text": "Build backend services.", "remote": False},
        {"title": "Backend Engineer", "location": "Berlin, Germany",
         "source_url": "https://boards.test/de-1", "company": "Groww",
         "jd_text": "Build backend services.", "remote": False},
    ]

    async def noop():
        return None
    monkeypatch.setattr(s.rate_limiter, "acquire", noop)

    india = await s.search_jobs("backend", "", max_results=10, region="india")
    assert [j.source_url for j in india] == ["https://boards.test/in-1"]

    s._seen_urls.clear()  # dedup is per-run, not per-region
    glob = await s.search_jobs("backend", "", max_results=10, region="global")
    assert {j.source_url for j in glob} == {
        "https://boards.test/in-1", "https://boards.test/de-1"
    }


@pytest.mark.asyncio
async def test_board_cache_survives_a_region_switch(monkeypatch):
    """Boards are fetched once per run: the fetch is region-agnostic and only
    the filter differs, so switching region must not re-hit every board."""
    s = ATSAggregatorScraper()
    fetches = {"n": 0}

    async def counting_fetch(board):
        fetches["n"] += 1
        return []
    monkeypatch.setattr(s, "_fetch_board", counting_fetch)
    monkeypatch.setattr(ATSAggregatorScraper, "_boards", staticmethod(
        lambda: [{"ats": "greenhouse", "token": "acme", "company": "Acme"}]
    ))

    async def noop():
        return None
    monkeypatch.setattr(s.rate_limiter, "acquire", noop)

    await s.search_jobs("x", "", region="india")
    await s.search_jobs("x", "", region="global")
    assert fetches["n"] == 1, "board list should be fetched once, not per region"


def test_seed_boards_are_well_formed():
    from scrapers.ats import SEED_BOARDS
    assert SEED_BOARDS
    for b in SEED_BOARDS:
        assert b["ats"] in ("greenhouse", "lever", "ashby", "workable", "smartrecruiters", "recruitee")
        assert b["token"] and b["company"]
