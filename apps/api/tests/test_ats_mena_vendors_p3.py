"""Offline tests for the Phase 3 ATS work (docs/mena/PHASE_3_BUILD.md): the new
seed boards (B2) and the Taleo (B3), Phenom (B4) and Avature (B5) vendors, plus
the harvester token round-trip and the Sabbar Arabic-slug support (B6).

Fixtures are real responses captured 2026-10-17, trimmed (Taleo: the
`initialHistory` input only; Phenom: the `phApp.ddo` script / the head and
ld+json; Avature: the article field blocks). The Taleo CSRF token is redacted.
Closing dates in the captured pages are real and will pass, so tests that need
an open job pin the date instead of relying on the clock.
"""
import json
import re
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from scrapers import ats as ats_mod
from scrapers.ats import ATSAggregatorScraper, _parse_ddmmyyyy, _parse_phenom_date
from services import ats_harvester as harvester
from services.geo import mena

FX = Path(__file__).parent / "fixtures"


def _text(name):
    return (FX / name).read_text(encoding="utf-8")


@pytest.fixture
def scraper(monkeypatch):
    s = ATSAggregatorScraper()

    async def noop():
        return None
    monkeypatch.setattr(s.rate_limiter, "acquire", noop)
    return s


def _board(ats):
    return next(b for b in ats_mod.MENA_SEED_BOARDS if b["ats"] == ats and b["ats"] in ("taleo", "phenom", "avature"))


# ═════════════════════════ B2: seeds ═════════════════════════

NEW_SEEDS = {
    ("teamtailor", "propertyfinder.teamtailor.com"), ("teamtailor", "dubizzle.teamtailor.com"),
    ("teamtailor", "rasan.teamtailor.com"), ("teamtailor", "qashio.teamtailor.com"),
    ("recruitee", "unifonic"),
    ("workable", "agility"), ("workable", "tamatem"), ("workable", "ananinja"), ("workable", "lucidya"),
    ("smartrecruiters", "almosafer"), ("smartrecruiters", "seera"),
    ("smartrecruiters", "brimore"), ("smartrecruiters", "homzmart"),
    ("bamboohr", "nymcard"), ("bamboohr", "bosta"),
}
REJECTED_LOOKALIKES = {
    ("teamtailor", "stc.teamtailor.com"), ("personio", "nbk"),
    ("smartrecruiters", "noonacademy"), ("breezy", "dubizzlelabs"),
}


def test_phase3_seed_boards_present_and_look_alikes_absent():
    have = {(b["ats"], b["token"]) for b in ats_mod.MENA_SEED_BOARDS}
    assert NEW_SEEDS <= have
    assert not (REJECTED_LOOKALIKES & have)


def test_phase3_seeds_serve_mena_only_and_new_vendors_are_not_in_india_runs():
    for b in ats_mod.MENA_SEED_BOARDS:
        if (b["ats"], b["token"]) in NEW_SEEDS:
            assert b["regions"] == ("mena",)
    for region in ("india",):
        vendors = {b["ats"] for b in ATSAggregatorScraper._boards(region)}
        assert not vendors & {"taleo", "phenom", "avature"}
    mena_vendors = {b["ats"] for b in ATSAggregatorScraper._boards("mena")}
    assert {"taleo", "phenom", "avature"} <= mena_vendors


def test_unifonic_amman_row_passes_mena_and_remote_job_does_not():
    assert ATSAggregatorScraper._is_mena({"location": "Amman, Al ‘A̅şimah, Jordan"})
    assert not ATSAggregatorScraper._is_mena({"location": "Remote job"})


def test_smartrecruiters_egypt_postings_resolve_without_the_trailing_code_fix():
    assert "eg" in ats_mod._SR_COUNTRIES["mena"]
    item = {"location": {"city": "Al Abageyah", "country": "eg"}}
    assert ATSAggregatorScraper._sr_location(item) == "Al Abageyah, Egypt"
    # ...and the raw feed form "Al Abageyah, EG" now resolves too (B1).
    assert ATSAggregatorScraper._is_mena({"location": "Al Abageyah, EG"})


