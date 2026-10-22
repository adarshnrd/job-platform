"""Content-level job dedup — the same role at the same company is one job.

URL-level dedup (unique source_url) cannot catch reposts: portals mint a new
job id for every repost or city variant, so the same role shows up N times
(observed: one Naukri posting stored 15x under different URLs). The
fingerprint collapses listings on normalized (title, company). Location and
platform are deliberately excluded — applying twice to the same role at the
same company is duplicate-application spam no matter which board or city
slug it was scraped from.

Normalization is Unicode-aware: an ASCII-only filter reduced every Arabic
title to "" and merged them all under one key. Pure-ASCII input normalizes
exactly as before, so existing India/global keys are unchanged.

Keep the normalization here in sync with job_dedupe_key() in
database/17_mena_region.sql (originally database/11_job_dedup.sql).
"""
import re
import unicodedata

# Legal/boilerplate suffixes that vary between boards for the same employer
# ("Accenture" vs "Accenture Solutions Pvt Ltd"). The MENA/French legal forms
# are whole tokens after normalization: dots are already gone, so "W.L.L."
# arrives as "w l l".
_COMPANY_NOISE = re.compile(
    r"\b(private|pvt|ltd|limited|inc|incorporated|llc|llp|corp|corporation|co"
    r"|fz|fze|fzco|fzc|wll|w l l|spc|saog|saoc|sae|s a e|pjsc|psc|plc|sarl|s a r l|spa|sas|est"
    r"|شركة|مؤسسة|المحدودة|ذ م م)\b"
)
# Arabic diacritics (tashkeel), superscript alef and tatweel: presentation
# only, and boards are inconsistent about including them.
# Ranges are explicit (not 064B-0670) so Arabic-Indic digits U+0660-0669 survive.
_AR_MARKS = re.compile(r"[ً-ٰٟـ]")
_NON_WORD = re.compile(r"[\W_]+")   # Unicode-aware: keeps Arabic and accented letters


def _norm(text: str) -> str:
    # Latin accents are deliberately kept: Postgres can't fold them without the
    # unaccent extension, and the SQL twin must produce identical keys.
    text = unicodedata.normalize("NFKC", (text or "")).lower()
    text = _AR_MARKS.sub("", text)
    return " ".join(_NON_WORD.sub(" ", text).split())


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
