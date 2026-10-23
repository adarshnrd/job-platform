# Phase 3: Long Tail, Enterprise ATS Vendors and Partnerships

> **Goal:** reach the large Gulf employers and portals that Phases 1–2 cannot (custom or enterprise ATSs and government portals), add Arabic-language coverage, and open the partnership track for the walled regional boards.
> **Depends on:** Phases 1 and 2 merged.
> **Nature of this phase:** unlike Phases 0–2, several items here were **identified but not fully verified** during research. Each one marked **SPIKE** starts with a time-boxed investigation (≤ 1 hour). Its success criterion decides whether to build it. Record what the spike found at the bottom of this file (§3.12) so the next session does not redo it.

Spike procedure (the same for every SPIKE item):
1. Fetch the page or endpoint with the project venv and httpx (browser UA). Save the raw response to the scratchpad, **not** to the repo.
2. Check robots.txt for the exact path you plan to call. If it is disallowed, **stop**: mark the item "blocked by robots" in §3.12.
3. If you got structured data (JSON, a JSON-LD JobPosting or an RSS/Atom feed) with title, location and URL for at least 10 jobs, **build it**: as an ATS vendor (Phase 1 pattern) when it is per-employer, or as a board scraper (Phase 2 pattern) when it is a portal.
4. If it only works with a headless browser, a login or a challenge bypass, **stop**: mark it "partnership only".

---

## 3.1 Generic "sitemap + JSON-LD" connector (`jsonld_sitemap`). Build this first

**Why:** Sabbar (Phase 2) proved the pattern: a published sitemap of job URLs, each page carrying a `JobPosting` JSON-LD block. Google for Jobs requires this markup, so many custom employer career sites and small boards have it too. A generic ATS vendor lets us add such a site **as data** (one board dict) instead of writing a scraper for each.

**Board dict:**

```python
{"ats": "jsonld_sitemap", "token": "<short-name>", "company": "<name or None for multi-employer>",
 "sitemap": "https://example.com/sitemap-jobs.xml",
 "url_pattern": r"/careers/job/\d+",          # only URLs matching this are job pages
 "default_location": "Dubai, United Arab Emirates",
 "regions": ("mena",)}
```

**Implementation in `scrapers/ats.py`:**
1. Read the sitemap and follow a `<sitemapindex>` (at most 5 children).
2. Keep the URLs matching `url_pattern` and sort them by `<lastmod>`, newest first.
3. Fetch the details, prioritising tech slugs (reuse `SABBAR_TECH_SLUGS` after moving it to `services/geo/mena.py` as `TECH_SLUG_HINTS`), capped at `_JSONLD_DETAIL_CAP = 15`.
4. Map each page with `jsonld.parse_job_posting`.

Once it exists, refactor Sabbar to reuse the shared helper functions. Keep Sabbar's own Platform value, because it is a board, not an employer.

**Candidates to try:** ProgressSoft's site carries JSON-LD (verified on its careers page). Run `scripts/detect_ats.py` (Phase 1.9) over the employer list and treat every `jsonld` signature hit without a supported ATS as a candidate.

---

## 3.2 Oracle Taleo (`taleo`). SPIKE, high value

**Targets:**
- **Dubai Careers** (`jobs.dubaicareers.ae`, career section `dubaicareers`). One endpoint covers **45+ Dubai government entities**, and the research doc notes it has application-development and infrastructure categories. Verified: the page answers 200 over plain HTTP.
- **Qatar Airways** (`aa115.taleo.net/careersection/qa_external_cs/jobsearch.ftl`).

**What to test:** Taleo career sections load their results via `POST https://{host}/careersection/rest/jobboard/searchjobs?lang=en&portal={portalNo}`, with a JSON body containing `"multilineEnabled", "sortingSelection", "fieldData": {"fields": {"KEYWORD": "", "LOCATION": ""}}, "pageNo": 1`. The `portalNo` is in the `jobsearch.ftl` HTML (search for `portal=` or `"portal"`). Open the page in the in-app browser and watch the network calls (`read_network_requests`) to capture the exact request.

**Success:** a JSON list with job id, title, location and posting date. The job URL is `https://{host}/careersection/{section}/jobdetail.ftl?job={contestNo}&lang=en`.

---

## 3.3 SAP SuccessFactors career sites (`successfactors`). SPIKE

**Targets:** Core42 (`career22.sapsf.com`, linked from careers.core42.ai) and solutions by stc (`career23.sapsf.com/career?company=stcsstcsol`).

**What we know:** `career23.sapsf.com/career?company=stcsstcsol&career_ns=job_listing_summary&resultType=XML` returned an **empty** `<Job-Listing>`, so that route is not it. Try these in order:
1. The employer's RMK site (e.g. `careers.core42.ai`) with `/sitemap.xml`, where RMK sites usually list `/job/<slug>/<id>/` URLs with JSON-LD. If that works, it is just a `jsonld_sitemap` board (3.1). No new vendor needed.
2. `/services/rss/job/?locale=en_US&keywords=` on the RMK host.
3. The `career?company=…&career_ns=job_listing&…` HTML and its XHR (capture it in the in-app browser).

