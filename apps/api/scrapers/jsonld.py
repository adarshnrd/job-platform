"""
schema.org JobPosting extraction from an HTML page.

Any board that wants its roles indexed by Google for Jobs must embed a
`<script type="application/ld+json">` JobPosting block. That contract is far
more stable than CSS classes — it survives the frontend rewrites that
routinely break selector-based scrapers — so prefer it whenever a board
publishes it (verified present on Welcome to the Jungle, 2026-07-27).

`parse_job_posting` returns a plain dict of the fields the job model cares
about; callers map it onto JobListingCreate.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Optional

from models.job import JobType, WorkMode

_LD_BLOCK = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I,
)
_HTML_TAG = re.compile(r"<[^>]+>")

# schema.org employmentType → our JobType. Boards use several spellings.
_EMPLOYMENT_TYPES: dict[str, JobType] = {
    "FULL_TIME": JobType.full_time, "FULLTIME": JobType.full_time,
    "PART_TIME": JobType.part_time, "PARTTIME": JobType.part_time,
    "CONTRACTOR": JobType.contract, "CONTRACT": JobType.contract,
    "TEMPORARY": JobType.contract, "INTERN": JobType.internship,
    "INTERNSHIP": JobType.internship, "OTHER": JobType.full_time,
}


def iter_ld_blocks(html: str):
    """Yield every parsed ld+json object on the page, flattening @graph lists."""
    for raw in _LD_BLOCK.findall(html or ""):
        try:
            data = json.loads(raw.strip())
        except Exception:
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if isinstance(graph, list):
                yield from (g for g in graph if isinstance(g, dict))
            else:
                yield item


def find_job_posting(html: str) -> Optional[dict]:
    """The first JobPosting object on the page, or None."""
    for obj in iter_ld_blocks(html):
        if obj.get("@type") == "JobPosting" or (
            isinstance(obj.get("@type"), list) and "JobPosting" in obj["@type"]
        ):
            return obj
    return None


def strip_html(value: Any) -> str:
    """JobPosting.description is HTML-in-a-JSON-string on most boards."""
    if not value:
        return ""
    text = _HTML_TAG.sub(" ", str(value))
    text = (
        text.replace("&nbsp;", " ").replace("&amp;", "&")
        .replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'")
        .replace("&quot;", '"')
    )
    return re.sub(r"\s+", " ", text).strip()


def _parse_date(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _first(value: Any) -> Any:
    """jobLocation/address fields are sometimes a list, sometimes a bare object."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _location_str(posting: dict) -> str:
    place = _first(posting.get("jobLocation"))
    if not isinstance(place, dict):
        return ""
    address = _first(place.get("address"))
    if not isinstance(address, dict):
        return str(address or "")
    parts = [
        address.get("addressLocality"),
        address.get("addressRegion"),
        address.get("addressCountry") if isinstance(address.get("addressCountry"), str)
        else (address.get("addressCountry") or {}).get("name"),
    ]
    return ", ".join(str(p) for p in parts if p)


def _salary(posting: dict) -> tuple[Optional[int], Optional[int], Optional[str]]:
    base = posting.get("baseSalary")
    if not isinstance(base, dict):
        return None, None, None
    currency = base.get("currency") or base.get("salaryCurrency")
    value = base.get("value")
    if isinstance(value, list):
        value = value[0] if value else None
    if not isinstance(value, dict):
        return None, None, currency

    def _as_int(v):
        try:
            n = int(float(v))
            return n if n > 0 else None
        except (TypeError, ValueError):
            return None

    lo = _as_int(value.get("minValue"))
    hi = _as_int(value.get("maxValue"))
    if lo is None and hi is None:
        exact = _as_int(value.get("value"))
        lo = hi = exact
    return lo, hi, currency


def parse_job_posting(html: str) -> Optional[dict]:
    """Extract a JobPosting into job-model field names, or None if absent.

    Only fields the posting actually carries are returned, so callers can
    `dict.update()` over their own defaults without clobbering them with None.
    """
    posting = find_job_posting(html)
    if not posting:
        return None

    org = posting.get("hiringOrganization")
    org = org if isinstance(org, dict) else {}
    salary_min, salary_max, currency = _salary(posting)

    employment = posting.get("employmentType")
    if isinstance(employment, list):
        employment = employment[0] if employment else None
    job_type = _EMPLOYMENT_TYPES.get(str(employment or "").upper().replace("-", "_"))

    remote = str(posting.get("jobLocationType") or "").upper() == "TELECOMMUTE"
    location = _location_str(posting)

    out: dict[str, Any] = {
        "title": strip_html(posting.get("title")) or None,
        "company": strip_html(org.get("name")) or None,
        "company_logo_url": org.get("logo") if isinstance(org.get("logo"), str) else None,
        "company_website": org.get("sameAs") if isinstance(org.get("sameAs"), str) else None,
        "company_industry": strip_html(posting.get("industry")) or None,
        "location": ("Remote" if remote and not location else location) or None,
        "jd_text": strip_html(posting.get("description")) or None,
        "posted_at": _parse_date(posting.get("datePosted")),
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": currency,
        "job_type": job_type,
        "work_mode": WorkMode.remote if remote else None,
        "is_remote_friendly": remote or None,
    }
    return {k: v for k, v in out.items() if v is not None}
