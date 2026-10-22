"""Offline tests for the Sabbar (KSA) scraper — sitemap shortlist + JSON-LD detail."""
from datetime import datetime

import httpx
import pytest

from models.job import Platform
from scrapers.sabbar import SabbarScraper
from services.geo import mena
from tests.mena_helpers import fixture, html, run_search

SITEMAP = fixture("sabbar_sitemap.xml")
DETAIL = fixture("sabbar_detail.html")
JOB_URL = "https://sabbar.com/en/jobs/c-riyadh-r-software-engineering/id-9efa8804-be0f-4109-b7aa-8e7789c0d8d6"


def _entries():
    return SabbarScraper._parse_sitemap(SITEMAP)


def test_sitemap_parses_url_city_role_and_lastmod():
    entries = _entries()
    assert len(entries) == 6
    url, city, role, lastmod = entries[0]
    assert city == "riyadh" and role == "software-engineering"
    assert lastmod == "2026-10-14"
    assert url.endswith("id-9efa8804-be0f-4109-b7aa-8e7789c0d8d6")


def test_sitemap_entry_without_lastmod_still_parses():
    xml = ("<urlset><url><loc>https://sabbar.com/en/jobs/c-riyadh-r-devops-engineer/"
           "id-9efa8804-be0f-4109-b7aa-8e7789c0d8d6</loc></url></urlset>")
    assert len(SabbarScraper._parse_sitemap(xml)) == 1


def test_slug_filter_keeps_only_the_two_tech_urls():
    picked = SabbarScraper()._candidates(_entries(), "engineer", "")
    assert {e[2] for e in picked} == {"software-engineering", "senior-backend-engineer"}


def test_city_search_ranks_that_city_first():
    s = SabbarScraper()
    assert s._candidates(_entries(), "engineer", "Jeddah, Saudi Arabia")[0][1] == "jeddah"
    assert s._candidates(_entries(), "engineer", "Riyadh")[0][1] == "riyadh"


def test_country_level_search_has_no_city_bias():
    assert SabbarScraper._city_token("Saudi Arabia") == ""
    assert SabbarScraper._city_token("Al Khobar, Saudi Arabia") == "al-khobar"


def test_non_tech_developer_slugs_are_excluded():
    xml = ("<urlset><url><loc>https://sabbar.com/en/jobs/c-riyadh-r-business-developer/"
           "id-9efa8804-be0f-4109-b7aa-8e7789c0d8d6</loc><lastmod>2026-10-14</lastmod></url></urlset>")
    assert SabbarScraper()._candidates(SabbarScraper._parse_sitemap(xml), "developer", "") == []


def test_detail_maps_to_a_saudi_listing_in_sar():
    job = SabbarScraper()._to_listing(DETAIL, JOB_URL, "riyadh")
    assert job.title == "Software Engineering"
    assert job.company == "Lean Technologies"
    assert job.location == "Riyadh, Saudi Arabia"          # bare "SA" replaced by the name
    assert mena.is_mena(job.location)
    assert job.salary_currency == "SAR"
    assert job.source_platform is Platform.sabbar
    assert job.source_job_id == "9efa8804-be0f-4109-b7aa-8e7789c0d8d6"
    assert job.source_url == job.apply_url == JOB_URL
    assert job.posted_at == datetime(2026, 10, 14)
    assert "Spring Boot" in job.jd_text


def test_expired_valid_through_is_skipped():
    expired = DETAIL.replace("2026-11-12T00:00:00+03:00", "2020-01-01T00:00:00+03:00")
    assert expired != DETAIL
    assert SabbarScraper()._to_listing(expired, JOB_URL, "riyadh") is None


def test_page_without_job_posting_is_skipped():
    assert SabbarScraper()._to_listing("<html></html>", JOB_URL, "riyadh") is None


def test_monthly_salary_is_annualized_in_sar():
    paid = DETAIL.replace(
        '"directApply":false',
        '"baseSalary":{"@type":"MonetaryAmount","currency":"SAR","value":{"@type":"QuantitativeValue",'
        '"minValue":8000,"maxValue":12000,"unitText":"MONTH"}},"directApply":false',
    )
    assert '"baseSalary"' in paid
    job = SabbarScraper()._to_listing(paid, JOB_URL, "riyadh")
    assert (job.salary_min, job.salary_max, job.salary_currency) == (96000, 144000, "SAR")


