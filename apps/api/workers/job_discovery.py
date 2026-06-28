"""
Job Discovery — searches platforms, scores jobs using dual-API parallel evaluation.
Runs directly via FastAPI BackgroundTasks (no Redis/Celery needed).

Sources are organized in a region-aware registry. Each entry declares whether
it is API-based, whether it needs a key (auto-skipped when absent), and which
regions ("india" / "global") it serves.
"""
import asyncio
import inspect
from loguru import logger
from database import get_db
from services.ai_service import batch_parse_jds, batch_score_jobs
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
# API-first sources — stable, no browser
from scrapers.remotive import RemotiveScraper
from scrapers.arbeitnow import ArbeitnowScraper
from scrapers.themuse import TheMuseScraper
from scrapers.adzuna import AdzunaScraper
from scrapers.jooble import JoobleScraper
from scrapers.jsearch import JSearchScraper
from config import settings

db = get_db()


class Source:
    """A discovery source and its routing metadata."""
    def __init__(self, name, cls, api_based, requires_key, regions, login_capable=False):
        self.name = name
        self.cls = cls
        self.api_based = api_based
        self.requires_key = requires_key
        self.regions = regions
        self.login_capable = login_capable


# Registry of every source. `regions` controls when each is used.
SOURCE_REGISTRY: dict[str, Source] = {
    # ── Playwright / login scrapers (India market) ──
    "naukri":         Source("naukri", NaukriScraper, False, False, {"india"}, login_capable=True),
    "linkedin":       Source("linkedin", LinkedInScraper, False, False, {"india", "global"}, login_capable=True),
    "indeed":         Source("indeed", IndeedScraper, False, False, {"india", "global"}, login_capable=True),
    "instahyre":      Source("instahyre", InstahyreScraper, False, False, {"india"}, login_capable=True),
    "hirist":         Source("hirist", HiristScraper, False, False, {"india"}),
    "cutshort":       Source("cutshort", CutshortScraper, False, False, {"india"}),
    "foundit":        Source("foundit", FounditScraper, False, False, {"india"}),
    "wellfound":      Source("wellfound", WellfoundScraper, False, False, {"india", "global"}),
    "glassdoor":      Source("glassdoor", GlassdoorScraper, False, False, {"global"}),
    "dice":           Source("dice", DiceScraper, False, False, {"global"}),
    "ziprecruiter":   Source("ziprecruiter", ZipRecruiterScraper, False, False, {"global"}),
    "weworkremotely": Source("weworkremotely", WeWorkRemotelyScraper, False, False, {"global"}),
    # ── API-first keyless sources ──
    "remoteok":       Source("remoteok", RemoteOKScraper, True, False, {"global", "india"}),
    "remotive":       Source("remotive", RemotiveScraper, True, False, {"global", "india"}),
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
    - Includes the user's preferred Playwright/login scrapers that serve the region.
    """
    region = region if region in ("india", "global") else "india"
    selected: dict[str, Source] = {}

    for name, src in SOURCE_REGISTRY.items():
        if region not in src.regions:
            continue
        # Keyed sources need a valid key.
        if src.requires_key and not _has_key(src.cls):
            continue
        # API-first keyless sources are always on for the region.
        if src.api_based and not src.requires_key:
            selected[name] = src
        # Keyed API sources that passed the key check are on.
        elif src.api_based and src.requires_key:
            selected[name] = src
        # Playwright sources: only if the user opted into them.
        elif name in (preferred_platforms or []):
            selected[name] = src

    return list(selected.values())


def _has_key(cls) -> bool:
    """True if a keyed source has its credentials configured."""
    has = getattr(cls, "has_key", None)
    return bool(has()) if callable(has) else True


async def _call_search(scraper, *, query, location, max_results, credentials, region):
    """Call search_jobs passing only the kwargs the scraper actually accepts."""
    params = inspect.signature(scraper.search_jobs).parameters
    kwargs = {"query": query, "location": location, "max_results": max_results}
    if "credentials" in params:
        kwargs["credentials"] = credentials
    if "region" in params:
        kwargs["region"] = region
    return await scraper.search_jobs(**kwargs)


def run_discovery_for_user(user_id: str, region: str = "india"):
    """Entry point called by FastAPI BackgroundTasks."""
    try:
        asyncio.run(_discover_for_user_async(user_id, region))
    except Exception as e:
        logger.error(f"Discovery failed for user {user_id}: {e}")


async def _discover_for_user_async(user_id: str, region: str = "india"):
    user_res = db.table("users").select("*").eq("id", user_id).single().execute()
    if not user_res.data:
        logger.warning(f"User {user_id} not found")
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
    location = preferred_locations[0] if preferred_locations else "India"

    # Company blacklist is optional — tolerate a missing table.
    blacklisted: set[str] = set()
    try:
        blacklist_res = db.table("company_blacklist").select("company_name").eq("user_id", user_id).execute()
        blacklisted = {r["company_name"].lower() for r in (blacklist_res.data or [])}
    except Exception as e:
        logger.warning(f"Blacklist lookup skipped: {e}")

    existing_urls: set[str] = set()
    try:
        existing_res = db.table("job_applications").select("job_listing_id").eq("user_id", user_id).execute()
        if existing_res.data:
            app_job_ids = [r["job_listing_id"] for r in existing_res.data]
            seen_res = db.table("job_listings").select("source_url").in_("id", app_job_ids).execute()
            existing_urls = {r["source_url"] for r in (seen_res.data or [])}
    except Exception as e:
        logger.warning(f"Existing-URL dedup lookup skipped: {e}")

    # ── Phase 1: Scrape selected sources for the region and collect raw jobs ──
    sources = select_sources(region, preferred_platforms)
    logger.info(
        f"Discovery for {user_id} (region={region}): "
        f"{len(sources)} sources → {[s.name for s in sources]}"
    )
    raw_jobs = []

    for src in sources:
        credentials = None
        if src.login_capable:
            creds_res = db.table("platform_credentials").select("*").eq("user_id", user_id).eq("platform", src.name).maybe_single().execute()
            if creds_res.data:
                credentials = {
                    "username": creds_res.data.get("encrypted_username"),
                    "password": creds_res.data.get("encrypted_password"),
                }

        try:
            async with src.cls() as scraper:
                for query in queries:
                    logger.info(f"Searching {src.name} for '{query}' in {location}")
                    try:
                        jobs = await _call_search(
                            scraper,
                            query=query,
                            location=location,
                            max_results=settings.MAX_JOBS_PER_DISCOVERY // len(queries),
                            credentials=credentials,
                            region=region,
                        )
                        for job in jobs:
                            if job.source_url not in existing_urls and job.company.lower() not in blacklisted:
                                raw_jobs.append(job)
                                existing_urls.add(job.source_url)
                    except Exception as e:
                        logger.error(f"Error searching {src.name} for '{query}': {e}")
                        continue
        except Exception as e:
            logger.error(f"Failed to initialize {src.name} scraper: {e}")
            continue

    if not raw_jobs:
        logger.info(f"No new jobs found for {user_id}")
        return

    logger.info(f"Scraped {len(raw_jobs)} new jobs — starting parallel AI evaluation")

    # ── Phase 2: Batch parse all JDs concurrently across both APIs ──
    jd_texts = [job.jd_text for job in raw_jobs]
    parsed_jds = await batch_parse_jds(jd_texts)

    # ── Phase 3: Store job listings in DB ──
    job_ids = []
    valid_indices = []
    for i, job in enumerate(raw_jobs):
        job_id = await _upsert_job_listing(job)
        job_ids.append(job_id)
        if job_id:
            valid_indices.append(i)

    # ── Phase 4: Batch score all jobs concurrently with double-eval ──
    score_inputs = [
        (parsed_jds[i], jd_texts[i])
        for i in valid_indices
    ]
    scores = await batch_score_jobs(user, score_inputs, double_eval_threshold=70)

    # ── Phase 5: Store results and queue auto-apply ──
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

        if tier == "auto_apply" and user.get("auto_apply_enabled"):
            if app_res.data:
                db.table("apply_queue").insert({
                    "application_id": app_res.data[0]["id"],
                    "user_id": user_id,
                    "priority": 10 - (score // 10),
                }).execute()
                db.table("job_applications").update(
                    {"status": "queued"}
                ).eq("id", app_res.data[0]["id"]).execute()

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


async def _upsert_job_listing(job) -> str | None:
    from datetime import datetime
    job_data = job.dict()
    job_data["required_skills"] = list(job_data.get("required_skills", []))
    job_data["nice_to_have_skills"] = list(job_data.get("nice_to_have_skills", []))
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
