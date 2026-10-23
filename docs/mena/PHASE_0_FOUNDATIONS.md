# Phase 0: MENA Foundations

> **Goal:** make `mena` a working discovery region and fix the shared code that would corrupt or drop MENA data, **before** any MENA source is added.
> **Estimated size:** 1 PR, about 9 tasks. No new scraper.
> **Read first:** [README.md](README.md) §4 (architecture) and §5 (ground rules).

Done means all of these hold:
- `POST /jobs/discover {"region":"mena"}` runs and is logged as `region=mena`.
- Inference: Dubai-only locations give `mena`, mixed Dubai and Bangalore gives `india`, London gives `global`.
- Arabic and French titles dedup correctly.
- Jobs open only to nationals are prefiltered.
- The UI can trigger a MENA run.
- The whole existing test suite still passes.

---

## 0.1 Shared region constant

**File:** `apps/api/models/job.py`

Add near the top, below the imports. `models` is the lowest layer, so everything else can import from it without a cycle.

```python
# Discovery regions. "india" stays the default (India-first deployment).
VALID_REGIONS: tuple[str, ...] = ("india", "global", "mena")
```

Update `DiscoveryRequest`:

```python
    region: Optional[str] = None  # "india" | "global" | "mena" | None

    @validator("region")
    @classmethod
    def _valid_region(cls, v):
        if v is None:
            return None
        return v if v in VALID_REGIONS else "india"
```

**File:** `apps/api/models/__init__.py`. Update the `discovery_region` comment on `ProfileBase` to `"india" | "global" | "mena" | None`. No validation is needed there; the DB CHECK constraint (0.8) enforces the values.

---

## 0.2 New module `services/geo/mena.py`

Create the package `apps/api/services/geo/__init__.py` (empty docstring only) and `apps/api/services/geo/mena.py`. **Every later phase imports from this module**, so get the API exactly as specified.

### Public API

```python
MENA_COUNTRIES: dict[str, dict]       # iso2 -> {"name", "currency", "aliases": tuple, "cities": tuple}
MENA_LOCATION_HINTS: tuple[str, ...]  # flat lowercase tokens for region inference
MENA_DEFAULT_LOCATIONS: tuple[str, ...] = (
    "United Arab Emirates", "Saudi Arabia", "Egypt", "Qatar",
)

def country_of(location: str | None) -> str | None
    """ISO-2 of the first MENA country named or implied by a city in `location`, else None.
    Accepts free text ("Dubai, United Arab Emirates", "Riyadh", "الرياض", "Casablanca, Maroc")
    and bare ISO-2 codes exactly ("AE", "sa"). Bare codes match only when the WHOLE stripped
    string is the code, never as a substring."""

def is_mena(location: str | None) -> bool               # country_of(location) is not None
def same_country(a: str | None, b: str | None) -> bool  # both resolve to the same non-None iso2
def currency_for(location_or_iso: str | None, default: str | None = None) -> str | None
def annualize(amount: int | None, unit: str | None) -> int | None
    """Salary to a yearly figure. unit is a schema.org unitText or a board label:
    HOUR -> x2080, DAY -> x260, WEEK -> x52, MONTH -> x12, YEAR or None -> unchanged.
    The repo stores salaries as annual amounts (INR LPA style), and Gulf boards
    quote monthly pay, so every MENA scraper calls this."""

def nationals_only(title: str | None, jd_text: str | None = "") -> bool
    """True when a posting is reserved for citizens (Emiratisation / Saudisation etc.)."""

def remote_ok_for_mena(restrictions) -> bool
    """For remote boards: True if a location-restriction value (str or list[str]) is empty,
    worldwide/anywhere, or names MENA, EMEA, the Middle East, GCC or any MENA country."""
```

### Country table (fill in completely)

