"""Offline tests for the Emploitic (Algeria) scraper — __NEXT_DATA__ search page."""
import httpx
import pytest

from models.job import JobType, Platform, WorkMode
from scrapers.emploitic import EmploiticScraper
from services.geo import mena
from tests.mena_helpers import fixture, html, run_search

PAGE = fixture("emploitic_search.html")


@pytest.fixture
def parsed():
    result = EmploiticScraper._search_result(PAGE)
    return result, EmploiticScraper._ld_urls(PAGE)


def test_next_data_contract(parsed):
    result, _ = parsed
    assert {"data", "totalPages", "currentPage", "total"} <= set(result)
    item = result["data"][0]
    for key in ("id", "title", "alias", "description", "location", "contractType",
                "experienceYears", "workMode", "isAnonymous", "tags", "company", "publishedAt"):
        assert key in item
    assert item["location"][0]["label"].endswith("Algérie")     # label field is `label`


def test_named_company_job_maps(parsed):
    result, urls = parsed
    job = EmploiticScraper()._to_listing(result["data"][0], urls)
    assert job.title == "Développeur Solutions Digitales"
    assert job.company == "Propharmal SPA"
    assert job.source_platform is Platform.emploitic
    assert job.source_url == (
        "https://emploitic.com/entreprises/propharmal-spa/offres-d-emploi/industries/developpeur-solutions-digitales-2j4mf"
    )
    assert job.apply_url == job.source_url
    assert job.salary_currency == "DZD"
    assert job.job_type is JobType.full_time                     # CDI
    assert job.work_mode is WorkMode.onsite
    assert (job.min_experience, job.max_experience) == (3, 5)    # "3 À 5 Ans"
    assert job.location.endswith("Algeria") and mena.is_mena(job.location)
    assert job.posted_at is not None and job.source_job_id
    assert len(job.jd_text) > 100 and "<" not in job.jd_text      # full JD, HTML stripped
    assert len(job.required_skills) <= 12


def test_anonymous_company_gets_placeholder(parsed):
    result, urls = parsed
    item = result["data"][1]
    assert item["isAnonymous"] is True
    job = EmploiticScraper()._to_listing(item, urls)
    assert job.company == "Confidential (via Emploitic)"
    # Anonymous postings have no /entreprises/{company}/ segment.
    assert job.source_url == (
        "https://emploitic.com/offres-d-emploi/informatique-telecom-internet/developpeur-odoo-confirme-hf-j079s"
    )
    assert (job.min_experience, job.max_experience) == (3, 10)   # two labels merged


def test_url_is_rebuilt_from_the_sector_when_the_page_listing_lacks_it(parsed):
    result, _ = parsed
    item = result["data"][2]                                      # not in the fixture's ItemList
    job = EmploiticScraper()._to_listing(item, {})
    assert job.source_url.startswith("https://emploitic.com/entreprises/")
    assert job.source_url.endswith("/offres-d-emploi/" + job.source_url.split("/")[-2] + "/developpeur-full-stack-06dpf")
    assert (job.min_experience, job.max_experience) == (0, 2)     # "1 À 2 Ans" + "Moins D’un An"


def test_contract_labels_map_to_job_types():
    from scrapers.emploitic import _CONTRACTS
    m = EmploiticScraper.match_terms
    assert m("CDD Ou Mission", _CONTRACTS) is JobType.contract
    assert m("Stage", _CONTRACTS) is JobType.internship
    assert m("Freelance", _CONTRACTS) is JobType.freelance


def _page(n: int, total_pages: int):
    """Same fixture page, relabelled so each fetched page has fresh ids/URLs."""
    out = PAGE.replace('"currentPage": 1', f'"currentPage": {n}').replace(
        '"totalPages": 16', f'"totalPages": {total_pages}'
    )
    return out.replace("-2j4mf", f"-p{n}a").replace("-j079s", f"-p{n}b").replace("-06dpf", f"-p{n}c")


def test_search_paginates_with_page_param_and_stops_at_total_pages():
    def handler(request: httpx.Request):
        page = int(request.url.params.get("page", "1"))
        return html(_page(page, total_pages=2))
    jobs, seen = run_search(EmploiticScraper, handler, "developpeur", location="Algeria", region="mena")
    assert len(seen) == 2                                         # page 1 and page=2, then stop
    assert "page=2" in seen[1] and "search=developpeur" in seen[0]
    assert len(jobs) == 6                                         # 3 items per page, distinct URLs


def test_search_respects_max_results():
    jobs, seen = run_search(EmploiticScraper, lambda r: html(PAGE), "developpeur", location="Algeria",
                            max_results=2, region="mena")
    assert len(jobs) == 2 and len(seen) == 1


def test_never_requests_a_robots_disallowed_path():
    _, seen = run_search(EmploiticScraper, lambda r: html(PAGE), "developpeur", location="Algiers", region="mena")
    assert seen and all("/partenaires/" not in u for u in seen)


@pytest.mark.parametrize("location", ["Dubai", "Riyadh", "Egypt"])
def test_other_countries_get_nothing_and_no_requests(location):
    jobs, seen = run_search(EmploiticScraper, lambda r: html(PAGE), "developpeur", location=location, region="mena")
    assert jobs == [] and seen == []


def test_page_without_next_data_returns_empty():
    jobs, _ = run_search(EmploiticScraper, lambda r: html("<html></html>"), "developpeur",
                         location="Algeria", region="mena")
    assert jobs == []


def test_registered_for_mena_only():
    from workers.job_discovery import SOURCE_REGISTRY
    assert SOURCE_REGISTRY["emploitic"].regions == {"mena"}


def test_contact_details_in_the_job_text_are_not_stored(parsed):
    result, urls = parsed
    item = dict(result["data"][0])
    item["description"] = "<p>Postulez : rh@acme.dz ou +213 555 12 34 56</p><p>Poste de dev</p>"
    job = EmploiticScraper()._to_listing(item, urls)
    assert "@" not in job.jd_text and "555" not in job.jd_text and "Poste de dev" in job.jd_text
