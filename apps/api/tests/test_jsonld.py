"""Tests for the shared schema.org JobPosting extractor."""
import json

from models.job import JobType, WorkMode
from scrapers.jsonld import find_job_posting, parse_job_posting, strip_html

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
