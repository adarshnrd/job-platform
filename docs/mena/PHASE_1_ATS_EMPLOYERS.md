# Phase 1: ATS and Direct-Employer Coverage for MENA

> **Goal:** the existing ATS aggregator (`scrapers/ats.py`) serves the `mena` region. It gets verified MENA employer boards, plus four new keyless ATS vendors that the large Gulf employers actually use: **Oracle HCM Candidate Experience, Workday CXS, BambooHR and Teamtailor**.
> **Depends on:** Phase 0 merged (`services/geo/mena.py`, `VALID_REGIONS`, `jsonld.map_job_posting`).
> **Estimated size:** 2 PRs. PR-A covers 1.1–1.3 (region-aware loading and MENA seeds on existing vendors). PR-B covers 1.4–1.8 (new vendors, harvester, detector script).
> **Why this is the highest-value phase:** these are canonical employer postings. They have stable JSON, no bot walls and few duplicates, and they are the compliant core recommended by the research doc. Every endpoint below was called live on 2026-10-17 (see README §3.1).

---

## 1.1 Region-scoped board loading

**File:** `apps/api/scrapers/ats.py`

Today `_ensure_loaded()` fetches **every** board on every run and caches the result unfiltered. With MENA boards added, India runs would also pull DP World's 559 jobs and Delivery Hero's 940. Scope the loading by region instead.

1. Every board dict may now carry an optional `"regions"` tuple. Boards without it (all current `SEED_BOARDS`) are treated as `("india", "global")`. Harvested boards (no tag) are treated as serving **all** regions, since we cannot tell.
2. Change `_boards()` to `_boards(region: str)`. It returns the seeds whose `regions` contain `region`, plus all harvested boards, deduped by `(ats, token)` exactly as today.
3. Change `_ensure_loaded()` to `_ensure_loaded(region)`. The scraper instance lives for one run and one run has one region, so the cache stays valid. Keep the `_all_jobs is not None` short-circuit.
4. Pass `region` into `_fetch_board(board, region)` so vendors with expensive detail calls (SmartRecruiters, Oracle, Workday, BambooHR) can pre-filter to the run's region **before** fetching details.
5. Add the tag `"regions": ("india", "global", "mena")` to the existing `elastic` seed. It has about 15 MENA roles, verified. Leave the other existing seeds as they are.

---

## 1.2 MENA seed boards on the existing vendors

Add this list below `SEED_BOARDS` and include it in `_boards()`. Every token was verified live (README §3.1). `default_location` replaces the hard-coded `"India"` fallback in the `_norm_*` functions (see 1.3).

