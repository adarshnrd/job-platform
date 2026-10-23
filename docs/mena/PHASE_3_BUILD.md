# Phase 3 Build Spec (from the 2026-10-17 research spikes)

> **What this is:** the buildable part of [PHASE_3_LONG_TAIL.md](PHASE_3_LONG_TAIL.md). Opus ran the spikes and Sonnet implements this file. Every endpoint, field and value below was observed live on 2026-10-17. The spike results are logged in PHASE_3_LONG_TAIL.md §3.12.
> **Depends on:** Phases 0–2 in the working tree. Read `scrapers/ats.py` (the vendor pattern, `MENA_SEED_BOARDS`, `_tech_first`, `_in_region`), `services/ats_harvester.py` (`_validate`, `split_token`) and `services/geo/mena.py` first.
> **Out of scope** (decided by the spikes; see §3.12): SuccessFactors, Emirates Group (Avature), government portals, Qatar Living, ReliefWeb (needs an owner-requested appname), the generic `jsonld_sitemap` vendor (no current consumer) and source quality scoring.

---

## B1. Geo fix: trailing ISO-2 segment

**File:** `services/geo/mena.py`, `country_of`

SmartRecruiters, Teamtailor JSON-LD and other feeds produce strings like `"Al Abageyah, EG"` or `"Maadi as Sarayat Al Gharbeyah, EG"`. The city isn't in our table and the bare code is only matched when it is the whole string, so these return `None` and the job is dropped from MENA runs.

Add this rule: split on commas, and if the **last** stripped segment (lowercased) is in `_ISO_CODES`, use it. That check comes after the existing whole-string check and **before** the token scan, because an explicit country code is the strongest signal. A single segment such as `"SA"` is still handled by the existing whole-string rule. Only codes after a comma count, so "Visa, USA" can never match `sa`.

Tests (`tests/test_geo_mena.py`):
- `country_of("Al Abageyah, EG") == "EG"`
- `country_of("Riyadh, SA") == "SA"`
- `country_of("Hörby, SE") is None`
- `country_of("Austin, US") is None`
- `country_of("La Medina, Tunis, TN") == "TN"`

---

## B2. New verified seed boards (existing vendors)

Add these to `MENA_SEED_BOARDS` in `scrapers/ats.py`, with `regions=("mena",)` unless noted. The counts are total/MENA jobs on 2026-10-17. All were checked against job locations; the rejected look-alikes are listed below.

| ats | token | company | default_location | total / mena |
|---|---|---|---|---|
| teamtailor | `propertyfinder.teamtailor.com` | Property Finder | Dubai, United Arab Emirates | 31 / 31 |
| teamtailor | `dubizzle.teamtailor.com` | Dubizzle | Dubai, United Arab Emirates | 6 / 4 |
| teamtailor | `rasan.teamtailor.com` | Rasan | Riyadh, Saudi Arabia | 21 / 21 |
| teamtailor | `qashio.teamtailor.com` | Qashio | Dubai, United Arab Emirates | 16 / 15 |
| recruitee | `unifonic` | Unifonic | Riyadh, Saudi Arabia | 36 / 19 (17 say "Remote job") |
| workable | `agility` | Agility | Riyadh, Saudi Arabia | 16 / 12 |
| workable | `tamatem` | Tamatem | Amman, Jordan | 12 / 11 |
| workable | `ananinja` | Ninja | Riyadh, Saudi Arabia | 27 / 27 |
| workable | `lucidya` | Lucidya | Riyadh, Saudi Arabia | 46 / 41 |
| smartrecruiters | `almosafer` | Almosafer | Riyadh, Saudi Arabia | 10 / 10 |
| smartrecruiters | `seera` | Seera Group | Dubai, United Arab Emirates | 9 / 9 |
| smartrecruiters | `brimore` | Brimore | Cairo, Egypt | 5 / 5 (after B1) |
| smartrecruiters | `homzmart` | Homzmart | Cairo, Egypt | 9 / 9 (after B1) |
| bamboohr | `nymcard` | NymCard | Dubai, United Arab Emirates | 3 / 2 |
| bamboohr | `bosta` | Bosta | Cairo, Egypt | 1 / 1 |

**Do NOT add these.** They are look-alikes that are not the MENA company:
- `stc.teamtailor.com`: a Swedish "STC", with jobs in Hörby SE
- personio `nbk`: German, Köln
- smartrecruiters `noonacademy`: India only
- breezy `dubizzlelabs`: Lahore PK