| iso2 | name | currency | aliases (lowercase; include Arabic and French) | major cities (lowercase; include Arabic) |
|---|---|---|---|---|
| AE | United Arab Emirates | AED | uae, u.a.e, emirates, united arab emirates, émirats arabes unis, الإمارات | dubai, abu dhabi, sharjah, ajman, ras al khaimah, fujairah, al ain, دبي, أبوظبي, الشارقة |
| SA | Saudi Arabia | SAR | ksa, saudi, kingdom of saudi arabia, arabie saoudite, السعودية, المملكة العربية السعودية | riyadh, jeddah, dammam, khobar, al khobar, dhahran, mecca, makkah, medina, madinah, neom, tabuk, jubail, الرياض, جدة, الدمام, الخبر |
| QA | Qatar | QAR | qatar, قطر | doha, lusail, al rayyan, الدوحة |
| KW | Kuwait | KWD | kuwait, الكويت | kuwait city, hawalli, salmiya, ahmadi |
| BH | Bahrain | BHD | bahrain, البحرين | manama, muharraq, المنامة |
| OM | Oman | OMR | oman, sultanate of oman, عمان, سلطنة عمان | muscat, salalah, sohar, مسقط |
| EG | Egypt | EGP | egypt, égypte, egypte, مصر | cairo, giza, alexandria, new cairo, smart village, 6th of october, sheikh zayed, القاهرة, الجيزة, الإسكندرية |
| JO | Jordan | JOD | jordan, jordanie, الأردن | amman, irbid, zarqa, aqaba, عمّان |
| LB | Lebanon | LBP | lebanon, liban, لبنان | beirut, metn, jounieh, بيروت |
| PS | Palestine | ILS | palestine, palestinian territories, فلسطين | ramallah, nablus, gaza, رام الله |
| IQ | Iraq | IQD | iraq, العراق | baghdad, erbil, basra, بغداد |
| MA | Morocco | MAD | morocco, maroc, المغرب | casablanca, rabat, marrakech, tangier, tanger, fes, fès, agadir, الدار البيضاء |
| TN | Tunisia | TND | tunisia, tunisie, تونس | tunis, sfax, sousse, ariana, la marsa |
| DZ | Algeria | DZD | algeria, algérie, algerie, الجزائر | algiers, alger, oran, constantine |
| LY | Libya | LYD | libya, libye, ليبيا | tripoli, benghazi |

### Matching rules (these are where bugs come from)

- Lowercase the input first. For **Latin** tokens, match on letter boundaries: `(?<![a-z])token(?![a-z])`. This stops `oman` matching inside `woman` or `romania`. Precompile a single alternation regex, sorted longest-first so `abu dhabi` wins over `abu`.
- For **Arabic** tokens, plain substring match is fine (word boundaries do not apply to Arabic script).
- **Do not** put "emea", "middle east", "mena", "gcc" or "gulf" in `country_of`. They are not countries. `remote_ok_for_mena` handles them.
- Known ambiguity to test: "Jordan" can be a surname in a JD, but `country_of` only ever receives *location* strings, so it is acceptable. "Georgia" and "Tripoli, Lebanon" are out of scope.
- `MENA_LOCATION_HINTS` = every alias and city above, deduplicated. `infer_region` uses it (0.3).

### `nationals_only` patterns

These come from real postings seen during research, e.g. *"Assistant Manager - Credit Risk (UAE National)"* (Emirates NBD) and *"Associate Director, Education Sector - Emiratized Role"* (FAB).

```python
_NAT = r"(uae|emirati|saudi|qatari|kuwaiti|omani|bahraini)"
TITLE_PATTERNS = [
    rf"\b{_NAT}\s+nationals?\b",                       # "(UAE National)"
    r"\bemirati[sz](ed|ation)\b",                      # "Emiratized Role", "Emiratisation"
    r"\b(saudi|qatar|oman|bahrain|kuwait)i?[sz]ation\b",
    r"\bnationals?\s+only\b",
    r"للمواطنين|سعوديين فقط|للسعوديين|مواطن(ين)? فقط",
]
JD_PATTERNS = [  # JD text is noisier, so require an exclusivity word
    rf"\b(only|exclusively)\s+(for\s+)?{_NAT}\s+nationals?\b",
    rf"\bmust\s+be\s+(an?\s+)?{_NAT}\s+national\b",
    rf"\b{_NAT}\s+nationals?\s+only\b",
    r"للسعوديين فقط|للمواطنين فقط",
]
```

