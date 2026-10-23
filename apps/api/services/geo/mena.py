"""MENA geography: country/city lookup, currencies, salary annualizing and the
"nationals only" check.

Why one module: every MENA source (ATS boards, regional boards, remote-board
filters) needs the same answers — is this location in the region, which
currency does it pay in, is the role reserved for citizens — and the answers
must agree across scrapers, the prefilter and region inference. Import it as
`from services.geo import mena`. See docs/mena/PHASE_0_FOUNDATIONS.md §0.2.

Matching rules (where bugs come from): Latin tokens match on letter
boundaries so "oman" never fires inside "woman" or "romania"; Arabic tokens use
plain substring matching because word boundaries do not apply to Arabic script.
"EMEA", "Middle East", "GCC" and similar are regions, not countries, so they
are handled only by `remote_ok_for_mena`.
"""
import re
import unicodedata
from typing import Optional

# iso2 -> name, currency, aliases (country names/abbreviations), major cities.
# All tokens lowercase; Arabic and French spellings included.
MENA_COUNTRIES: dict[str, dict] = {
    "AE": {
        "name": "United Arab Emirates", "currency": "AED",
        "aliases": ("uae", "u.a.e", "emirates", "united arab emirates",
                    "émirats arabes unis", "emirats", "emirats arabes unis",
                    "الإمارات", "الامارات"),
        "cities": ("dubai", "abu dhabi", "sharjah", "ajman", "ras al khaimah",
                   "fujairah", "al ain", "دبي", "أبوظبي", "ابوظبي", "الشارقة"),
    },
    "SA": {
        "name": "Saudi Arabia", "currency": "SAR",
        "aliases": ("ksa", "saudi", "kingdom of saudi arabia", "saudi arabia",
                    "arabie saoudite", "السعودية", "المملكة العربية السعودية"),
        "cities": ("riyadh", "jeddah", "dammam", "khobar", "al khobar", "dhahran",
                   "mecca", "makkah", "medina", "madinah", "neom", "tabuk",
                   "jubail", "الرياض", "جدة", "الدمام", "الخبر"),
    },
    "QA": {
        "name": "Qatar", "currency": "QAR",
        "aliases": ("qatar", "قطر"),
        "cities": ("doha", "lusail", "al rayyan", "الدوحة"),
    },
    "KW": {
        "name": "Kuwait", "currency": "KWD",
        "aliases": ("kuwait", "koweit", "koweït", "الكويت"),
        "cities": ("kuwait city", "hawalli", "salmiya", "ahmadi"),
    },
    "BH": {
        "name": "Bahrain", "currency": "BHD",
        "aliases": ("bahrain", "bahrein", "bahreïn", "البحرين"),
        "cities": ("manama", "muharraq", "المنامة"),
    },
    "OM": {
        "name": "Oman", "currency": "OMR",
        "aliases": ("oman", "sultanate of oman", "عمان", "سلطنة عمان"),
        "cities": ("muscat", "salalah", "sohar", "مسقط"),
    },
    "EG": {
        "name": "Egypt", "currency": "EGP",
        "aliases": ("egypt", "égypte", "egypte", "مصر"),
        "cities": ("cairo", "giza", "alexandria", "new cairo", "smart village",
                   "6th of october", "sheikh zayed", "القاهرة", "الجيزة",
                   "الإسكندرية", "الاسكندرية"),
    },
    "JO": {
        "name": "Jordan", "currency": "JOD",
        "aliases": ("jordan", "jordanie", "الأردن", "الاردن"),
        "cities": ("amman", "irbid", "zarqa", "aqaba", "عمّان"),
    },
    "LB": {
        "name": "Lebanon", "currency": "LBP",
        "aliases": ("lebanon", "liban", "لبنان"),
        "cities": ("beirut", "metn", "jounieh", "بيروت"),
    },
    "PS": {
        "name": "Palestine", "currency": "ILS",
        "aliases": ("palestine", "palestinian territories", "فلسطين"),
        "cities": ("ramallah", "nablus", "gaza", "رام الله"),
    },
    "IQ": {
        "name": "Iraq", "currency": "IQD",
        "aliases": ("iraq", "irak", "العراق"),
        "cities": ("baghdad", "erbil", "basra", "بغداد"),
    },
    "MA": {
        "name": "Morocco", "currency": "MAD",
        "aliases": ("morocco", "maroc", "المغرب"),
        "cities": ("casablanca", "rabat", "marrakech", "tangier", "tanger", "fes",
                   "fès", "agadir", "الدار البيضاء"),
    },
    "TN": {
        "name": "Tunisia", "currency": "TND",
        "aliases": ("tunisia", "tunisie", "تونس"),
        "cities": ("tunis", "sfax", "sousse", "ariana", "la marsa"),
    },
    "DZ": {
        "name": "Algeria", "currency": "DZD",
        "aliases": ("algeria", "algérie", "algerie", "الجزائر"),
        "cities": ("algiers", "alger", "oran", "constantine"),
    },
    "LY": {
        "name": "Libya", "currency": "LYD",
        "aliases": ("libya", "libye", "ليبيا"),
        "cities": ("tripoli", "benghazi"),
    },
}