### Recruitee and MENA

The recruitee branch in `_fetch_board` has no MENA handling beyond `default_loc`. `"Remote job"` locations are not MENA and are correctly dropped by `_is_mena`. Nothing else is needed, but add a test showing that a Unifonic `"Amman, Al ‘A̅şimah, Jordan"` row passes `_is_mena`. The `"jordan"` alias handles it.

### SmartRecruiters country codes

`_SR_COUNTRIES["mena"]` already includes `eg`, so Brimore and Homzmart are fetched. `_sr_location` turns `eg` into "Egypt", so those jobs already resolve even before B1. Verify this in a test.

---

## B3. New vendor `taleo` (Oracle Taleo career sections). Target: Dubai Careers

One board covers **382 jobs across Dubai government entities**: RTA, Dubai Culture, the Department of Finance, Dubai Media and others. robots.txt returns 404, so nothing is disallowed.

**Board dict:**

```python
{"ats": "taleo", "token": "jobs.dubaicareers.ae|dubaicareers|40505100456", "company": "Dubai Government",
 "host": "jobs.dubaicareers.ae", "site": "dubaicareers", "portal": "40505100456",
 "regions": ("mena",), "default_location": "Dubai, United Arab Emirates"}
```

Extend `split_token` and `board_from_pair` in `ats_harvester.py` for `taleo` (`host|section|portal`), the same way oracle and workday work. **No harvester pattern:** the portal id is only found in the page HTML (see Validate below).

### Search (verified)

```text
POST https://{host}/careersection/rest/jobboard/searchjobs?lang=en&portal={portal}
Headers: Content-Type: application/json, Accept: application/json, X-Requested-With: XMLHttpRequest,
         tz: GMT+04:00, Accept-Encoding: identity     ← Taleo hosts sometimes send a broken gzip
                                                         body (httpx DecodingError seen on aa115.taleo.net)
Body:
{"multilineEnabled": false,
 "sortingSelection": {"sortBySelectionParam": "3", "ascendingSortingOrder": "false"},
 "fieldData": {"fields": {"KEYWORD": "<query or empty>", "LOCATION": ""}, "valid": true},
 "filterSelectionParam": {"searchFilterSelections": [
     {"id": "POSTING_DATE", "selectedValues": []}, {"id": "LOCATION", "selectedValues": []},
     {"id": "JOB_FIELD", "selectedValues": []}]},
 "advancedSearchFiltersSelectionParam": {"searchFilterSelections": [
     {"id": "ORGANIZATION", "selectedValues": []}, {"id": "LOCATION", "selectedValues": []},
     {"id": "JOB_FIELD", "selectedValues": []}, {"id": "JOB_NUMBER", "selectedValues": []},
     {"id": "URGENT_JOB", "selectedValues": []}, {"id": "EMPLOYEE_STATUS", "selectedValues": []},
     {"id": "STUDY_LEVEL", "selectedValues": []}, {"id": "WILL_TRAVEL", "selectedValues": []},
     {"id": "JOB_SHIFT", "selectedValues": []}]},
 "pageNo": 1}
```

**Response:** `{requisitionList, facetResults, pagingData: {currentPageNo, pageSize: 25, totalCount}, ...}`.
- Each requisition is `{"jobId": "168455", "contestNo": "26003340", "column": [title, "16/10/2026" (DD/MM/YYYY posted), nationality], "hotJob", ...}`.
- The **nationality column** values seen were `"UAE Only"` (66 of 100) and `"All Nationalities (Priority for UAE National)"`.
- `facetResults[id=ORGANIZATION].facetValueResults[]` gives `{id, text: "Roads and Transport Authority", quantity}`.

**Paging:** set `pageNo` and fetch at most `_TALEO_MAX_PAGES = 4` (100 jobs). The board cache is region-wide (one load per run), so load with an **empty KEYWORD**, sorted newest first (`sortBySelectionParam: "3"`). Keyword search does work (`software` gave 25, `developer` 6, `engineer` 22), but the cache is not per-query.

### Pre-filter before detail calls

1. Drop rows whose nationality column (lowercased) contains `"uae only"` or `"nationals only"`, when `settings.MENA_EXCLUDE_NATIONALS_ONLY` is on. These are unusable for expats, and dropping them here saves two thirds of the detail calls.
2. Sort the rest with `_tech_first` on the title, then cap at `_TALEO_DETAIL_CAP = 12`.