# ═════════════════════════ B3: Taleo ═════════════════════════

SEARCH = json.loads(_text("taleo_dubaicareers_search.json"))
DETAIL_HTML = _text("taleo_dubaicareers_detail.html")
FAR_FUTURE = "01/01/2099"


def _req(contest):
    return next(r for r in SEARCH["requisitionList"] if r["contestNo"] == contest)


def _fields(closing=FAR_FUTURE):
    fields = ATSAggregatorScraper._taleo_decode_fields(DETAIL_HTML)
    i = fields.index("26001069")
    fields[i + 30] = closing
    return fields


def test_taleo_search_fixture_contract():
    assert SEARCH["pagingData"]["pageSize"] == 25 and SEARCH["pagingData"]["totalCount"] > 0
    for r in SEARCH["requisitionList"]:
        assert r["contestNo"] and len(r["column"]) == 3
    assert {r["column"][2] for r in SEARCH["requisitionList"]} >= {"UAE Only", "All Nationalities (Priority for UAE National)"}


def test_taleo_dd_mm_yyyy_dates():
    assert _parse_ddmmyyyy("16/10/2026") == datetime(2026, 10, 16)
    assert _parse_ddmmyyyy("13/10/2026").month == 10          # not read as MM/DD
    assert _parse_ddmmyyyy("12/11/2026") == datetime(2026, 11, 12)
    assert _parse_ddmmyyyy("") is None and _parse_ddmmyyyy("2026-10-16") is None


def test_taleo_decode_and_offset_mapping():
    fields = _fields()
    job = ATSAggregatorScraper._norm_taleo(
        _req("26001069"), fields, "Dubai Government",
        "https://jobs.dubaicareers.ae/careersection/dubaicareers/jobdetail.ftl?job=26001069&lang=en",
        "Dubai, United Arab Emirates")
    assert job["title"] == "Senior Engineer - Rail Network Permits and Services"
    assert job["company"] == "Roads and Transport Authority"          # organization, not the board name
    assert job["location"] == "Dubai, United Arab Emirates"
    assert job["posted_at"] == datetime(2026, 10, 13)
    assert job["source_job_id"] == "26001069"
    assert job["source_url"] == job["apply_url"]
    assert job["source_url"].endswith("jobdetail.ftl?job=26001069&lang=en")
    jd = job["jd_text"]
    assert "No Objection Certificate" in jd                           # description
    assert "Civil Engineering" in jd                                  # qualifications
    assert "<" not in jd and "\\:" not in jd and "%" not in jd


def test_taleo_html_fields_are_decoded_once():
    fields = ATSAggregatorScraper._taleo_decode_fields(DETAIL_HTML)
    assert fields[fields.index("26001069") - 1] == "Senior Engineer - Rail Network Permits and Services"
    assert all("!*!" not in f and "!|!" not in f for f in fields)
    assert ATSAggregatorScraper._taleo_decode_fields("<html></html>") is None


def test_taleo_offset_sanity_falls_back_to_title_and_longest_text(caplog):
    fields = _fields()
    i = fields.index("26001069")
    fields[i + 28] = "not a date"          # layout shifted
    job = ATSAggregatorScraper._norm_taleo(_req("26001069"), fields, "Dubai Government", "https://x/y", "Dubai, United Arab Emirates")
    assert job["title"] == "Senior Engineer - Rail Network Permits and Services"
    assert job["company"] == "Dubai Government"                       # org slot not trusted
    assert len(job["jd_text"]) > 200 and "No Objection Certificate" in job["jd_text"]
    assert job["posted_at"] == datetime(2026, 10, 13)                  # from the list column


def test_taleo_offset_fallback_without_the_contest_number():
    job = ATSAggregatorScraper._norm_taleo(_req("26001069"), ["a", "b" * 300], "Dubai Government", "https://x/y", "Dubai, United Arab Emirates")
    assert job["title"] == "Senior Engineer - Rail Network Permits and Services"   # list title
    assert job["jd_text"] == "b" * 300