---

## 3.4 Avature (`avature`). SPIKE

**Targets:** Emirates Group (`emiratesjobs.avature.net`) and Qatar Airways (`qatarairways.avature.net`).

**What to test:** Avature portals usually expose `/careers/SearchJobs` (HTML) and an RSS feed at `/careers/SearchJobs/feed/` or `…/SearchJobs/?jobRecordsPerPage=…&format=rss`. The Emirates link found during research was `/careersmarketplace/Login`, so the public job list may live under a different portal path. Find it from the emiratesgroupcareers.com "search jobs" link first.

---

## 3.5 Phenom People (`phenom`). SPIKE

**Target:** G42 (`careers.g42.ai/global/en/search-results`). This is a major UAE AI employer, and the research doc cites direct software-engineering demand there.

**What to test:** Phenom pages embed the first page of results in an inline script (`phApp.ddo = {...}`, under `eagerLoadRefineSearch.data.jobs`). Paging goes through `POST /widgets` with a `ddoKey: "refineSearch"` body. Parse the inline JSON first; it may be enough (about 10–50 jobs). Also check `https://careers.g42.ai/global/en/sitemap_index.xml`; if job URLs are listed with JSON-LD, use `jsonld_sitemap` (3.1) instead.

---

## 3.6 Arabic-language coverage

1. **Sabbar Arabic sitemap** (`/ar/jobs/sitemaps/job-details.xml`). Many postings exist only in Arabic. Add it behind a flag, `MENA_ARABIC_POSTINGS: bool = False`. The detail JSON-LD has Arabic `title` values, which is why Phase 0's Unicode dedup and Arabic prefilter words are a prerequisite.
2. **Query expansion.** The discovery queries come from the English profile (`headline` and `skills`). For Arabic boards, add a small static map in `services/geo/mena.py`, `ARABIC_ROLE_TERMS = {"software engineer": "مهندس برمجيات", "developer": "مطور", "backend": "مطور خلفية", "frontend": "مطور واجهات", "full stack": "مطور فل ستاك", "data engineer": "مهندس بيانات", "devops": "ديف أوبس", "mobile": "مطور تطبيقات"}`. Arabic-capable sources search with both the original query and its mapped term. Do **not** call an LLM for translation in the discovery hot path.
3. **AI scoring check.** Run the parse and score prompts on 5 Arabic JDs and compare the result with the same JD in English (Sabbar often has both). If scores diverge by more than 15 points, add an instruction to the parse prompt: *"The JD may be in Arabic or French; extract fields in English."*

---

## 3.7 ReliefWeb (NGO and international jobs: Syria, Yemen, Iraq, Lebanon, Palestine)

- The v1 API returns **410 Gone**. v2 (`https://api.reliefweb.int/v2/jobs`) returns 403 until you have an **approved appname**. Request one (free) at `https://apidoc.reliefweb.int/parameters#appname`. **This is a manual step for the owner.** Add `RELIEFWEB_APPNAME: str = ""` to config and make the scraper `requires_key=True` with `has_key()` checking it.
- Then use `POST /v2/jobs?appname=…` with a filter on `country.iso3` in (SYR, YEM, IRQ, LBN, PSE, JOR, EGY, LBY, SDN) and `career_categories.name: "Information and Communications Technology"`. Request the fields `title, url, source.name, country.name, city.name, date.created, body`.
- Platform `reliefweb`. Regions `{"mena"}`. Add an enum migration.

---

## 3.8 Qatar Living Jobs (classifieds). Low priority

robots.txt allows everything except `/api/`. `/en/jobs/jobs/list` is HTML only (no JSON-LD), and the links follow the shape `/en/jobs/jobs/profile/<slug>`. Classified listings vary in quality, so build it only with:
- a quality gate: drop postings with no company name, a JD under 200 characters, or a personal email or phone as the only contact
- the `listing_validator` revalidation already in the repo

Treat it as a Phase 2-style board scraper, with regions `{"mena"}` and `salary_currency` QAR.

---

## 3.9 Partnership track (no code until there is an agreement)

These sources carry most of the MENA volume but are either Cloudflare-walled for plain HTTP or restrict automated collection in their terms (research doc, "Red" table; confirmed 403 on 2026-10-17):

| Board | Ask for | Contact route |
|---|---|---|
| Bayt | XML/JSON job feed or a distribution/affiliate agreement | bayt.com, "Contact us / Partnerships" |
| Naukrigulf | Written consent and a feed (their terms name a legal contact) | naukrigulf.com terms page |
| GulfTalent | Feed, or written approval of a snippet-and-link model | gulftalent.com terms page |
| WUZZUF / Forasna | Partner API or feed (WUZZUF has no public API; only third-party scrapers exist) | wuzzuf.net business contact |
| Qureos | Partner API. Its robots.txt disallows `/api/` and query URLs but publishes `sitemap-hire/*.xml`. Ask whether detail-page indexing is acceptable before using it. | qureos.com |
| Tanqeeb | Feed. It is itself an aggregator, so prefer the original sources it links to. | tanqeeb.com |
| Jobs.ps, Jadarat, Mihnati, Daleel Madani | Feed or partnership | site contacts |

