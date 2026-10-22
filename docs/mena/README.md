# MENA Expansion: Overview, Research Verification and Phase Index

> **Status (2026-10-17):** Phases 0–2 and the Phase 3 build ([PHASE_3_BUILD.md](PHASE_3_BUILD.md)) are **implemented and not yet committed**, with 645 tests passing. The remaining Phase 3 items are blocked or waiting on owner steps (see PHASE_3_LONG_TAIL.md §3.12). Migrations `database/17_mena_region.sql` and `18_mena_sources.sql` still have to be run in Supabase (run 18 on its own). See §6 for where the build differed from the plan.
> **Goal:** add a third discovery region, `mena`, next to `india` and `global`. It should find software jobs in the Gulf (UAE, KSA, Qatar, Kuwait, Bahrain, Oman), Egypt and the Levant, and North Africa (Morocco, Tunisia, Algeria).
> **Source research:** `MENA Software-Job Sources and Compliant Collection Strategy.md` (user-provided). Section 2 below records which of its claims held up when tested against the live web.
> **Implementer:** these docs are written so a smaller model (Sonnet) can build each phase without re-doing the research. Read this file first, then the one phase file you are working on.

---

## 1. Phase index

| Phase | File | What it delivers | Depends on |
|---|---|---|---|
| **0** | [PHASE_0_FOUNDATIONS.md](PHASE_0_FOUNDATIONS.md) | `mena` region end to end (API, DB, scheduler, UI), a MENA geo/currency helper module, Unicode-safe dedup (**a blocking bug**), French and Arabic prefilter vocabulary, a filter for jobs open only to nationals | none |
| **1** | [PHASE_1_ATS_EMPLOYERS.md](PHASE_1_ATS_EMPLOYERS.md) | MENA boards on the existing ATS aggregator, plus 4 new keyless ATS vendors: Oracle HCM, Workday, BambooHR and Teamtailor | Phase 0 |
| **2** | [PHASE_2_REGIONAL_BOARDS.md](PHASE_2_REGIONAL_BOARDS.md) | foundit Gulf (an extension of an existing scraper), Sabbar (KSA), Emploitic (DZ), Keejob (TN), ReKrute (MA), MENA eligibility on remote boards, MENA routing for keyed aggregators | Phase 0 |
| **3** | [PHASE_3_LONG_TAIL.md](PHASE_3_LONG_TAIL.md) | Taleo, Phenom, SuccessFactors and Avature employers (Dubai Careers, Qatar Airways, G42, Emirates), ReliefWeb, Arabic queries, partnership-only boards, source quality scoring | Phases 1–2 |

Phases 1 and 2 are independent of each other and can be built in parallel after Phase 0 merges. Inside each phase, every numbered task is sized for one session or one PR.

---

## 2. Verification of the research document

Every claim below was tested on 2026-10-17. Tests used direct HTTP calls (httpx, browser User-Agent) and live web searches.

### 2.1 Confirmed

| Claim | Evidence |
|---|---|
| Greenhouse, Lever, SmartRecruiters and Workable have keyless public job APIs | All four answered for MENA employers (table 3.1) |
| Careem has a public Greenhouse board | `boards-api.greenhouse.io/v1/boards/careem/jobs`: 14 jobs, 9 in MENA |
| Tamara (KSA fintech) is a strong target | Greenhouse `tamara`: 40 jobs, 35 in MENA |
| LinkedIn prohibits crawling | `linkedin.com/robots.txt` is `Disallow: /` for `*` |
| Bayt, GulfTalent, WUZZUF, Indeed and Jadarat cannot be reached by plain HTTP | All return **403 behind a Cloudflare challenge**. ToS restrictions aside, they are technically closed to a keyless HTTP scraper |
| Sabbar exposes a large Saudi catalogue | Its sitemap `/en/jobs/sitemaps/job-details.xml` lists **16,090 job URLs**, each detail page carries a `JobPosting` JSON-LD block, and robots.txt allows crawling |
| Emploitic is the main Algerian source | robots.txt allows crawling (only `/partenaires/` is disallowed). Listings sit in `__NEXT_DATA__`, and a "developpeur" search returned 320 jobs |
| Keejob has an IT category and is crawlable | robots.txt allows everything except `/api/`, `/recruiter/*` and similar paths. Detail pages carry `JobPosting` JSON-LD |
| ReKrute is crawlable | robots.txt has no disallows, and detail pages carry `JobPosting` JSON-LD |
| Dubai Careers aggregates government entities on Taleo | `jobs.dubaicareers.ae/careersection/...` answers 200 |
| Saudi PDPL, UAE PDPL and Qatar PDPPL exist and cover vacancy-adjacent personal data | Consistent with official portals. This is a legal reading, not something a script can check |

