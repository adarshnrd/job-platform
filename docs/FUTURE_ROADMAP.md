# Future Roadmap — From Auto-Apply Tool to Career Operating System

> **Status:** VISION / PLANNING — companion to `PORTAL_INTEGRATION_ROADMAP.md` (tactical, phases 0–3 shipped).
> **Date:** 2026-07-04 · reflects the post-phase-3 codebase (Answer Bank, 6 session adapters, live activity feed).
> **Scope:** everything *beyond* the current portal initiative — short-term consolidation through multi-year vision.

---

## 1. Vision

Today the platform answers one question well: **"Which jobs match me, and can a bot apply to them?"**

The end state this roadmap works toward is broader — a **personal career operating system** that owns the entire loop:

```
discover → qualify → tailor → apply → track replies → schedule interviews →
prep → negotiate → accept → (repeat, smarter each cycle)
```

Each horizon below moves one ring outward from the current core, and each ships standalone user value — nothing depends on a "big bang."

**Guiding principles (carried from the codebase, non-negotiable):**

1. **Local-first, single-user by default.** Everything must run on one machine, 10am–9pm. Cloud/multi-tenant is an *optional* deployment mode (Horizon 4), never a prerequisite.
2. **Never fabricate.** The Answer Bank pause-don't-guess model extends to every new feature (resumes, negotiations, emails).
3. **Human-in-the-loop for consequential actions.** Auto-apply is opt-in per tier; anything that *represents the user to another human* (emails, negotiation, messages to founders) is draft-and-approve by default.
4. **Account safety over throughput.** Per-platform caps, human-like pacing, and "assisted" fallbacks are features, not limitations.

---

## 2. Where We Are (2026-07-04)

| Layer | State |
|---|---|
| **Discovery** | 23+ scrapers (India + global), region-aware registry, keyed-source auto-skip, live progress feed (`/activity`) |
| **Scoring** | Dual-LLM (Groq + NVIDIA), double-eval ≥70, tiering auto/recommended/watchlist |
| **Apply** | 6 session adapters (LinkedIn, Naukri, Instahyre, Foundit, Hirist, Cutshort) + generic Playwright filler; assisted flow; Answer Bank (detect → fill → pause → persist → reuse) |
| **Post-apply** | Follow-up email drafts, weekly digest, Excel tracker, interview prep packs, skill-gap analysis, career copilot chat |
| **Infra** | FastAPI + APScheduler in-process, Supabase, Fernet-encrypted sessions, Next.js 14 frontend, 30+ tests |

**Carried debt (from portal roadmap phases 4–5, not yet done):** stale-listing lifecycle completion, analytics snapshots, confirmation screenshots, legacy `platform_credentials` retirement, `.in_()` batching, stale README/PROJECT_DOCUMENTATION.

---

## 3. Horizon 1 — Consolidate & Instrument (0–1 month, ≈15–20 dev-days)

*Goal: make the machine we already built observable, trustworthy, and finished.*

### 3.1 Finish the portal initiative (carry-over)
- Ship remaining phase-4/5 items: YC adapter completion, Wellfound/Indeed assisted modes, stale-listing cleanup UI, legacy credential retirement.
- Refresh README + PROJECT_DOCUMENTATION to the APScheduler/session-auth reality.

### 3.2 Observability & cost control ("mission control")
- **Run ledger**: persist every discovery/apply run with per-source timings, error rates, LLM token usage and $ cost (Groq/NVIDIA price tables). Surface in `/activity` as history, not just live state.
- **Scraper health dashboard**: per-source success-rate sparkline over 14 days; auto-flag a source when yield drops >70% vs. its baseline (the earliest possible signal of selector drift).
- **LLM budget guardrails**: daily token budget, per-feature attribution (scoring vs. cover letters vs. copilot), hard stop + notification when exceeded.

### 3.3 Proof-of-application
- Screenshot + DOM snapshot at submit time, stored per application; "View proof" in the application detail UI. This is the single biggest trust feature for auto-apply — the user should never wonder *"did it really apply, and what did it say about me?"*
- Full form-payload replay: exactly which answers/files were submitted (extends `application_events`).

### 3.4 Test & resilience hardening
- Golden-file tests for every scraper (recorded HTML/JSON fixtures) so parser breakage is caught by CI, not by a silent 0-result run.
- Crash-recovery sweep already exists for `applying` rows — add the same for half-finished discovery runs and orphaned Playwright processes.

**Why first:** every later horizon (self-healing scrapers, learning loop, autonomy) needs this telemetry as its substrate.

---

## 4. Horizon 2 — Intelligence (1–3 months, ≈30–40 dev-days)

*Goal: stop treating every job and every application as independent. Close the feedback loop.*

### 4.1 Resume tailoring engine ⭐ (highest-leverage single feature)
- Per-application tailored resume: reorder/reweight bullets against the JD, inject exact keyword phrasing for ATS matching — **from the user's real experience only** (anti-fabrication: it may rephrase and reorder, never invent).
- Resume versioning: base resume + generated variants stored per application; diff view so the user sees exactly what changed.
- ATS-score preview (keyword coverage %, section checks) before submission.
- Adapter capability flag: portals that accept per-application uploads get the tailored file; profile-hosted portals (Naukri etc.) get a "sync suggestion" instead.