Check the title against `TITLE_PATTERNS` and the JD against `JD_PATTERNS`, with `re.I`. Only scan the first 3,000 characters of the JD, for speed.

### `remote_ok_for_mena`

The input is either a string or a list (Himalayas sends `locationRestrictions: ["United States"]`). Return True if any of these hold:
- the input is empty or `None`
- any value is in `{"worldwide", "anywhere", "global", "remote"}`
- any value contains "emea", "middle east", "mena", "gcc" or "gulf"
- any value satisfies `is_mena()`

### Tests: `apps/api/tests/test_geo_mena.py`

- `country_of("Dubai, United Arab Emirates") == "AE"`, `country_of("Riyadh") == "SA"`, `country_of("الرياض") == "SA"`, `country_of("Casablanca, Maroc") == "MA"`, `country_of("SA") == "SA"`, `country_of("Saudi Arabia, Riyadh") == "SA"`.
- `country_of("Woman's Health, London") is None`, `country_of("Romania") is None`, `country_of("Bangalore") is None`, `country_of("") is None`, `country_of(None) is None`.
- `same_country("Dubai", "Abu Dhabi, UAE")` is True. `same_country("Dubai", "Riyadh")` is False.
- `currency_for("Doha") == "QAR"`, and `currency_for("London", default="USD") == "USD"`.
- `annualize(10000, "MONTH") == 120000` and `annualize(None, "MONTH") is None`.
- `nationals_only("Assistant Manager - Credit Risk (UAE National)")` and `nationals_only("Associate Director - Emiratized Role")` are True. `nationals_only("Senior Backend Engineer", "We value Emirati culture")` is False.
- `remote_ok_for_mena([]) is True`, `remote_ok_for_mena(["United States"]) is False`, `remote_ok_for_mena(["EMEA"]) is True`, `remote_ok_for_mena("Saudi Arabia") is True`.

---

## 0.3 Region selection and inference

**File:** `apps/api/workers/job_discovery.py`

1. Import `VALID_REGIONS` from `models.job`, and `MENA_LOCATION_HINTS` and `MENA_DEFAULT_LOCATIONS` from `services.geo.mena`.
2. `select_sources`: replace `region = region if region in ("india", "global") else "india"` with `region = region if region in VALID_REGIONS else "india"`.
3. `infer_region`: keep India first, so mixed locations still prefer India (an existing test asserts this). Then check MENA, and only then fall back to global:

```python
    for loc in locations:
        low = loc.lower()
        if any(hint in low for hint in INDIA_LOCATION_HINTS):
            return "india"
    if any(mena.is_mena(loc) for loc in locations):
        return "mena"
    return "global"
```

   Use `is_mena()`, not a substring loop over `MENA_LOCATION_HINTS`, because it applies the word-boundary rules. Update the docstring.
4. `resolve_region`: accept `choice in VALID_REGIONS`.
5. **Search locations for a MENA run.** In `_discover_for_user_async`, the line `locations = [loc for loc in (preferred_locations or []) if loc] or ["India"]` must become a call to a new pure helper:

```python
def search_locations(region: str, preferred_locations: list[str] | None) -> list[str]:
    """Locations to fan a run out over.

    A MENA run for someone whose saved cities are Indian (explicit region
    override) must not search "Bangalore" on Gulf boards: keep only the MENA
    entries, else fall back to the MENA defaults. Other regions keep today's
    behaviour exactly.
    """
    locs = [loc for loc in (preferred_locations or []) if loc]
    if region == "mena":
        mena_locs = [loc for loc in locs if mena.is_mena(loc)]
        return mena_locs or list(settings.MENA_DEFAULT_LOCATIONS)
    return locs or ["India"]
```

6. Add `"mena"` to the `regions` set of **`linkedin` only** in `SOURCE_REGISTRY` in this phase. LinkedIn's public guest search already takes any location string. *Owner decision:* the research doc advises against scraping LinkedIn. The repo already does it for india and global, so this keeps parity. Drop `"mena"` from linkedin if you do not want it. Every other source gets `"mena"` in Phase 1 or 2 together with its MENA filtering logic. **Do not add `mena` to `ats` here**: the ATS scraper has no MENA location filter yet and would leak worldwide remote roles.