### Detail (verified)

```text
GET https://{host}/careersection/{site}/jobdetail.ftl?job={contestNo}&lang=en   (Accept: text/html, Accept-Encoding: identity)
```

The page has no JSON-LD. The data sits in `<input type="hidden" name="initialHistory" ... value="...">`, whose value is a list of fields separated by `!|!`. Each field is URL-encoded (`urllib.parse.unquote`), and HTML-bearing fields start with the marker `!*!`. Taleo also escapes `:` as `\:`, so replace `\:` with `:` after unquoting. Decode each field as `re.sub(r"\s+", " ", html.unescape(strip_tags(unquote(f.replace("!*!", "")).replace("\\:", ":")))).strip()`.

Observed layout. Let `i` be the index of the field equal to `contestNo`; the field just before it is the title.

| index | content (sample) |
|---|---|
| i-1 | title ("Office Manager- Corporate Administrative Support Services CEO") |
| i | contestNo ("26003340") |
| i+2 | **description** (HTML) |
| i+4 | **qualifications** (HTML) |
| i+6 | job field ("Organizational Performance and Development") |
| i+8 | **organization** ("Roads and Transport Authority"), used as the company |
| i+10 | department |
| i+12 | education level |
| i+20 | nationality ("UAE Only") |
| i+26 | schedule ("Full time") |
| i+28 | posted date ("16/10/2026") |
| i+30 | closing date ("16/11/2026") |

The values are duplicated at odd offsets (i+3, i+5, …).

**Do not trust the fixed offsets blindly.** Assert `fields[i+28]` matches `^\d{2}/\d{2}/\d{4}$`. If it does not, log a warning and fall back to `title + description` only (search for the first field longer than 200 characters after i). Save the real page as a fixture: trim it to the `<input name="initialHistory">` tag, keeping < 50 KB.

### Mapping

- `company = organization or board company`
- `location = default_location` (Dubai). The list's `locationsColumns` was empty.
- `jd_text = description + " " + qualifications`
- `posted_at` comes from `DD/MM/YYYY` (`datetime.strptime(v, "%d/%m/%Y")`)
- Skip the job if the closing date is in the past
- `source_url = apply_url = https://{host}/careersection/{site}/jobdetail.ftl?job={contestNo}&lang=en`
- Re-check `mena.nationals_only(title, jd)` and the nationality field, and drop when the flag is on

### Validate (for `detect_ats.py`)

`detect_ats.py` already flags `UNSUPPORTED taleo`. Make it supported:
1. Fetch the careers page.
2. Find `/careersection/<section>/` and `portal=(\d{6,})` in the HTML.
3. Build the composite token.
4. POST a search with `pageNo: 1` and treat `totalCount > 0` as valid.

**Qatar Airways' Taleo** (`aa115.taleo.net/qa_external_cs`) now redirects to a login page (`mysubmissions.ftl`). It moved to Avature; see B5.

---

## B4. New vendor `phenom` (Phenom People career sites). Target: G42 group

`careers.g42.ai` serves the whole G42 group: G42, Core42, Presight, Inception, CPX, Space42, Analog and AIQ (per-brand sitemaps are listed in robots.txt). There were **49 jobs** on 2026-10-17. robots.txt disallows `*/apply`, `*/jobcart`, `*/px-widgets`, `*/chatbot` and similar, but **not** `search-results` or `job/`. Use only those two paths.

**Board dict:**

```python
{"ats": "phenom", "token": "careers.g42.ai|global/en", "company": "G42",
 "host": "careers.g42.ai", "site": "global/en", "regions": ("mena", "global"),
 "default_location": "Abu Dhabi, United Arab Emirates"}
```

Extend `split_token` for `phenom` as `host|site`.

### List (verified)

```text
GET https://{host}/{site}/search-results?from={n}&s=1     (n = 0, 10, 20, …; 10 jobs per page)
```

The page embeds `phApp.ddo = {...};` in an inline script. Extract it with `re.search(r"phApp\.ddo\s*=\s*(\{.*?\});\s*phApp", html, re.S)` and parse with `json.loads`. Data lives at `ddo["eagerLoadRefineSearch"]`: `totalHits` (49), plus `data.jobs[]` with these keys:
- `jobId ("2948"), reqId, jobSeqNo, title, postedDate ("2026-04-28T07:20:13.000+0000"), dateCreated`
- `city, country ("United Arab Emirates"), cityStateCountry ("MBZ City, Abu Dhabi, United Arab Emirates"), location, multi_location, workLocation`
- `category ("Sales & Business Development"), department, businessUnit, type, ml_skills, descriptionTeaser`

