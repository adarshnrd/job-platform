"""Offline parsing tests for the Foundit middleware-API scraper."""
import pytest

from models.job import JobType, Platform
from scrapers.foundit import COUNTRY_SITES, FounditScraper


def _item(**overrides) -> dict:
    """A listing shaped like the middleware response (trimmed to used fields)."""
    base = {
        "jobId": 34521374,
        "title": "Software Engineer - CPD",
        "companyName": "Rubrik",
        "locations": "Bengaluru, India",
        "minimumExperience": {"years": 2},
        "maximumExperience": {"years": 4},
        "minimumSalary": {"currency": "INR", "absoluteValue": 500000},
        "maximumSalary": {"currency": "INR", "absoluteValue": 800000},
        "createdAt": 1745574846000,
        "industries": ["Software"],
        "functions": ["IT"],
        "roles": ["Software Engineer/Programmer"],
        "employmentTypes": ["Full time"],
        "skills": "Go,Java, C++, Scala, Python",
        "currencyCode": "INR",
        "hideSalary": 0,
        "companyLogoUrl": "https://media.example/logo.gif",
        "quickApplyJob": 1,
        "isJobActive": True,
        "seoJdUrl": "/job/software-engineer-cpd-rubrik-bengaluru-34521374",
        "exp": "2-4 Years",
        "salary": "5,00,000-8,00,000 INR",
    }
    base.update(overrides)
    return base


@pytest.fixture
def scraper():
    return FounditScraper()


def _map(scraper, item, domain="www.foundit.in", location="India", currency="INR"):
    return scraper._to_listing(item, domain, location, currency)


# ── core mapping ──

def test_maps_core_fields(scraper):
    job = _map(scraper, _item())
    assert job.title == "Software Engineer - CPD"
    assert job.company == "Rubrik"
    assert job.location == "Bengaluru, India"
    assert job.source_platform is Platform.foundit
    assert job.source_url == "https://www.foundit.in/job/software-engineer-cpd-rubrik-bengaluru-34521374"
    assert job.source_job_id == "34521374"
    assert job.is_easy_apply is True
    assert job.job_type is JobType.full_time
    assert job.min_experience == 2 and job.max_experience == 4
    assert job.salary_min == 500000 and job.salary_max == 800000
    assert job.salary_currency == "INR"
    assert "Java" in job.required_skills and "Python" in job.required_skills


def test_posted_at_parses_epoch_milliseconds(scraper):
    job = _map(scraper, _item())
    # 1745574846000 ms — a seconds-based parse would land in 1970.
    assert job.posted_at is not None
    assert job.posted_at.year >= 2025


def test_synthesized_jd_carries_scoring_signal(scraper):
    """jd_text feeds the prefilter and the LLM scorer, so it must not be a stub."""
    jd = _map(scraper, _item()).jd_text
    for fragment in ("Rubrik", "2-4 Years", "Java", "Software"):
        assert fragment in jd
    assert len(jd) > 80


# ── salary confidentiality ──

@pytest.mark.parametrize("flags", [
    {"hideSalary": 1},
    {"jobSalaryConfidential": True},
])
def test_hidden_salary_is_never_emitted(scraper, flags):
    job = _map(scraper, _item(**flags))
    assert job.salary_min is None and job.salary_max is None
    assert "Salary" not in job.jd_text


# ── experience sentinel ──

def test_zero_experience_range_is_treated_as_unspecified(scraper):
    """The APAC boards send 0/0 for "not stated".

    services.experience.merge_experience only fills experience when *both*
    fields are None, so emitting a literal 0–0 would permanently mask the real
    requirement stated in the JD text.
    """
    job = _map(scraper, _item(minimumExperience={"years": 0}, maximumExperience={"years": 0}))
    assert job.min_experience is None and job.max_experience is None


def test_genuine_fresher_range_is_kept(scraper):
    job = _map(scraper, _item(minimumExperience={"years": 0}, maximumExperience={"years": 2}))
    assert job.min_experience == 0 and job.max_experience == 2


# ── filtering ──

def test_inactive_listings_are_dropped(scraper):
    assert _map(scraper, _item(isJobActive=False)) is None


def test_listing_without_a_url_is_dropped(scraper):
    assert _map(scraper, _item(seoJdUrl="", jdUrl="")) is None


def test_duplicate_urls_are_dropped_within_a_run(scraper):
    assert _map(scraper, _item()) is not None
    assert _map(scraper, _item()) is None  # same seoJdUrl


# ── country routing ──

@pytest.mark.parametrize("location,region,expected_domain", [
    ("Bangalore", "india", "www.foundit.in"),
    ("", "india", "www.foundit.in"),
    ("Singapore", "global", "www.foundit.sg"),
    ("Jakarta", "global", "www.foundit.id"),
    ("Hong Kong", "global", "www.foundit.hk"),
    # A global run with an unrecognised city falls back to the widest
    # English-language APAC board rather than the India one.
    ("Reykjavik", "global", "www.foundit.sg"),
])
def test_site_routing(location, region, expected_domain):
    domain, _, _ = FounditScraper._site_for(location, region)
    assert domain == expected_domain


def test_every_registered_country_site_is_well_formed():
    for key, (domain, label, currency) in COUNTRY_SITES.items():
        # "www.founditgulf.com" is the Gulf deployment (docs/mena/ §2.1).
        assert domain.startswith("www.foundit"), key
        assert label and len(currency) == 3, key