**File:** `apps/api/config.py`. Add to the discovery block:

```python
    # ── MENA region (docs/mena/) ──
    # Searched when a MENA run has no MENA city in preferred_locations.
    MENA_DEFAULT_LOCATIONS: Annotated[List[str], NoDecode] = [
        "United Arab Emirates", "Saudi Arabia", "Egypt", "Qatar",
    ]
    # Drop postings reserved for citizens (Emiratisation/Saudisation) before AI
    # scoring. They stay stored as prefiltered, so flipping this is replayable.
    MENA_EXCLUDE_NATIONALS_ONLY: bool = True
```

Reuse the comma-split `field_validator` pattern from `ALLOWED_ORIGINS` for `MENA_DEFAULT_LOCATIONS`. The module constant in `services/geo/mena.py` stays the documented default; `search_locations` reads `settings`.

**Files:** `apps/api/routers/jobs.py` and `apps/api/routers/telemetry.py`. These call `resolve_region` and need no logic change. Check that no literal `("india", "global")` tuple is left anywhere: `grep -rn '"india", "global")' apps/api --include=*.py`. Ignore the `regions = {...}` sets on scrapers.

### Tests: extend `apps/api/tests/test_source_selection.py`

Add these. Do **not** change existing assertions.
- `infer_region(["Dubai"]) == "mena"`, `infer_region(["Riyadh", "Cairo"]) == "mena"`, `infer_region(["Dubai", "Bangalore"]) == "india"`, `infer_region(["London"]) == "global"`.
- `resolve_region({"preferred_locations": ["Pune"], "discovery_region": "mena"}) == "mena"`.
- `select_sources("mena", [])` contains `linkedin` and no India-only sources (naukri, shine, ...).
- `search_locations("mena", ["Bangalore"]) == list(settings.MENA_DEFAULT_LOCATIONS)`, `search_locations("mena", ["Dubai", "Pune"]) == ["Dubai"]`, `search_locations("india", []) == ["India"]`.
- `DiscoveryRequest(region="mena").region == "mena"` and `DiscoveryRequest(region="mars").region == "india"`.

---

## 0.4 Unicode-safe dedup (**blocking bug, fix first**)

**Bug, reproduced 2026-10-17:**

```text
job_fingerprint('مهندس برمجيات', 'شركة علم')     -> '::'
job_fingerprint('محاسب', 'شركة علم')             -> '::'      <- different job, same key
job_fingerprint('Développeur Full-Stack', 'X')   -> 'd veloppeur full stack::x'
```

`services/dedup._NON_ALNUM = [^a-z0-9]+` deletes every non-ASCII letter. `job_pipeline` looks up existing listings by `dedupe_key`, and the DB has a **UNIQUE index** on `job_listings.dedupe_key` (`database/11_job_dedup.sql`). As a result, every Arabic-titled job is silently merged into the first Arabic job ever stored. French accents also split words.

### Fix in `apps/api/services/dedup.py`

```python
import unicodedata

# Arabic diacritics (tashkeel), superscript alef and tatweel: presentation
# only, and boards are inconsistent about including them.
_AR_MARKS = re.compile(r"[ً-ٰٟـ]")
_NON_WORD = re.compile(r"[\W_]+")   # Unicode-aware: keeps Arabic and accented letters


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", (text or "")).lower()
    text = _AR_MARKS.sub("", text)
    return " ".join(_NON_WORD.sub(" ", text).split())
```

- **Do not strip Latin accents** ("développeur" stays "développeur"). Postgres cannot match Python's accent folding without the `unaccent` extension, and the two implementations must agree (see the SQL below). For pure-ASCII input the output is **byte-for-byte identical** to today's, so existing India and global keys are unchanged. Add a test for this.
- Extend `_COMPANY_NOISE` with MENA legal suffixes. Write them as whole tokens *after* normalization (dots are already gone, so "W.L.L." arrives as "w l l"):

