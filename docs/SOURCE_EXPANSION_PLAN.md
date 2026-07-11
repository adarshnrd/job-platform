# Source Expansion Plan — Comprehensive India Job Aggregation

> **Status:** PLANNING — research complete (2026-07-05), awaiting approval before implementation.
> **Goal:** maximize reliable job coverage for Tier-1 India cities (Bangalore, Pune, Gurgaon, Noida, + Hyderabad/Chennai/Mumbai) for a senior software-engineering profile.
> **Companion docs:** `PORTAL_INTEGRATION_ROADMAP.md` (portal apply tiers), `FUTURE_ROADMAP.md` (Horizon 2 dedup/intelligence).

---

## 1. Diagnosis: why only 3 sources ran

The platform ships **24 scrapers**, but the last discovery run used only remoteok, remotive, themuse. Three independent gates caused this:

| # | Gate | Where | Effect |
|---|------|-------|--------|
| 1 | **Playwright scrapers are opt-in** — `select_sources()` includes them only if listed in the user's `preferred_platforms` | `workers/job_discovery.py:112` | Profile has `preferred_platforms: []` → **all 17 browser scrapers skipped** (naukri, linkedin, indeed, instahyre, hirist, iimjobs, timesjobs, shine, freshersworld, cutshort, foundit, wellfound, …). The `.get(key, default)` fallback to `["linkedin","naukri","indeed"]` never fires because the column exists (as `[]`) |
| 2 | **Keyed API sources are dormant** — adzuna, jooble, jsearch skip without keys | `job_discovery.py:103` | `.env` has no `ADZUNA_*`, `JOOBLE_API_KEY`, `JSEARCH_RAPIDAPI_KEY` → 3 more sources off |
| 3 | What's left = the 3 keyless API sources serving region "india" | registry | remoteok/remotive/themuse — all remote-job boards, hence 0 results for India-city queries |

**Additional latent bugs found during diagnosis:**

- **Only the first preferred location is ever searched** — `location = preferred_locations[0]` (`job_discovery.py:190`). Bangalore+Pune+Gurgaon+Noida can never be covered in one run today.
- **Region inference breaks on city names** — scheduler picks region "india" only if a location contains the substring `"india"` (`scheduler.py`). "Bangalore" doesn't → scheduled runs would flip to `global` and drop every India board the moment preferred_locations is set to actual cities.
- **Settings UI lists only 11 of 24 platforms** (`settings-client.tsx` `PLATFORMS`) — iimjobs, timesjobs, shine, freshersworld, ycombinator, dice, ziprecruiter can't even be enabled.
- Profile also has `preferred_locations: []` — so even location targeting is unset.

**Conclusion:** before adding a single new source, turning on and fixing what exists takes coverage from 3 → ~20 sources. That is Phase 0.

---

## 2. Research summary: the India source landscape

### 2.1 Aggregator APIs (highest reliability, zero anti-bot risk)

| API | India coverage | Cost | Notes |
|---|---|---|---|
| **Adzuna** | Yes (19 countries incl. IN) | Free dev tier | Scraper already built — just needs a key from developer.adzuna.com |
| **Jooble** | Yes | Free API key on request | Scraper already built |
| **JSearch (RapidAPI)** | Yes (`country=in`) — sources **Google for Jobs** | Free tier ~200 req/mo, paid tiers cheap | Scraper already built. This is effectively "Google for Jobs India" access |
| **Careerjet** | Yes (careerjet.co.in) | Free public search API (affiliate ID) | **New scraper needed** — simple REST |

### 2.2 ATS-direct aggregation (the structural multiplier) ⭐

Nearly every funded startup and tech MNC publishes jobs through an ATS with a **public, keyless JSON API**:

- **Greenhouse:** `GET boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true`
- **Lever:** `GET api.lever.co/v0/postings/{company}?mode=json` (supports location filters)
- **Ashby:** public posting API, `includeCompensation=true` gives salary
- Also: **Workable, SmartRecruiters, Recruitee** — same pattern.

