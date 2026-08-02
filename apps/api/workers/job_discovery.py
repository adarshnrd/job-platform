"""
Job Discovery — searches platforms, scores jobs using dual-API parallel evaluation.
Runs directly via FastAPI BackgroundTasks (no Redis/Celery needed).

Sources are organized in a region-aware registry. Each entry declares whether
it is API-based, whether it needs a key (auto-skipped when absent), and which
regions ("india" / "global") it serves.
"""
import asyncio
import inspect
from datetime import datetime
from loguru import logger
from database import get_db, select_in_batches
from services.ai import batch_parse_jds, batch_score_jobs
# Playwright (browser) scrapers — brittle, login-capable
from scrapers.linkedin import LinkedInScraper
from scrapers.naukri import NaukriScraper
from scrapers.indeed import IndeedScraper
from scrapers.wellfound import WellfoundScraper
from scrapers.hirist import HiristScraper
from scrapers.instahyre import InstahyreScraper
from scrapers.foundit import FounditScraper
from scrapers.cutshort import CutshortScraper
from scrapers.remoteok import RemoteOKScraper
from scrapers.weworkremotely import WeWorkRemotelyScraper
from scrapers.glassdoor import GlassdoorScraper
from scrapers.dice import DiceScraper
from scrapers.ziprecruiter import ZipRecruiterScraper
from scrapers.iimjobs import IimjobsScraper
from scrapers.timesjobs import TimesJobsScraper
from scrapers.shine import ShineScraper
from scrapers.freshersworld import FreshersworldScraper
from scrapers.ycombinator import YCombinatorScraper
# API-first sources — stable, no browser
from scrapers.remotive import RemotiveScraper
from scrapers.arbeitnow import ArbeitnowScraper
from scrapers.themuse import TheMuseScraper
from scrapers.adzuna import AdzunaScraper
from scrapers.jooble import JoobleScraper
from scrapers.jsearch import JSearchScraper
from scrapers.careerjet import CareerjetScraper
from scrapers.jobicy import JobicyScraper
from scrapers.himalayas import HimalayasScraper
from scrapers.ats import ATSAggregatorScraper
# Global-first sources (phase: global expansion)
from scrapers.arc import ArcScraper
from scrapers.welcometothejungle import WelcomeToTheJungleScraper
from scrapers.peerlist import PeerlistScraper
from scrapers.flexjobs import FlexJobsScraper
from config import settings
from services import discovery_progress as progress
from services import job_pipeline as pipeline
from services.dedup import job_fingerprint
from services.experience import merge_experience

db = get_db()


class Source:
    """A discovery source and its routing metadata."""
    def __init__(self, name, cls, api_based, requires_key, regions, login_capable=False, discoverable=True):
        self.name = name
        self.cls = cls
        self.api_based = api_based
        self.requires_key = requires_key
        self.regions = regions
        self.login_capable = login_capable
        # C-tier boards (hard bot-walls) stay registered for display/apply but
        # are skipped during discovery so they don't burn run time yielding nothing.
        self.discoverable = discoverable

    @property
    def kind(self) -> str:
        """Declarative source class for UI/telemetry: ats | api | browser."""
        if self.name == "ats":
            return "ats"
        return "api" if self.api_based else "browser"