```python
_COMPANY_NOISE = re.compile(
    r"\b(private|pvt|ltd|limited|inc|incorporated|llc|llp|corp|corporation|co"
    r"|fz|fze|fzco|fzc|wll|w l l|spc|saog|saoc|sae|s a e|pjsc|psc|plc|sarl|s a r l|spa|sas|est"
    r"|شركة|مؤسسة|المحدودة|ذ م م)\b"
)
```

  Python's `\b` works with Arabic under `re` Unicode mode. Test it.
- Update the module docstring: "Keep in sync with job_dedupe_key() in database/17_mena_region.sql".

### SQL in migration 17 (see 0.8)

The SQL is only a fallback, because Python always sends `dedupe_key` (`job_pipeline.py:151`). It must still produce the same keys for parity:

```sql
CREATE OR REPLACE FUNCTION public.job_dedupe_key(p_title TEXT, p_company TEXT)
RETURNS TEXT LANGUAGE sql IMMUTABLE AS $$
  WITH norm AS (
    SELECT
      trim(regexp_replace(regexp_replace(regexp_replace(lower(normalize(coalesce(p_title, ''), NFKC)),
        '[ً-ٰٟـ]', '', 'g'),
        '[^[:alnum:]]+', ' ', 'g'), '\s+', ' ', 'g')) AS t,
      trim(regexp_replace(regexp_replace(regexp_replace(lower(normalize(coalesce(p_company, ''), NFKC)),
        '[ً-ٰٟـ]', '', 'g'),
        '[^[:alnum:]]+', ' ', 'g'), '\s+', ' ', 'g')) AS c
  )
  SELECT t || '::' || coalesce(
    nullif(trim(regexp_replace(regexp_replace(c,
      '\m(private|pvt|ltd|limited|inc|incorporated|llc|llp|corp|corporation|co|fz|fze|fzco|fzc|wll|w l l|spc|saog|saoc|sae|s a e|pjsc|psc|plc|sarl|s a r l|spa|sas|est|شركة|مؤسسة|المحدودة|ذ م م)\M',
      ' ', 'g'), '\s+', ' ', 'g')), ''),
    c)
  FROM norm
$$;
```

`normalize(text, NFKC)` needs PostgreSQL 13 or later, which Supabase has. `[[:alnum:]]` depends on the DB ctype, and Supabase uses `en_US.UTF-8`. Verify with `SELECT public.job_dedupe_key('مهندس برمجيات','شركة علم');`, which must return `مهندس برمجيات::علم`. **Do not backfill existing rows.** ASCII *title* normalization is unchanged, and recomputing the few non-ASCII keys could collide on the unique index. The one intended change for ASCII data is that companies ending in a new noise token ("… PLC", "… PJSC", "… SPA") now drop it. An already-stored listing for such a company can therefore be re-inserted once under the new key, which is a harmless one-off duplicate.

### Tests: extend `apps/api/tests/test_dedup.py`

- The two Arabic titles above give **different** fingerprints, and neither starts with `::`.
- `job_fingerprint("مُهندس برمجيات", "علم") == job_fingerprint("مهندس برمجيات", "علم")` (diacritics are ignored).
- `normalize_company("Careem Networks FZ-LLC") == "careem networks"`, `normalize_company("Gulf Bank W.L.L.") == "gulf bank"`, `normalize_company("شركة علم") == "علم"`.
- **Regression:** for a list of ~10 existing ASCII cases (copy them from the current tests), the output equals the old normalization. Hard-code the expected strings.

---

## 0.5 Prefilter: French and Arabic tech vocabulary and the nationals-only filter

**File:** `apps/api/services/prefilter.py`

1. Add to `TECH_ROLE_WORDS`. Matching is substring-on-lowercased-title, so the French entries cover their accented variants too:
   - French: `"développeur", "developpeur", "ingénieur logiciel", "ingenieur logiciel", "informatique", "logiciel", "programmeur", "devops", "données", "cybersécurité"`
   - Arabic: `"مطور", "مبرمج", "مهندس برمجيات", "برمجة", "تقنية المعلومات", "تطوير", "أمن المعلومات", "علم البيانات"`

   Bare `"ingénieur"` and `"مهندس"` (engineer) are deliberately left out. English already has `"engineer"`, which lets civil engineers through, and the Gulf boards are dominated by construction "ingénieur/مهندس" roles. Recall stays fine because the user's own skills still match the JD.
