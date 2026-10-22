"""
Helpers shared by the MENA regional-board scrapers (Sabbar, Emploitic, Keejob,
ReKrute — docs/mena/PHASE_2_REGIONAL_BOARDS.md).

All four boards face the same small problems: a location that must carry its
country so `services.geo.mena` and the dedup/ranking stages can resolve it,
salary figures that are monthly and need annualizing in the board's currency
(never the model's INR default), French experience labels, and slug-based
shortlisting of sitemap URLs. Keeping them here means each scraper only holds
what is specific to its board.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

from scrapers import jsonld
from services.geo import mena

# Not shared with scrapers.ats / services.prefilter: those keep "." for skills
# like "node.js", and each has its own stopword list for its matching rule. Here
# tokens are matched against URL slugs, which never contain a dot.
_STOPWORDS = {"the", "and", "for", "with", "job", "jobs", "role", "roles", "remote"}


def query_tokens(query: str) -> list[str]:
    """Lowercase search words of 3+ characters, minus filler words."""
    return [
        t for t in re.split(r"[^a-z0-9+#]+", (query or "").lower())
        if len(t) >= 3 and t not in _STOPWORDS
    ]


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").lower().strip()


def _is_country_token(part: str, iso: str) -> bool:
    """True for a bare country name/alias/ISO code (not a city) of `iso`."""
    p = _norm(part)
    c = mena.MENA_COUNTRIES[iso]
    return p == iso.lower() or p == _norm(c["name"]) or p in {_norm(a) for a in c["aliases"]}


def with_country(location: Optional[str], iso: str) -> str:
    """Location text that always names the country, in English.

    "Hammam Zriba, Zaghouan, TN" -> "Hammam Zriba, Zaghouan, Tunisia";
    "Alger, Algérie" -> "Alger, Algeria"; "Riyadh" -> "Riyadh, Saudi Arabia".
    A bare ISO code or a local-language country name in last position is
    replaced by the canonical English name rather than duplicated.
    """
    name = mena.MENA_COUNTRIES[iso]["name"]
    parts = [p.strip() for p in (location or "").split(",") if p.strip()]
    if not parts:
        return name
    if _is_country_token(parts[-1], iso):
        parts[-1] = name
    elif not any(_is_country_token(p, iso) for p in parts):
        parts.append(name)
    return ", ".join(parts)


def apply_salary(fields: dict, iso: str) -> None:
    """Annualize the salary in a `parse_job_posting` dict, in place, and make
    sure `salary_currency` is set.

    Pops `salary_unit` (not a JobListingCreate field). A currency the posting
    labelled itself wins when it also quotes a figure; otherwise the currency of
    `iso` (the board's own country, passed explicitly because free-text lookups
    are ambiguous: Tunis's "La Medina" resolves to Saudi Arabia's Medina).
    Never the model's INR default.
    """
    unit = fields.pop("salary_unit", None)
    has_pay = fields.get("salary_min") is not None or fields.get("salary_max") is not None
    for key in ("salary_min", "salary_max"):
        if fields.get(key) is not None:
            fields[key] = mena.annualize(fields[key], unit)
    posted = fields.get("salary_currency") if has_pay else None
    fields["salary_currency"] = posted or mena.MENA_COUNTRIES[iso]["currency"]


_YEARS_RANGE = re.compile(r"(\d+)\s*(?:à|a|-|–)\s*(\d+)\s*ans?", re.I)
_YEARS_MORE = re.compile(r"plus\s+de\s+(\d+)\s*ans?", re.I)
_YEARS_LESS = re.compile(r"(?:moins\s+de|<)\s*(\d+)\s*ans?", re.I)
_LESS_THAN_ONE = re.compile(r"moins\s+d\W{0,2}\s*un\s+an", re.I)


def parse_experience_fr(label: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    """(min, max) years from a French board label.

    "3 À 5 Ans" -> (3, 5); "Plus de 10 Ans" -> (10, None); "Moins D'un An" ->
    (0, 1); "Confirmé (5 à 10 ans)" -> (5, 10); "Sans Expérience" -> (0, 0).
    Anything unrecognised is (None, None) so merge_experience can still fill it
    from the JD text.
    """
    text = label or ""
    if m := _YEARS_RANGE.search(text):
        return int(m.group(1)), int(m.group(2))
    if m := _YEARS_MORE.search(text):
        return int(m.group(1)), None
    if _LESS_THAN_ONE.search(text):
        return 0, 1
    if m := _YEARS_LESS.search(text):
        return 0, int(m.group(1))
    if re.search(r"sans\s+exp[ée]rience|d[ée]butant", text, re.I):
        return 0, 0
    return None, None


def merge_experience_labels(labels: list[str]) -> tuple[Optional[int], Optional[int]]:
    """Combine several experience labels (Emploitic lists e.g. "1 À 2 Ans" and
    "3 À 5 Ans" for one job) into one range; any open-ended label leaves max open."""
    ranges = [r for r in (parse_experience_fr(l) for l in labels) if r != (None, None)]
    if not ranges:
        return None, None
    lo = min(r[0] for r in ranges)
    hi = None if any(r[1] is None for r in ranges) else max(r[1] for r in ranges)
    return lo, hi


def compile_slug_terms(terms: tuple[str, ...]) -> list[re.Pattern]:
    """Slug matchers. A term with a leading/trailing hyphen ("-ai", "it-") must
    be a whole hyphen-delimited token ("it-" must not fire inside "credit-"
    or "-erp-" inside "enterprise"); other terms match as substrings."""
    out = []
    for t in terms:
        core = t.strip("-")
        if t != core:
            out.append(re.compile(rf"(?:^|-){re.escape(core)}(?:-|$)"))
        else:
            out.append(re.compile(re.escape(core)))
    return out


def slug_has_any(slug: str, patterns: list[re.Pattern]) -> bool:
    return any(p.search(slug) for p in patterns)


def currency_from(*places: Optional[str], default: str = "AED") -> str:
    """Currency of the first of `places` that resolves to a MENA country.

    Keyed aggregators (Careerjet, JSearch, Jooble) rarely label the pay
    currency, so MENA listings take it from the job's location, then from the
    searched location, never the model's INR default.
    """
    for place in places:
        if cur := mena.currency_for(place):
            return cur
    return default


_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_PHONE = re.compile(r"(?<![\w/])\+\d{2,3}[\s.-]?\(?\d[\d\s().-]{6,14}\d")


def scrub_contacts(text: Optional[str]) -> str:
    """Drop e-mail addresses and international phone numbers from job text.

    Ground rule (docs/mena/README.md §5.2): vacancy data only, never recruiter
    contact details (Saudi/UAE PDPL). Application instructions that name an
    address ("send your CV to ...") lose the address and keep the sentence.
    """
    if not text:
        return ""
    return _PHONE.sub("[phone removed]", _EMAIL.sub("[email removed]", text))


def listing_fields(
    posting: dict,
    iso: str,
    *,
    company_fallback: str,
    location: Optional[str] = None,
    location_fallback: str = "",
    generic_locations: tuple[str, ...] = (),
) -> Optional[dict]:
    """JobListingCreate keyword fields from a schema.org JobPosting dict, or None.

    The three JSON-LD boards (Sabbar, Keejob, ReKrute) share this whole recipe:
    drop expired or title-less postings, put the board's country on the
    location, annualize salary in the board's currency, fall back to a labelled
    company, and strip recruiter contacts from the JD. Each scraper keeps what
    is board-specific (URLs, ids, experience, extra JD sources) and builds the
    JobListingCreate itself.

    `location` overrides the posting's own location text (ReKrute reads the
    address parts itself); otherwise the JSON-LD location is used, falling back
    to `location_fallback` (Sabbar's URL city) when empty or listed in
    `generic_locations` (Keejob's bare "Remote", which names no place).
    """
    if jsonld.is_expired(posting):
        return None
    fields = jsonld.map_job_posting(posting)
    if not fields.get("title"):
        return None
    if location is None:
        location = fields.get("location")
        if location in generic_locations:
            location = None
        location = location or location_fallback
    apply_salary(fields, iso)
    fields["location"] = with_country(location, iso)
    fields["company"] = fields.get("company") or company_fallback
    fields["jd_text"] = scrub_contacts(fields.get("jd_text")) or fields["title"]
    return fields