```python
# Verified live 2026-10-17 (docs/mena/README.md §3.1). MENA-region boards.
MENA_SEED_BOARDS: list[dict] = [
    # ── Greenhouse ──
    {"ats": "greenhouse", "token": "tamara",  "company": "Tamara",  "regions": ("mena", "global"), "default_location": "Riyadh, Saudi Arabia"},
    {"ats": "greenhouse", "token": "careem",  "company": "Careem",  "regions": ("mena", "global"), "default_location": "Dubai, United Arab Emirates"},
    {"ats": "greenhouse", "token": "binance", "company": "Binance", "regions": ("mena", "global")},
    # ── Ashby ──
    {"ats": "ashby", "token": "ziina",    "company": "Ziina",             "regions": ("mena", "global"), "default_location": "Dubai, United Arab Emirates"},
    {"ats": "ashby", "token": "thndr",    "company": "Thndr",             "regions": ("mena", "global"), "default_location": "Cairo, Egypt"},
    {"ats": "ashby", "token": "LeanTech", "company": "Lean Technologies", "regions": ("mena", "global"), "default_location": "Riyadh, Saudi Arabia"},
    # ── Workable ──
    {"ats": "workable", "token": "salla",       "company": "Salla",       "regions": ("mena", "global"), "default_location": "Saudi Arabia"},
    {"ats": "workable", "token": "foodics",     "company": "Foodics",     "regions": ("mena", "global"), "default_location": "Riyadh, Saudi Arabia"},
    {"ats": "workable", "token": "progressoft", "company": "ProgressSoft", "regions": ("mena", "global"), "default_location": "Amman, Jordan"},
    # ── SmartRecruiters ──
    {"ats": "smartrecruiters", "token": "deliveryhero",   "company": "Delivery Hero / talabat", "regions": ("mena",)},
    {"ats": "smartrecruiters", "token": "EtihadAirways5", "company": "Etihad Airways",          "regions": ("mena",), "default_location": "Abu Dhabi, United Arab Emirates"},  # gitleaks:allow
    # ── Oracle HCM (1.4) ──
    {"ats": "oracle_hcm", "token": "dpworld",     "company": "DP World",
     "host": "ehpv.fa.em2.oraclecloud.com", "site": "CX_1", "regions": ("mena",)},
    {"ats": "oracle_hcm", "token": "emiratesnbd", "company": "Emirates NBD",
     "host": "fa-evlo-saasfaprod1.fa.ocs.oraclecloud.com", "site": "CX_1", "regions": ("mena",)},
    {"ats": "oracle_hcm", "token": "fab",         "company": "First Abu Dhabi Bank",
     "host": "ehjd.fa.em2.oraclecloud.com", "site": "fabCareers", "regions": ("mena",)},
    # ── Workday (1.5) ──
    {"ats": "workday", "token": "murex", "company": "Murex",
     "host": "murex.wd3.myworkdayjobs.com", "tenant": "murex", "site": "MurexCareerPage1", "regions": ("mena", "global")},
    # ── BambooHR (1.6) ──
    {"ats": "bamboohr", "token": "toters",   "company": "Toters",   "regions": ("mena",), "default_location": "Beirut, Lebanon"},
    {"ats": "bamboohr", "token": "instabug", "company": "Instabug", "regions": ("mena", "global")},
    # ── Teamtailor (1.7) ──
    {"ats": "teamtailor", "token": "careers.chalhoubgroup.com", "company": "Chalhoub Group", "regions": ("mena",), "default_location": "Dubai, United Arab Emirates"},
]
```

Things to check while implementing:
- **Ashby token case.** `LeanTech` worked and `lean` did not. The harvester lowercases every token (`ats_harvester.extract_tokens`), so test whether `api.ashbyhq.com/posting-api/job-board/leantech` also works. If it does not, stop lowercasing Ashby, Workday and Teamtailor tokens in the harvester (see 1.8).
- **Lever `kitopi`** returned 404 although kitopi.com links to `jobs.lever.co/kitopi/`. Try `Kitopi` and the EU host `api.eu.lever.co/v0/postings/kitopi`. If one works, add it, and add EU-host support to the lever branch in `_fetch_board` and `_validate` (`"host": "api.eu.lever.co"` on the board).
- `known_pairs()` in `services/ats_harvester.py` must include `MENA_SEED_BOARDS`, so the harvester does not re-validate them.

---

## 1.3 Region filtering, location defaults and currency in `search_jobs`

**File:** `apps/api/scrapers/ats.py`

### Location defaults

Every `_norm_<ats>(j, company)` ends with `"location": loc or "India"`. Change the signature to `_norm_<ats>(j, company, default_loc="India")` and use `loc or default_loc`. `_fetch_board` passes `board.get("default_location", "India")`. Existing seeds therefore behave exactly as before, and `tests/test_ats_scraper.py` calls without the argument and keeps passing.

### SmartRecruiters for MENA

`_fetch_smartrecruiters` always sends `country=in`. Make the country depend on the region:

```python
_SR_COUNTRIES = {
    "india": ("in",),
    "global": ("in",),   # unchanged legacy behaviour — do not alter global here
    "mena": ("ae", "sa", "eg", "qa", "kw", "bh", "om", "jo", "ma"),
}
```

- For each country, make **one** list call (`limit=100`) and merge the results, deduped by posting id.
- **Before the detail calls**, sort the items so tech titles come first. Use `services.prefilter.TECH_ROLE_WORDS` as a substring test on `it["name"].lower()`. Then apply `_SR_DETAIL_CAP` (12) **per board**, not per country.
- `_sr_location`: replace `"India" if country == "in" else country` with `"India" if country == "in" else (mena.MENA_COUNTRIES.get(country.upper(), {}).get("name") or country.upper())`, so you get e.g. `"Dubai, United Arab Emirates"`.