### 2.2 Corrected or refined

| Research claim | What we found |
|---|---|
| "Teamtailor normally requires an account-generated key" | **Partly wrong for our purpose.** Every Teamtailor career site serves a public **`/jobs.json`** (JSON Feed, each item carrying a `_jobposting` JSON-LD dict) and **`/jobs.rss`**. Chalhoub Group's feed returned 100 items with no key. |
| "Build Greenhouse/Lever/SmartRecruiters/Workable connectors" (implying these cover MENA) | **The big MENA enterprises mostly do not use them.** ATS detection on 70 employer careers pages found **Oracle HCM** (DP World, Emirates NBD, FAB, ROSHN), **SuccessFactors** (Core42, solutions by stc), **Avature** (Emirates Group, Qatar Airways), **Taleo** (Qatar Airways, Dubai Careers), **Phenom** (G42), **Workday** (Murex), **BambooHR** (Toters, Instabug/Luciq) and **Teamtailor** (Chalhoub). Greenhouse, Lever, Ashby and Workable are mainly used by startups. Phase 1 therefore adds Oracle HCM, Workday, BambooHR and Teamtailor connectors, all keyless and all verified. |
| Akhtaboot listed as a Phase 2 country source | **Excluded.** robots.txt is `Disallow: /`. |
| Jobzella listed as an Egyptian source | **Excluded.** robots.txt is `Disallow: /`. |
| WUZZUF, Forasna, Jobs.ps, Mihnati, Daleel Madani and Jadarat listed as Phase 2 crawl targets | **Moved to partnership-only (Phase 3).** All return a Cloudflare 403 to plain HTTP. Getting past that would mean bot-wall evasion, which this project does not do for these boards. |
| Qatar Living as a crawl target | **Deferred to Phase 3.** robots.txt allows crawling, but job pages have no JSON-LD and listings are classified ads with mixed quality. |
| "Monster Gulf / foundit Gulf: commercial agreement recommended" | **The repo already uses this exact API.** `scrapers/foundit.py` calls `/middleware/jobsearch` on foundit.in/sg/id/hk, and `www.founditgulf.com/middleware/jobsearch` answers the same way (182 "software engineer" jobs, mostly KSA/UAE, currency AED). Note that founditgulf's robots.txt disallows `/middleware/`, and so does foundit.in's, which the repo already scrapes. The project owner should make the call; see the Phase 2 notes. |
| Adzuna as a MENA aggregator (implied by "aggregators") | **Not usable.** Adzuna covers about 19 countries and none of them is in MENA. |
| Careerjet for MENA | **Likely usable.** Careerjet runs `careerjet.ae`, `careerjet.com.sa`, `careerjet.com.eg` and `careerjet.com.kw`. The API locale codes (`en_AE`, etc.) could not be confirmed from public docs and must be tested once a key is set. |
| ReliefWeb as a free NGO jobs source | **Needs an approved `appname`.** The v1 API returns 410 Gone. v2 returns 403 *"You are not using an approved appname"*, and the appname request form is free. |
| Remote boards (Himalayas etc.) for MENA | Himalayas jobs carry `locationRestrictions`, and most say `["United States"]` or similar. Only rows with no restriction, or a MENA or EMEA restriction, should pass for `mena`. |

