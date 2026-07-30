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
        assert domain.startswith("www.foundit."), key
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