2. In `rejected_indices` (and `prefilter_jobs`, for parity), also reject a job when `settings.MENA_EXCLUDE_NATIONALS_ONLY and mena.nationals_only(job.title, job.jd_text)`. Keep the early `if not keywords: return set()` behaviour **only for the keyword check**. The nationals check must run even when the user has no keywords. Restructure the function like this:

```python
def rejected_indices(jobs: list, user: dict) -> set[int]:
    keywords = build_user_keywords(user)
    out: set[int] = set()
    for i, job in enumerate(jobs):
        if keywords and not is_relevant(job, keywords):
            out.add(i)
        elif _nationals_blocked(job):
            out.add(i)
    return out
```

   `_nationals_blocked` imports `settings` lazily, so tests can monkeypatch it.

### Tests: extend `apps/api/tests/test_prefilter.py`

- A job titled "Développeur Full Stack" passes with user skills `["react"]` and a JD that does not mention react.
- "مطور برمجيات" passes. "Ingénieur génie civil" with an off-profile JD is rejected.
- "Software Engineer (UAE National)" is rejected even when it matches the user's skills, and is kept when `MENA_EXCLUDE_NATIONALS_ONLY=False`.
- An empty-keyword user still gets nationals-only jobs rejected.

---

## 0.6 Shared scraper helpers

**File:** `apps/api/scrapers/api_base.py`. Add a text GET next to `_get_json`, with the same contract (rate-limited, returns None on failure, never raises):

```python
    async def _get_text(self, url: str, params: Optional[dict] = None, headers: Optional[dict] = None) -> Optional[str]:
        """Rate-limited GET returning the body text (HTML/XML), or None on failure.

        A Cloudflare/bot-wall challenge counts as failure: MENA boards that wall
        plain HTTP are partnership-only (docs/mena/README.md §5), never bypassed.
        """
        await self.rate_limiter.acquire()
        try:
            resp = await self._client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            text = resp.text
            if "cf-chl" in text or "challenge-platform" in text:
                logger.warning(f"[{self.platform.value}] {url} served a bot challenge — skipping")
                return None
            return text
        except Exception as e:
            logger.warning(f"[{self.platform.value}] GET {url} failed: {e}")
            return None
```

`DEFAULT_HEADERS` sends `Accept: application/json`, so HTML callers must pass `headers={"Accept": "text/html,application/xhtml+xml"}`.

**File:** `apps/api/scrapers/jsonld.py`. Split `parse_job_posting` so that an already-parsed JobPosting dict can be mapped. Teamtailor's feed (Phase 1) gives us the dict directly.

```python
def map_job_posting(posting: dict) -> dict:
    """Map an already-parsed schema.org JobPosting dict to job-model fields."""
    ...  # the current body of parse_job_posting, from `org = ...` onward

def parse_job_posting(html: str) -> Optional[dict]:
    posting = find_job_posting(html)
    return map_job_posting(posting) if posting else None
```

While you are in this file:
- `_location_str` must also accept `addressCountry` given as an ISO-2 string, which is already handled as `str`.
- Add `"CDI": JobType.full_time, "CDD": JobType.contract, "STAGE": JobType.internship, "FREELANCE": JobType.freelance` to `_EMPLOYMENT_TYPES`. ReKrute sends `"employmentType": "CDI"`.
- `_salary` should also return `unitText` (`value.unitText` or `base.unitText`) so callers can `annualize`. Change the return to a 4-tuple, update `map_job_posting`, and add `"salary_unit"` to its output dict (callers pop it before building `JobListingCreate`). Update `tests/test_jsonld.py` if it unpacks `_salary`.
- `_parse_date` must also accept `"2026-10-15 14:30:02"` (space separator, as ReKrute sends it). `fromisoformat` handles that on Python 3.11+, but the venv is **3.10**, so normalize with `.replace(" ", "T", 1)` when the value has no `T`.