_ARABIC = re.compile(r"[؀-ۿ]")


def _build_pattern() -> tuple[re.Pattern, dict[str, str]]:
    token_iso: dict[str, str] = {}
    for iso, c in MENA_COUNTRIES.items():
        for tok in (*c["aliases"], *c["cities"]):
            token_iso.setdefault(tok, iso)
    # Longest first so "abu dhabi" / "saudi arabia" win over their prefixes.
    toks = sorted(token_iso, key=len, reverse=True)
    latin = [re.escape(t) for t in toks if not _ARABIC.search(t)]
    arabic = [re.escape(t) for t in toks if _ARABIC.search(t)]
    pattern = (
        r"(?<![a-z])(?:" + "|".join(latin) + r")(?![a-z])"
        + r"|" + "|".join(arabic)
    )
    return re.compile(pattern), token_iso


_PATTERN, _TOKEN_ISO = _build_pattern()
_ISO_CODES = frozenset(c.lower() for c in MENA_COUNTRIES)
_ALIAS_TOKENS = frozenset(tok for c in MENA_COUNTRIES.values() for tok in c["aliases"])


def country_of(location: Optional[str]) -> Optional[str]:
    """ISO-2 of the MENA country named (or implied by a city) in `location`, else None.

    Accepts free text ("Dubai, United Arab Emirates", "الرياض") and bare ISO-2
    codes ("AE", "sa"). A bare code matches only when it is the WHOLE stripped
    string or the last comma-separated segment ("Cairo Gardens, EG"), never as a
    substring ("sa" inside "usa" must not fire).
    """
    if not location:
        return None
    text = unicodedata.normalize("NFKC", location).lower().strip()
    if not text:
        return None
    if text in _ISO_CODES:
        return text.upper()
    # A trailing ", XX" segment ("Al Abageyah, EG") is an explicit country code
    # and the strongest signal. Only after a comma, so "Visa, USA" can't hit "sa".
    if "," in text:
        last = text.rsplit(",", 1)[1].strip()
        if last in _ISO_CODES:
            return last.upper()
    matches = [m.group(0) for m in _PATTERN.finditer(text)]
    if not matches:
        return None
    # A country name beats any city: "La Medina, Tunis, Tunisia" is Tunisia even
    # though "medina" is also a Saudi city. With cities only, the last one wins —
    # locations read narrow → broad ("La Medina, Tunis"), so the later token is
    # the more reliable anchor.
    aliases = [t for t in matches if t in _ALIAS_TOKENS]
    return _TOKEN_ISO[(aliases or matches)[-1]]


def is_mena(location: Optional[str]) -> bool:
    return country_of(location) is not None


def same_country(a: Optional[str], b: Optional[str]) -> bool:
    ca, cb = country_of(a), country_of(b)
    return ca is not None and ca == cb


def currency_for(location_or_iso: Optional[str], default: Optional[str] = None) -> Optional[str]:
    iso = country_of(location_or_iso)
    return MENA_COUNTRIES[iso]["currency"] if iso else default


