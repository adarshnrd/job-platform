"""Offline tests for the Keejob (Tunisia) scraper — HTML list + JSON-LD detail."""
import httpx
import pytest

from models.job import JobType, Platform, WorkMode
from scrapers.keejob import KeejobScraper
from services.geo import mena
from tests.mena_helpers import fixture, html, run_search

LIST = fixture("keejob_list.html")
REMOTE = fixture("keejob_detail_remote.html")
SALARY = fixture("keejob_detail_salary.html")


def test_link_extraction_dedupes_ids_and_strips_query_and_action_paths():
    paths = KeejobScraper.extract_job_paths(LIST)
    assert len(paths) == 5                                        # each card links twice
    assert "248558" in paths and "247979" in paths
    assert all(p.startswith("/offres-emploi/") and "?" not in p for p in paths.values())
    assert not any("postuler" in p for p in paths.values())       # robots.txt-disallowed action path


def test_remote_detail_maps_with_remote_flag_and_tunisian_location():
    url = "https://www.keejob.com/offres-emploi/248558/developpeur-software-hpc-junior/"
    job = KeejobScraper()._to_listing(REMOTE, url, "248558")
    assert job.company == "ENNOLAB"
    assert job.work_mode is WorkMode.remote and job.is_remote_friendly
    assert job.location == "La Medina, Tunis, Tunisia" and mena.is_mena(job.location)
    # "La Medina" also names a Saudi city, so the currency must come from the
    # board's country, not from re-parsing the free-text location.
    assert job.salary_currency == "TND"
    assert job.source_job_id == "248558"
    assert job.source_platform is Platform.keejob
    assert job.job_type is JobType.full_time


def test_detail_with_monthly_salary_is_annualized():
    url = "https://www.keejob.com/offres-emploi/247979/full-stack-developer-symfony-vuejs-mobile/"
    job = KeejobScraper()._to_listing(SALARY, url, "247979")
    assert (job.salary_min, job.salary_max, job.salary_currency) == (14400, 30000, "TND")
    assert job.location == "Hammam Zriba, Zaghouan, Tunisia"
    assert job.company.split() == ["RAYEN", "SOFT"]


def test_expired_posting_is_skipped():
    expired = REMOTE.replace("2026-11-15T23:59:59", "2020-01-01T00:00:00")
    assert expired != REMOTE
    assert KeejobScraper()._to_listing(expired, "https://www.keejob.com/x/", "1") is None


def _handler(request: httpx.Request):
    if request.url.path == "/offres-emploi/":
        return html(LIST)
    return html(REMOTE)


def test_search_end_to_end_caps_details_and_skips_disallowed_paths():
    jobs, seen = run_search(KeejobScraper, _handler, "developpeur", location="Tunisia", region="mena")
    assert 1 <= len(jobs) <= KeejobScraper.DETAIL_FETCH_LIMIT
    assert len(seen) == 2 + 5                                     # list pages 1 and 2 + 5 distinct details
    assert all("/api/" not in u and "/postuler" not in u and "?source=" not in u for u in seen)


def test_second_page_only_fetched_when_first_is_short():
    _, seen = run_search(KeejobScraper, _handler, "developpeur", location="Tunis", region="mena")
    assert any("page=2" in u for u in seen)                       # 5 ids < limit 12 -> page 2 asked
    assert not any("page=3" in u for u in seen)


@pytest.mark.parametrize("location", ["Dubai", "Casablanca", "Saudi Arabia"])
def test_wrong_country_returns_nothing_without_requests(location):
    jobs, seen = run_search(KeejobScraper, _handler, "developpeur", location=location, region="mena")
    assert jobs == [] and seen == []


def test_registered_for_mena_only():
    from workers.job_discovery import SOURCE_REGISTRY
    assert SOURCE_REGISTRY["keejob"].regions == {"mena"}


def test_multi_word_query_falls_back_to_single_words_when_empty():
    """Keejob ANDs every word: English "software engineer" matches nothing, "software" does."""
    def handler(request: httpx.Request):
        if request.url.path == "/offres-emploi/":
            kw = request.url.params.get("keywords")
            return html(LIST if kw == "software" else "<html></html>")
        return html(REMOTE)
    jobs, seen = run_search(KeejobScraper, handler, "software engineer", location="Tunisia", region="mena")
    lists = [u for u in seen if "keywords=" in u]
    assert "keywords=software%20engineer" in lists[0]
    assert any("keywords=software" in u and "engineer" not in u for u in lists)
    assert len(lists) <= 2 + KeejobScraper.MAX_PAGES              # bounded extra requests
    assert jobs


def test_single_word_query_has_no_variants():
    assert KeejobScraper._query_variants("developpeur") == ["developpeur"]