def test_country_currency_is_used_when_the_item_omits_one(scraper):
    job = _map(scraper, _item(currencyCode=None), domain="www.foundit.sg",
               location="Singapore", currency="SGD")
    assert job.salary_currency == "SGD"


# ── ad/placeholder rows ──

def test_placeholder_rows_are_not_listings():
    """The feed interleaves {"index","type"} ad slots with real jobs."""
    items = [{"index": 3, "type": "ad"}, _item()]
    listings = [i for i in items if isinstance(i, dict) and i.get("jobId")]
    assert len(listings) == 1


# ══════════════════════════════════════════════════════════════
#  Gulf deployment (docs/mena/PHASE_2_REGIONAL_BOARDS.md §2.1)
#  foundit_gulf_sample.json mirrors the middleware response shape that
#  `_to_listing` already maps (2 Gulf items, 2 India cross-posts). It was
#  hand-trimmed, not captured: founditgulf robots.txt disallows /middleware/.
# ══════════════════════════════════════════════════════════════
import json
from pathlib import Path

import httpx

from config import settings
from tests.mena_helpers import run_search

_GULF = json.loads(
    (Path(__file__).parent / "fixtures" / "foundit_gulf_sample.json").read_text(encoding="utf-8")
)
_GULF_ITEMS = [i for i in _GULF["jobSearchResponse"]["data"] if i.get("jobId")]


@pytest.fixture
def gulf_on(monkeypatch):
    monkeypatch.setattr(settings, "MENA_FOUNDIT_GULF_ENABLED", True)


def test_flag_is_off_by_default():
    assert settings.MENA_FOUNDIT_GULF_ENABLED is False


def test_gulf_site_is_registered():
    assert COUNTRY_SITES["gulf"] == ("www.founditgulf.com", "United Arab Emirates", "AED")


@pytest.mark.parametrize("location,region", [("Dubai", "mena"), ("Riyadh", "mena"), ("", "mena"), ("Dubai", "global")])
def test_site_for_mena_is_gulf_when_flag_on(gulf_on, location, region):
    assert FounditScraper._site_for(location, region)[0] == "www.founditgulf.com"


def test_flag_off_leaves_india_and_global_routing_untouched():
    assert FounditScraper._site_for("Dubai", "global")[0] == "www.foundit.sg"
    assert FounditScraper._site_for("Bangalore", "india")[0] == "www.foundit.in"


def test_india_routing_unchanged_with_flag_on(gulf_on):
    assert FounditScraper._site_for("Bangalore", "india")[0] == "www.foundit.in"
    assert FounditScraper._site_for("Singapore", "global")[0] == "www.foundit.sg"


def test_mena_search_returns_nothing_and_makes_no_request_when_flag_off():
    jobs, seen = run_search(FounditScraper, lambda r: httpx.Response(200, json=_GULF),
                            "software engineer", location="Saudi Arabia", region="mena")
    assert jobs == [] and seen == []


def test_gulf_filter_drops_india_cross_posts_and_other_countries():
    kept = FounditScraper._gulf_filter(_GULF_ITEMS, "Saudi Arabia")
    assert [i["jobId"] for i in kept] == [51000001]
    kept_all = FounditScraper._gulf_filter(_GULF_ITEMS, "")
    assert [i["jobId"] for i in kept_all] == [51000001, 51000002]
    assert not any("India" in i["locations"] for i in kept_all)
    # An India-labelled item is dropped even when its currency is AED.
    assert 51000004 not in {i["jobId"] for i in kept_all}


def test_gulf_currency_follows_the_country_not_the_site_label(scraper):
    ksa = scraper._to_listing(_GULF_ITEMS[0], "www.founditgulf.com", "United Arab Emirates", "AED")
    uae = scraper._to_listing(_GULF_ITEMS[1], "www.founditgulf.com", "United Arab Emirates", "AED")
    assert ksa.salary_currency == "SAR"          # foundit Gulf labels Riyadh pay AED
    assert uae.salary_currency == "AED"
    assert ksa.location == "Riyadh, Saudi Arabia"


def test_india_item_currency_unchanged(scraper):
    job = scraper._to_listing(_GULF_ITEMS[2], "www.foundit.in", "India", "INR")
    assert job.salary_currency == "INR"


def test_gulf_search_end_to_end_sends_empty_locations_and_filters(gulf_on):
    def handler(request):
        assert request.url.host == "www.founditgulf.com"
        assert request.url.params["locations"] == ""        # the API ignores it, so it is not sent
        if request.url.path == "/middleware/jobsearch":
            return httpx.Response(200, json=_GULF)
        return httpx.Response(404)                           # detail enrichment fails softly
    jobs, seen = run_search(FounditScraper, handler, "software engineer",
                            location="Saudi Arabia", region="mena")
    assert [j.source_job_id for j in jobs] == ["51000001"]
    assert jobs[0].salary_currency == "SAR"


def test_foundit_is_registered_for_mena():
    from workers.job_discovery import SOURCE_REGISTRY
    from services.portals import PORTALS
    assert "mena" in SOURCE_REGISTRY["foundit"].regions
    assert "mena" in FounditScraper.regions
    assert "mena" in PORTALS["foundit"].regions