**Deliverable for the owner** (a doc, not code): `docs/mena/PARTNERSHIP_OUTREACH.md`, holding a short email template. It covers who we are, that we link back to the canonical posting, store vacancy data only (no candidate data), honour takedowns, and want a feed in any format with stated rate limits. Track the status of each board in a table. When a feed is granted, implement it as a Phase 2 board scraper that reads the feed.

---

## 3.10 Government portals. SPIKE each, low priority

- UAE: Federal (FAHR, `u.ae` lists the portals), TAMM (Abu Dhabi), Nafis (Emiratis only, so out of scope for expat users)
- Bahrain: LMRA Talent Portal
- Saudi: Jadarat (Cloudflare 403) and Taqat

Most need an account or are restricted to citizens. Spike only the ones whose job lists are public, and skip any portal that serves only nationals: the Phase 0 `nationals_only` filter would drop nearly everything anyway.

---

## 3.11 Quality and operations

1. **Source quality score.** Per source and per region, compute from existing telemetry (`services/telemetry.py`):
   - canonicality: the share of listings whose `apply_url` is an employer ATS domain
   - freshness: median age of `posted_at`
   - duplicate rate: the share of listings deduped by fingerprint
   - match rate: the share scoring at or above `RECOMMENDED_THRESHOLD`

   Show it in the source-health panel. Add one endpoint to `routers/telemetry.py` that mirrors the existing coverage endpoint.
2. **ATS migration alerts.** When a seeded or harvested board's validation fails 3 runs in a row, log a warning and mark it `stale` in `data/ats_boards.json`. Employers switch ATS, and the detector script (Phase 1.9) re-finds them.
3. **Salary sanity.** For MENA listings, flag annual salaries below 12,000 or above 3,000,000 in the local currency as a probable monthly/annual mix-up, and clear them rather than store wrong numbers.
4. **Employer self-submission** (from the research doc): accept a JSON Feed or XML URL from an employer and store it as a `jsonld_sitemap` or `teamtailor`-style board. Admin-only, no UI in this phase.

---

## 3.12 Spike log (fill this in as spikes complete)

| Item | Date | Result | Notes |
|---|---|---|---|
| 3.2 Taleo / Dubai Careers | 2026-10-17 | **BUILD** (PHASE_3_BUILD.md B3) | The `rest/jobboard/searchjobs` POST works with portal `40505100456`: 382 jobs, 25 per page. The detail data is in the hidden `initialHistory` field, `!\|!`-separated. 66% of rows are "UAE Only", so they are pre-filtered. No robots.txt (404). |
| 3.2 Taleo / Qatar Airways | 2026-10-17 | moved | The Taleo section now redirects to a login page; QR uses Avature (row below). |
| 3.3 SuccessFactors / Core42 | 2026-10-17 | skip | The RMK sitemap lists 1 job and the detail page has no JSON-LD. `/services/` (RSS) is robots-disallowed. Core42 jobs are covered via the G42 Phenom site. |
| 3.3 SuccessFactors / solutions by stc | 2026-10-17 | blocked by robots | `career23.sapsf.com/robots.txt` is `Disallow: /`, and solutions.com.sa was unreachable. Partnership only. |
| 3.4 Avature / Emirates | 2026-10-17 | blocked by robots | Jobs sit under `/careersmarketplace/` (disallowed) and emiratesgroupcareers.com has no sitemap (404). |
| 3.4 Avature / Qatar Airways | 2026-10-17 | **BUILD** (B5) | `careers.qatarairways.com/global/sitemap.xml` lists 177 JobDetail URLs. Detail pages use label/value HTML with no JSON-LD. |
| 3.5 Phenom / G42 | 2026-10-17 | **BUILD** (B4) | `search-results?from=N&s=1` embeds `phApp.ddo` (49 jobs, 10 per page). `/job/{id}` has JSON-LD. Covers G42, Core42, Presight, Inception, CPX and Space42. |
| JS-loaded employers (detect_ats leftovers) | 2026-10-17 | **BUILD** (B2) | Token guessing over 7 vendors found 15 real MENA boards. 4 look-alikes were rejected (a Swedish STC, a German NBK, India-only Noon Academy, Dubizzle Labs in Lahore). No board was found for noon, tabby, e&, du, wio, mubadala, neom, sabic or elm; they likely use Workday or Oracle tenants with unguessable hosts, or custom sites. |
| 3.10 Government portals | 2026-10-17 | skip | Dubai Careers (B3) already covers Dubai government, and 66% of its jobs are nationals-only. Federal and other portals need accounts or serve citizens only, so the value for expat users is low. |
| 3.7 ReliefWeb | 2026-10-17 | owner step | The v2 API needs an approved appname. Request one free at apidoc.reliefweb.int; build once it is granted. |
