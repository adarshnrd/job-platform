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
from scrapers.ats import ATSAggregatorScraper
from config import settings
from services import discovery_progress as progress
from services.dedup import job_fingerprint

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
    "foundit":        Source("foundit", FounditScraper, False, False, {"india"}, discoverable=False),
    "wellfound":      Source("wellfound", WellfoundScraper, False, False, {"india", "global"}, discoverable=False),
    "ycombinator":    Source("ycombinator", YCombinatorScraper, False, False, {"global"}),
    "glassdoor":      Source("glassdoor", GlassdoorScraper, False, False, {"global"}),
    "dice":           Source("dice", DiceScraper, False, False, {"global"}),
    "ziprecruiter":   Source("ziprecruiter", ZipRecruiterScraper, False, False, {"global"}),
    "weworkremotely": Source("weworkremotely", WeWorkRemotelyScraper, False, False, {"global"}),
    # ── API-first keyless sources ──
    "remoteok":       Source("remoteok", RemoteOKScraper, True, False, {"global", "india"}),
    "remotive":       Source("remotive", RemotiveScraper, True, False, {"global", "india"}),
    "timesjobs":      Source("timesjobs", TimesJobsScraper, True, False, {"india"}),
    "hirist":         Source("hirist", HiristScraper, True, False, {"india"}),
    "iimjobs":        Source("iimjobs", IimjobsScraper, True, False, {"india"}),
    # ATS-direct: many company career boards (Greenhouse/Lever/Ashby) in one source.
    "ats":            Source("ats", ATSAggregatorScraper, True, False, {"india"}),
    "arbeitnow":      Source("arbeitnow", ArbeitnowScraper, True, False, {"global"}),
    "themuse":        Source("themuse", TheMuseScraper, True, False, {"india", "global"}),
    # ── API-first keyed sources (dormant until keys set) ──
    "adzuna":         Source("adzuna", AdzunaScraper, True, True, {"india", "global"}),
    "jooble":         Source("jooble", JoobleScraper, True, True, {"india", "global"}),
    "jsearch":        Source("jsearch", JSearchScraper, True, True, {"india", "global"}),
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
    to india (this is an India-first deployment)."""
    locations = [loc for loc in (preferred_locations or []) if loc]
    if not locations:
        return "india"
    for loc in locations:
        low = loc.lower()
        if any(hint in low for hint in INDIA_LOCATION_HINTS):
            return "india"
    return "global"


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
    """True only for Tier-A portals we can submit end to end.

    Unknown platforms default to True so a portal missing from the registry still
    behaves as before (auto-queue) rather than silently never applying.
    """
    try:
        from services.portals import get_portal
        cap = get_portal(platform)
        return cap.auto_apply if cap else True
    except Exception:
        return True


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
        if existing_res.data:
            app_job_ids = [r["job_listing_id"] for r in existing_res.data]
            # Batched IN — the id set grows unbounded with a user's history and a
            # single .in_() would eventually exceed PostgREST's URL length limit.
            seen_rows = select_in_batches(db, "job_listings", "source_url, title, company", "id", app_job_ids)
            existing_urls = {r["source_url"] for r in seen_rows}
            # Content fingerprints catch reposts of the same role under a fresh
            # URL — the unique source_url alone can't.
            existing_fps = {job_fingerprint(r.get("title"), r.get("company")) for r in seen_rows}
    except Exception as e:
        logger.warning(f"Existing-URL dedup lookup skipped: {e}")

    # ── Phase 1: Scrape selected sources for the region and collect raw jobs ──
    sources = select_sources(region, preferred_platforms)
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
    raw_jobs = []

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
                        new_count = 0
                        for job in jobs:
                            fp = job_fingerprint(job.title, job.company)
                            if (
                                job.source_url not in existing_urls
                                and fp not in existing_fps
                                and job.company.lower() not in blacklisted
                            ):
                                raw_jobs.append(job)
                                existing_urls.add(job.source_url)
                                existing_fps.add(fp)
                                new_count += 1
                        progress.query_result(run_id, src.name, query, len(jobs), new_count)
                    except Exception as e:
                        logger.error(f"Error searching {src.name} for '{query}': {e}")
                        progress.log(run_id, f"{src.name}: '{query}' failed — {e}", "error")
                        continue
            progress.source_finished(run_id, src.name)
        except Exception as e:
            logger.error(f"Failed to initialize {src.name} scraper: {e}")
            progress.source_finished(run_id, src.name, error=str(e))
            continue

    if not raw_jobs:
        logger.info(f"No new jobs found for {user_id}")
        progress.log(run_id, "No new jobs found across all sources")
        return

    logger.info(f"Scraped {len(raw_jobs)} new jobs — starting parallel AI evaluation")

    # ── Phase 2: Batch parse all JDs concurrently across both APIs ──
    progress.set_phase(run_id, "analyzing", f"Parsing {len(raw_jobs)} job descriptions with AI")
    jd_texts = [job.jd_text for job in raw_jobs]
    parsed_jds = await batch_parse_jds(jd_texts)

    # ── Phase 3: Store job listings in DB ──
    progress.log(run_id, f"Storing {len(raw_jobs)} job listings")
    job_ids = []
    valid_indices = []
    for i, job in enumerate(raw_jobs):
        job_id = await _upsert_job_listing(job)
        job_ids.append(job_id)
        if job_id:
            valid_indices.append(i)

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
    progress.set_phase(run_id, "saving", "Saving match results and queueing auto-applies")
    queued_count = 0
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

        app_res = db.table("job_applications").upsert(
            app_data, on_conflict="user_id,job_listing_id"
        ).execute()

        # Only auto-queue when the *portal* supports full automation (Tier A).
        # Tier-B portals (e.g. Wellfound, Indeed) stay as matches for assisted
        # apply even at a high score — we never queue what we can't submit.
        job_platform = getattr(raw_jobs[orig_idx].source_platform, "value", raw_jobs[orig_idx].source_platform)
        if tier == "auto_apply" and user.get("auto_apply_enabled") and _portal_auto_appliable(job_platform):
            if app_res.data:
                db.table("apply_queue").insert({
                    "application_id": app_res.data[0]["id"],
                    "user_id": user_id,
                    "priority": 10 - (score // 10),
                }).execute()
                db.table("job_applications").update(
                    {"status": "queued"}
                ).eq("id", app_res.data[0]["id"]).execute()
                queued_count += 1

        if score >= settings.RECOMMENDED_THRESHOLD:
            job_dict = raw_jobs[orig_idx].dict()
            job_dict["match_score"] = score
            job_dict["id"] = job_id
            newly_matched.append(job_dict)

    logger.info(
        f"Discovery complete for {user_id}: "
        f"{len(raw_jobs)} scraped, {len(valid_indices)} evaluated, "
        f"{len(newly_matched)} matched (>={settings.RECOMMENDED_THRESHOLD}%)"
    )
    progress.update_counts(run_id, matched=len(newly_matched), queued=queued_count)

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


def _ilike_exact(text: str) -> str:
    """Escape LIKE wildcards so .ilike() does a case-insensitive exact match."""
    return (text or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _find_existing_listing(job_data: dict) -> str | None:
    """Content-level dedup: a listing with the same normalized title+company is
    the same job, no matter what URL the portal minted for the repost."""
    try:
        res = db.table("job_listings").select("id")\
            .eq("dedupe_key", job_data["dedupe_key"]).limit(1).execute()
        return res.data[0]["id"] if res.data else None
    except Exception:
        # Pre-migration: dedupe_key column missing (run database/11_job_dedup.sql).
        # Fall back to case-insensitive exact title+company — catches identical
        # reposts, just not punctuation/suffix variants.
        try:
            res = db.table("job_listings").select("id")\
                .ilike("title", _ilike_exact(job_data.get("title")))\
                .ilike("company", _ilike_exact(job_data.get("company")))\
                .limit(1).execute()
            return res.data[0]["id"] if res.data else None
        except Exception as e:
            logger.warning(f"Dedup lookup skipped: {e}")
            return None


async def _upsert_job_listing(job) -> str | None:
    from datetime import datetime
    from services.portals import normalize_job_url
    job_data = job.dict()
    # Canonicalize the URL (e.g. angel.co → wellfound.com) so the same role from
    # different hosts collapses onto one listing via the unique source_url index.
    if job_data.get("source_url"):
        job_data["source_url"] = normalize_job_url(job_data["source_url"])
    job_data["dedupe_key"] = job_fingerprint(job_data.get("title"), job_data.get("company"))
    # Same role already stored under a different URL? Reuse that listing so the
    # application lands on it instead of creating a duplicate row.
    existing_id = _find_existing_listing(job_data)
    if existing_id:
        return existing_id
    job_data["required_skills"] = list(job_data.get("required_skills") or [])
    job_data["nice_to_have_skills"] = list(job_data.get("nice_to_have_skills") or [])
    # Pydantic enum → its string value for the Postgres enum column.
    platform_value = getattr(job_data.get("source_platform"), "value", job_data.get("source_platform"))
    job_data["source_platform"] = platform_value
    if job_data.get("posted_at"):
        job_data["posted_at"] = job_data["posted_at"].isoformat() if isinstance(job_data["posted_at"], datetime) else job_data["posted_at"]
    else:
        job_data["posted_at"] = datetime.utcnow().isoformat()

    try:
        result = db.table("job_listings").upsert(job_data, on_conflict="source_url").execute()
        return result.data[0]["id"] if result.data else None
    except Exception as e:
        # Pre-migration safety: dedupe_key column not in the DB yet — store
        # without it. Run database/11_job_dedup.sql for DB-level dedup.
        if "dedupe_key" in str(e).lower():
            logger.warning("dedupe_key column missing — run database/11_job_dedup.sql for DB-level dedup.")
            job_data.pop("dedupe_key", None)
            try:
                result = db.table("job_listings").upsert(job_data, on_conflict="source_url").execute()
                return result.data[0]["id"] if result.data else None
            except Exception as e2:
                logger.error(f"Job upsert retry failed: {e2}")
                return None
        # Pre-migration safety: if the new enum value isn't in the DB yet,
        # fall back to 'other' so discovery still works. Run database/02_api_sources.sql
        # to store the real source name.
        if "invalid input value for enum" in str(e).lower():
            logger.warning(f"Enum value '{platform_value}' not in DB yet — storing as 'other'. Run 02_api_sources.sql.")
            job_data["source_platform"] = "other"
            try:
                result = db.table("job_listings").upsert(job_data, on_conflict="source_url").execute()
                return result.data[0]["id"] if result.data else None
            except Exception as e2:
                logger.error(f"Job upsert retry failed: {e2}")
                return None
        logger.error(f"Job upsert failed: {e}")
        return None
