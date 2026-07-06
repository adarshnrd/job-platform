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

6. **Careerjet API scraper** (free key, structured, India coverage) — ~half a day, same shape as adzuna.py.
7. **apna.co scraper** — city-page scrape for the tech categories; gate by role fit so it doesn't flood entry-level listings.
8. **BigShyft spike** (timeboxed 1 day) — if jobs aren't browsable without invite, mark C-tier and move on.

### Phase 2 — ATS-direct aggregation (5–8 days) ⭐ the multiplier

9. **`ats_boards` table** (company, ats_type, board_token, discovered_from, active, last_seen) + **token harvester**: regex-parse every `apply_url`/`source_url` we already store, backfill once, then harvest continuously during discovery.
10. **One generic `ATSBoardScraper`** with per-ATS adapters (greenhouse/lever/ashby/workable/smartrecruiters) that iterates active boards, filters by preferred cities + remote-India, and emits jobs into the normal pipeline. API-based, parallel, incremental via `updated_at` where offered.
11. **Seed list** of ~100 India-hiring companies per ATS to bootstrap before harvesting compounds.

### Phase 3 — Scale & reliability architecture (1–2 weeks, incremental)

12. **Source SDK**: declarative per-source config (regions, city-format mapping, rate limits, RSS/incremental support, role-fit tags) so adding a source is config + one class, and the registry/UI/docs derive from it.
13. **Smart scheduling**: telemetry source-health (built 2026-07-05) drives the scheduler — degraded sources get retried less often and flagged; healthy high-yield sources run more; per-source jitter to spread load.
14. **Volume controls**: rule-based prefilter (title/location/salary keywords) before LLM scoring so 5–10× more raw jobs doesn't mean 5–10× LLM cost (budget guardrails already enforce the ceiling); per-run per-source caps.
15. **Dedup upgrade**: same job appears on Naukri+LinkedIn+Adzuna+ATS — URL dedup no longer enough; add company+title+location fingerprint now, embedding dedup later (FUTURE_ROADMAP Horizon 2 item).
16. **Coverage dashboard**: sources active/total, jobs/day per city and per source (Mission Control data already collects this).

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