### Region filter

Add this to the loop in `search_jobs`:

```python
            if region == "india" and not self._is_india(job):
                continue
            if region == "mena" and not self._is_mena(job):
                continue
```

```python
    @staticmethod
    def _is_mena(job: dict) -> bool:
        loc = job.get("location") or ""
        if mena.is_mena(loc):
            return True
        # Remote roles qualify only when explicitly open to the region.
        low = loc.lower()
        return bool(job.get("remote")) and any(t in low for t in ("emea", "middle east", "mena", "gcc"))
```

### Location match for MENA

`_location_ok` currently has India-specific logic. Add a MENA branch before it. Search locations for a MENA run are country names or MENA cities (Phase 0 `search_locations`), so match on **country**, not on city substring:

```python
    @staticmethod
    def _location_ok(job, loc_low, want_any_india, region="india"):
        if region == "mena":
            # "United Arab Emirates" should match a "Dubai" job and vice versa.
            # Location not resolvable to a MENA country → don't narrow further.
            return mena.same_country(job.get("location"), loc_low) or not mena.is_mena(loc_low)
        ...existing body unchanged...
```

Pass `region=region` from `search_jobs`.

### Currency

In `_to_listing`, set `salary_currency=mena.currency_for(job["location"]) or "INR"`. This keeps INR for everything that is not MENA (today's behaviour) and gives AED, SAR, etc. for MENA jobs.

### Registry

**File:** `apps/api/workers/job_discovery.py`. The `ats` entry becomes `Source("ats", ATSAggregatorScraper, True, False, {"india", "global", "mena"})`. Set `regions = {"india", "global", "mena"}` on the class too.

### Tests: extend `tests/test_ats_scraper.py`

- Preload `s._all_jobs` with normalized dicts for locations "Riyadh, Saudi Arabia", "Dubai", "Remote", "Remote - EMEA" and "Bengaluru". `search_jobs("engineer", location="Saudi Arabia", region="mena")` must return only the Riyadh job. `location="United Arab Emirates"` returns Dubai and Remote-EMEA. `region="india"` returns only Bengaluru.
- `_boards("india")` contains `postman` and not `tamara`. `_boards("mena")` contains `tamara` and `elastic` and not `postman`.
- A MENA job's listing has `salary_currency == "SAR"`.

---

## 1.4 New vendor: Oracle HCM Candidate Experience (`oracle_hcm`)

This is the public REST API behind every `…/hcmUI/CandidateExperience/en/sites/<site>` careers page. It needs no key. Verified: DP World (559 jobs), FAB (116) and Emirates NBD (31). ROSHN is blocked by Oracle's WAF ("W4S-101"); skip such boards.

**List** (verified):

```text
GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions
    ?onlyData=true
    &expand=requisitionList.secondaryLocations
    &finder=findReqs;siteNumber={site},limit=25,offset={n},sortBy=POSTING_DATES_DESC
```

`limit=25` was verified. Before committing to paging, check that `offset=25` returns the next page and that `limit=100` is accepted. Fetch at most `_ORACLE_MAX_JOBS = 200` per board.

Response: `items[0].TotalJobsCount`, `items[0].requisitionList[]`. Fields seen on each requisition: `Id, Title, PostedDate (YYYY-MM-DD), PostingEndDate, PrimaryLocation ("Dubai, United Arab Emirates"), PrimaryLocationCountry ("AE"), WorkplaceType, WorkplaceTypeCode, JobFamily, JobFunction, ContractType, JobType, ShortDescriptionStr, ExternalResponsibilitiesStr, ExternalQualificationsStr, secondaryLocations[]`.

**Detail** (verified, 200; `ExternalDescriptionStr` was about 4.9k chars):

```text
GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails
    ?expand=all&onlyData=true&finder=ById;Id="{Id}",siteNumber={site}
```

The quotes around the Id are literal. Read `items[0].ExternalDescriptionStr`, `ExternalResponsibilitiesStr` and `ExternalQualificationsStr`.

> ⚠ The detail payload contains **`ExternalContactName`, `ExternalContactEmail` and `HiringManager`**. Never copy these into the job dict (README §5.2, PDPL).

**Public job URL:** `https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{Id}`

**Implementation (`_fetch_oracle(board, region)`):**
1. Page through the list until `_ORACLE_MAX_JOBS`, or until a page is empty.
2. If `region == "mena"`, keep only requisitions where `mena.is_mena(PrimaryLocation)` or a `secondaryLocations[].Name` is MENA. If `region == "india"`, use `_is_india` on the location string.
3. JD = strip HTML of `ShortDescriptionStr + ExternalResponsibilitiesStr + ExternalQualificationsStr`. If that is shorter than 300 chars, fetch the detail, prioritising tech titles (`TECH_ROLE_WORDS`) and capped at `_ORACLE_DETAIL_CAP = 12` per board.
4. Normalize to the common dict: `title, company, location=PrimaryLocation or default_loc, source_url=apply_url=public URL, jd_text, posted_at=_parse_iso(PostedDate), remote="remote" in (WorkplaceType or "").lower()`.

**Harvester pattern:**

```python
("oracle_hcm", re.compile(r"https?://([a-z0-9.-]+\.oraclecloud\.com)/hcmUI/CandidateExperience/[a-z]{2}(?:-[A-Z]{2})?/sites/([A-Za-z0-9_]+)", re.I)),
```

This has **two** groups. See 1.8 for how composite tokens are stored.

**Validate:** list call with `limit=1`. Valid if it returns 200 and `TotalJobsCount > 0`. Company: board-supplied, else `_titlecase(host.split(".")[0])`, which will be ugly ("Ehpv"). Log it so a human can rename it later.

---

## 1.5 New vendor: Workday CXS (`workday`)

This is the JSON API behind every `*.myworkdayjobs.com` careers site. It needs no key. Verified on Murex (45 jobs, Beirut).

**List** (verified):

```text
POST https://{host}/wday/cxs/{tenant}/{site}/jobs
Content-Type: application/json
{"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}
```

- `limit` max is **20** (Workday rejects larger values). Page with `offset` up to `_WD_MAX_JOBS = 100`.
- Response: `total`, `jobPostings[]` with `title, externalPath ("/job/Beirut/Software-Engineer--Java-_JR_SF22936"), locationsText ("Beirut" or "2 Locations"), postedOn ("Posted Today" / "Posted Yesterday" / "Posted 18 Days Ago" / "Posted 30+ Days Ago"), bulletFields[]`. It also returns `facets[]`; the `facetParameter` values seen were `jobFamilyGroup, timeType, workerSubType, locationMainGroup`.
- Use `self._post_json`. It already rate-limits and swallows errors.

**Detail** (verified):

```text
GET https://{host}/wday/cxs/{tenant}/{site}{externalPath}
```

Read `jobPostingInfo`: `title, jobDescription (HTML), location, country, startDate (ISO), timeType, jobReqId, externalUrl, jobRequisitionLocation`.

**Implementation (`_fetch_workday(board, region)`):**
1. Page through the list.
2. Region pre-filter on `locationsText`. Keep it if it is MENA (for mena) or India (for india), or if it matches `r"^\d+ Locations$"` (ambiguous, so resolve via detail). For `global`, keep all.
3. Fetch the detail for kept postings, tech titles first, capped at `_WD_DETAIL_CAP = 15` per board. After the detail, re-check the region against `jobPostingInfo.location` (and `country.descriptor` if present) and drop anything outside it.
4. `source_url = apply_url = jobPostingInfo.externalUrl or f"https://{host}/{site}{externalPath}"`.
5. `posted_at`: prefer `startDate`. Otherwise parse `postedOn` with a small helper:

```python
def _parse_workday_posted(text: str) -> Optional[datetime]:
    low = (text or "").lower()
    now = datetime.utcnow()
    if "today" in low:
        return now
    if "yesterday" in low:
        return now - timedelta(days=1)
    m = re.search(r"(\d+)\+?\s*day", low)   # "18 Days Ago", "30+ Days Ago"
    return now - timedelta(days=int(m.group(1))) if m else None
```

   `BaseScraper.parse_relative_date` does **not** handle "30+ Days", which is why this helper exists.

**Harvester pattern** (keep the site's case):

```python
("workday", re.compile(r"https?://(([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com)/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)", re.I)),
```

Groups: host, tenant, site. Skip site values `wday`, `job` and `jobs`.

**Validate:** list POST with `limit=1`. Valid if it returns 200 and `total > 0`.

---

## 1.6 New vendor: BambooHR (`bamboohr`)

Verified on Toters (63 jobs) and Instabug (2).

**List:** `GET https://{token}.bamboohr.com/careers/list` returns `{"meta": {"totalCount": N}, "result": [...]}`. Each item has `id ("59"), jobOpeningName, departmentLabel, employmentStatusLabel ("Full-Time"), location {city, state}, atsLocation {country, state, province, city}, isRemote, locationType`.

**Detail:** `GET https://{token}.bamboohr.com/careers/{id}/detail` returns `result.jobOpening` with `jobOpeningShareUrl, jobOpeningName, jobOpeningStatus, departmentLabel, employmentStatusLabel, location {city, state, postalCode, addressCountry}, description (HTML), compensation, datePosted ("2022-05-25"), minimumExperience, locationType`.

**Implementation:**
1. List location = `", ".join(p for p in (city, state, atsLocation.country) if p)`. The list often has no country.
2. Region pre-filter. Keep an item if it matches the region, or if its location cannot be resolved at all (resolve via detail). Use `default_location` only when the list location is completely empty.
3. Fetch the detail for kept items, tech titles first, capped at `_BAMBOO_DETAIL_CAP = 15`. Final location = `"{city}, {addressCountry}"`. Re-check the region.
4. Skip anything with `jobOpeningStatus != "Open"`.
5. `source_url = apply_url = jobOpeningShareUrl or f"https://{token}.bamboohr.com/careers/{id}"`. Set `posted_at = _parse_iso(datePosted)` and `remote = str(isRemote).lower() == "true" or locationType == "1"`. Verify what `locationType` means on a known-remote job before relying on it; otherwise use `isRemote` only.

**Harvester pattern:** `("bamboohr", re.compile(r"https?://([a-z0-9-]+)\.bamboohr\.com/(?:careers|jobs)", re.I))`. Add `"resources"` and `"www"` to `_TOKEN_BLOCKLIST`.

**Validate:** list call. Valid if it returns 200 and `meta.totalCount > 0`.

---

## 1.7 New vendor: Teamtailor public feed (`teamtailor`)

The research doc says Teamtailor needs a key. That is true for its REST API, but every career site also publishes **`/jobs.json`** (JSON Feed 1.1) and `/jobs.rss` with no key. Verified on `careers.chalhoubgroup.com` (100 items per page, `next_url` for paging).

**Feed:** `GET https://{token}/jobs.json`, where `token` is the career-site host. Feed keys: `version, title, home_page_url, feed_url, next_url, items[]`. Item keys: `id, title, url, date_published (ISO with offset), content_html, _jobposting`. `_jobposting` is a full schema.org JobPosting **dict**; handle a JSON string too with `json.loads` when `isinstance(str)`.

**Implementation:**
1. Follow `next_url` for at most 5 pages.
2. For each item, `fields = jsonld.map_job_posting(item["_jobposting"])` (added in Phase 0), with fallbacks `title = item["title"]`, `jd_text = strip_html(item["content_html"])` and `posted_at = _parse_iso(item["date_published"])`.
3. `location = fields.get("location") or default_loc`. Region filter as usual. `source_url = apply_url = item["url"]`.
4. Drop the `salary_unit` key from `fields`, or use it with `mena.annualize` if salary is present.

**Harvester pattern:** `("teamtailor", re.compile(r"https?://([a-z0-9-]+\.teamtailor\.com)", re.I))`, where the token is the full host. Custom domains (like Chalhoub's) come only from seeds or from the detector script (1.9). Blocklist `www.teamtailor.com` and `app.teamtailor.com`.

**Validate:** `GET https://{host}/jobs.json`. Valid if it returns 200 and `items` is non-empty. Company comes from feed `title`, with " - Jobs"/"Career" suffixes stripped.

---

## 1.8 Harvester changes for composite tokens

**File:** `apps/api/services/ats_harvester.py`

Today every pattern has one group and `extract_tokens` returns `(ats, token.lower())`. The new vendors need more parts and case-sensitive values.

1. Change `extract_tokens` to return `set[tuple[str, str]]`, where the token is a **canonical composite string**:
   - oracle_hcm: `f"{host}|{site}"`
   - workday: `f"{host}|{tenant}|{site}"`
   - teamtailor: `host`
   - everything else: unchanged

   Lowercase only the hosts. Keep the case of `site` for oracle and workday, and keep Ashby's case if 1.2's check shows it matters.
2. Add `board_from_pair(ats, token) -> dict`, which expands a composite token into the board dict fields (`host`, `site`, `tenant`). `harvest_urls` uses it when it appends to `added`, so stored boards look exactly like seeds.
3. `_fetch_board` in `scrapers/ats.py` reads `board.get("host")` and the other parts. If they are missing (an old store), it parses them from `token` with the same split. Put the split function in `ats_harvester.py` and import it, so the format is defined in one place.
4. Add `_validate` branches for the four vendors (described in 1.4–1.7).
5. Existing harvested entries (single-part tokens) keep working unchanged.

### Tests: extend `tests/test_ats_harvester.py`

- `extract_tokens("https://ehpv.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs")` returns `{("oracle_hcm", "ehpv.fa.em2.oraclecloud.com|CX_1")}`.
- `extract_tokens("https://murex.wd3.myworkdayjobs.com/en-US/MurexCareerPage1/job/Beirut/X_JR1")` returns `{("workday", "murex.wd3.myworkdayjobs.com|murex|MurexCareerPage1")}`.
- `extract_tokens("https://toters.bamboohr.com/careers/59")` returns `{("bamboohr", "toters")}`. `https://resources.bamboohr.com/x` returns nothing.
- `extract_tokens("https://acme.teamtailor.com/jobs/123-x")` returns `{("teamtailor", "acme.teamtailor.com")}`.
- `board_from_pair` round-trips each composite.

---

## 1.9 ATS detector script (grows the employer registry without Opus)

**New file:** `scripts/detect_ats.py`. This is a CLI that turns a list of employer careers URLs into ready-to-paste board dicts. It is how the 300-employer registry from the research doc gets built cheaply.

Behaviour:
1. Input is a text file with one `name,url` pair per line (`--in employers.csv`). Fetch each URL with a browser UA, `follow_redirects`, a 25s timeout and concurrency 10.
2. Run `services.ats_harvester.extract_tokens` over the final URL **and** every absolute URL found in the HTML (regex `https?://[^"' <>]+`).
3. Also detect vendors we cannot ingest yet, and print them as `UNSUPPORTED <vendor>`:

| Vendor | Signature in the HTML |
|---|---|
| successfactors | `sapsf.com`, `successfactors` |
| taleo | `taleo.net`, `/careersection/` |
| avature | `avature.net` |
| phenom | `phenompeople`, `/global/en/search-results` |
| icims | `icims.com` |
| eightfold | `eightfold.ai` |
| zoho | `zohorecruit` |

4. For each supported pair, call `_validate` and print a dict line in the `MENA_SEED_BOARDS` format, with `company` from the CSV, `regions=("mena",)` and the total job count as a comment.
5. Print a summary: supported/valid, unsupported by vendor, and blocked (403/WAF/timeout).

Run it with the project venv (`apps/api/venv/Scripts/python.exe scripts/detect_ats.py --in employers.csv`). Add `apps/api` to `sys.path` at the top of the script so `services.*` imports resolve.

### Seed input for the first run

Save this as `docs/mena/employers_seed.csv`. It contains the research doc's target employers that were **not** resolved during research; for the resolved ones, see 1.2. Several URLs below returned 403, 404 or a timeout from plain HTTP during research. Let the script report them and fix the URLs by hand if needed.

```text
noon,https://careers.noon.com/
talabat,https://careers.deliveryhero.com/talabat
tabby,https://tabby.ai/en-AE/careers
propertyfinder,https://www.propertyfinder.ae/en/careers
dubizzle,https://careers.dubizzlegroup.com/
e&,https://www.eand.com/en/careers.html
du,https://www.du.ae/about-us/careers
wio,https://wio.io/careers
mubadala,https://www.mubadala.com/en/careers
presight,https://www.presight.ai/
stc,https://www.stc.com.sa/
elm,https://elm.sa/
neom,https://www.neom.com/en-us/be-part-of-neom/work-at-neom
unifonic,https://www.unifonic.com/en/careers
sabic,https://www.sabic.com/en/careers
qf,https://www.qf.org.qa/careers
vodafone_qa,https://www.vodafone.qa/en/about-us/careers
nbk,https://www.nbk.com/kuwait/careers.html
agility,https://agility.com/careers/
beyon,https://beyon.com/careers/
paymob,https://paymob.com/en/careers
sumerge,https://www.sumerge.com/careers
giza_systems,https://www.gizasystems.com/careers/
vermeg,https://www.vermeg.com/careers/
instadeep,https://instadeep.com/about-us/careers/
sqli,https://www.sqli.com/int-en/careers
```

**Known ATS for later phases** (do not ingest in Phase 1): Core42 and solutions by stc use SuccessFactors; Emirates Group uses Avature; Qatar Airways uses Taleo and Avature; G42 uses Phenom. These are in Phase 3.

---

## 1.10 Fixtures and tests

Capture fixtures once, then keep tests offline. Trim each fixture to 3 items, and **delete contact or person fields** (Oracle `ExternalContact*`, `HiringManager`) before committing.

```bash
cd apps/api/tests/fixtures
curl -s "https://ehpv.fa.em2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.secondaryLocations&finder=findReqs;siteNumber=CX_1,limit=3,sortBy=POSTING_DATES_DESC" -o oracle_dpworld_list.json
curl -s -X POST -H "Content-Type: application/json" -d "{\"appliedFacets\":{},\"limit\":3,\"offset\":0,\"searchText\":\"\"}" "https://murex.wd3.myworkdayjobs.com/wday/cxs/murex/MurexCareerPage1/jobs" -o workday_murex_list.json
curl -s "https://toters.bamboohr.com/careers/list" -o bamboohr_toters_list.json
curl -s "https://careers.chalhoubgroup.com/jobs.json" -o teamtailor_chalhoub_feed.json
```

Also save one Oracle detail, one Workday detail (GET the `externalPath` of the first posting) and one BambooHR detail. **New test file:** `tests/test_ats_mena_vendors.py`, covering:

- **Contract:** each fixture still has the fields listed in 1.4–1.7.
- **Normalization:** each `_norm_*` returns `title`, `company`, a `location` that `is_mena`, an `https` `source_url` and stripped `jd_text`. Oracle output has no contact keys.
- `_parse_workday_posted` handles "Posted Today", "Posted Yesterday", "Posted 18 Days Ago" and "Posted 30+ Days Ago".
- The Teamtailor `_jobposting` as a dict and as a str both map.

---

## 1.11 Acceptance checklist

- [ ] PR-A: a MENA run on a profile with skills like `["python", "react"]` yields ATS jobs from at least Tamara, Salla, Foodics, Ziina, Careem and Delivery Hero (talabat) or Etihad. Check `query_result` on the Activity page. An India run fetches no MENA-only boards (check the "ATS: loaded N jobs from M boards" log line; M is unchanged from before).
- [ ] PR-B: the MENA run also yields DP World, FAB or Emirates NBD (Oracle), Murex (Workday), Toters (BambooHR) and Chalhoub (Teamtailor) jobs, with **no** contact fields stored.
- [ ] `scripts/detect_ats.py --in docs/mena/employers_seed.csv` runs end to end and prints a summary.
- [ ] All tests pass. A run's ATS phase finishes in under 3 minutes (detail caps are respected).