### 4.2 Outcome feedback loop (the moat)
- Track terminal outcomes per application: no-reply / rejected / recruiter-viewed / interview / offer (fed manually at first, by email parsing in 4.3).
- **Score calibration**: correlate match-score vs. actual response rate per source/title/company-size; recalibrate the tiering thresholds from data instead of the fixed 80/60/50.
- Learn from user behavior signals already available: dismissals, watchlist promotions, which drafted answers get edited before approval.
- Weekly "what's working" report: which sources, titles, and resume variants actually convert.

### 4.3 Email integration (Gmail API / IMAP) ⭐
- Read-only inbox watcher classifies incoming mail: rejection / interview invite / recruiter question / OTP.
- Auto-update application status (closing the loop 4.2 needs), attach the email thread to the application timeline.
- Interview invites → extract date/time → propose calendar event (Google Calendar).
- OTP capture assists session-handshake logins for portals that email login codes.
- *Strictly read + draft; never auto-send replies without approval (principle 3).*

### 4.4 Job-market intelligence
- **Cross-portal dedup by embedding**: the same job on Naukri + LinkedIn + Indeed collapses into one canonical listing with "found on 3 portals" (apply via the cheapest/safest channel). Uses pgvector on Supabase.
- **Ghost-job / spam detection**: repost-frequency, staffing-agency fingerprints, salary-absent + evergreen postings → confidence flag shown on the card, factored into ranking.
- **Company enrichment**: funding stage, headcount trend, layoffs history, Glassdoor rating pulled per company once and cached; a "company dossier" tab on the job detail page.
- **Salary intelligence**: aggregate the salary bands the platform already scrapes into title × city × experience percentile bands; show "this offer is P40 for your profile."

### 4.5 Semantic search & saved searches
- Natural-language job search over the local corpus ("remote-first fintech, Series B+, ₹35L+, no US-shift") powered by the same embeddings as dedup. Saved searches become standing discovery filters.

---

## 5. Horizon 3 — Autonomy & Reach (3–6 months, ≈40–55 dev-days)

*Goal: apply anywhere, not just on integrated portals — and expand from applying to interviewing.*

### 5.1 Universal ATS agent ⭐ (biggest coverage multiplier)
The long tail of "external apply" links overwhelmingly resolve to ~6 ATS platforms: **Greenhouse, Lever, Workday, Ashby, SmartRecruiters, Zoho Recruit**. Unlike job boards, these are *structurally standardized* and mostly anti-bot-light:
- Build ATS adapters the same way as portal adapters (detect ATS from URL/DOM → structured fill → Answer Bank for custom questions).
- Fallback tier: **vision-based form agent** — screenshot → LLM identifies fields → maps to profile/Answer Bank → fills → pauses on anything unknown or on CAPTCHA (never solve CAPTCHAs automatically; escalate to the user).
- This converts thousands of currently "link-out only" jobs (RemoteOK, WeWorkRemotely, YC externals, Google-for-Jobs results) into automatable ones.

### 5.2 Self-healing scrapers
- When the Horizon-1 health monitor flags a source: capture the new page HTML, have an LLM propose updated selectors, validate against golden-files, open a "repair PR" (local branch) for one-click human approval. Scrapers stop being permanent maintenance debt.

### 5.3 Companion browser extension
- Capture portal sessions without the handshake dance (one click on any logged-in tab).
- "Save to platform" on any job page anywhere on the web → enters the normal scoring pipeline.
- On any application form: overlay that fills from profile/Answer Bank — the assisted-apply experience, but on *every* site, driven by the same question-matcher service.

### 5.4 Mobile command channel (Telegram/WhatsApp bot) ⭐ for the "approve from anywhere" moment
- Push: "3 new auto-apply-tier jobs", "Application paused — needs an answer: *Expected CTC?*", "Interview invite from Acme, Tue 3pm — accept?"
- Reply in chat to answer paused questions (feeds the Answer Bank), approve applications, or snooze. This makes the 10am–9pm local machine feel like a 24/7 service without any cloud migration.

### 5.5 Interview pipeline
- Kanban stage tracking beyond "applied": screening → rounds → offer, with per-round notes.
- **Prep packs v2**: auto-generated from JD + company dossier + the user's actual resume variant that was submitted; likely questions with STAR-story suggestions drawn from the user's profile.
- **Mock interview mode**: copilot runs a timed Q&A session (text first; voice via Web Speech API later), scores answers against the JD, tracks improvement across sessions.
- Post-interview debrief capture → feeds the outcome loop (4.2).

### 5.6 Referral & network assist
- For each shortlisted job: surface 1st/2nd-degree LinkedIn connections at the company (session already exists) and draft a personalized referral-request message — *draft only, user sends*.

---

## 6. Horizon 4 — Platform & Scale (6–12+ months, visionary)

*Goal: optionally outgrow "one machine, one user" without betraying local-first defaults.*