Page until `from >= totalHits` or `_PHENOM_MAX_JOBS = 100`. Use `self._get_text` with the HTML Accept header. If the ddo regex fails (the site changed), log once and return `[]`.

### Pre-filter

`_in_region(cityStateCountry, region)`. Some G42 jobs are in the US (`" , United States"`) or elsewhere. Then sort with `_tech_first` on the title and cap at `_PHENOM_DETAIL_CAP = 15`.

### Detail (verified)

`GET https://{host}/{site}/job/{jobId}` carries a JobPosting JSON-LD, which `jsonld.parse_job_posting` handles. Seen: `title`, `datePosted ("2026-10-15")`, `hiringOrganization.name ("CPX Holding L.L.C O.P.C")` (the brand entity), `jobLocation.geo` and address, `employmentType ["FULL_TIME"]` and `description` (about 800+ chars).

### Mapping

- `company = JSON-LD hiringOrganization.name or "G42"`. Keep the raw name; dedup normalizes legal suffixes itself.
- `location = cityStateCountry` (list). Strip a leading `" , "`.
- `posted_at = JSON-LD datePosted or list postedDate`
- `source_url = apply_url = https://{host}/{site}/job/{jobId}`

**Validate:** the list GET with `from=0`. Valid if the ddo parses and `totalHits > 0`. detect_ats already flags phenom as unsupported; make it supported by deriving `site` from the URL path (e.g. `/global/en/`).

---

## B5. New vendor `avature` (Avature career portals). Target: Qatar Airways

`careers.qatarairways.com/global` is Avature. robots.txt disallows only `/global/*qtvc=` and declares the sitemap `https://careers.qatarairways.com/global/sitemap_index.xml`. That index has one child, `/global/sitemap.xml`, which lists **177 `JobDetail` URLs** with `<lastmod>`.

**Board dict:**

```python
{"ats": "avature", "token": "careers.qatarairways.com|global", "company": "Qatar Airways",
 "host": "careers.qatarairways.com", "site": "global", "regions": ("mena", "global"),
 "default_location": "Doha, Qatar"}
```

### List