### 2.3 Not re-verified (no implementation impact)

- The exact wording of Bayt, Naukrigulf and GulfTalent ToS. These boards are Cloudflare-walled or timed out (Naukrigulf), so we do not touch them anyway.
- The recruiter-behaviour narrative and the employer lists in the research doc. We used them as seed candidates, and table 3.1 lists the ones that actually resolve.

---

## 3. Verified source inventory (live on 2026-10-17)

### 3.1 ATS boards with MENA jobs

`total` is the number of jobs on the board. `mena` is the number whose location matches a MENA city or country.

| ATS | Token / host | Employer | total | mena |
|---|---|---|---:|---:|
| greenhouse | `tamara` | Tamara (KSA) | 40 | 35 |
| greenhouse | `careem` | Careem (UAE) | 14 | 9 |
| greenhouse | `binance` | Binance (Dubai roles) | 205 | 34 |
| ashby | `ziina` | Ziina (UAE) | 13 | 13 |
| ashby | `thndr` | Thndr (EG/UAE) | 14 | 12 |
| ashby | `LeanTech` (case matters) | Lean Technologies (KSA/UAE) | 7 | n/a |
| workable | `salla` | Salla (KSA) | 41 | 41 |
| workable | `foodics` | Foodics (KSA/EG) | 28 | 28 |
| workable | `progressoft` | ProgressSoft (JO) | 37 | n/a |
| smartrecruiters | `deliveryhero` | Delivery Hero, which includes **talabat** | 940 | 141 (ae 46, sa 25, eg 56, qa 14) |
| smartrecruiters | `EtihadAirways5` | Etihad Airways | 102 | 102 |
| oracle_hcm | `ehpv.fa.em2.oraclecloud.com` / site `CX_1` | DP World | 559 | many (global employer) |
| oracle_hcm | `fa-evlo-saasfaprod1.fa.ocs.oraclecloud.com` / `CX_1` | Emirates NBD | 31 | 31 |
| oracle_hcm | `ehjd.fa.em2.oraclecloud.com` / `fabCareers` | First Abu Dhabi Bank | 116 | 116 |
| workday | `murex.wd3.myworkdayjobs.com` / tenant `murex` / site `MurexCareerPage1` | Murex (Beirut) | 45 | ~ |
| bamboohr | `toters` | Toters (Lebanon) | 63 | 63 |
| bamboohr | `instabug` | Instabug/Luciq (Cairo) | 2 | 1 |
| teamtailor | `careers.chalhoubgroup.com` | Chalhoub Group (UAE) | 100+ | most |

**Blocked or not found:** ROSHN Oracle HCM (`W4S-101: Blocked by WAF4SaaS`). Lever `kitopi` returned 404 even though kitopi.com links to `jobs.lever.co/kitopi`, so retry it with the exact casing before giving up. Probes for noon, tabby, propertyfinder, anghami, swvl, sary, nana, jahez and others on Greenhouse, Lever, Ashby and Workable found nothing. Those companies use custom or other ATSs; see Phase 3.

### 3.2 Regional boards