# Hours/year and days/year use the usual full-time conventions.
_ANNUAL_FACTORS = {
    "HOUR": 2080, "HOURLY": 2080,
    "DAY": 260, "DAILY": 260,
    "WEEK": 52, "WEEKLY": 52,
    "MONTH": 12, "MONTHLY": 12,
    "YEAR": 1, "YEARLY": 1, "ANNUAL": 1, "ANNUALLY": 1,
}


def annualize(amount: Optional[int], unit: Optional[str]) -> Optional[int]:
    """Salary to a yearly figure.

    The repo stores salaries as annual amounts (INR LPA style) while Gulf boards
    quote monthly pay, so every MENA scraper calls this. Unknown/None units are
    left unchanged.
    """
    if amount is None:
        return None
    factor = _ANNUAL_FACTORS.get((unit or "").strip().upper(), 1)
    return round(amount * factor)


_NAT = r"(uae|emirati|saudi|qatari|kuwaiti|omani|bahraini)"
_TITLE_PATTERNS = re.compile("|".join([
    rf"\b{_NAT}\s+nationals?\b",                       # "(UAE National)"
    r"\bemirati[sz](ed|ation)\b",                      # "Emiratized Role"
    r"\b(saudi|qatar|oman|bahrain|kuwait)i?[sz]ation\b",
    r"\bnationals?\s+only\b",
    r"للمواطنين|سعوديين فقط|للسعوديين|مواطن(ين)? فقط",
]), re.I)
_JD_PATTERNS = re.compile("|".join([  # noisier text: require an exclusivity word
    rf"\b(only|exclusively)\s+(for\s+)?{_NAT}\s+nationals?\b",
    rf"\bmust\s+be\s+(an?\s+)?{_NAT}\s+national\b",
    rf"\b{_NAT}\s+nationals?\s+only\b",
    r"للسعوديين فقط|للمواطنين فقط",
]), re.I)
_JD_SCAN_CHARS = 3000


def nationals_only(title: Optional[str], jd_text: Optional[str] = "") -> bool:
    """True when a posting is reserved for citizens (Emiratisation, Saudisation...)."""
    if title and _TITLE_PATTERNS.search(title):
        return True
    return bool(jd_text and _JD_PATTERNS.search(jd_text[:_JD_SCAN_CHARS]))


# Arabic spellings of tech role terms, used to shortlist Arabic-slug sitemap URLs
# (Sabbar) that the English-only tech filter cannot see. docs/mena/PHASE_3_BUILD.md B6.
ARABIC_ROLE_TERMS: dict[str, str] = {
    "software engineer": "مهندس برمجيات", "developer": "مطور", "programmer": "مبرمج",
    "backend": "مطور خلفية", "frontend": "مطور واجهات", "full stack": "فل ستاك",
    "data engineer": "مهندس بيانات", "data scientist": "عالم بيانات", "devops": "ديف أوبس",
    "mobile": "تطبيقات", "cyber security": "أمن سيبراني", "information technology": "تقنية المعلومات",
}


_WORLDWIDE = {"worldwide", "anywhere", "global", "remote"}
_REGION_WORDS = re.compile(r"(?<![a-z])(emea|mena|gcc|gulf|middle[\s-]?east)(?![a-z])")


def names_mena_region(text: Optional[str]) -> bool:
    """True when `text` names a MENA-wide region ("Remote - EMEA", "Gulf", "Middle East").

    Region words are not countries, so `country_of` ignores them; callers that
    must admit region-wide roles (ATS remote jobs, remote boards) use this.
    """
    return bool(text and _REGION_WORDS.search(text.lower()))


def remote_ok_for_mena(restrictions) -> bool:
    """For remote boards: True if a location restriction admits MENA candidates.

    `restrictions` is a str or list[str] (Himalayas sends
    locationRestrictions: ["United States"]). Passes when empty, worldwide,
    or naming MENA/EMEA/the Middle East/GCC/a MENA country.
    """
    if restrictions is None:
        return True
    values = [restrictions] if isinstance(restrictions, str) else list(restrictions)
    values = [str(v).strip() for v in values if v is not None and str(v).strip()]
    if not values:
        return True
    for v in values:
        low = v.lower()
        if low in _WORLDWIDE or names_mena_region(low) or is_mena(v):
            return True
    return False