# Registry of every source. `regions` controls when each is used.
SOURCE_REGISTRY: dict[str, Source] = {
    # ── Playwright / login scrapers (India market) ──
    "naukri":         Source("naukri", NaukriScraper, False, False, {"india"}, login_capable=True),
    "linkedin":       Source("linkedin", LinkedInScraper, False, False, {"india", "global"}, login_capable=True),
    "indeed":         Source("indeed", IndeedScraper, False, False, {"india", "global"}, login_capable=True, discoverable=False),
    "instahyre":      Source("instahyre", InstahyreScraper, False, False, {"india"}, login_capable=True, discoverable=False),
    "shine":          Source("shine", ShineScraper, False, False, {"india"}),
    "freshersworld":  Source("freshersworld", FreshersworldScraper, False, False, {"india"}, discoverable=False),
    "cutshort":       Source("cutshort", CutshortScraper, False, False, {"india"}, discoverable=False),
    # Wellfound's bot wall rejects headless *and* headed browsers alike, so the
    # scraper is a documented no-op; kept registered for display/assisted apply.
    "wellfound":      Source("wellfound", WellfoundScraper, False, False, {"india", "global"}, discoverable=False),
    "ycombinator":    Source("ycombinator", YCombinatorScraper, False, False, {"global"}),
    # Headed-browser sources: they load only in a visible window, and their
    # detail pages still withhold JD text, so both are opt-in rather than part
    # of a default run (see each scraper's module docstring).
    "peerlist":       Source("peerlist", PeerlistScraper, False, False, {"global", "india"}, discoverable=False),
    "flexjobs":       Source("flexjobs", FlexJobsScraper, False, False, {"global"}, discoverable=False),
    # Renders client-side but with stable data-testid hooks; carries pay bands,
    # seniority and skills inline, and serves country-scoped boards.
    "arc":            Source("arc", ArcScraper, False, False, {"global"}),
    # Hybrid: browser clears the WAF, then HTTP for sitemaps + JSON-LD details.
    "welcometothejungle": Source(
        "welcometothejungle", WelcomeToTheJungleScraper, False, False, {"global"}
    ),
    "glassdoor":      Source("glassdoor", GlassdoorScraper, False, False, {"global"}),
    "dice":           Source("dice", DiceScraper, False, False, {"global"}),
    "ziprecruiter":   Source("ziprecruiter", ZipRecruiterScraper, False, False, {"global"}),
    # ── API-first keyless sources ──
    # Foundit runs off the site's own /middleware/jobsearch JSON API (the HTML
    # search is Akamai-walled). One deployment per country shares that API, so
    # it serves both regions.
    "foundit":        Source("foundit", FounditScraper, True, False, {"india", "global"}),
    "remoteok":       Source("remoteok", RemoteOKScraper, True, False, {"global", "india"}),
    # RSS-based — no browser, despite the board itself being Cloudflare-fronted.
    "weworkremotely": Source("weworkremotely", WeWorkRemotelyScraper, True, False, {"global"}),
    "remotive":       Source("remotive", RemotiveScraper, True, False, {"global", "india"}),
    "timesjobs":      Source("timesjobs", TimesJobsScraper, True, False, {"india"}),
    "hirist":         Source("hirist", HiristScraper, True, False, {"india"}),
    "iimjobs":        Source("iimjobs", IimjobsScraper, True, False, {"india"}),
    # ATS-direct: many company career boards (Greenhouse/Lever/Ashby) in one
    # source. Region-aware: india runs keep only India roles, global runs keep
    # the overseas postings those same boards carry.
    "ats":            Source("ats", ATSAggregatorScraper, True, False, {"india", "global"}),
    "arbeitnow":      Source("arbeitnow", ArbeitnowScraper, True, False, {"global"}),
    "themuse":        Source("themuse", TheMuseScraper, True, False, {"india", "global"}),
    "jobicy":         Source("jobicy", JobicyScraper, True, False, {"global", "india"}),
    "himalayas":      Source("himalayas", HimalayasScraper, True, False, {"global", "india"}),
    # ── API-first keyed sources (dormant until keys set) ──
    "adzuna":         Source("adzuna", AdzunaScraper, True, True, {"india", "global"}),
    "jooble":         Source("jooble", JoobleScraper, True, True, {"india", "global"}),
    "jsearch":        Source("jsearch", JSearchScraper, True, True, {"india", "global"}),
    "careerjet":      Source("careerjet", CareerjetScraper, True, True, {"india", "global"}),
}

def select_sources(region: str, preferred_platforms: list[str]) -> list[Source]:
    """
    Pick the active sources for a region.

    - Always includes API-first sources serving the region (keyed ones only if
      their key is present).
    - Playwright scrapers are opt-OUT: with no explicit `preferred_platforms`,
      every regional scraper runs (public, unauthenticated search — login only
      matters at apply time). A non-empty list narrows to that subset.
    """
    region = region if region in ("india", "global") else "india"
    selected: dict[str, Source] = {}

    for name, src in SOURCE_REGISTRY.items():
        if region not in src.regions:
            continue
        # C-tier boards are display/apply-only — never discovered.
        if not src.discoverable:
            continue
        # Keyed sources need a valid key.
        if src.requires_key and not _has_key(src.cls):
            continue
        # API-first sources (keyless, or keyed with key present) are always on.
        if src.api_based:
            selected[name] = src
        # Playwright sources: all by default; user list narrows the set.
        elif not preferred_platforms or name in preferred_platforms:
            selected[name] = src

    return list(selected.values())