Tests: `map_job_posting` on a dict fixture, CDI mapping, the space-separated date, and `salary_unit` passthrough.

---

## 0.7 AI prompt currency and frontend salary display

**File:** `apps/api/services/ai/job_analysis.py`. In the JD-parse prompt, change `"salary_currency": "INR|USD|GBP|EUR"` to `"INR|USD|GBP|EUR|AED|SAR|QAR|KWD|BHD|OMR|EGP|JOD|MAD|TND|DZD"`. Add one line to the prompt: *"Report salaries as annual amounts; if the JD states a monthly figure multiply by 12."*

**File:** `apps/web/src/lib/utils.ts`. `formatSalary` currently renders every non-INR currency as `$…K`, so 15,000 AED would show as "$15K". Change it to:

```ts
export function formatSalary(min?: number, max?: number, currency = "INR"): string {
  if (!min && !max) return "Salary not disclosed";
  const fmt = (n: number) => {
    if (currency === "INR") return `₹${(n / 100000).toFixed(1)}L`;
    const k = `${Math.round(n / 1000)}K`;
    return currency === "USD" ? `$${k}` : `${currency} ${k}`;
  };
  ...rest unchanged
}
```

---

## 0.8 Database migration `database/17_mena_region.sql`

Create it idempotent, with a header in the style of `15_global_sources.sql`:

1. Widen the region check:

```sql
ALTER TABLE public.users DROP CONSTRAINT IF EXISTS users_discovery_region_check;
ALTER TABLE public.users
  ADD CONSTRAINT users_discovery_region_check
  CHECK (discovery_region IS NULL OR discovery_region IN ('india', 'global', 'mena'));
COMMENT ON COLUMN public.users.discovery_region IS
  'Explicit discovery region: india | global | mena. NULL infers from preferred_locations.';
```

2. Replace `job_dedupe_key()` with the SQL from 0.4 (`CREATE OR REPLACE`; the trigger is unchanged).
3. **No platform enum values in this file.** Each phase adds its own enum migration (18, 19, ...).

Also append migration 17 to `database/PENDING_MIGRATIONS_BUNDLE.sql` if that file is kept current (check its header first).

---

## 0.9 Frontend: MENA region option

**Files:** `apps/web/src/components/dashboard/dashboard-client.tsx` and `apps/web/src/components/activity/activity-client.tsx`

- `type Region = "india" | "global" | "mena";`
- Dashboard toggle: add a third button, labelled **"MENA"**, after "Global", with the same classes. Toast text: `region === "india" ? "Searching the Indian job market." : region === "mena" ? "Searching the Middle East & North Africa." : "Searching globally."`
- Activity page: change `(["india", "global"] as Region[])` to `(["india", "global", "mena"] as Region[])`. If the button label renders `r` raw, map it through `{ india: "India", global: "Global", mena: "MENA" }[r]`.

**Optional, recommended:** a saved preference in `apps/web/src/components/settings/settings-client.tsx`. Add a "Discovery region" `<select>` with these options: Auto (`null`), India, Global, MENA. It is bound to `discovery_region` and saved through the existing profile update call. Read how `preferred_locations` is saved in that file and do the same. Check that `routers/profile.py` passes `discovery_region` through; `ProfileBase` already declares it.

---

## 0.10 Acceptance checklist

- [ ] `pytest tests -q` (from `apps/api`) passes, including the new geo, dedup, prefilter, jsonld and source-selection tests.
- [ ] Migration 17 applied in Supabase, and `SELECT public.job_dedupe_key('مهندس برمجيات','شركة علم')` returns `مهندس برمجيات::علم`.
- [ ] A manual MENA run from the dashboard shows `region=mena` on the Activity page and searches LinkedIn for "United Arab Emirates" (or for your saved MENA cities).
- [ ] An India run is unchanged: same sources and same locations as before.
- [ ] `npm run build` in `apps/web` succeeds (TypeScript union changes).