1. Read `https://{host}/{site}/sitemap_index.xml`, then follow each child `<loc>` ending in `.xml` (at most 3).
2. Keep only URLs matching `rf"https://{re.escape(host)}/{site}/JobDetail/([^/<]+)/(\d+)$"`. The sitemap also lists `/JobDetail` and `/JobDetailApplied` without ids; skip those.
3. Slug words are joined with `-` (e.g. `Software-Test-Engineer-Manual-Automation-Selenium-Playwright-Appium-Ahmedabad-India`), so the slug carries title **and** location. Pre-filter:
   - Tech-first: take the slug's words, lowercase them, and run `_tech_first` on the joined title.
   - When `region == "mena"`, drop slugs that end in a non-MENA place. Slug `...-Ahmedabad-India` gives `country_of("ahmedabad india")`, which is None, so it is dropped. If the slug has no recognizable place, keep it (most Doha roles don't name a place).
4. Cap at `_AVATURE_DETAIL_CAP = 15`, newest `lastmod` first.

### Detail (verified)

`GET https://{host}/{site}/JobDetail/{slug}/{id}` has no JSON-LD. The fields are Avature label/value pairs:

```text
label:  re.findall(r'class="article__content__view__field__label[^"]*"[^>]*>\s*(.*?)\s*</', html, re.S)
value:  re.findall(r'class="article__content__view__field__value[^"]*"[^>]*>(.*?)</div>', html, re.S)
```

The labels seen were `Ref #` (236353), `Location` (`"India-Ahmedabad"`, i.e. Country-City) and `Job family` (`"Corporate & Commercial"`). There are 7 values; those after the labelled ones hold the JD body. Build `jd_text` from every value block not consumed by a label, with tags stripped. Fall back to `<meta property="og:description" content="...">`.

Pair labels to values by order: the first N values belong to the N labels. Check this on the fixture, and if the counts disagree, use a single regex over the whole field block. Keep the extraction in one small function with a docstring, tested on the fixture.

### Mapping

- `Location "Qatar-Doha"` becomes `"Doha, Qatar"`: split on the first `-` into country and city. Then apply the region filter with `_in_region`, and drop non-MENA when `region == "mena"`.
- `title`: take it from the `<h2>`/`<h1>` heading on the page (verify on the fixture). Fall back to the slug with `-` turned into spaces.
- `source_job_id = Ref #`. `source_url = apply_url = the JobDetail URL`.
- `posted_at`: the sitemap `lastmod`, unless the page shows a date.

**Note:** Emirates Group also uses Avature, but its job list sits under `/careersmarketplace/`, which robots.txt **disallows**, and `www.emiratesgroupcareers.com/sitemap.xml` returns 404. Do not add Emirates.

---

## B6. Sabbar: non-ASCII slugs and Arabic hints

Phase 2 parses 11,798 of 16,090 Sabbar sitemap URLs. The other ~4.3k have non-ASCII (Arabic, usually percent-encoded) slugs and are skipped.

1. In `scrapers/sabbar.py`, widen the URL regex to accept any slug characters (`[^/]+`) for the city and role parts, and `urllib.parse.unquote` them before matching.
2. Add `ARABIC_ROLE_TERMS` to `services/geo/mena.py` (from PHASE_3_LONG_TAIL.md §3.6):

```python
ARABIC_ROLE_TERMS = {
    "software engineer": "مهندس برمجيات", "developer": "مطور", "programmer": "مبرمج",
    "backend": "مطور خلفية", "frontend": "مطور واجهات", "full stack": "فل ستاك",
    "data engineer": "مهندس بيانات", "data scientist": "عالم بيانات", "devops": "ديف أوبس",
    "mobile": "تطبيقات", "cyber security": "أمن سيبراني", "information technology": "تقنية المعلومات",
}
```

3. Sabbar's tech-slug filter also accepts an unquoted slug containing any Arabic value from that map, joined with `-` as in the slugs. Verify on a real Arabic slug from the sitemap and store one in the fixture.
4. This uses only the English sitemap. The `/ar/` sitemap stays out of scope (`MENA_ARABIC_POSTINGS` is not needed yet).

Tests: an Arabic-slug URL containing `مطور` passes the filter, and one containing `محاسب` (accountant) does not.

---

## B7. Docs (no code)

1. `docs/mena/PARTNERSHIP_OUTREACH.md`: the email template and status table described in PHASE_3_LONG_TAIL.md §3.9. Fill the table's "Status" column with "not contacted".
2. Do **not** edit PHASE_3_LONG_TAIL.md §3.12; Opus has already filled it in.

---

## B8. Tests and acceptance

- Fixtures, trimmed to under 50 KB each:
  - `taleo_dubaicareers_search.json`: 3 requisitions, including one "UAE Only" and one "All Nationalities"
  - `taleo_dubaicareers_detail.html`: only the `initialHistory` input
  - `phenom_g42_search.html`: only the `phApp.ddo` script, 3 jobs, one of them US
  - `phenom_g42_detail.html`: head plus ld+json
  - `avature_qr_sitemap.xml`: 5 URLs, including one India slug and one without an id
  - `avature_qr_detail.html`: the article field block plus og:description
- Tests in a new `tests/test_ats_mena_vendors_p3.py`:
  - Taleo: nationality pre-filter, decode-and-offset mapping, the offset-sanity fallback, closing-date skip, and the DD/MM/YYYY date
  - Phenom: ddo parse, US job filtered on mena, JSON-LD detail mapping
  - Avature: sitemap filtering, Country-City location flip, label/value extraction
  - Harvester: `split_token` and `board_from_pair` round-trip for taleo, phenom and avature
  - B1 and B6 tests as listed above
- Live smoke test (fresh instance, `region="mena"`): ATS `search_jobs("engineer", location="United Arab Emirates", max_results=200)`. Report per-vendor and per-company counts. Expect new rows from taleo (Dubai government entities), phenom (G42/CPX/Core42…), teamtailor (Property Finder, Qashio…) and workable (Lucidya, Ninja…, mostly under "Saudi Arabia"). Also run `location="Qatar"` to see avature results.
- Make sure the full ATS load stays under about 3 minutes, then report the time. If it is over, lower the new detail caps rather than the existing ones.
- Full suite passes. The baseline is 577.