# Location tokens that mark a profile as India-based. Substring match,
# lowercase — covers city spellings the portals themselves use.
INDIA_LOCATION_HINTS = (
    "india", "bangalore", "bengaluru", "pune", "gurgaon", "gurugram",
    "noida", "delhi", "ncr", "hyderabad", "chennai", "mumbai", "kolkata",
    "ahmedabad", "jaipur", "indore", "kochi", "trivandrum", "chandigarh",
)


def infer_region(preferred_locations: list[str] | None) -> str:
    """Region for a user's locations. City names imply india; empty defaults
    to india (this is an India-first deployment).

    Inference only — `resolve_region` applies the user's explicit choice first.
    """
    locations = [loc for loc in (preferred_locations or []) if loc]
    if not locations:
        return "india"
    for loc in locations:
        low = loc.lower()
        if any(hint in low for hint in INDIA_LOCATION_HINTS):
            return "india"
    return "global"


def resolve_region(user: dict | None) -> str:
    """The region a discovery run should use for `user`.

    An explicit `discovery_region` on the profile wins. It exists because
    inference cannot express intent: someone living in Bengaluru who wants to
    relocate to Berlin has India cities in `preferred_locations`, so
    `infer_region` would pin them to India forever and never reach the
    global-only sources. Anything other than a recognised value falls back to
    inference, so an unset or stale column behaves exactly as before.
    """
    user = user or {}
    choice = str(user.get("discovery_region") or "").strip().lower()
    if choice in ("india", "global"):
        return choice
    return infer_region(user.get("preferred_locations"))


def build_search_pairs(
    queries: list[str],
    locations: list[str],
    cap: int,
    offset: int = 0,
) -> list[tuple[str, str]]:
    """(query, location) pairs for one source, capped to keep runs bounded.

    Locations vary in the outer loop so the cap never starves a city of every
    query. When capped, `offset` rotates the starting pair so successive runs
    walk the full matrix instead of always searching the same slice.
    """
    pairs = [(q, loc) for loc in locations for q in queries]
    if not pairs or len(pairs) <= cap:
        return pairs
    offset = offset % len(pairs)
    return (pairs[offset:] + pairs[:offset])[:cap]


def _has_key(cls) -> bool:
    """True if a keyed source has its credentials configured."""
    has = getattr(cls, "has_key", None)
    return bool(has()) if callable(has) else True


def _portal_auto_appliable(platform: str) -> bool:
    """Deprecated shim — use services.portals.auto_appliable."""
    from services.portals import auto_appliable
    return auto_appliable(platform)


async def _call_search(scraper, *, query, location, max_results, credentials, region):
    """Call search_jobs passing only the kwargs the scraper actually accepts."""
    params = inspect.signature(scraper.search_jobs).parameters
    kwargs = {"query": query, "location": location, "max_results": max_results}
    if "credentials" in params:
        kwargs["credentials"] = credentials
    if "region" in params:
        kwargs["region"] = region
    return await scraper.search_jobs(**kwargs)


def run_discovery_for_user(user_id: str, region: str = "india", trigger: str = "manual", run_id: str | None = None):
    """Entry point called by FastAPI BackgroundTasks. The /jobs/discover endpoint
    pre-creates the run so it can return the run_id immediately; scheduled runs
    create it here."""
    run_id = run_id or progress.start_run(user_id, region, trigger)
    try:
        asyncio.run(_discover_for_user_async(user_id, region, run_id))
        progress.finish_run(run_id)
    except Exception as e:
        logger.error(f"Discovery failed for user {user_id}: {e}")
        progress.finish_run(run_id, status="failed", error=str(e))