| Board | Country | robots.txt | Plain HTTP | Data shape | Phase |
|---|---|---|---|---|---|
| Sabbar | KSA | allows; publishes sitemaps | 200 | sitemap of 16k detail URLs, JSON-LD per job | 2 |
| foundit Gulf | GCC | `/middleware/` disallowed | 200 | same JSON API as `scrapers/foundit.py` | 2 (owner decision) |
| Emploitic | DZ | allows | 200 | `__NEXT_DATA__.props.pageProps.searchResult` | 2 |
| Keejob | TN | allows (not `/api/`) | 200 | HTML list, JSON-LD detail | 2 |
| ReKrute | MA | allows | 200 | HTML list, JSON-LD detail | 2 |
| Qatar Living | QA | allows (not `/api/`) | 200 | HTML only, classifieds | 3 |
| for9a | JO/MENA | allows | 200 | Next.js, mostly trainings and scholarships | 3 (low value) |
| Dubai Careers | UAE gov | 404 (no robots file) | 200 | Taleo | 3 |
| WUZZUF, Forasna, Bayt, GulfTalent, Jobs.ps, Jadarat, Mihnati, Daleel Madani, Indeed AE | many | n/a | **403 Cloudflare** | n/a | partnership only |
| Akhtaboot, Jobzella, LinkedIn | many | **Disallow: /** | n/a | n/a | excluded (LinkedIn's existing scraper stays as-is; see Phase 0 §0.4) |

---

## 4. Architecture recap (what Sonnet must know about this repo)

These are the parts of the existing system that all four phases plug into. Read the referenced files before editing them.

### 4.1 Discovery flow

1. `POST /jobs/discover` in `apps/api/routers/jobs.py` resolves the region: `DiscoveryRequest.region`, then `users.discovery_region`, then `infer_region(preferred_locations)`. It then calls `workers/job_discovery.run_discovery_for_user(user_id, region, ...)`.
2. `workers/job_discovery.py`:
   - `SOURCE_REGISTRY: dict[str, Source]` lists every source. Each `Source(name, cls, api_based, requires_key, regions, login_capable, discoverable)` entry controls when that source runs.
   - `select_sources(region, preferred_platforms)` filters by `region in src.regions`. **Its first line currently coerces any region other than "india" or "global" to "india".**
   - For each `(query, location)` pair from `build_search_pairs`, it calls `scraper.search_jobs(query=, location=, max_results=, [credentials=], [region=])`. `_call_search` passes `region` only if the scraper's signature has that parameter.
   - Each batch is deduped against `existing_urls` and `existing_fps` (`services/dedup.job_fingerprint`), prefiltered (`services/prefilter.rejected_indices`) and persisted (`services/job_pipeline.persist_scraped_batch`), and then AI-scored by the durable pipeline.
   - After the run, `services/ats_harvester.harvest_from_db` mines the stored apply URLs for new ATS boards.
3. The scheduler (`apps/api/scheduler.py`) also calls `resolve_region(user)`.

### 4.2 Scraper conventions

- HTTP sources subclass `scrapers/api_base.APIBaseScraper`. They set `platform`, `requires_key`, `regions` and `rate_limit_per_minute`, implement `async search_jobs(...) -> list[JobListingCreate]`, and use `self._get_json` / `self._post_json` (rate-limited; they return `None` on failure and never raise) and `self._is_new(url)` for per-run URL dedup.
- For HTML or text responses there is no helper. Use `await self.rate_limiter.acquire()`, then `self._client.get(url, headers=...)`, inside a try/except that logs and returns. Mirror `_get_json`. (Phase 0 adds `_get_text`.)
- `scrapers/jsonld.py` has `parse_job_posting(html) -> dict` (job-model field names, only the fields that are present). Use it for every JSON-LD source.
- `JobListingCreate` (`models/job.py`) defaults `salary_currency="INR"`. **Every MENA scraper must set the currency explicitly** using the Phase 0 helper.
- Every new board needs: a `Platform` enum value (`models/job.py`), a DB enum value (a migration with `ALTER TYPE platform ADD VALUE IF NOT EXISTS '<name>'`), a `SOURCE_REGISTRY` entry, a `services/portals.py` `PORTALS` entry (tier "C", display only), and offline tests with a saved JSON or HTML fixture in `apps/api/tests/fixtures/`.
- Import the Phase 0 geo helpers as `from services.geo import mena`, then call `mena.is_mena(...)`, `mena.currency_for(...)` and so on. The phase docs use that `mena.` prefix throughout.
- ATS vendors are **not** separate sources. They are branches inside `scrapers/ats.py` (`_fetch_board`, plus a `_norm_<ats>` that returns the common dict) and `services/ats_harvester.py` (`_PATTERNS` and `_validate`). All of their jobs use `Platform.company_portal`.

### 4.3 Testing

- pytest is **not** in `requirements.txt` or the venv. Install it once with `apps/api/venv/Scripts/python.exe -m pip install pytest pytest-asyncio`.
- Run tests **from `apps/api`**, because they import `scrapers.*`, `services.*` and `workers.*` as top-level packages and there is no pytest.ini or conftest: `cd apps/api && ./venv/Scripts/python.exe -m pytest tests -q`.
- Some test modules import `workers.job_discovery`, which imports `database` and `config`. Those need `.env` values (`SUPABASE_URL` etc.) to construct settings. If collection fails on settings, export dummy values for the test run (`SUPABASE_URL=http://x SUPABASE_ANON_KEY=x SUPABASE_SERVICE_ROLE_KEY=x`).
- Tests must be **offline**. Save a real response as a fixture once (`apps/api/tests/fixtures/<source>_<sample>.json|html`, trimmed to 2–5 items), then test both the contract (expected keys exist) and the normalization. Follow `tests/test_ats_scraper.py` and `tests/test_jsonld.py`.

---

## 5. Ground rules (apply to every phase)

1. **Compliance first.** Use only (a) public ATS JSON APIs that power the employer's own careers site, (b) boards whose robots.txt allows the paths we fetch, or (c) licensed or keyed APIs. Never add Cloudflare or bot-wall bypasses for MENA boards. If a board returns a challenge page, log it, return `[]` and move on.
2. **Vacancy data only.** Never persist recruiter personal data from MENA sources. Oracle HCM detail responses include `ExternalContactEmail`, `ExternalContactName` and `HiringManager`: **drop them**. (Saudi PDPL and UAE PDPL; see the research doc's legal section.)
3. **Be polite.** Keep `rate_limit_per_minute` at 30 or below for boards and 60 or below for ATS APIs. Cap detail-page fetches per search (follow `DETAIL_FETCH_LIMIT` in `foundit.py`). Always send the `JobPlatformBot/1.0` UA unless an endpoint rejects it; foundit needs a browser UA, which is documented in that file.
4. **Never break `india` or `global`.** Every change to shared code (dedup, prefilter, region selection) must keep the existing tests green. Add new tests; do not edit old assertions unless a phase doc says so explicitly.
5. **Migrations are additive and idempotent.** `ADD VALUE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`, and drop-and-recreate for CHECK constraints. Run enum additions in their own file (see the header of `database/15_global_sources.sql`).
6. **Match the surrounding code style:** module docstrings that explain *why*, short inline comments, loguru `logger`, type hints.

---

## 6. Implementation notes (where the build differed from this plan)

These were verified against the live sites during implementation. They take precedence over the phase docs.

**Phase 0**
- The settings-page region selector (0.9, optional) was **skipped**. `PUT /profile/application` whitelists fields and excludes `discovery_region`, and the settings page writes straight to Supabase. To add it later, extend that whitelist and the web `User` type. The dashboard and Activity page buttons work.
- `mena.country_of`: a country name now beats any city, and with cities only the last one wins. Without this, "La Medina, Tunis" resolved to Saudi Arabia (Medina).

**Phase 1**
- Ashby tokens are case-insensitive, so the token is seeded as `leantech`. Lever `kitopi` is dead on both the US and EU hosts and was not added.
- Oracle paging was verified (`limit=100`, `offset`); the scraper does 2 list calls per board, capped at 200 jobs.
- For `region == "mena"`, ATS results are **round-robined across employers**, with a start position that rotates between searches. Discovery passes about 8 results per search, and board order would otherwise let the first Greenhouse boards take every slot. India and global ordering is unchanged.
- A remote job tagged EMEA/MENA/GCC passes on any MENA country search.
- `scripts/detect_ats.py` found no new supported boards among the 26 seed employers. Most of those load their ATS via JavaScript, so they are Phase 3 candidates.

**Phase 2**
- **ReKrute**: robots.txt disallows `/offres.html` for the AI and search crawlers it names, so discovery uses the declared `/sitemap.xml` (about 1.9k offer URLs), filters by slug and fetches at most 12 offers. The JSON-LD *does* have a `description`; the scraper prefers the HTML "Poste" and "Profil recherché" sections.
- **Emploitic**: labels are in `label`, the company is `company.name`, anonymous postings have no name, and paging is `&page=N` (20 per page). Job URLs are `/entreprises/{company.alias}/offres-d-emploi/{sector-slug}/{alias}`, taken from the page's JSON-LD ItemList. The bare `/offres-d-emploi/{alias}` URL redirects.
- **Keejob**: search ANDs all words, so there is a bounded single-word retry (at most 3 list requests). Detail JSON-LD can carry `baseSalary` with `unitText: MONTH`.
- **Sabbar**: about 11.8k of the 16k sitemap URLs have ASCII slugs, of which about 528 pass the tech-slug filter.
- Currency comes from the **board's country**, not the location string. All four boards scrub emails and phone numbers from `jd_text` (`scrapers/mena_common.scrub_contacts`).
- `jsonld.iter_ld_blocks` retries with `json.loads(strict=False)`, because some ReKrute pages have raw newlines inside JSON-LD strings.
- foundit Gulf is implemented but **not live-tested**. It sits behind `MENA_FOUNDIT_GULF_ENABLED=false`, and its fixture is hand-built.
- Keyed aggregators (Careerjet, JSearch, Jooble) are only unit-tested. The MENA locale and country codes still need checking once keys exist. There is an existing bug: Careerjet sets `salary_currency=None` for the global region, which fails validation once a key is set.

**Phase 3 build**
- A full MENA ATS load takes about **190 s** (1,295 jobs from 37 boards), because every board shares one 60 req/min limiter. The new detail caps were lowered for this: Taleo 8, Phenom 10, Avature 10. The real fix is a per-host rate limiter.
- SmartRecruiters seeds accept `sr_countries=(None,)`, which makes one unfiltered call for small boards instead of 9 per-country calls.
- Avature: the sitemap has no `lastmod` on JobDetail URLs, so they are sorted by numeric id. Expired postings and slugs marked "Nationals Only" or "Qatarization" are skipped. Non-MENA slugs are pre-dropped with a foreign-place word list.
- Sabbar now reads percent-encoded Arabic slugs. Arabic tech terms match whole hyphen-delimited tokens.

**Code review cleanup (after Phase 3)**
- Removed dead code: `mena.MENA_DEFAULT_LOCATIONS` and `mena.MENA_LOCATION_HINTS` (use `settings.MENA_DEFAULT_LOCATIONS` and `mena.is_mena()`), and `prefilter.prefilter_jobs()` (use `rejected_indices`). PHASE_0_FOUNDATIONS.md still mentions all three, so treat this note as current.
- `_get_text` treats a response as a bot challenge only when it is a 403/503 with Cloudflare markers, or a 200 carrying `cf-chl` or the "Just a moment" title. Cloudflare's normal `challenge-platform` beacon no longer counts as a block.
- The detail caps are back to Taleo 12, Phenom 15 and Avature 15 (per-host limiting keeps the load at about 70 s).
- Sabbar, Keejob and ReKrute share `mena_common.listing_fields()`. French country spellings now live in `MENA_COUNTRIES` aliases. `mena.names_mena_region()` is the single region-word check.
- Workable, SmartRecruiters and Recruitee descriptions now decode HTML entities (`&amp;` becomes `&`) through `strip_html`.