def _handler(request: httpx.Request):
    if request.url.path.endswith("job-details.xml"):
        return html(SITEMAP)
    return html(DETAIL)


def test_search_end_to_end_fetches_sitemap_once_and_only_tech_details():
    jobs, seen = run_search(SabbarScraper, _handler, "software engineer", location="Saudi Arabia", region="mena")
    assert {j.source_platform for j in jobs} == {Platform.sabbar}
    assert len(jobs) == 2
    assert sum(u.endswith("job-details.xml") for u in seen) == 1
    assert len(seen) == 3                         # sitemap + 2 tech details, nothing else


@pytest.mark.parametrize("location", ["Dubai", "Cairo", "United Arab Emirates"])
def test_other_mena_countries_get_nothing_and_no_requests(location):
    jobs, seen = run_search(SabbarScraper, _handler, "software engineer", location=location, region="mena")
    assert jobs == [] and seen == []


def test_sitemap_failure_returns_empty():
    jobs, _ = run_search(SabbarScraper, lambda r: httpx.Response(500), "software engineer",
                         location="Riyadh", region="mena")
    assert jobs == []


def test_registered_for_mena_only():
    from workers.job_discovery import SOURCE_REGISTRY, select_sources
    src = SOURCE_REGISTRY["sabbar"]
    assert src.regions == {"mena"} and src.api_based and not src.requires_key
    assert "sabbar" in {s.name for s in select_sources("mena", [])}
    assert "sabbar" not in {s.name for s in select_sources("india", [])}


# ── Phase 3 B6: percent-encoded Arabic slugs ──

AR_SITEMAP = fixture("sabbar_sitemap_arabic.xml")


def test_arabic_slugs_are_parsed_after_unquoting():
    entries = SabbarScraper._parse_sitemap(AR_SITEMAP)
    assert len(entries) == 5
    by_city = {e[1] for e in entries}
    assert by_city == {"madinah", "riyadh", "jeddah"}
    roles = {e[2] for e in entries}
    assert "مطور-امن-النظام" in roles and "محاسب" in roles
    assert "مدربة-كرة-قدم-/-سباحة" in roles                  # a role slug may contain "/"
    assert all("%" in e[0] for e in entries)                  # the fetched URL stays encoded


def test_arabic_developer_slug_passes_the_tech_filter_and_accountant_does_not():
    picked = SabbarScraper()._candidates(SabbarScraper._parse_sitemap(AR_SITEMAP), "developer", "")
    roles = {e[2] for e in picked}
    assert roles == {"مطور-امن-النظام", "مبرمج"}              # developer, programmer
    assert "محاسب" not in roles                              # accountant
    # "partner designer AND developer of laser products" only contains the word fused to a prefix
    assert not any("ليزر" in r for r in roles)


def test_arabic_multiword_terms_are_hyphen_joined_and_business_developer_excluded():
    xml = ("<urlset>"
           "<url><loc>https://sabbar.com/en/jobs/c-riyadh-r-%D9%85%D9%87%D9%86%D8%AF%D8%B3-%D8%A8%D8%B1%D9%85%D8%AC%D9%8A%D8%A7%D8%AA/id-9efa8804-be0f-4109-b7aa-8e7789c0d8d6</loc></url>"
           "<url><loc>https://sabbar.com/en/jobs/c-riyadh-r-%D9%85%D8%B7%D9%88%D8%B1-%D8%B9%D9%82%D8%A7%D8%B1%D9%8A/id-8efa8804-be0f-4109-b7aa-8e7789c0d8d6</loc></url>"
           "</urlset>")
    picked = SabbarScraper()._candidates(SabbarScraper._parse_sitemap(xml), "", "")
    assert [e[2] for e in picked] == ["مهندس-برمجيات"]        # software engineer; real-estate developer dropped


def test_arabic_listing_uuid_comes_from_the_unquoted_url():
    url = SabbarScraper._parse_sitemap(AR_SITEMAP)[0][0]
    job = SabbarScraper()._to_listing(DETAIL, url, "madinah")
    assert job.source_job_id and job.source_url == url