def test_taleo_closed_jobs_are_skipped():
    assert ATSAggregatorScraper._norm_taleo(_req("26001069"), _fields("01/01/2020"), "Dubai Government", "u", "Dubai") is None


def test_taleo_nationality_recheck_after_detail():
    fields = _fields()
    i = fields.index("26001069")
    fields[i + 20] = "UAE Only"
    args = (_req("26001069"), fields, "Dubai Government", "u", "Dubai, United Arab Emirates")
    assert ATSAggregatorScraper._norm_taleo(*args) is None
    assert ATSAggregatorScraper._norm_taleo(*args, drop_nationals=False) is not None
    # "(Priority for UAE National)" is a preference, not a restriction
    assert ATSAggregatorScraper._norm_taleo(_req("26001069"), _fields(), "Dubai Government", "u", "Dubai") is not None


def test_taleo_jd_has_contact_details_scrubbed():
    fields = _fields()
    i = fields.index("26001069")
    fields[i + 2] += " Send your CV to hr.person@dubaiholding.example or call +971 4 123 4567."
    job = ATSAggregatorScraper._norm_taleo(_req("26001069"), fields, "Dubai Government", "u", "Dubai, United Arab Emirates")
    assert "@" not in job["jd_text"] and "+971" not in job["jd_text"]


async def _run_taleo(scraper, monkeypatch, *, region="mena", nationals_flag=True):
    from config import settings
    monkeypatch.setattr(settings, "MENA_EXCLUDE_NATIONALS_ONLY", nationals_flag)
    posts, gets = [], []

    async def post(url, body, headers=None):
        posts.append((url, body, headers))
        return SEARCH if body["pageNo"] == 1 else {"requisitionList": [], "pagingData": SEARCH["pagingData"]}

    async def get(url, params=None, headers=None):
        gets.append((url, headers))
        return DETAIL_HTML

    monkeypatch.setattr(scraper, "_post_json", post)
    monkeypatch.setattr(scraper, "_get_text", get)
    jobs = await scraper._fetch_taleo(_board("taleo"), region, "Dubai, United Arab Emirates")
    return jobs, posts, gets


@pytest.mark.asyncio
async def test_taleo_prefilters_uae_only_rows_before_any_detail_call(scraper, monkeypatch):
    # Pin "now" so the fixture's real closing date is open whenever this runs.
    monkeypatch.setattr(ats_mod, "datetime", type("D", (datetime,), {"utcnow": staticmethod(lambda: datetime(2026, 10, 17))}))
    jobs, posts, gets = await _run_taleo(scraper, monkeypatch)
    detail_ids = sorted(re.search(r"job=(\d+)", u).group(1) for u, _ in gets)
    assert detail_ids == ["26001069", "26003247"]                    # the "UAE Only" row 26003340 never fetched
    assert all(h["Accept-Encoding"] == "identity" for _, h in gets)
    url, body, headers = posts[0]
    assert "portal=40505100456" in url and "/careersection/rest/jobboard/searchjobs" in url
    assert body["fieldData"]["fields"]["KEYWORD"] == "" and body["pageNo"] == 1
    assert body["sortingSelection"]["sortBySelectionParam"] == "3"
    assert headers["Accept-Encoding"] == "identity" and headers["tz"] == "GMT+04:00"
    # The mock serves one captured page for both ids: the matching one maps fully,
    # the other trips the layout check and degrades to the board name.
    assert sorted(j["company"] for j in jobs) == ["Dubai Government", "Roads and Transport Authority"]


@pytest.mark.asyncio
async def test_taleo_keeps_uae_only_rows_when_the_flag_is_off(scraper, monkeypatch):
    monkeypatch.setattr(ats_mod, "datetime", type("D", (datetime,), {"utcnow": staticmethod(lambda: datetime(2026, 10, 17))}))
    _jobs, _posts, gets = await _run_taleo(scraper, monkeypatch, nationals_flag=False)
    assert len(gets) == 3