### 6.1 Deployment tiers
- **Tier 0 (today):** single process, one machine, APScheduler.
- **Tier 1:** dockerized split (api / worker / browser pool) on the same machine — resilience without cloud.
- **Tier 2 (opt-in SaaS/multi-user):** re-introduce a real queue (the Celery removal was right for Tier 0; Tier 2 justifies it), per-tenant encryption keys, worker autoscaling, headless browser farm with residential-proxy pools. Household/coaching use case: one deployment, several candidates.

### 6.2 Career OS features
- **Skill-gap → learning loop**: the existing skill-gap analysis gains teeth — recommend specific courses/projects, track completion, and measure whether closing a gap moves the response-rate needle (via 4.2 data).
- **Offer management & negotiation copilot**: side-by-side offer comparison (comp, equity, growth), negotiation email drafts backed by the salary-intelligence percentiles.
- **Career trajectory planning**: "you're 2 skills and 1 title away from X" — long-range planning grounded in the corpus of thousands of real, scored JDs the platform accumulates.

### 6.3 Ecosystem
- **Public REST API + webhooks** (the FastAPI layer is 80% there): let users pipe events into Notion, Sheets, n8n.
- **Adapter plugin SDK**: portal/ATS adapters as installable plugins with a manifest (capabilities, caps, risk tier) — community-maintained coverage instead of first-party-only.
- **Local LLM option (Ollama)**: scoring and question-matching on a local model for zero marginal cost and full privacy; cloud LLMs reserved for high-stakes generation (cover letters, negotiation). Provider abstraction in `services/ai/provider.py` already makes this a clean seam.

### 6.4 Voice & ambient
- Morning voice briefing ("6 new matches, 2 need answers, interview at 3"), voice mock interviews, hands-free approve/dismiss via the Telegram bot.

---

## 7. Cross-Cutting Tracks (run through every horizon)

| Track | Items |
|---|---|
| **Performance** | Playwright context pooling; incremental discovery (only re-scrape sources whose feeds changed); RSS/sitemap deltas where available; embedding cache; move run-history from JSON file to a table before it grows unbounded |
| **Security & trust** | Retire plaintext `platform_credentials` (H1); per-feature audit log UI; one-click full data export; encrypted backups of profile + Answer Bank; secrets scanning in CI |
| **Quality** | Golden-file scraper tests (H1) → contract tests per adapter → nightly canary run against live portals with alerting |
| **Docs** | Fix stale README/PROJECT_DOCUMENTATION (H1); per-adapter runbooks; architecture decision records for the big pivots (queue re-introduction, embeddings, extension) |

---

## 8. Suggested Sequencing & Effort

| Order | Item | Horizon | Effort | Rationale |
|---|---|---|---|---|
| 1 | Finish portal phases 4–5 + docs refresh | H1 | 6–8 d | Close the open initiative |
| 2 | Run ledger + scraper health + LLM cost tracking | H1 | 5–6 d | Substrate for everything later |
| 3 | Proof-of-application (screenshots + payload replay) | H1 | 3–4 d | Trust in auto-apply |
| 4 | Resume tailoring engine | H2 | 8–10 d | Highest per-application impact |
| 5 | Email integration + outcome tracking | H2 | 8–10 d | Closes the feedback loop |
| 6 | Score calibration from outcomes | H2 | 4–5 d | Depends on #5 data |
| 7 | Embedding dedup + semantic search | H2 | 5–6 d | Shared pgvector foundation |
| 8 | Ghost-job detection + company enrichment | H2 | 5–6 d | Ranking quality |
| 9 | Universal ATS agent (Greenhouse/Lever first) | H3 | 12–15 d | Coverage multiplier |
| 10 | Telegram approval bot | H3 | 4–5 d | Mobility without cloud |
| 11 | Self-healing scrapers | H3 | 6–8 d | Kills maintenance debt |
| 12 | Interview pipeline + mock mode | H3 | 8–10 d | Expands past "applied" |
| 13 | Browser extension | H3 | 10–12 d | Universal assisted apply |
| 14+ | Horizon 4 items | H4 | scoped per-item | Re-plan after H2/H3 learnings |

**Decision gates:** after H2, the outcome data (item 6) should decide whether the next investment is *more coverage* (item 9) or *better conversion* (double down on tailoring/prep). Don't pre-commit.

---

## 9. Risks & Watch Items

- **Portal ToS / account safety**: the more autonomous the applying, the more valuable per-platform caps and assisted fallbacks become. Every new automation ships behind a per-portal risk tier and opt-in toggle.
- **LLM cost creep**: embeddings + tailoring + mock interviews multiply token use — hence budget guardrails in H1 *before* the intelligence features land, and the Ollama option in H4.
- **Feedback-loop sample size**: a single user generates sparse outcome data; calibration (item 6) must use robust priors and never over-fit to a dozen applications.
- **Scope gravity**: the extension, the bot, and the ATS agent are each mini-products. Each must reuse the existing services (question-matcher, Answer Bank, profile) rather than fork logic — the architecture seams for this already exist and should be treated as contracts.
