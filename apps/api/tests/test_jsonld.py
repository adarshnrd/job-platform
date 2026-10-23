"""Tests for the shared schema.org JobPosting extractor."""
import json

from models.job import JobType, WorkMode
from scrapers.jsonld import find_job_posting, map_job_posting, parse_job_posting, strip_html

POSTING = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    "title": "Senior Data Engineer",
    "description": "<p>Build <b>pipelines</b>&nbsp;at scale.</p>",
    "datePosted": "2026-07-14T00:11:00Z",
    "employmentType": "FULL_TIME",
    "hiringOrganization": {
        "@type": "Organization",
        "name": "iwoca",
        "logo": "https://example.test/logo.png",
        "sameAs": "https://iwoca.co.uk",
    },
    "jobLocation": {
        "@type": "Place",
        "address": {
            "@type": "PostalAddress",
            "addressLocality": "London",
            "addressCountry": "GB",
        },
    },
    "baseSalary": {
        "@type": "MonetaryAmount",
        "currency": "GBP",
        "value": {"@type": "QuantitativeValue", "minValue": 70000, "maxValue": 100000},
    },
}


def _page(*objects) -> str:
    blocks = "".join(
        f'<script type="application/ld+json">{json.dumps(o)}</script>' for o in objects
    )
    return f"<html><head>{blocks}</head><body>ignored</body></html>"


def test_parses_a_full_posting():
    out = parse_job_posting(_page(POSTING))
    assert out["title"] == "Senior Data Engineer"
    assert out["company"] == "iwoca"
    assert out["company_website"] == "https://iwoca.co.uk"
    assert out["location"] == "London, GB"
    assert out["job_type"] is JobType.full_time
    assert out["salary_min"] == 70000 and out["salary_max"] == 100000
    assert out["salary_currency"] == "GBP"
    assert out["posted_at"].year == 2026
    assert out["jd_text"] == "Build pipelines at scale."


def test_absent_fields_are_omitted_not_none():
    """Callers dict.update() this over their defaults, so None must never leak."""
    minimal = {"@type": "JobPosting", "title": "Role"}
    out = parse_job_posting(_page(minimal))
    assert out == {"title": "Role"}
    assert all(v is not None for v in out.values())


def test_remote_postings_map_to_work_mode():
    out = parse_job_posting(_page({**POSTING, "jobLocationType": "TELECOMMUTE"}))
    assert out["work_mode"] is WorkMode.remote
    assert out["is_remote_friendly"] is True


def test_remote_without_an_address_falls_back_to_remote_label():
    posting = {k: v for k, v in POSTING.items() if k != "jobLocation"}
    out = parse_job_posting(_page({**posting, "jobLocationType": "TELECOMMUTE"}))
    assert out["location"] == "Remote"


def test_list_valued_fields_are_tolerated():
    """Boards variously send objects or single-element lists for these."""
    out = parse_job_posting(_page({
        **POSTING,
        "employmentType": ["PART_TIME"],
        "jobLocation": [POSTING["jobLocation"]],
    }))
    assert out["job_type"] is JobType.part_time
    assert out["location"] == "London, GB"


def test_finds_the_posting_among_other_ld_blocks():
    breadcrumb = {"@type": "BreadcrumbList", "itemListElement": []}
    org = {"@type": "Organization", "name": "Not the job"}
    out = parse_job_posting(_page(breadcrumb, org, POSTING))
    assert out["title"] == "Senior Data Engineer"


def test_reads_postings_nested_in_a_graph():
    graph = {"@context": "https://schema.org", "@graph": [{"@type": "WebPage"}, POSTING]}
    assert find_job_posting(_page(graph)) is not None


def test_type_may_be_a_list():
    assert find_job_posting(_page({**POSTING, "@type": ["JobPosting", "Thing"]})) is not None


def test_malformed_json_is_skipped_not_raised():
    html = (
        '<script type="application/ld+json">{not json,,,}</script>'
        + _page(POSTING)
    )
    assert parse_job_posting(html)["title"] == "Senior Data Engineer"


def test_no_posting_returns_none():
    assert parse_job_posting("<html><body>nothing here</body></html>") is None
    assert parse_job_posting("") is None


def test_zero_and_negative_salaries_are_dropped():
    out = parse_job_posting(_page({
        **POSTING,
        "baseSalary": {"currency": "USD", "value": {"minValue": 0, "maxValue": 0}},
    }))
    assert "salary_min" not in out and "salary_max" not in out


def test_strip_html_unescapes_entities():
    assert strip_html("<p>A&nbsp;&amp;&nbsp;B</p>") == "A & B"
    assert strip_html(None) == ""


# ── MENA additions (docs/mena/PHASE_0_FOUNDATIONS.md §0.6) ──

def test_map_job_posting_matches_parse_job_posting():
    assert map_job_posting(POSTING) == parse_job_posting(_page(POSTING))


def test_french_contract_types_map():
    assert map_job_posting({**POSTING, "employmentType": "CDI"})["job_type"] is JobType.full_time
    assert map_job_posting({**POSTING, "employmentType": "CDD"})["job_type"] is JobType.contract
    assert map_job_posting({**POSTING, "employmentType": "STAGE"})["job_type"] is JobType.internship
    assert map_job_posting({**POSTING, "employmentType": "FREELANCE"})["job_type"] is JobType.freelance


def test_space_separated_date_is_parsed():
    out = map_job_posting({**POSTING, "datePosted": "2026-10-15 14:30:02"})
    assert (out["posted_at"].year, out["posted_at"].hour, out["posted_at"].second) == (2026, 14, 2)


def test_salary_unit_passthrough():
    posting = {**POSTING, "baseSalary": {
        "currency": "AED",
        "value": {"minValue": 10000, "maxValue": 15000, "unitText": "month"},
    }}
    out = map_job_posting(posting)
    assert out["salary_unit"] == "MONTH"
    assert out["salary_currency"] == "AED"
    # unitText may also sit on the MonetaryAmount itself.
    posting["baseSalary"] = {"currency": "AED", "unitText": "YEAR",
                             "value": {"minValue": 1, "maxValue": 2}}
    assert map_job_posting(posting)["salary_unit"] == "YEAR"
    # Absent unit is omitted, not None.
    assert "salary_unit" not in map_job_posting(POSTING)


def test_iso2_country_string_in_address():
    posting = {**POSTING, "jobLocation": {"address": {
        "addressLocality": "Casablanca", "addressCountry": "MA"}}}
    assert map_job_posting(posting)["location"] == "Casablanca, MA"


# ── Phase 2 additions (MENA boards) ──

def test_raw_control_characters_in_a_string_are_tolerated():
    """ReKrute emits literal newlines inside `description`; strict JSON rejects them."""
    block = (
        '<script type="application/ld+json">{"@type":"JobPosting","title":"Dev",'
        '"description":"line one\nline\ttwo"}</script>'
    )
    out = parse_job_posting(block)
    assert out["title"] == "Dev" and "line one" in out["jd_text"]


def test_strip_html_decodes_named_and_numeric_entities():
    assert strip_html("Rattach&eacute;(e) &agrave; l&#39;&eacute;quipe d&rsquo;infra") == "Rattaché(e) à l'équipe d’infra"


def test_is_expired():
    from datetime import datetime
    from scrapers.jsonld import is_expired
    now = datetime(2026, 10, 17)
    assert is_expired({"validThrough": "2026-10-01T00:00:00+03:00"}, now) is True
    assert is_expired({"validThrough": "2026-12-15 14:30:02"}, now) is False
    assert is_expired({}, now) is False
    assert is_expired({"validThrough": "not a date"}, now) is False