Properties: structured JSON (title, location, department, description), no scraping brittleness, no CAPTCHAs, explicitly public (these APIs exist to power companies' own career pages). One "ATS source" = hundreds of companies once we have their board tokens.

**Where do tokens come from?** Two feeds:
1. **Harvest from our own data** — apply URLs we already collect from Wellfound/Cutshort/YC/RemoteOK frequently point to `boards.greenhouse.io/{token}`, `jobs.lever.co/{company}`, `jobs.ashbyhq.com/{org}`. Parse and persist tokens automatically → the company registry grows itself.
2. **Seed list** — one-time curated list of India-hiring tech companies per ATS (Razorpay, CRED, Zerodha, Postman, Atlassian India, etc. — easy to assemble, ~100 companies).

### 2.3 India-native platforms not yet covered

| Platform | What it is | Fit for this profile | Method |
|---|---|---|---|
| **apna.co** | India's largest mass-hiring platform (50M+ users); server-rendered city pages (e.g. `/jobs/jobs-in-bengaluru`, ~19k live) | Medium — mostly entry/mid ops roles, growing tech section | Scrape city pages (low anti-bot) |
| **BigShyft** | Info Edge's curated tech-talent platform (Noida) | Good for senior tech, but invite/curated model — jobs not freely browsable | Timebox a 1-day spike; likely C-tier |
| **TopHire** | Curated "top 2%" tech marketplace | Same — marketplace model, not a browsable board | Exclude (platform model incompatible) |
| **WorkIndia / Jobhai** | Blue-collar & entry-level mass boards | Poor for senior SWE | Exclude for this profile; note for future multi-user |
| **NCS (ncs.gov.in)** | Govt National Career Service; MOUs with Zomato/Zepto/Foundit | Low tech-role density; no public API found (state-level web services only) | Deprioritize — revisit if data.gov.in publishes a feed |
| **Hirect** | Chat-based hiring app | Mobile-app only (confirmed in portal roadmap) | Remains excluded |

### 2.4 City-specific reality check

There are no meaningful *city-exclusive* job boards for Bangalore/Pune/NCR tech roles — Indian tech hiring concentrates on national portals with city filters plus startup ecosystems (Wellfound/Cutshort/YC for Bangalore, iimjobs/Naukri for NCR corporates). **"City coverage" is therefore a query-routing problem (search every portal × every preferred city), not a new-portal problem.** That's what Phase 0's multi-location fan-out fixes.

---

## 3. The plan

### Phase 0 — Turn on what we already own (1–2 days) → 3 to ~20 sources

1. **Flip Playwright gating from opt-in to opt-out.** Region-appropriate scrapers run by default; `preferred_platforms` becomes an *exclusion-capable* preference (UI: "All sources (recommended)" vs explicit picks). Empty profile ⇒ full regional coverage, never silence.
2. **Multi-location fan-out.** Search every preferred location, not `[0]` — query × city matrix with a per-source results cap and per-city dedup. Profile gets seeded with Bangalore, Pune, Gurgaon, Noida (+ optional Hyderabad/Chennai/Mumbai).
3. **Fix region inference.** Map city names → region via a small constant (`{bangalore, bengaluru, pune, gurgaon, gurugram, noida, delhi, ncr, hyderabad, chennai, mumbai, kolkata, …} ⇒ india`); default india when ambiguous (matches this deployment).
4. **Activate the 3 dormant keyed APIs.** Register for free Adzuna + Jooble + JSearch (RapidAPI) keys → paste into `.env`. JSearch alone adds Google-for-Jobs India coverage.
5. **Sync the settings UI** to the full registry (auto-derive the platform list from a `/sources` endpoint instead of a hard-coded array — never drifts again).

### Phase 1 — New sources, ranked by ROI (3–5 days)

6. ✅ **DONE (2026-07-08): Careerjet API scraper** (`scrapers/careerjet.py`) — structured aggregator API, strong India coverage, `locale_code=en_IN`. Dormant keyed source (needs a free `CAREERJET_AFFID` from partners.careerjet.com) — same pattern as Adzuna/Jooble/JSearch. Added `careerjet` to the Platform enum + migration bundle + frontend labels. Strips HTML from descriptions. Tests in `tests/test_careerjet_scraper.py`.
7. **apna.co scraper** — DEFERRED. Evaluated: apna is a mass-hiring / entry-level-heavy board (blue-collar + junior white-collar). Low relevance for a senior SWE profile and it would flood the pipeline with off-target roles. Not worth building for the current single-user deployment; revisit if a multi-user / junior-profile use case appears. (The Phase-3 prefilter would gate it anyway.)
8. **BigShyft** — DEFERRED as C-tier: invite/curated model, jobs not freely browsable (per portal roadmap). Not a scrapeable board.

### Phase 2 — ATS-direct aggregation (5–8 days) ⭐ the multiplier — **STARTED 2026-07-07**

**Shipped (v1, seed-list):** `scrapers/ats.py` `ATSAggregatorScraper` — one source fanning out across public Greenhouse/Lever/Ashby JSON boards (keyless, no bot-walls). Verified live: **329 India jobs from 11 seed companies** (Postman, Groww, Druva, Netskope, PhonePe, HackerRank, MongoDB, GitLab, Elastic, Databricks on Greenhouse; Meesho on Lever). Registered as `ats` (api_based, region india, platform `company_portal`). Loads all boards once per run (concurrent), caches, filters each `search_jobs(query, location)` by India-location + query relevance (recall-first; LLM scoring is the precision gate). Offline fixture tests in `tests/test_ats_scraper.py`.

**Still to do (v2):** the `ats_boards` DB table + token harvester (parse `apply_url`/`source_url` we already store → auto-grow the company list), per-run incremental via `updated_at`, and a larger curated seed. Below is the original design.



9. ✅ **DONE (2026-07-07): One generic `ATSAggregatorScraper`** (`scrapers/ats.py`) — Greenhouse/Lever/Ashby per-ATS normalizers, fans out across all boards in parallel, filters to India + remote-India, emits into the normal pipeline. Browserless (APIBaseScraper), registered as the `ats` source (api_based, always-on). **20 verified India-hiring boards** yielding ~520 India jobs.
10. ✅ **DONE (2026-07-07): Token harvester** (`services/ats_harvester.py`) — regex-extracts Greenhouse/Lever/Ashby tokens from stored `apply_url`/`source_url`, validates each board resolves to live jobs, persists to `data/ats_boards.json`. Runs at the end of every discovery (`harvest_from_db`, bounded to 15 new/run); the ATS scraper loads seed ∪ harvested, so coverage compounds automatically. Chose a JSON store over an `ats_boards` table to stay local-first (no migration).
11. ✅ **Seed list** — 20 boards verified live (not ~100; many big India startups use non-Greenhouse/custom-token ATS, which is exactly what the harvester discovers over time rather than us guessing tokens).
12. ✅ **Content-level dedup** (`services/dedup.py` + `database/11_job_dedup.sql`) — normalized title+company fingerprint (`dedupe_key`) collapses reposts across boards/cities; graceful pre-migration fallback in `_upsert_job_listing`.

### Phase 3 — Scale & reliability architecture (1–2 weeks, incremental)

12. ✅ **DONE (2026-07-08): Declarative source metadata** — `Source` now carries a derived `kind` (ats/api/browser) alongside the existing declarative fields (regions, api_based, requires_key, login_capable, discoverable). The registry stays one `Source(...)` line per source; `/discovery/sources` and the coverage view derive from it. (A full plugin-manifest SDK is deferred as over-engineering for a first-party registry — the declarative registry already delivers the "config + one class" goal.)
13. ✅ **DONE (2026-07-08): Health-driven scheduling** — `services/source_scheduler.py` `plan_sources()` uses telemetry source-health to back off hard-broken sources (`consecutive_errors`) with a recovery probe every Nth run, and orders healthy high-baseline-yield sources first. Conservative: never skips user-pinned sources, `yield_drop` (still-yielding) sources, or sources with insufficient history. Wired into `_discover_for_user_async`; toggles `DISCOVERY_HEALTH_SCHEDULING_ENABLED` / `SOURCE_ERROR_BACKOFF_PROBE_EVERY`. Tests `tests/test_source_scheduler.py`.
14. ✅ **DONE (2026-07-08): Volume controls** — `services/prefilter.py`, a deterministic recall-first relevance gate that runs *before* LLM parse/score (`DISCOVERY_PREFILTER_ENABLED`, default on). Matches the user's distinctive skills (as whole phrases — never decomposed, so "Express.js" ≠ "express interest") against title+skills+JD, plus generic tech-role vocabulary against the title only. Drops clearly off-profile roles (sales/HR/finance/content); verified live dropping ~28% of the ATS flood with zero false drops. This is what makes the 520-job ATS source affordable through dual-LLM double-eval. Tests in `tests/test_prefilter.py`.
15. ✅ **"Now" part DONE; embedding part = Horizon 2.** The company+title fingerprint (`services/dedup.py`, migration 11) shipped in Phase 2 and collapses reposts across boards/cities. True *semantic* dedup (same role, differently worded across portals) needs an embedding model + pgvector and is explicitly a FUTURE_ROADMAP Horizon-2 item — intentionally **not** bolted on here, because naive fuzzy title-matching risks merging genuinely distinct roles (e.g. "Backend Engineer" vs "Backend Engineer II"). The conservative exact-fingerprint is the correct current-phase deliverable.
16. ✅ **DONE (2026-07-08): Coverage dashboard** — `GET /telemetry/coverage` aggregates the registry + source-health + per-source 14-day contribution + the scheduling decision the next run would make (running / probing / backed-off / needs-key / display-only). Surfaced in Mission Control's Source-health tab as a "Source coverage" panel (active/total tiles, per-source status badges, 14-day contribution bars). Verified live: 10 active / 26 registered, with real contribution (Naukri 165, LinkedIn 150, TimesJobs 96, Hirist 58, ATS 37…). Tests `tests/test_coverage_endpoint.py`.

---

## 4. Expected outcome

| Stage | Active sources | Est. relevant jobs/day (4 cities, senior SWE) |
|---|---|---|
| Today | 3 (all remote-only boards) | ~0–5 |
| After Phase 0 | ~20 | 100–300 |
| After Phase 1 | ~23 | +20–50 |
| After Phase 2 | 23 + hundreds of ATS boards | +50–150 (highest-quality: direct from company careers pages) |

## 5. Phase 0 field results (2026-07-05, verified live)

Phase 0 was implemented and live-tested the same day. Empirical scraper matrix
(`search_jobs("Node.js", "Bangalore")`, real-Chrome channel):

| Board | Result | Notes |
|---|---|---|
| naukri | ✅ works, **headed only** | Akamai serves "Access Denied" to every headless browser (incl. real-Chrome headless). `requires_headed = True` opens a visible window — acceptable local-first tradeoff. Selectors were fine all along. |
| linkedin | ✅ works headless | Only with `channel="chrome"` — bundled Chromium timed out. |
| shine | ✅ works headless | Low yield per query but real results. |
| indeed | ❌ blocked | Cloudflare 403 at HTTP level — assisted/JSearch path only (as roadmap predicted). |
| timesjobs | ✅ **fixed** | Migrated to Next.js SPA — rewrote as browserless API scraper against `POST tjapi.timesjobs.com/search/api/v1/search/jobs/list`. |
| hirist, iimjobs | ✅ **fixed** | React SPAs (Info Edge). Both use the same public gladiator JSON API `GET gladiator.<site>/job/search?query=…` (the `query=` param was the key; earlier `keyword=` attempts 404'd). Rewrote both browserless via a shared `InfoEdgeGladiatorScraper` base. iimjobs is a management board — hands-on tech queries legitimately return few results. |
| indeed, foundit, instahyre, freshersworld, cutshort, wellfound | 🟥 **C-tier (retired from discovery)** | Hard bot-walls: Cloudflare (indeed, instahyre), Access-Denied 403 even headed (foundit, freshersworld), auth-gated (cutshort), PerimeterX (wellfound). Marked `discoverable=False` — still registered for display/apply, but skipped in discovery so they stop burning run time. Recoverable later only via stealth/residential proxies or session-authenticated adapters. |

**Infrastructure added:** `PLAYWRIGHT_CHANNEL="chrome"` (fall back to bundled), per-scraper `requires_headed` flag, `SCRAPER_ALLOW_HEADED` global switch, and a `Source.discoverable` flag (C-tier boards skip discovery). Spoofed UA now applied only on bundled Chromium (a Windows UA on real macOS Chrome is itself a fingerprint mismatch). New shared base `scrapers/infoedge_base.py` for the gladiator API family.

**Net result:** India discovery went from 3 → **12 working sources** (naukri, linkedin, shine browser + timesjobs, hirist, iimjobs, remoteok, remotive, themuse API + adzuna/jooble/jsearch once keyed). Three of the four best India tech boards (Naukri, Hirist, TimesJobs) now run browserless or headed and verified returning real Bangalore/Pune/etc. jobs.

**Takeaway for Phase 2:** the boards that fixed cleanly were the ones with JSON APIs (timesjobs, hirist, iimjobs); the ones that stayed broken were all DOM-scrape bot-walls. This is exactly why ATS-direct JSON aggregation should be the next investment — no fingerprints, no selectors, no walls.

## 6. Risks & guardrails

- **Anti-bot on browser scrapers** (LinkedIn/Indeed/Glassdoor high; Naukri/Shine medium): keep per-source caps, staggered runs, graceful degradation — health monitoring now flags breakage same-day.
- **LLM cost growth**: prefilter + daily budget hard-stop (already live) + per-run eval caps.
- **ToS**: aggregator APIs and ATS public APIs are licensed/intended access — prefer them over scraping wherever both exist; keep scrape rate human-scale elsewhere.
- **Noise from mass boards** (apna): role-fit gating per source; off by default for senior profiles.
