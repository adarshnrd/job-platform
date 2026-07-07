"""Content-level job dedup — the same role at the same company is one job.

URL-level dedup (unique source_url) cannot catch reposts: portals mint a new
job id for every repost or city variant, so the same role shows up N times
(observed: one Naukri posting stored 15x under different URLs). The
fingerprint collapses listings on normalized (title, company). Location and
platform are deliberately excluded — applying twice to the same role at the
same company is duplicate-application spam no matter which board or city
slug it was scraped from.

Keep the normalization here in sync with job_dedupe_key() in
database/11_job_dedup.sql.
"""
import re

# Legal/boilerplate suffixes that vary between boards for the same employer
# ("Accenture" vs "Accenture Solutions Pvt Ltd").
_COMPANY_NOISE = re.compile(
    r"\b(private|pvt|ltd|limited|inc|incorporated|llc|llp|corp|corporation|co)\b"
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _norm(text: str) -> str:
    return " ".join(_NON_ALNUM.sub(" ", (text or "").lower()).split())


def normalize_title(title: str) -> str:
    return _norm(title)


def normalize_company(company: str) -> str:
    base = _norm(company)
    stripped = " ".join(_COMPANY_NOISE.sub(" ", base).split())
    # A name made up entirely of noise words must not collapse to "".
    return stripped or base


def job_fingerprint(title: str, company: str) -> str:
    """Stable dedupe key for a job posting: normalized title + company."""
    return f"{normalize_title(title)}::{normalize_company(company)}"
