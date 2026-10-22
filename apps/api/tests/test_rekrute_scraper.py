"""Offline tests for the ReKrute (Morocco) scraper — sitemap shortlist + JSON-LD/HTML detail."""
from datetime import datetime

import httpx
import pytest

from models.job import JobType, Platform
from scrapers import rekrute
from scrapers.rekrute import RekruteScraper, extract_jd
from services.geo import mena
from tests.mena_helpers import fixture, html, run_search

SITEMAP = fixture("rekrute_sitemap.xml")
DETAIL = fixture("rekrute_detail.html")
RAW = fixture("rekrute_detail_rawnewline.html")
URL = "https://www.rekrute.com/offre-emploi-developpeur-python-ia-recrutement-alten-maroc-fes-187569.html"


def _offers():
    return [(m.group(1), m.group(2), int(m.group(3))) for m in rekrute._OFFER_RE.finditer(SITEMAP)]


def test_sitemap_lists_only_offer_urls():
    offers = _offers()
    assert len(offers) == 6                                        # the category URL is ignored
    assert all(u.endswith(".html") and "/offre-emploi-" in u for u, _, _ in offers)


def test_shortlist_is_tech_only_and_morocco_first():
    picked = RekruteScraper()._candidates(_offers(), "developpeur", "MA")
    slugs = [p[1] for p in picked]
    assert any("alten-maroc-fes" in x for x in slugs) and any("sofrecom" in x for x in slugs)
    assert not any("comptable" in x or "cabin-crew" in x or "ariana" in x for x in slugs)


def test_other_country_offers_shortlist_only_for_that_country():
    tn = RekruteScraper()._candidates(_offers(), "it bid", "TN")
    assert [p[1] for p in tn] == ["charge-dappels-doffres-it-bid-officer-recrutement-xtensus-ariana"]


def test_job_text_comes_from_poste_and_profil_sections():
    jd = extract_jd(DETAIL)
    assert jd.startswith("Poste: Concevoir et développer")
    assert "Profil recherché: Compétences solides" in jd
    assert "ENTREPRISE" not in jd and "<" not in jd


def test_jd_falls_back_to_json_ld_then_meta_description():
    no_body = DETAIL.split("<body>")[0] + "<body></body></html>"
    assert extract_jd(no_body).startswith("Concevoir et développer des solutions")
    meta_only = '<html><head><meta name="description" content="Découvrez l’offre X &amp; Y"></head></html>'
    assert extract_jd(meta_only) == "Découvrez l’offre X & Y"


def test_entities_in_job_text_are_decoded():
    jd = extract_jd(RAW)
    assert "&eacute;" not in jd and "&rsquo;" not in jd and "&#39;" not in jd


def test_detail_maps_french_fields():
    job = RekruteScraper()._to_listing(DETAIL, URL, "187569")
    assert job.title == "Développeur Python IA"
    assert job.company == "ALTEN Maroc"
    assert job.location == "Fes, Morocco" and mena.is_mena(job.location)
    assert job.salary_currency == "MAD"
    assert job.job_type is JobType.full_time                       # CDI
    assert (job.min_experience, job.max_experience) == (5, 10)     # "Confirmé (5 à 10 ans)"
    assert job.posted_at == datetime(2026, 10, 15, 14, 30, 2)      # space-separated date
    assert job.source_platform is Platform.rekrute and job.source_job_id == "187569"


def test_json_ld_with_raw_newlines_still_parses():
    """Some offer pages put literal newlines in the description string."""
    job = RekruteScraper()._to_listing(RAW, "https://www.rekrute.com/x-187559.html", "187559")
    assert job is not None and job.location == "Rabat, Morocco"
    assert (job.min_experience, job.max_experience) == (3, 5)


def test_foreign_country_posting_is_dropped():
    foreign = DETAIL.replace('"addressCountry": "Maroc"', '"addressCountry": "Sénégal"')
    assert foreign != DETAIL
    assert RekruteScraper()._to_listing(foreign, URL, "1") is None


def test_wanted_country_must_match_the_posting():
    assert RekruteScraper()._to_listing(DETAIL, URL, "1", wanted="TN") is None
    assert RekruteScraper()._to_listing(DETAIL, URL, "1", wanted="MA") is not None


def test_expired_posting_is_skipped():
    expired = DETAIL.replace("2026-12-15 14:30:02", "2020-01-01 00:00:00")
    assert expired != DETAIL
    assert RekruteScraper()._to_listing(expired, URL, "1") is None


def _handler(request: httpx.Request):
    if request.url.path == "/sitemap.xml":
        return html(SITEMAP)
    return html(DETAIL)


def test_search_uses_the_sitemap_never_the_disallowed_search_page():
    jobs, seen = run_search(RekruteScraper, _handler, "developpeur", location="Morocco", region="mena")
    assert jobs and all(j.source_platform is Platform.rekrute for j in jobs)
    assert seen[0].endswith("/sitemap.xml")
    assert all("/offres.html" not in u for u in seen)


@pytest.mark.parametrize("location", ["Dubai", "Saudi Arabia", "Egypt"])
def test_gulf_and_other_countries_get_nothing_without_requests(location):
    jobs, seen = run_search(RekruteScraper, _handler, "developpeur", location=location, region="mena")
    assert jobs == [] and seen == []


def test_registered_for_mena_only():
    from workers.job_discovery import SOURCE_REGISTRY
    assert SOURCE_REGISTRY["rekrute"].regions == {"mena"}
