"""Shared MENA board helpers (scrapers/mena_common.py)."""
import pytest

from scrapers.mena_common import (
    apply_salary, compile_slug_terms, currency_from, merge_experience_labels,
    parse_experience_fr, query_tokens, slug_has_any, with_country,
)


@pytest.mark.parametrize("raw,iso,expected", [
    ("Riyadh", "SA", "Riyadh, Saudi Arabia"),
    ("", "SA", "Saudi Arabia"),
    ("Hammam Zriba, Zaghouan, TN", "TN", "Hammam Zriba, Zaghouan, Tunisia"),
    ("Alger, Algérie", "DZ", "Alger, Algeria"),
    ("Fes, Maroc", "MA", "Fes, Morocco"),
    ("La Medina, Tunis", "TN", "La Medina, Tunis, Tunisia"),   # a city is not a country token
    ("Algérie", "DZ", "Algeria"),
    ("Cairo, Egypt", "EG", "Cairo, Egypt"),
])
def test_with_country(raw, iso, expected):
    assert with_country(raw, iso) == expected


def test_with_country_output_resolves_through_mena():
    from services.geo import mena
    assert mena.country_of(with_country("Hammam Zriba, Zaghouan, TN", "TN")) == "TN"


def test_apply_salary_annualizes_monthly_and_keeps_posted_currency():
    f = {"salary_min": 1200, "salary_max": 2500, "salary_currency": "TND", "salary_unit": "MONTH"}
    apply_salary(f, "TN")
    assert (f["salary_min"], f["salary_max"], f["salary_currency"]) == (14400, 30000, "TND")
    assert "salary_unit" not in f


def test_apply_salary_never_defaults_to_inr():
    f = {"title": "x"}
    apply_salary(f, "DZ")
    assert f["salary_currency"] == "DZD"
    assert "salary_min" not in f


def test_apply_salary_ignores_a_currency_without_pay():
    f = {"salary_currency": "USD"}
    apply_salary(f, "SA")
    assert f["salary_currency"] == "SAR"


@pytest.mark.parametrize("label,expected", [
    ("3 À 5 Ans", (3, 5)),
    ("1 À 2 Ans", (1, 2)),
    ("Plus de 10 Ans", (10, None)),
    ("Moins D’un An", (0, 1)),
    ("Moins d'un an", (0, 1)),
    ("Sans Expérience", (0, 0)),
    ("Confirmé (5 à 10 ans)", (5, 10)),
    ("Débutant (< 3 ans)", (0, 3)),
    ("", (None, None)),
    ("n/a", (None, None)),
])
def test_parse_experience_fr(label, expected):
    assert parse_experience_fr(label) == expected


def test_merge_experience_labels():
    assert merge_experience_labels(["1 À 2 Ans", "3 À 5 Ans"]) == (1, 5)
    assert merge_experience_labels(["3 À 5 Ans", "Plus de 10 Ans"]) == (3, None)
    assert merge_experience_labels([]) == (None, None)


def test_slug_terms_respect_token_boundaries():
    pats = compile_slug_terms(("it-", "-erp-", "cloud"))
    assert slug_has_any("it-helpdesk-support", pats)
    assert slug_has_any("senior-erp-consultant", pats)
    assert slug_has_any("cloud-architect", pats)
    assert not slug_has_any("credit-analyst", pats)        # "it-" inside "credit-"
    assert not slug_has_any("enterprise-sales", pats)      # "erp" inside "enterprise"


def test_query_tokens_drop_filler_and_short_words():
    assert query_tokens("Senior Python Developer in AI jobs") == ["senior", "python", "developer"]


def test_currency_from_prefers_first_resolvable_place():
    assert currency_from("Jeddah", "Dubai") == "SAR"
    assert currency_from(None, "Dubai") == "AED"
    assert currency_from("London", None, default="AED") == "AED"


def test_scrub_contacts_removes_emails_and_international_phones_only():
    from scrapers.mena_common import scrub_contacts
    text = "Send your CV to hr.team@acme.com or call +213 555 12 34 56. Salary 120000 DZD, 3-5 ans."
    out = scrub_contacts(text)
    assert "@" not in out and "555" not in out
    assert "Send your CV to" in out and "Salary 120000 DZD, 3-5 ans." in out
    assert scrub_contacts(None) == ""


def _posting(**over):
    base = {
        "@type": "JobPosting", "title": "Backend Developer",
        "description": "<p>Build APIs. Mail hr@acme.tn</p>",
        "hiringOrganization": {"name": "Acme"},
        "jobLocation": {"address": {"addressLocality": "Tunis", "addressCountry": "TN"}},
    }
    return {**base, **over}


def test_listing_fields_builds_country_scrubbed_fields():
    from scrapers.mena_common import listing_fields
    f = listing_fields(_posting(), "TN", company_fallback="X (via Y)")
    assert f["title"] == "Backend Developer" and f["company"] == "Acme"
    assert f["location"].endswith("Tunisia") and f["salary_currency"] == "TND"
    assert "hr@acme.tn" not in f["jd_text"] and "[email removed]" in f["jd_text"]


def test_listing_fields_rejects_expired_and_titleless():
    from scrapers.mena_common import listing_fields
    assert listing_fields(_posting(validThrough="2020-01-01"), "TN", company_fallback="c") is None
    assert listing_fields(_posting(title=""), "TN", company_fallback="c") is None


def test_listing_fields_fallbacks():
    from scrapers.mena_common import listing_fields
    bare = _posting(hiringOrganization=None, description="", jobLocation=None)
    f = listing_fields(bare, "SA", company_fallback="Co (via Sabbar)", location_fallback="Al Khobar")
    assert f["company"] == "Co (via Sabbar)" and f["jd_text"] == "Backend Developer"
    assert f["location"] == "Al Khobar, Saudi Arabia"
    f = listing_fields(_posting(jobLocation=None, jobLocationType="TELECOMMUTE"), "TN",
                       company_fallback="c", generic_locations=("Remote",))
    assert f["location"] == "Tunisia"
    f = listing_fields(_posting(), "MA", company_fallback="c", location="Fès")
    assert f["location"] == "Fès, Morocco"