@pytest.mark.asyncio
async def test_taleo_pages_are_capped_and_detail_is_capped(scraper, monkeypatch):
    calls = []

    async def post(url, body, headers=None):
        calls.append(body["pageNo"])
        rows = [{"contestNo": f"{body['pageNo']}{n:03d}", "jobId": "1", "column": [f"Engineer {n}", "01/10/2026", "All Nationalities"]}
                for n in range(25)]
        return {"requisitionList": rows, "pagingData": {"totalCount": 382}}

    monkeypatch.setattr(scraper, "_post_json", post)
    gets = []

    async def counting_get(url, params=None, headers=None):
        gets.append(url)
        return ""

    monkeypatch.setattr(scraper, "_get_text", counting_get)
    await scraper._fetch_taleo(_board("taleo"), "mena", "Dubai, United Arab Emirates")
    assert calls == list(range(1, ats_mod._TALEO_MAX_PAGES + 1))
    assert len(gets) == ats_mod._TALEO_DETAIL_CAP


@pytest.mark.asyncio
async def test_taleo_not_loaded_for_a_non_mena_default_location(scraper, monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("no request expected")
    monkeypatch.setattr(scraper, "_post_json", boom)
    assert await scraper._fetch_taleo(_board("taleo"), "india", "Dubai, United Arab Emirates") == []


# ═════════════════════════ B4: Phenom ═════════════════════════

PH_SEARCH = _text("phenom_g42_search.html")
PH_DETAIL = _text("phenom_g42_detail.html")


def test_phenom_ddo_parse():
    data = ATSAggregatorScraper._phenom_search_data(PH_SEARCH)
    assert data["totalHits"] == 49
    jobs = data["data"]["jobs"]
    assert [j["jobId"] for j in jobs] == ["3429", "3422", "3414"]
    for j in jobs:
        for k in ("jobId", "title", "postedDate", "cityStateCountry", "country"):
            assert k in j
    assert ATSAggregatorScraper._phenom_search_data("<html>no ddo</html>") is None
    assert ATSAggregatorScraper._phenom_search_data("phApp.ddo = {not json}; phApp.x = 1;") is None


def test_phenom_location_strips_the_leading_comma_of_unknown_cities():
    assert ATSAggregatorScraper._phenom_location({"cityStateCountry": " , United States"}) == "United States"
    assert ATSAggregatorScraper._phenom_location({"cityStateCountry": "MBZ City, Abu Dhabi, United Arab Emirates"}) \
        == "MBZ City, Abu Dhabi, United Arab Emirates"


def test_phenom_posted_date_with_colonless_offset():
    assert _parse_phenom_date("2026-04-28T07:20:13.000+0000") == datetime(2026, 4, 28, 7, 20, 13)
    assert _parse_phenom_date(None) is None


def test_phenom_jsonld_detail_mapping():
    from scrapers.jsonld import find_job_posting, map_job_posting
    listed = next(j for j in ATSAggregatorScraper._phenom_search_data(PH_SEARCH)["data"]["jobs"] if j["jobId"] == "3414")
    fields = map_job_posting(find_job_posting(PH_DETAIL))
    job = ATSAggregatorScraper._norm_phenom(listed, fields, "G42", "https://careers.g42.ai/global/en/job/3414",
                                           "Abu Dhabi, United Arab Emirates")
    assert job["title"] == "Manager - Cyber Consulting Services (CPX)"
    assert job["company"] == "CPX Holding L.L.C O.P.C"                # the brand entity, raw
    assert job["location"] == "MBZ City, Abu Dhabi, United Arab Emirates"
    assert job["posted_at"] == datetime(2026, 10, 15)                  # JSON-LD, not the list's postedDate
    assert job["source_url"] == job["apply_url"] == "https://careers.g42.ai/global/en/job/3414"
    assert len(job["jd_text"]) > 500
    assert "<" not in job["jd_text"] and "&lt;" not in job["jd_text"]  # double-escaped HTML fully stripped
    assert "Overview" in job["jd_text"]


def test_phenom_without_jsonld_falls_back_to_the_list_row():
    listed = ATSAggregatorScraper._phenom_search_data(PH_SEARCH)["data"]["jobs"][1]
    job = ATSAggregatorScraper._norm_phenom(listed, {}, "G42", "https://careers.g42.ai/global/en/job/3422",
                                           "Abu Dhabi, United Arab Emirates")
    assert job["company"] == "G42" and job["title"] == "Senior Applied Scientist"
    assert job["posted_at"] == datetime(2026, 10, 5, 9, 23, 58)
    assert job["jd_text"] == listed["descriptionTeaser"]


async def _run_phenom(scraper, monkeypatch, region):
    urls = []

    async def get(url, params=None, headers=None):
        urls.append(url)
        if "/search-results" in url:
            return PH_SEARCH if "from=0" in url else ""
        return PH_DETAIL

    monkeypatch.setattr(scraper, "_get_text", get)
    jobs = await scraper._fetch_phenom(_board("phenom"), region, "Abu Dhabi, United Arab Emirates")
    return jobs, urls


@pytest.mark.asyncio
async def test_phenom_us_job_is_filtered_on_mena_and_only_allowed_paths_are_used(scraper, monkeypatch):
    jobs, urls = await _run_phenom(scraper, monkeypatch, "mena")
    detail = [u for u in urls if "/job/" in u]
    assert sorted(u.rsplit("/", 1)[1] for u in detail) == ["3414", "3422"]    # 3429 (United States) never fetched
    for u in urls:
        assert u.startswith("https://careers.g42.ai/global/en/")
        assert "/search-results?from=" in u or "/job/" in u                    # robots: nothing else
    assert len(jobs) == 2


@pytest.mark.asyncio
async def test_phenom_global_run_keeps_the_us_job(scraper, monkeypatch):
    jobs, urls = await _run_phenom(scraper, monkeypatch, "global")
    assert sorted(u.rsplit("/", 1)[1] for u in urls if "/job/" in u) == ["3414", "3422", "3429"]
    assert any(j["location"] == "United States" for j in jobs)


@pytest.mark.asyncio
async def test_phenom_site_change_logs_once_and_returns_nothing(scraper, monkeypatch):
    async def get(url, params=None, headers=None):
        return "<html>redesigned</html>"
    monkeypatch.setattr(scraper, "_get_text", get)
    assert await scraper._fetch_phenom(_board("phenom"), "mena", "Abu Dhabi, United Arab Emirates") == []


@pytest.mark.asyncio
async def test_phenom_paging_stops_at_the_job_cap(scraper, monkeypatch):
    seen = []
    job = lambda n: {"jobId": str(n), "title": "Engineer", "cityStateCountry": "Dubai, United Arab Emirates"}  # noqa: E731

    async def get(url, params=None, headers=None):
        if "/search-results" in url:
            frm = int(re.search(r"from=(\d+)", url).group(1))
            seen.append(frm)
            ddo = {"eagerLoadRefineSearch": {"totalHits": 500, "data": {"jobs": [job(frm + n) for n in range(10)]}}}
            return f"<script>phApp.ddo = {json.dumps(ddo)}; phApp.x = 1;</script>"
        return ""

    monkeypatch.setattr(scraper, "_get_text", get)
    jobs = await scraper._fetch_phenom(_board("phenom"), "mena", "Abu Dhabi, United Arab Emirates")
    assert seen == list(range(0, ats_mod._PHENOM_MAX_JOBS, 10))
    assert len(jobs) == ats_mod._PHENOM_DETAIL_CAP


# ═════════════════════════ B5: Avature ═════════════════════════

AV_SITEMAP = _text("avature_qr_sitemap.xml")
AV_DETAIL = _text("avature_qr_detail.html")
AV_OPEN = AV_DETAIL.replace("2026-10-16", "2099-01-01")      # the captured posting has since closed


def test_avature_sitemap_keeps_only_job_urls_with_ids():
    entries = ATSAggregatorScraper._avature_entries(AV_SITEMAP, "careers.qatarairways.com", "global")
    assert [e[2] for e in entries] == [65952, 67414, 66457, 1259]      # bare /JobDetail skipped
    assert entries[0][1] == "Senior-Data-Science-Analyst"
    xml = ("<urlset><url><loc>https://careers.qatarairways.com/global/JobDetail/A-B/1</loc><lastmod>2026-01-02</lastmod></url>"
           "<url><loc>https://evil.example/global/JobDetail/A-B/2</loc></url>"
           "<url><loc>https://careers.qatarairways.com/global/JobDetailApplied</loc></url></urlset>")
    assert ATSAggregatorScraper._avature_entries(xml, "careers.qatarairways.com", "global") == [
        ("https://careers.qatarairways.com/global/JobDetail/A-B/1", "A-B", 1, "2026-01-02")]


@pytest.mark.parametrize("slug,foreign", [
    ("Software-Test-Engineer-Manual-Automation-Selenium-Playwright-Appium-Ahmedabad-India", True),
    ("Duty-Engineer-JFK", True),
    ("Account-Manager-Sales-Kuala-Lumpur-Malaysia", True),
    ("Senior-Data-Science-Analyst", False),            # no recognisable place: kept
    ("Cargo-Sales-Doha-Qatar", False),
    ("Airline-Customer-Contact-Centre-Agent-Cairo-Egypt", False),
])
def test_avature_slug_place_filter(slug, foreign):
    assert ATSAggregatorScraper._avature_slug_foreign(slug) is foreign


def test_avature_label_value_extraction():
    parsed = ATSAggregatorScraper._avature_parse(AV_DETAIL)
    assert parsed["labels"] == {"Ref #": "235339", "Location": "Qatar-Doha", "Job family": "Pilots & Flight Operations"}
    assert parsed["closing"] == datetime(2026, 10, 16)
    body = parsed["body"]
    assert "About the role" in body and "About you" in body
    assert "taleo.net" not in body and "<" not in body                  # bare apply URL and tags dropped


def test_avature_label_value_fallback_regex_when_field_wrappers_change():
    page = ('<div class="article__content__view__field__label">Ref #</div><div class="article__content__view__field__value">9</div>'
            '<div class="article__content__view__field__label">Location</div><div class="article__content__view__field__value">Qatar-Doha</div>'
            '<div class="article__content__view__field__value"><p>Body text</p></div>')
    parsed = ATSAggregatorScraper._avature_parse(page)
    assert parsed["labels"] == {"Ref #": "9", "Location": "Qatar-Doha"} and parsed["body"] == "Body text"


def test_avature_country_city_location_flip_and_mapping():
    url = "https://careers.qatarairways.com/global/JobDetail/Senior-Data-Science-Analyst/65952"
    job = ATSAggregatorScraper._norm_avature(AV_OPEN, url, "Senior-Data-Science-Analyst", "", "Qatar Airways", "Doha, Qatar")
    assert job["title"] == "Senior Data Science Analyst"               # from the page heading
    assert job["location"] == "Doha, Qatar"                            # "Qatar-Doha" flipped
    assert job["source_job_id"] == "235339"
    assert job["source_url"] == job["apply_url"] == url
    assert job["posted_at"] == datetime(2026, 8, 5)                    # page ld+json beats the sitemap lastmod
    assert "About the role" in job["jd_text"]
    foreign = AV_OPEN.replace("Qatar-Doha", "India-Ahmedabad")
    other = ATSAggregatorScraper._norm_avature(foreign, url, "x-y", "", "Qatar Airways", "Doha, Qatar")
    assert other["location"] == "Ahmedabad, India"
    assert ATSAggregatorScraper._in_region(other["location"], "mena") is False
    assert ATSAggregatorScraper._in_region(other["location"], "global") is True


def test_avature_closed_posting_is_skipped_and_slug_and_lastmod_are_fallbacks():
    url = "https://careers.qatarairways.com/global/JobDetail/Senior-Data-Science-Analyst/65952"
    assert ATSAggregatorScraper._norm_avature(AV_DETAIL, url, "Senior-Data-Science-Analyst", "", "QA", "Doha, Qatar") is None
    bare = ('<html><meta property="og:description" content="Fly with us &amp;amp; grow" />'
            '<div class="article__content__view__field__label">Location</div>'
            '<div class="article__content__view__field__value">Qatar-Doha</div></html>')
    job = ATSAggregatorScraper._norm_avature(bare, url, "Cabin-Crew", "2026-09-29", "Qatar Airways", "Doha, Qatar")
    assert job["title"] == "Cabin Crew"                                # slug fallback
    assert job["jd_text"] == "Fly with us & grow"                      # og:description fallback
    assert job["posted_at"] == datetime(2026, 9, 29)                   # sitemap lastmod fallback


def test_avature_jd_contact_details_scrubbed():
    page = AV_OPEN.replace("About the role:", "About the role: mail recruiter@qa.example or +974 4000 0000 ", 1)
    job = ATSAggregatorScraper._norm_avature(page, "u", "s", "", "QA", "Doha, Qatar")
    assert "@" not in job["jd_text"] and "+974" not in job["jd_text"]


@pytest.mark.asyncio
async def test_avature_fetch_reads_only_the_declared_sitemap_and_filters(scraper, monkeypatch):
    urls = []
    index = ('<sitemapindex><sitemap><loc>https://careers.qatarairways.com/global/sitemap.xml</loc></sitemap>'
             '<sitemap><loc>https://elsewhere.example/sitemap.xml</loc></sitemap></sitemapindex>')

    async def get(url, params=None, headers=None):
        urls.append(url)
        if url.endswith("sitemap_index.xml"):
            return index
        if url.endswith("/global/sitemap.xml"):
            return AV_SITEMAP
        return AV_OPEN

    monkeypatch.setattr(scraper, "_get_text", get)
    jobs = await scraper._fetch_avature(_board("avature"), "mena", "Doha, Qatar")
    assert urls[0] == "https://careers.qatarairways.com/global/sitemap_index.xml"
    assert not any("elsewhere.example" in u or "qtvc=" in u or "careersmarketplace" in u for u in urls)
    fetched = sorted(u.rsplit("/", 1)[1] for u in urls if "/JobDetail/" in u)
    assert fetched == ["65952", "67414"]            # India slug and "Qatari Nationals Only" never fetched
    assert len(jobs) == 2 and all(j["location"] == "Doha, Qatar" for j in jobs)


@pytest.mark.asyncio
async def test_avature_global_run_keeps_the_india_slug_but_judges_it_by_the_detail_page(scraper, monkeypatch):
    async def get(url, params=None, headers=None):
        if url.endswith("sitemap_index.xml"):
            return AV_SITEMAP
        return AV_OPEN.replace("Qatar-Doha", "India-Ahmedabad") if "66457" in url else AV_OPEN

    monkeypatch.setattr(scraper, "_get_text", get)
    jobs = await scraper._fetch_avature(_board("avature"), "global", "Doha, Qatar")
    assert "Ahmedabad, India" in {j["location"] for j in jobs}


@pytest.mark.asyncio
async def test_avature_without_a_sitemap_yields_nothing(scraper, monkeypatch):
    async def get(url, params=None, headers=None):
        return None
    monkeypatch.setattr(scraper, "_get_text", get)
    assert await scraper._fetch_avature(_board("avature"), "mena", "Doha, Qatar") == []


@pytest.mark.asyncio
async def test_avature_detail_cap(scraper, monkeypatch):
    xml = "<urlset>" + "".join(
        f"<url><loc>https://careers.qatarairways.com/global/JobDetail/Software-Engineer-{n}/{n}</loc></url>" for n in range(1, 40)
    ) + "</urlset>"
    got = []

    async def get(url, params=None, headers=None):
        if url.endswith("sitemap_index.xml"):
            return xml
        got.append(url)
        return AV_OPEN

    monkeypatch.setattr(scraper, "_get_text", get)
    await scraper._fetch_avature(_board("avature"), "mena", "Doha, Qatar")
    assert len(got) == ats_mod._AVATURE_DETAIL_CAP


# ═════════════════════════ Harvester ═════════════════════════

@pytest.mark.parametrize("ats,token,fields", [
    ("taleo", "jobs.dubaicareers.ae|dubaicareers|40505100456",
     {"host": "jobs.dubaicareers.ae", "site": "dubaicareers", "portal": "40505100456"}),
    ("phenom", "careers.g42.ai|global/en", {"host": "careers.g42.ai", "site": "global/en"}),
    ("avature", "careers.qatarairways.com|global", {"host": "careers.qatarairways.com", "site": "global"}),
])
def test_split_token_and_board_from_pair_round_trip(ats, token, fields):
    assert harvester.split_token(ats, token) == fields
    assert harvester.board_from_pair(ats, token) == {"ats": ats, "token": token, **fields}
    assert ATSAggregatorScraper._board_parts({"ats": ats, "token": token}) == fields


@pytest.mark.parametrize("ats,token", [
    ("taleo", "jobs.dubaicareers.ae|dubaicareers"), ("taleo", "a||c"), ("taleo", "plain"),
    ("phenom", "careers.g42.ai"), ("phenom", "a|b|c"), ("avature", "|global"),
])
def test_malformed_composite_tokens_split_to_nothing(ats, token):
    assert harvester.split_token(ats, token) == {}


def test_seed_boards_match_their_composite_tokens():
    for b in ats_mod.MENA_SEED_BOARDS:
        if b["ats"] in ("taleo", "phenom", "avature"):
            parts = harvester.split_token(b["ats"], b["token"])
            assert all(b[k] == v for k, v in parts.items()), b


def test_taleo_phenom_avature_have_no_url_harvest_pattern():
    for url in ("https://jobs.dubaicareers.ae/careersection/dubaicareers/jobdetail.ftl?job=26001069&lang=en",
                "https://careers.g42.ai/global/en/job/3414",
                "https://careers.qatarairways.com/global/JobDetail/Senior-Data-Science-Analyst/65952"):
        assert harvester.extract_tokens(url) == set()


def _validate(handler, ats, token):
    import asyncio

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as c:
            return await harvester._validate(c, ats, token)
    return asyncio.run(go())


def test_validate_taleo_needs_a_positive_total_count():
    def ok(req):
        assert "portal=40505100456" in str(req.url) and req.headers["accept-encoding"] == "identity"
        return httpx.Response(200, json={"pagingData": {"totalCount": 382}})
    assert _validate(ok, "taleo", "jobs.dubaicareers.ae|dubaicareers|40505100456")["jobs"] == 382
    zero = lambda req: httpx.Response(200, json={"pagingData": {"totalCount": 0}})  # noqa: E731
    assert _validate(zero, "taleo", "jobs.dubaicareers.ae|dubaicareers|40505100456") is None
    assert _validate(lambda r: httpx.Response(404), "taleo", "jobs.dubaicareers.ae|dubaicareers|40505100456") is None


def test_validate_phenom_needs_a_parsable_ddo_with_hits():
    good = lambda req: httpx.Response(200, text=PH_SEARCH)  # noqa: E731
    assert _validate(good, "phenom", "careers.g42.ai|global/en")["jobs"] == 49
    assert _validate(lambda r: httpx.Response(200, text="<html></html>"), "phenom", "careers.g42.ai|global/en") is None


def test_validate_avature_follows_the_declared_sitemap_only():
    def handler(req):
        url = str(req.url)
        if url.endswith("sitemap_index.xml"):
            return httpx.Response(200, text="<sitemapindex><sitemap><loc>https://careers.qatarairways.com/global/sitemap.xml</loc></sitemap></sitemapindex>")
        if url.endswith("/global/sitemap.xml"):
            return httpx.Response(200, text=AV_SITEMAP)
        return httpx.Response(404)
    assert _validate(handler, "avature", "careers.qatarairways.com|global")["jobs"] == 4
    # a portal with no sitemap (Emirates) is invalid: its job list is robots-disallowed
    assert _validate(lambda r: httpx.Response(404), "avature", "www.emiratesgroupcareers.com|careersmarketplace") is None
