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

    async def counting_fetch(board, region):
        fetches["n"] += 1
        return []
    monkeypatch.setattr(s, "_fetch_board", counting_fetch)
    monkeypatch.setattr(ATSAggregatorScraper, "_boards", staticmethod(
        lambda region: [{"ats": "greenhouse", "token": "acme", "company": "Acme"}]
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


# ── MENA region (docs/mena/PHASE_1_ATS_EMPLOYERS.md §1.1–1.3) ──

def _mena_jobs():
    def job(loc, url, remote=False):
        return {"title": "Backend Engineer", "location": loc, "source_url": url,
                "company": "Acme", "jd_text": "Build backend services.", "remote": remote}
    return [
        job("Riyadh, Saudi Arabia", "https://boards.test/riyadh"),
        job("Dubai", "https://boards.test/dubai"),
        job("Remote", "https://boards.test/remote", remote=True),
        job("Remote - EMEA", "https://boards.test/emea", remote=True),
        job("Bengaluru", "https://boards.test/blr"),
    ]


async def _search(monkeypatch, **kw):
    s = ATSAggregatorScraper()
    s._all_jobs = _mena_jobs()

    async def noop():
        return None
    monkeypatch.setattr(s.rate_limiter, "acquire", noop)
    out = await s.search_jobs("backend", max_results=10, **kw)
    return {j.source_url.rsplit("/", 1)[1]: j for j in out}


@pytest.mark.asyncio
async def test_mena_run_filters_by_country(monkeypatch):
    sa = await _search(monkeypatch, location="Saudi Arabia", region="mena")
    # Riyadh matches on country; the region-wide remote EMEA role is open to every
    # MENA country. Dubai, plain "Remote" and Bengaluru never qualify.
    assert set(sa) == {"riyadh", "emea"}
    ae = await _search(monkeypatch, location="United Arab Emirates", region="mena")
    assert set(ae) == {"dubai", "emea"}   # "Dubai" matches the UAE by country


@pytest.mark.asyncio
async def test_india_run_returns_only_india_roles(monkeypatch):
    out = await _search(monkeypatch, location="India", region="india")
    assert set(out) == {"blr"}


@pytest.mark.asyncio
async def test_mena_listing_currency_follows_location(monkeypatch):
    sa = await _search(monkeypatch, location="Saudi Arabia", region="mena")
    assert sa["riyadh"].salary_currency == "SAR"
    ae = await _search(monkeypatch, location="United Arab Emirates", region="mena")
    assert ae["dubai"].salary_currency == "AED"
    india = await _search(monkeypatch, location="India", region="india")
    assert india["blr"].salary_currency == "INR"   # non-MENA keeps the legacy default


def test_boards_are_scoped_by_region(monkeypatch):
    from services import ats_harvester
    monkeypatch.setattr(ats_harvester, "load_harvested", lambda: [])
    india = {(b["ats"], b["token"]) for b in ATSAggregatorScraper._boards("india")}
    mena = {(b["ats"], b["token"]) for b in ATSAggregatorScraper._boards("mena")}
    assert ("greenhouse", "postman") in india and ("greenhouse", "tamara") not in india
    assert ("oracle_hcm", "dpworld") not in india
    assert ("greenhouse", "tamara") in mena and ("greenhouse", "elastic") in mena
    assert ("greenhouse", "postman") not in mena
    # Global keeps legacy seeds plus the MENA boards tagged global (never MENA-only ones).
    glob = {(b["ats"], b["token"]) for b in ATSAggregatorScraper._boards("global")}
    assert ("greenhouse", "postman") in glob and ("greenhouse", "tamara") in glob
    assert ("smartrecruiters", "deliveryhero") not in glob


def test_harvested_boards_serve_every_region(monkeypatch):
    from services import ats_harvester
    monkeypatch.setattr(ats_harvester, "load_harvested",
                        lambda: [{"ats": "lever", "token": "harvested_co", "company": "H"}])
    for region in ("india", "global", "mena"):
        assert ("lever", "harvested_co") in {(b["ats"], b["token"]) for b in ATSAggregatorScraper._boards(region)}


def test_default_location_replaces_india_fallback():
    s = ATSAggregatorScraper()
    j = {"title": "Eng", "location": {"name": ""}, "absolute_url": "https://x.test/1", "content": ""}
    assert s._norm_greenhouse(j, "Tamara", "Riyadh, Saudi Arabia")["location"] == "Riyadh, Saudi Arabia"
    assert s._norm_greenhouse(j, "Groww")["location"] == "India"   # legacy default untouched


def test_sr_location_names_mena_countries():
    sr = ATSAggregatorScraper._sr_location
    assert sr({"location": {"city": "Dubai", "country": "ae"}}) == "Dubai, United Arab Emirates"
    assert sr({"location": {"city": "Pune", "country": "in"}}) == "Pune, India"


@pytest.mark.asyncio
async def test_smartrecruiters_mena_merges_countries_and_caps_per_board(monkeypatch):
    s = ATSAggregatorScraper()
    calls = []

    async def fake_get_json(url, params=None, headers=None):
        calls.append((url, params))
        if url.endswith("/postings"):
            cc = params["country"]
            # "ae" and "sa" both return the shared id 1 (must dedupe); the rest are
            # non-tech titles that must sort behind the tech ones.
            if cc == "ae":
                return {"content": [{"id": "1", "name": "Office Manager", "location": {"city": "Dubai", "country": "ae"}}]
                        + [{"id": f"a{i}", "name": "Accountant", "location": {"city": "Dubai", "country": "ae"}} for i in range(20)]}
            if cc == "sa":
                return {"content": [{"id": "1", "name": "Office Manager", "location": {"city": "Dubai", "country": "ae"}},
                                    {"id": "t", "name": "Senior Software Engineer", "location": {"city": "Riyadh", "country": "sa"}}]}
            return {"content": []}
        return {}
    monkeypatch.setattr(s, "_get_json", fake_get_json)

    out = await s._fetch_smartrecruiters("acme", "Acme", "mena", "Dubai, United Arab Emirates")
    list_calls = [p["country"] for u, p in calls if u.endswith("/postings")]
    assert list_calls == ["ae", "sa", "eg", "qa", "kw", "bh", "om", "jo", "ma"]
    assert len(out) == 12                                   # per-board cap, not per-country
    assert out[0]["title"] == "Senior Software Engineer"    # tech title first
    assert len({o["source_url"] for o in out}) == 12        # id "1" appeared once
    # Legacy runs stay on country=in only.
    calls.clear()
    await s._fetch_smartrecruiters("acme", "Acme", "global")
    assert [p["country"] for u, p in calls if u.endswith("/postings")] == ["in"]


# ── Result diversity under a small cap ──

def _diverse_jobs(loc_a, loc_b, loc_c):
    def job(company, loc, i):
        return {"title": "Backend Engineer", "location": loc, "source_url": f"https://boards.test/{company}-{i}",
                "company": company, "jd_text": "Build backend services.", "remote": False}
    return ([job("A", loc_a, i) for i in range(10)]
            + [job("B", loc_b, i) for i in range(2)] + [job("C", loc_c, i) for i in range(2)])


async def _capped(monkeypatch, jobs, **kw):
    s = ATSAggregatorScraper()
    s._all_jobs = jobs

    async def noop():
        return None
    monkeypatch.setattr(s.rate_limiter, "acquire", noop)
    return s, await s.search_jobs("backend", max_results=6, **kw)


@pytest.mark.asyncio
async def test_mena_interleaves_employers_under_small_cap(monkeypatch):
    jobs = _diverse_jobs("Dubai, United Arab Emirates", "Dubai, United Arab Emirates", "Abu Dhabi, United Arab Emirates")
    s, out = await _capped(monkeypatch, jobs, location="United Arab Emirates", region="mena")
    assert [j.company for j in out] == ["A", "B", "C", "A", "B", "C"]
    # Only returned jobs are marked seen, so the rest stay available to later searches.
    assert len(s._seen_urls) == 6
    again = await s.search_jobs("backend", location="United Arab Emirates", max_results=20, region="mena")
    assert len(again) == 8


@pytest.mark.asyncio
async def test_mena_picks_newest_first_within_a_company(monkeypatch):
    from datetime import datetime
    jobs = _diverse_jobs("Dubai", "Dubai", "Dubai")
    for i, j in enumerate(jobs[:10]):
        j["posted_at"] = datetime(2026, 1, 1 + i) if i != 3 else None
    _, out = await _capped(monkeypatch, jobs, location="United Arab Emirates", region="mena")
    a = [j.source_url for j in out if j.company == "A"]
    assert a == ["https://boards.test/A-9", "https://boards.test/A-8"]   # newest dated first


@pytest.mark.asyncio
async def test_india_path_keeps_board_order(monkeypatch):
    jobs = _diverse_jobs("Bengaluru, India", "Bengaluru, India", "Bengaluru, India")
    _, out = await _capped(monkeypatch, jobs, location="India", region="india")
    assert [j.company for j in out] == ["A"] * 6      # unchanged: fills in load order


@pytest.mark.asyncio
async def test_mena_successive_searches_rotate_through_employers(monkeypatch):
    def job(company, i):
        return {"title": "Backend Engineer", "location": "Dubai, United Arab Emirates",
                "source_url": f"https://boards.test/{company}-{i}", "company": company,
                "jd_text": "Build backend services.", "remote": False}
    s = ATSAggregatorScraper()
    s._all_jobs = [job(c, i) for c in "ABCDE" for i in range(3)]

    async def noop():
        return None
    monkeypatch.setattr(s.rate_limiter, "acquire", noop)
    seen = []
    for _ in range(3):
        out = await s.search_jobs("backend", location="United Arab Emirates", max_results=2, region="mena")
        seen += [j.company for j in out]
    assert seen == ["A", "B", "C", "D", "E", "A"]   # every employer is reached before any repeats
