"""Offline tests for the MENA ATS vendors: Oracle HCM, Workday CXS, BambooHR and
Teamtailor (docs/mena/PHASE_1_ATS_EMPLOYERS.md §1.4–1.7).

Fixtures are real responses captured 2026-10-17, trimmed to ~3 items. The Oracle
ones had ExternalContactName / ExternalContactEmail / HiringManager removed
before commit; the tests below assert none of that leaks into job dicts.
"""
import json
from datetime import datetime
from pathlib import Path

import pytest

from scrapers import ats as ats_mod
from scrapers.ats import ATSAggregatorScraper, _parse_workday_posted
from services.geo import mena

FX = Path(__file__).parent / "fixtures"
CONTACT_KEYS = {"ExternalContactName", "ExternalContactEmail", "HiringManager"}


def _load(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


@pytest.fixture
def scraper(monkeypatch):
    s = ATSAggregatorScraper()

    async def noop():
        return None
    monkeypatch.setattr(s.rate_limiter, "acquire", noop)
    return s


def _assert_common(job, *, company):
    assert job["title"]
    assert job["company"] == company
    assert mena.is_mena(job["location"]), job["location"]
    assert job["source_url"].startswith("https://") and job["apply_url"] == job["source_url"]
    assert job["jd_text"] and "<" not in job["jd_text"]       # HTML stripped
    assert job["jd_text"] == job["jd_text"].strip()


# ── Contracts: the fields the normalizers rely on ──

def test_oracle_contract():
    head = _load("oracle_dpworld_list.json")["items"][0]
    assert head["TotalJobsCount"] > 0
    for req in head["requisitionList"]:
        for k in ("Id", "Title", "PostedDate", "PrimaryLocation", "PrimaryLocationCountry",
                  "ShortDescriptionStr", "secondaryLocations"):
            assert k in req, f"Oracle dropped '{k}'"
    detail = _load("oracle_dpworld_detail.json")["items"][0]
    for k in ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr"):
        assert k in detail


def test_oracle_fixtures_carry_no_contact_data():
    blob = (FX / "oracle_dpworld_list.json").read_text(encoding="utf-8") + (FX / "oracle_dpworld_detail.json").read_text(encoding="utf-8")
    for key in CONTACT_KEYS:
        assert key not in blob


def test_workday_contract():
    data = _load("workday_murex_list.json")
    assert data["total"] > 0
    for p in data["jobPostings"]:
        for k in ("title", "externalPath", "locationsText", "postedOn"):
            assert k in p, f"Workday dropped '{k}'"
    info = _load("workday_murex_detail.json")["jobPostingInfo"]
    for k in ("title", "jobDescription", "location", "country", "startDate", "externalUrl"):
        assert k in info


def test_bamboohr_contract():
    data = _load("bamboohr_toters_list.json")
    assert data["meta"]["totalCount"] > 0
    for it in data["result"]:
        for k in ("id", "jobOpeningName", "location", "atsLocation", "locationType"):
            assert k in it, f"BambooHR dropped '{k}'"
    op = _load("bamboohr_toters_detail.json")["result"]["jobOpening"]
    for k in ("jobOpeningShareUrl", "jobOpeningName", "jobOpeningStatus", "location", "description", "datePosted"):
        assert k in op


def test_teamtailor_contract():
    feed = _load("teamtailor_chalhoub_feed.json")
    for k in ("items", "next_url"):
        assert k in feed
    for it in feed["items"]:
        for k in ("id", "title", "url", "date_published", "content_html", "_jobposting"):
            assert k in it, f"Teamtailor dropped '{k}'"


# ── Normalization ──

def test_oracle_normalization_whitelists_fields():
    req = _load("oracle_dpworld_list.json")["items"][0]["requisitionList"][0]
    detail = _load("oracle_dpworld_detail.json")["items"][0]
    # Poison the inputs: even if contact fields were present they must not surface.
    req = {**req, **{k: "leak" for k in CONTACT_KEYS}}
    jd = ("Detailed description. " * 20).strip()
    job = ATSAggregatorScraper._norm_oracle(req, "DP World", "ehpv.fa.em2.oraclecloud.com", "CX_1", req["PrimaryLocation"], jd)
    _assert_common(job, company="DP World")
    assert job["source_url"] == f"https://ehpv.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/{req['Id']}"
    assert job["posted_at"] is not None
    assert not CONTACT_KEYS & set(job)
    assert "leak" not in json.dumps(job, default=str)
    assert detail  # fixture loads


@pytest.mark.asyncio
async def test_oracle_fetch_filters_region_and_uses_detail(scraper, monkeypatch):
    listing = _load("oracle_dpworld_list.json")
    detail = _load("oracle_dpworld_detail.json")
    calls = []

    async def fake_get_json(url, params=None, headers=None):
        calls.append((url, params))
        return detail if "Details" in url else listing
    monkeypatch.setattr(scraper, "_get_json", fake_get_json)
    board = {"ats": "oracle_hcm", "token": "dpworld", "company": "DP World",
             "host": "ehpv.fa.em2.oraclecloud.com", "site": "CX_1"}

    mena_jobs = await scraper._fetch_oracle(board, "mena", "United Arab Emirates")
    assert [j["location"] for j in mena_jobs] == ["Dubai, United Arab Emirates"]   # India roles dropped
    for j in mena_jobs:
        _assert_common(j, company="DP World")
        assert not CONTACT_KEYS & set(j)
    # The list's page request used the verified paging parameters.
    list_params = next(p for u, p in calls if u.endswith("recruitingCEJobRequisitions"))
    assert "siteNumber=CX_1,limit=100,offset=0" in list_params["finder"]

    india_jobs = await scraper._fetch_oracle(board, "india", "India")
    assert {j["location"] for j in india_jobs} == {"Mumbai, Maharashtra, India", "India"}
    global_jobs = await scraper._fetch_oracle(board, "global", "India")
    assert len(global_jobs) == 3


@pytest.mark.asyncio
async def test_oracle_blocked_board_yields_nothing(scraper, monkeypatch):
    async def blocked(url, params=None, headers=None):
        return None   # what _get_json returns on a WAF 403
    monkeypatch.setattr(scraper, "_get_json", blocked)
    board = {"ats": "oracle_hcm", "token": "roshn", "company": "ROSHN", "host": "x.oraclecloud.com", "site": "CX"}
    assert await scraper._fetch_oracle(board, "mena", "Saudi Arabia") == []


def test_workday_normalization():
    posting = _load("workday_murex_list.json")["jobPostings"][0]
    info = _load("workday_murex_detail.json")["jobPostingInfo"]
    job = ATSAggregatorScraper._norm_workday(posting, info, "Murex", "murex.wd3.myworkdayjobs.com", "MurexCareerPage1")
    _assert_common(job, company="Murex")
    assert job["location"] == "Beirut, Lebanon"      # country appended from the detail
    assert job["posted_at"] == datetime.fromisoformat(info["startDate"])  # startDate wins over "Posted Today"


@pytest.mark.asyncio
async def test_workday_fetch_pages_and_rechecks_region(scraper, monkeypatch):
    listing = _load("workday_murex_list.json")
    detail = _load("workday_murex_detail.json")
    posted = []

    async def fake_post(url, json_body, headers=None):
        posted.append(json_body)
        return listing
    seen_details = []

    async def fake_get(url, params=None, headers=None):
        seen_details.append(url)
        return detail
    monkeypatch.setattr(scraper, "_post_json", fake_post)
    monkeypatch.setattr(scraper, "_get_json", fake_get)
    board = {"ats": "workday", "token": "murex", "company": "Murex", "host": "murex.wd3.myworkdayjobs.com",
             "tenant": "murex", "site": "MurexCareerPage1"}

    jobs = await scraper._fetch_workday(board, "mena", "Beirut, Lebanon")
    assert posted[0]["limit"] == 20          # Workday rejects larger pages
    assert len(jobs) == len(listing["jobPostings"])
    assert all(mena.is_mena(j["location"]) for j in jobs)
    assert seen_details[0].startswith("https://murex.wd3.myworkdayjobs.com/wday/cxs/murex/MurexCareerPage1/job/")
    # An India run drops Beirut roles even though the detail call succeeded.
    assert await scraper._fetch_workday(board, "india", "India") == []


def test_workday_board_parts_fall_back_to_composite_token():
    parts = ATSAggregatorScraper._board_parts(
        {"ats": "workday", "token": "murex.wd3.myworkdayjobs.com|murex|MurexCareerPage1"})
    assert parts == {"host": "murex.wd3.myworkdayjobs.com", "tenant": "murex", "site": "MurexCareerPage1"}


def test_parse_workday_posted():
    def days_ago(dt):
        return round((datetime.utcnow() - dt).total_seconds() / 86400)
    assert days_ago(_parse_workday_posted("Posted Today")) == 0
    assert days_ago(_parse_workday_posted("Posted Yesterday")) == 1
    assert days_ago(_parse_workday_posted("Posted 18 Days Ago")) == 18
    assert days_ago(_parse_workday_posted("Posted 30+ Days Ago")) == 30
    assert _parse_workday_posted("") is None
    assert _parse_workday_posted("sometime") is None


def test_bamboohr_normalization():
    item = _load("bamboohr_toters_list.json")["result"][0]
    opening = _load("bamboohr_toters_detail.json")["result"]["jobOpening"]
    job = ATSAggregatorScraper._norm_bamboohr(item, opening, "Toters", "toters", "Beirut, Lebanon")
    _assert_common(job, company="Toters")
    assert job["location"] == "Metn, Lebanon"
    assert job["source_url"].startswith("https://toters.bamboohr.com/careers/")
    assert job["posted_at"] is not None
    assert job["remote"] is False             # isRemote is null on this board


def test_bamboohr_list_location_dedupes_city_and_state():
    it = {"location": {"city": "Metn", "state": "Metn"}, "atsLocation": {"country": None}}
    assert ATSAggregatorScraper._bamboo_list_location(it) == "Metn"


@pytest.mark.asyncio
async def test_bamboohr_fetch_skips_closed_and_foreign_roles(scraper, monkeypatch):
    listing = _load("bamboohr_toters_list.json")
    opening = _load("bamboohr_toters_detail.json")
    closed = json.loads(json.dumps(opening))
    closed["result"]["jobOpening"]["jobOpeningStatus"] = "Filled"
    calls = []

    async def fake_get(url, params=None, headers=None):
        calls.append(url)
        if url.endswith("/careers/list"):
            return listing
        return closed if url.endswith(f"/careers/{listing['result'][0]['id']}/detail") else opening
    monkeypatch.setattr(scraper, "_get_json", fake_get)
    board = {"ats": "bamboohr", "token": "toters", "company": "Toters", "default_location": "Beirut, Lebanon"}

    jobs = await scraper._fetch_bamboohr(board, "mena", "Beirut, Lebanon")
    assert len(jobs) == len(listing["result"]) - 1     # the Filled one is skipped
    assert all(mena.is_mena(j["location"]) for j in jobs)
    # India run: Lebanon roles are out of region.
    assert await scraper._fetch_bamboohr(board, "india", "India") == []


@pytest.mark.parametrize("as_str", [False, True])
def test_teamtailor_normalization_accepts_dict_and_str_jobposting(as_str):
    item = json.loads(json.dumps(_load("teamtailor_chalhoub_feed.json")["items"][0]))
    if as_str:
        item["_jobposting"] = json.dumps(item["_jobposting"])
    job = ATSAggregatorScraper._norm_teamtailor(item, "Chalhoub Group", "Dubai, United Arab Emirates")
    _assert_common(job, company="Chalhoub Group")
    assert job["source_url"] == item["url"]
    assert job["posted_at"] is not None


def test_teamtailor_falls_back_without_jobposting():
    item = {"title": "Barista", "url": "https://c.test/jobs/1", "content_html": "<p>Serve coffee</p>",
            "date_published": "2026-10-16T16:13:23+04:00", "_jobposting": "not json"}
    job = ATSAggregatorScraper._norm_teamtailor(item, "Acme", "Dubai, United Arab Emirates")
    assert job["location"] == "Dubai, United Arab Emirates"
    assert job["jd_text"] == "Serve coffee"
    assert job["posted_at"] == datetime(2026, 10, 16, 16, 13, 23)


@pytest.mark.asyncio
async def test_teamtailor_fetch_follows_next_url_with_a_page_cap(scraper, monkeypatch):
    feed = _load("teamtailor_chalhoub_feed.json")
    urls = []

    async def fake_get(url, params=None, headers=None):
        urls.append(url)
        return {**feed, "next_url": "https://careers.chalhoubgroup.com/jobs.json?page=2"}   # never ends
    monkeypatch.setattr(scraper, "_get_json", fake_get)
    board = {"ats": "teamtailor", "token": "careers.chalhoubgroup.com", "company": "Chalhoub Group"}

    jobs = await scraper._fetch_teamtailor(board, "Dubai, United Arab Emirates")
    assert urls[0] == "https://careers.chalhoubgroup.com/jobs.json"
    assert len(urls) == ats_mod._TT_MAX_PAGES
    assert len(jobs) == len(feed["items"]) * ats_mod._TT_MAX_PAGES


def test_mena_seed_boards_are_well_formed():
    from scrapers.ats import MENA_SEED_BOARDS
    vendors = {"greenhouse", "lever", "ashby", "workable", "smartrecruiters", "recruitee",
               "oracle_hcm", "workday", "bamboohr", "teamtailor",
               "taleo", "phenom", "avature"}   # Phase 3 vendors (PHASE_3_BUILD.md B3-B5)
    seen = set()
    for b in MENA_SEED_BOARDS:
        assert b["ats"] in vendors and b["token"] and b["company"]
        assert "mena" in b["regions"]
        if b["ats"] == "oracle_hcm":
            assert b["host"] and b["site"]
        if b["ats"] == "workday":
            assert b["host"] and b["tenant"] and b["site"]
        if b["ats"] == "taleo":
            assert b["host"] and b["site"] and b["portal"]
        if b["ats"] in ("phenom", "avature"):
            assert b["host"] and b["site"]
        if "default_location" in b:
            assert mena.is_mena(b["default_location"]), b
        key = (b["ats"], b["token"])
        assert key not in seen
        seen.add(key)
