"""
Health-driven source scheduling (Source Plan Phase 3 #13).

Discovery runs every source every time. Once a source breaks (a scraper's DOM
drifts, a site starts bot-walling), it burns run time and error budget on every
run until someone notices. This module uses the telemetry source-health signal
(services/telemetry.source_health) to *back off* a genuinely-broken source —
skipping it on most runs while still probing periodically so recovery is
detected automatically — and to run healthy, high-yield sources first.

It is deliberately conservative — losing coverage is worse than a wasted fetch:

  • Only sources flagged `consecutive_errors` (hard-broken) are backed off.
    A `yield_drop` source still returns *some* jobs, so it always runs.
  • Every Nth run is a "probe" run that includes even backed-off sources, so a
    recovered source rejoins on its own.
  • A source the user explicitly selected is never skipped.
  • Sources with too little history to judge are never skipped.

Disable entirely with DISCOVERY_HEALTH_SCHEDULING_ENABLED=false.
"""
from dataclasses import dataclass

from loguru import logger

from config import settings


@dataclass
class SourcePlan:
    """The scheduling decision for one discovery run."""
    to_run: list          # source objects (or names) to actually search, ordered
    skipped: dict         # {source_name: reason} that were backed off this run
    is_probe: bool        # True → backed-off sources were included to test recovery


def _baseline_yield(health: dict | None) -> float:
    return (health or {}).get("baseline_yield") or 0.0


def _is_backed_off(name: str, health: dict | None, explicit: set[str]) -> bool:
    """A source is backed off only if hard-broken and not user-pinned."""
    if not health or name in explicit:
        return False
    # `consecutive_errors` = last two runs both errored → genuinely broken.
    return health.get("flagged") and health.get("flag_reason") == "consecutive_errors"


def plan_sources(
    sources: list,
    health_by_name: dict[str, dict],
    run_seq: int,
    explicit_platforms: list[str] | None = None,
    name_of=lambda s: getattr(s, "name", s),
) -> SourcePlan:
    """Decide which sources to run this discovery, and in what order.

    `run_seq` is the user's completed-run count; every PROBE_EVERY-th run is a
    probe that includes backed-off sources. Healthy, high-baseline-yield sources
    are ordered first so a capped/interrupted run still gets the best coverage.
    """
    if not settings.DISCOVERY_HEALTH_SCHEDULING_ENABLED:
        return SourcePlan(to_run=list(sources), skipped={}, is_probe=False)

    explicit = set(explicit_platforms or [])
    probe_every = max(1, settings.SOURCE_ERROR_BACKOFF_PROBE_EVERY)
    is_probe = (run_seq % probe_every == 0)

    to_run, skipped = [], {}
    for src in sources:
        name = name_of(src)
        if not is_probe and _is_backed_off(name, health_by_name.get(name), explicit):
            skipped[name] = "backed_off_consecutive_errors"
        else:
            to_run.append(src)

    # Order: healthy high-yield first; unknown-health sources keep a neutral
    # middle position so new sources aren't starved.
    def sort_key(src):
        h = health_by_name.get(name_of(src))
        flagged = bool(h and h.get("flagged"))
        return (flagged, -_baseline_yield(h), name_of(src))

    to_run.sort(key=sort_key)

    if skipped:
        logger.info(f"Source scheduler: backing off {list(skipped)} (probe run: {is_probe})")
    return SourcePlan(to_run=to_run, skipped=skipped, is_probe=is_probe)
