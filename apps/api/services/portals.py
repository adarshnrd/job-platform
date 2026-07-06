"""
Portal capability registry — the single source of truth for what each job portal
supports (search / details / auto-apply / assisted-apply / resume upload /
question detection) and its integration tier.

Tiers:
  A — full auto-apply (bot submits end to end)
  B — assisted (we prefill everything; the user reviews & confirms in-app)
  C — discovery/display only (search + details; applying links out)

This layer is declarative metadata. The actual scraping lives in scrapers/* and
the actual applying in services/sessions/adapters/*. The frontend reads this via
GET /portals to render per-job tier badges and per-portal connect buttons, so
every portal shows up consistently without hand-maintained UI lists.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass(frozen=True)
class PortalCapabilities:
    key: str                      # canonical portal id (matches scraper/adapter keys)
    display_name: str
    tier: str                     # "A" | "B" | "C"
    regions: tuple[str, ...]      # ("india",) / ("global",) / ("india", "global")
    search: bool = True
    details: bool = True
    auto_apply: bool = False      # Tier A
    assisted_apply: bool = False  # Tier B
    resume_upload: bool = False
    question_detection: bool = False
    requires_session: bool = False
    requires_key: bool = False
    anti_bot: str = "low"         # low | medium | high
    aliases: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""

    @property
    def apply_label(self) -> str:
        if self.tier == "A":
            return "Auto"
        if self.tier == "B":
            return "Assisted"
        return "View only"


# Ordered roughly by tier then region. `key` values match the scraper registry /
# adapter registry so callers can cross-reference `has_adapter`, `has_scraper`.
PORTALS: dict[str, PortalCapabilities] = {
    # ── Tier A: full auto-apply ──────────────────────────────────────────
    "linkedin": PortalCapabilities(
        "linkedin", "LinkedIn", "A", ("india", "global"),
        auto_apply=True, resume_upload=True, question_detection=True,
        requires_session=True, anti_bot="high",
        notes="Easy Apply only; external ATS applies fall back to assisted.",
    ),
    "naukri": PortalCapabilities(
        "naukri", "Naukri", "A", ("india",),
        auto_apply=True, resume_upload=True, question_detection=True,
        requires_session=True, anti_bot="medium",
        notes="Resume served from Naukri profile; chatbot questionnaire.",
    ),
    "instahyre": PortalCapabilities(
        "instahyre", "Instahyre", "A", ("india",),
        auto_apply=True, resume_upload=True, question_detection=True,
        requires_session=True, anti_bot="medium",
    ),
    "foundit": PortalCapabilities(
        "foundit", "Foundit", "A", ("india",),
        auto_apply=True, resume_upload=True, question_detection=True,
        requires_session=True, anti_bot="medium", aliases=("monster",),
    ),
    "hirist": PortalCapabilities(
        "hirist", "Hirist", "A", ("india",),
        auto_apply=True, resume_upload=True, question_detection=True,
        requires_session=True, anti_bot="low",
    ),
    "cutshort": PortalCapabilities(
        "cutshort", "Cutshort", "A", ("india",),
        auto_apply=True, resume_upload=True, question_detection=True,
        requires_session=True, anti_bot="medium",
        notes="Assessments pause the application — never auto-answered.",
    ),
    "iimjobs": PortalCapabilities(
        "iimjobs", "iimjobs", "A", ("india",),
        auto_apply=True, resume_upload=True, question_detection=True,
        requires_session=True, anti_bot="low",
        notes="Info Edge platform family (shares Hirist mechanics).",
    ),
    "timesjobs": PortalCapabilities(
        "timesjobs", "TimesJobs", "A", ("india",),
        auto_apply=True, resume_upload=True, question_detection=True,
        requires_session=True, anti_bot="low",
    ),
    "shine": PortalCapabilities(
        "shine", "Shine", "A", ("india",),
        auto_apply=True, resume_upload=True, question_detection=True,
        requires_session=True, anti_bot="medium",
    ),
    "freshersworld": PortalCapabilities(
        "freshersworld", "Freshersworld", "A", ("india",),
        auto_apply=True, resume_upload=True, question_detection=True,
        requires_session=True, anti_bot="low",
        notes="Entry-level roles; gate by experience or explicit opt-in.",
    ),
    "ycombinator": PortalCapabilities(
        "ycombinator", "Y Combinator (Work at a Startup)", "A", ("global",),
        auto_apply=True, resume_upload=True, question_detection=True,
        requires_session=True, anti_bot="low", aliases=("workatastartup", "yc"),
    ),

    # ── Tier B: assisted (prefill + user confirms) ───────────────────────
    "wellfound": PortalCapabilities(
        "wellfound", "Wellfound", "B", ("india", "global"),
        assisted_apply=True, resume_upload=True, question_detection=True,
        requires_session=True, anti_bot="high", aliases=("angellist", "angel.co"),
        notes="Founder-note applies; automatable but risky, kept assisted.",
    ),
    "indeed": PortalCapabilities(
        "indeed", "Indeed", "B", ("india", "global"),
        assisted_apply=True, resume_upload=True, question_detection=True,
        anti_bot="high",
        notes="JSearch API is the primary discovery channel; hCaptcha blocks auto-submit.",
    ),

    # ── Tier C: discovery / display only ─────────────────────────────────
    "remoteok": PortalCapabilities(
        "remoteok", "Remote OK", "C", ("global", "india"),
        anti_bot="low", notes="External apply link; generic-portal filler where possible.",
    ),
    "weworkremotely": PortalCapabilities(
        "weworkremotely", "We Work Remotely", "C", ("global",),
        anti_bot="low", notes="External apply links.",
    ),
    "remotive": PortalCapabilities(
        "remotive", "Remotive", "C", ("global", "india"), anti_bot="low",
    ),
    "arbeitnow": PortalCapabilities(
        "arbeitnow", "Arbeitnow", "C", ("global",), anti_bot="low",
    ),
    "themuse": PortalCapabilities(
        "themuse", "The Muse", "C", ("india", "global"), anti_bot="low",
    ),
    "glassdoor": PortalCapabilities(
        "glassdoor", "Glassdoor", "C", ("global",),
        anti_bot="high", notes="Display + link-out only; applies proxy to Indeed/ATS.",
    ),
    "google_jobs": PortalCapabilities(
        "google_jobs", "Google for Jobs", "C", ("india", "global"),
        requires_key=True, anti_bot="low", aliases=("jsearch",),
        notes="Sourced via the licensed JSearch API; aggregator, links to origin portal.",
    ),
    "adzuna": PortalCapabilities(
        "adzuna", "Adzuna", "C", ("india", "global"), requires_key=True, anti_bot="low",
    ),
    "jooble": PortalCapabilities(
        "jooble", "Jooble", "C", ("india", "global"), requires_key=True, anti_bot="low",
    ),
    "dice": PortalCapabilities(
        "dice", "Dice", "C", ("global",), anti_bot="medium",
    ),
    "ziprecruiter": PortalCapabilities(
        "ziprecruiter", "ZipRecruiter", "C", ("global",), anti_bot="high",
    ),
    "flexjobs": PortalCapabilities(
        "flexjobs", "FlexJobs", "C", ("global",),
        requires_session=True, anti_bot="medium",
        notes="Paywalled; display-only using the user's own subscription. Off by default.",
    ),

    # ── Documented-unsupported (kept visible so the UI can explain why) ───
    "hirect": PortalCapabilities(
        "hirect", "Hirect", "C", ("india",),
        search=False, details=False, anti_bot="high",
        notes="Mobile-app-only chat hiring; no candidate web surface — unsupported.",
    ),
}

# Reverse alias lookup: "angel.co" / "angellist" → "wellfound", etc.
_ALIAS_MAP: dict[str, str] = {
    alias.lower(): key
    for key, cap in PORTALS.items()
    for alias in cap.aliases
}


def resolve_portal_key(name: str) -> str:
    """Normalize a portal name/alias to its canonical key. Returns input if unknown."""
    if not name:
        return name
    n = name.strip().lower()
    if n in PORTALS:
        return n
    return _ALIAS_MAP.get(n, n)


def get_portal(name: str) -> PortalCapabilities | None:
    return PORTALS.get(resolve_portal_key(name))


def normalize_job_url(url: str) -> str:
    """Canonicalize a job URL for dedup.

    - angel.co → wellfound.com (angel.co 301-redirects there), so the same role
      scraped from either host collapses onto one listing.
    - drops tracking query params and trailing slashes.
    Unknown URLs are returned trimmed but otherwise unchanged.
    """
    if not url:
        return url
    u = url.strip()
    u = u.replace("://angel.co", "://wellfound.com").replace("://www.angel.co", "://www.wellfound.com")
    # Strip query string / fragment (job URLs are stable without them).
    for sep in ("?", "#"):
        if sep in u:
            u = u.split(sep, 1)[0]
    if u.endswith("/") and len(u) > len("https://x/"):
        u = u.rstrip("/")
    return u


def list_portals() -> list[dict]:
    """Full capability matrix for the frontend, annotated with live wiring state."""
    # Imported lazily to avoid a circular import at module load.
    try:
        from services.sessions.adapters.registry import ADAPTERS
    except Exception:
        ADAPTERS = {}
    try:
        from workers.job_discovery import SOURCE_REGISTRY
    except Exception:
        SOURCE_REGISTRY = {}

    out = []
    for key, cap in PORTALS.items():
        d = asdict(cap)
        d["apply_label"] = cap.apply_label
        d["regions"] = list(cap.regions)
        d["aliases"] = list(cap.aliases)
        d["has_adapter"] = key in ADAPTERS
        d["has_scraper"] = key in SOURCE_REGISTRY
        out.append(d)
    # Tier A first, then B, then C; stable within tier.
    tier_rank = {"A": 0, "B": 1, "C": 2}
    out.sort(key=lambda p: tier_rank.get(p["tier"], 3))
    return out