async def _discover_for_user_async(user_id: str, region: str = "india", run_id: str = ""):
    user_res = db.table("users").select("*").eq("id", user_id).single().execute()
    if not user_res.data:
        logger.warning(f"User {user_id} not found")
        progress.log(run_id, "User profile not found — aborting", "error")
        return

    user = user_res.data
    skills = user.get("skills", [])
    preferred_platforms = user.get("preferred_platforms", ["linkedin", "naukri", "indeed"])
    preferred_locations = user.get("preferred_locations", ["India"])
    career_goals = user.get("career_goals", "")

    headline = user.get("headline", "")
    queries = []
    if headline:
        queries.append(headline.split("·")[0].strip())
    if skills:
        queries.extend([
            " ".join(skills[:3]),
            skills[0] if skills else "software developer",
        ])
    if career_goals:
        queries.append(career_goals[:50])

    queries = list(set(q for q in queries if q))[:3]
    if not queries:
        queries = ["software developer"]
    locations = [loc for loc in (preferred_locations or []) if loc] or ["India"]
    # Rotate the capped query×city matrix hourly so every run covers a
    # different slice and the full matrix is walked across a day's runs.
    search_pairs = build_search_pairs(
        queries, locations,
        cap=settings.DISCOVERY_MAX_SEARCHES_PER_SOURCE,
        offset=datetime.utcnow().hour,
    )

    # Company blacklist is optional — tolerate a missing table.
    blacklisted: set[str] = set()
    try:
        blacklist_res = db.table("company_blacklist").select("company_name").eq("user_id", user_id).execute()
        blacklisted = {r["company_name"].lower() for r in (blacklist_res.data or [])}
    except Exception as e:
        logger.warning(f"Blacklist lookup skipped: {e}")

    existing_urls: set[str] = set()
    existing_fps: set[str] = set()
    try:
        existing_res = db.table("job_applications").select("job_listing_id").eq("user_id", user_id).execute()
        seen_ids = [r["job_listing_id"] for r in (existing_res.data or [])]
        # Jobs already staged by an earlier run count as seen too. Without this,
        # a run interrupted before scoring would re-scrape everything it had
        # already saved — the listings exist, but no application row points to them.
        seen_ids += pipeline.staged_listing_ids(user_id)
        if seen_ids:
            # Batched IN — the id set grows unbounded with a user's history and a
            # single .in_() would eventually exceed PostgREST's URL length limit.
            seen_rows = select_in_batches(
                db, "job_listings", "source_url, title, company", "id", list(dict.fromkeys(seen_ids))
            )
            existing_urls = {r["source_url"] for r in seen_rows}
            # Content fingerprints catch reposts of the same role under a fresh
            # URL — the unique source_url alone can't.
            existing_fps = {job_fingerprint(r.get("title"), r.get("company")) for r in seen_rows}
    except Exception as e:
        logger.warning(f"Existing-URL dedup lookup skipped: {e}")

    # ── Phase 1: Scrape selected sources, persisting each batch as it arrives ──
    sources = select_sources(region, preferred_platforms)

    # Health-driven scheduling: back off hard-broken sources (with periodic
    # recovery probes) and run healthy high-yield sources first. Non-fatal.
    try:
        from services import telemetry
        from services.source_scheduler import plan_sources
        plan = plan_sources(
            sources,
            telemetry.source_health_map(user_id),
            telemetry.discovery_run_count(user_id),
            explicit_platforms=preferred_platforms,
        )
        sources = plan.to_run
        for name, reason in plan.skipped.items():
            progress.log(run_id, f"Skipping {name} — {reason} (health-based backoff)")
    except Exception as e:
        logger.warning(f"Source scheduling skipped (running all): {e}")

    logger.info(
        f"Discovery for {user_id} (region={region}): "
        f"{len(sources)} sources → {[s.name for s in sources]}"
    )
    progress.register_sources(run_id, [s.name for s in sources])
    progress.set_phase(
        run_id, "searching",
        f"Searching {len(sources)} sources with queries {queries} "
        f"across {', '.join(locations)}",
    )
    # Jobs are written to the database as each query returns (see _checkpoint).
    # `raw_jobs` / `job_ids` only carry the already-persisted batch forward to
    # the AI stages — losing them costs re-processing, never re-scraping.
    raw_jobs = []
    job_ids: list[str] = []
    prefiltered_total = 0

    for src in sources:
        # Discovery runs unauthenticated. The legacy platform_credentials table
        # stored plaintext passwords and has been retired here — authenticated
        # actions (applying) go through the encrypted SessionService instead.
        # Login-capable scrapers already degrade gracefully to public search.
        credentials = None

        try:
            progress.source_started(run_id, src.name)
            async with src.cls() as scraper:
                for query, loc in search_pairs:
                    logger.info(f"Searching {src.name} for '{query}' in {loc}")
                    progress.searching_query(run_id, src.name, query, loc)
                    try:
                        jobs = await _call_search(
                            scraper,
                            query=query,
                            location=loc,
                            max_results=max(5, settings.MAX_JOBS_PER_DISCOVERY // len(search_pairs)),
                            credentials=credentials,
                            region=region,
                        )
                        fresh = []
                        for job in jobs:
                            fp = job_fingerprint(job.title, job.company)
                            if (
                                job.source_url not in existing_urls
                                and fp not in existing_fps
                                and job.company.lower() not in blacklisted
                            ):
                                fresh.append(job)
                                existing_urls.add(job.source_url)
                                existing_fps.add(fp)
                        progress.query_result(run_id, src.name, query, len(jobs), len(fresh))

                        # ── DURABILITY CHECKPOINT ──
                        # Persist before moving on. From here the scrape output
                        # survives any later failure, crash or restart.
                        if fresh:
                            kept, kept_ids, dropped = await _checkpoint(
                                fresh, user=user, user_id=user_id, run_id=run_id
                            )
                            raw_jobs.extend(kept)
                            job_ids.extend(kept_ids)
                            prefiltered_total += dropped
                    except Exception as e:
                        logger.error(f"Error searching {src.name} for '{query}': {e}")
                        progress.log(run_id, f"{src.name}: '{query}' failed — {e}", "error")
                        continue
            progress.source_finished(run_id, src.name)
        except Exception as e:
            logger.error(f"Failed to initialize {src.name} scraper: {e}")
            progress.source_finished(run_id, src.name, error=str(e))
            continue

    if prefiltered_total:
        progress.log(
            run_id,
            f"Prefilter: {prefiltered_total} off-profile job(s) stored but skipped for AI scoring",
        )

    if not raw_jobs:
        logger.info(f"No new jobs to process for {user_id}")
        progress.log(run_id, "No new on-profile jobs found across all sources")
        return

    logger.info(f"Scraped and stored {len(raw_jobs)} new jobs — starting parallel AI evaluation")

    # ── Phases 2–5: AI processing ──
    # Every scraped job is already in the database. When the durable queue is
    # available the AI stages run off it, so a failure here costs at most the
    # in-flight batch and the scheduled drain finishes the rest. Otherwise the
    # legacy in-memory path runs (migration 16 not applied, or the feature is
    # switched off) — same results, but a failure still forfeits the run.
    if pipeline.pipeline_available():
        progress.set_phase(
            run_id, "analyzing", f"Processing {len(raw_jobs)} saved jobs with AI"
        )
        from workers import pipeline_worker
        totals = await pipeline_worker.drain(user_id, run_id=run_id)
        evaluated, matched, deferred = totals["scored"], totals["matched"], totals["failed"]
    else:
        matched, _queued = await _process_in_memory(
            user=user, user_id=user_id, run_id=run_id, raw_jobs=raw_jobs, job_ids=job_ids,
        )
        evaluated, deferred = len(raw_jobs), 0

    logger.info(
        f"Discovery complete for {user_id}: {len(raw_jobs)} scraped, {evaluated} evaluated, "
        f"{matched} matched (>={settings.RECOMMENDED_THRESHOLD}%)"
        + (f", {deferred} deferred for retry" if deferred else "")
    )
    progress.set_phase(run_id, "saving", "Wrapping up")

    try:
        from services.job_tracker import update_tracker
        update_tracker(user_id)
    except Exception as e:
        logger.warning(f"Job tracker update failed (non-fatal): {e}")

    # Grow ATS coverage from the URLs this run collected — validated boards are
    # persisted and picked up by the next run's ATS source. Non-fatal, bounded.
    try:
        from services.ats_harvester import harvest_from_db
        added = await harvest_from_db(db, max_new=15)
        if added:
            progress.log(run_id, f"ATS harvester discovered {len(added)} new company board(s)")
    except Exception as e:
        logger.warning(f"ATS harvest failed (non-fatal): {e}")


async def _process_in_memory(
    *, user: dict, user_id: str, run_id: str, raw_jobs: list, job_ids: list
) -> tuple[int, int]:
    """Legacy AI pipeline — used when the durable queue isn't available.

    Kept as the fallback for a database without migration 16 (or with
    PIPELINE_DURABLE_ENABLED=false). Listings are already stored either way, so
    a failure here loses evaluation work but never the scrape.
    """
    # ── Phase 2: Batch parse all JDs concurrently across both APIs ──
    progress.set_phase(run_id, "analyzing", f"Parsing {len(raw_jobs)} job descriptions with AI")
    jd_texts = [job.jd_text for job in raw_jobs]
    parsed_jds = await batch_parse_jds(jd_texts)

    # ── Phase 2.2: fill experience requirements on the stored listings ──
    # Precedence: scraper-set > LLM-parsed > regex over the JD (services/experience.py).
    # The listing row already exists, so this is a write-back, not a precondition
    # for storing it — a parse failure costs experience metadata, not the job.
    n_experience = 0
    for i, job in enumerate(raw_jobs):
        parsed = parsed_jds[i] if isinstance(parsed_jds[i], dict) else {}
        if merge_experience(job, parsed):
            n_experience += 1
            pipeline.update_listing(job_ids[i], pipeline.experience_fields(job))
    if n_experience:
        progress.log(run_id, f"Experience: extracted requirements for {n_experience} listing(s)")

    # ── Phase 2.5: Enrich listings with an HR contact ──
    # Job sources never carry a recruiter email/LinkedIn, so it is enriched here:
    # a keyless LinkedIn people-search link always, plus VERIFIED email/profile
    # when an enrichment provider key is set. Per-company cached, non-fatal.
    if settings.HR_CONTACT_ENRICHMENT_ENABLED:
        try:
            from services.hr_contact import enrich_jobs
            n_enriched = await enrich_jobs(raw_jobs)
            for i, job in enumerate(raw_jobs):
                fields = pipeline.hr_contact_fields(job)
                if any(fields.values()):
                    pipeline.update_listing(job_ids[i], fields)
            if n_enriched:
                progress.log(run_id, f"HR contact: added contact links to {n_enriched} listing(s)")
        except Exception as e:
            logger.warning(f"HR-contact enrichment failed (non-fatal): {e}")

    # Listings were stored at scrape time, so every job carries an id already.
    valid_indices = [i for i, job_id in enumerate(job_ids) if job_id]

    # ── Phase 4: Batch score all jobs concurrently with double-eval ──
    progress.set_phase(
        run_id, "scoring",
        f"Scoring {len(valid_indices)} jobs against your profile (dual-LLM double-eval)",
    )
    progress.update_counts(run_id, evaluated=len(valid_indices))
    score_inputs = [
        (parsed_jds[i], jd_texts[i])
        for i in valid_indices
    ]
    scores = await batch_score_jobs(user, score_inputs, double_eval_threshold=70)

    # ── Phase 5: Store results and queue auto-apply ──
    # Every write here is isolated per job. A transient DB/network fault on one
    # listing used to abort the whole loop and discard every remaining match —
    # losing hours of scraping to a single blip (see docs/PIPELINE_DURABILITY_DESIGN.md).
    progress.set_phase(run_id, "saving", "Saving match results and queueing auto-applies")
    queued_count = 0
    saved_count = 0
    save_failures = 0
    newly_matched = []
    for result_idx, orig_idx in enumerate(valid_indices):
        job_id = job_ids[orig_idx]
        score_result = scores[result_idx]
        score = score_result.get("overall_score", 0)
        tier = score_result.get("tier", "archived")

        app_data = {
            "user_id": user_id,
            "job_listing_id": job_id,
            "match_score": score,
            "match_tier": tier,
            "match_analysis": {
                "strengths": score_result.get("strengths", []),
                "gaps": score_result.get("gaps", []),
                "recommendations": score_result.get("recommendations", []),
                "summary": score_result.get("summary", ""),
                "score_breakdown": score_result.get("score_breakdown", {}),
                "evaluated_by": score_result.get("_evaluated_by", ""),
                "score_spread": score_result.get("_score_spread"),
                "dual_scores": score_result.get("_scores"),
            },
            "skill_gaps": score_result.get("missing_required_skills", []),
            "missing_skills": score_result.get("missing_nice_skills", []),
            "status": "matched",
        }

        try:
            app_res = db.table("job_applications").upsert(
                app_data, on_conflict="user_id,job_listing_id"
            ).execute()
        except Exception as e:
            save_failures += 1
            logger.error(f"Saving match for listing {job_id} failed: {e}")
            progress.log(run_id, f"Could not save match for a listing — {e}", "error")
            continue

        saved_count += 1
        application_id = app_res.data[0]["id"] if app_res.data else None

        # Only auto-queue when the *portal* supports full automation (Tier A).
        # Tier-B portals (e.g. Wellfound, Indeed) stay as matches for assisted
        # apply even at a high score — we never queue what we can't submit.
        # Queueing is best-effort: a failure here must not discard the match
        # record that was just written.
        job_platform = getattr(raw_jobs[orig_idx].source_platform, "value", raw_jobs[orig_idx].source_platform)
        if tier == "auto_apply" and user.get("auto_apply_enabled") and _portal_auto_appliable(job_platform):
            if application_id:
                try:
                    db.table("apply_queue").insert({
                        "application_id": application_id,
                        "user_id": user_id,
                        "priority": 10 - (score // 10),
                    }).execute()
                    db.table("job_applications").update(
                        {"status": "queued"}
                    ).eq("id", application_id).execute()
                    queued_count += 1
                except Exception as e:
                    logger.error(f"Auto-apply queueing failed for application {application_id}: {e}")
                    progress.log(run_id, f"Match saved but auto-apply queueing failed — {e}", "error")

        if score >= settings.RECOMMENDED_THRESHOLD:
            job_dict = raw_jobs[orig_idx].dict()
            job_dict["match_score"] = score
            job_dict["id"] = job_id
            newly_matched.append(job_dict)

        # Live counts so a partial run still shows what it managed to save.
        progress.update_counts(
            run_id, matched=len(newly_matched), queued=queued_count, saved=saved_count,
        )

    if save_failures:
        progress.log(
            run_id,
            f"{save_failures} of {len(valid_indices)} match records could not be saved "
            f"(the job listings themselves are stored and will be retried)",
            "error",
        )

    logger.info(
        f"Discovery complete for {user_id}: "
        f"{len(raw_jobs)} scraped, {len(valid_indices)} evaluated, "
        f"{len(newly_matched)} matched (>={settings.RECOMMENDED_THRESHOLD}%)"
    )
    progress.update_counts(run_id, matched=len(newly_matched), queued=queued_count)
    return len(newly_matched), queued_count


async def _checkpoint(
    jobs: list, *, user: dict, user_id: str, run_id: str
) -> tuple[list, list[str], int]:
    """Store a freshly scraped batch and enqueue it for AI processing.

    This is the point where scrape work becomes durable — it runs after every
    query, so a failure in any later stage costs processing time, never the
    scrape. Returns (jobs_to_process, their_listing_ids, prefiltered_count);
    the first two are index-aligned and exclude prefiltered jobs and any listing
    that could not be stored.
    """
    prefiltered: set[int] = set()
    if settings.DISCOVERY_PREFILTER_ENABLED:
        from services.prefilter import rejected_indices
        prefiltered = rejected_indices(jobs, user)

    dropped = len(prefiltered)
    if prefiltered and not settings.PIPELINE_PERSIST_PREFILTERED:
        # Legacy behaviour: off-profile jobs are discarded before they reach the
        # database at all. Recorded here as a deliberate opt-out.
        jobs = [job for i, job in enumerate(jobs) if i not in prefiltered]
        prefiltered = set()

    try:
        listing_ids = await pipeline.persist_scraped_batch(
            jobs, user_id=user_id, run_id=run_id, prefiltered=prefiltered,
        )
    except Exception as e:
        # persist_scraped_batch is non-fatal by contract; this guards the caller
        # against anything it could not absorb, so scraping continues regardless.
        logger.error(f"Checkpoint failed for a batch of {len(jobs)} job(s): {e}")
        progress.log(run_id, f"Could not store a scraped batch — {e}", "error")
        return [], [], dropped

    kept, kept_ids = [], []
    for i, (job, listing_id) in enumerate(zip(jobs, listing_ids)):
        if i in prefiltered or not listing_id:
            continue
        kept.append(job)
        kept_ids.append(listing_id)
    return kept, kept_ids, dropped
