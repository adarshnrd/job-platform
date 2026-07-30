"""Mission-control telemetry router — run ledger, scraper health, AI usage & budget."""
from auth import get_user_id
from config import settings
from fastapi import APIRouter, Depends, HTTPException

from services import telemetry

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

VALID_KINDS = {"discovery", "apply"}


@router.get("/runs")
async def list_runs(
    kind: str | None = None,
    limit: int = 30,
    user_id: str = Depends(get_user_id),
):
    """Durable run ledger, newest first, with per-source breakdowns."""
    if kind is not None and kind not in VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {sorted(VALID_KINDS)}")
    limit = max(1, min(limit, 100))
    return {"runs": telemetry.list_runs(user_id, kind=kind, limit=limit)}


@router.get("/source-health")
async def source_health(days: int = 14, user_id: str = Depends(get_user_id)):
    """Per-scraper health over the window: daily yields, error rates, degradation flags."""
    days = max(1, min(days, 60))
    return {"days": days, "sources": telemetry.source_health(user_id, days=days)}


@router.get("/coverage")
async def coverage(days: int = 14, user_id: str = Depends(get_user_id)):
    """Source coverage overview: active/total, per-source health, contribution,
    and the scheduling decision the next run would make (running/backed-off/probing).
    """
    days = max(1, min(days, 60))
    from workers.job_discovery import SOURCE_REGISTRY, select_sources
    from services.source_scheduler import _is_backed_off

    health = telemetry.source_health_map(user_id, days=days)
    contrib = telemetry.source_contribution(user_id, days=days)
    run_seq = telemetry.discovery_run_count(user_id)
    probe_every = max(1, settings.SOURCE_ERROR_BACKOFF_PROBE_EVERY)
    next_is_probe = settings.DISCOVERY_HEALTH_SCHEDULING_ENABLED and (run_seq % probe_every == 0)

    # Which sources would actually be selected for this user's region right now.
    region = _user_region(user_id)
    active_names = {s.name for s in select_sources(region, [])}

    items = []
    for name, src in sorted(SOURCE_REGISTRY.items()):
        h = health.get(name)
        c = contrib.get(name, {})
        in_region = region in src.regions
        if not src.discoverable:
            scheduling = "c_tier"
        elif src.requires_key and (name not in active_names):
            scheduling = "dormant"        # keyed source without a key
        elif not in_region:
            scheduling = "other_region"
        elif settings.DISCOVERY_HEALTH_SCHEDULING_ENABLED and not next_is_probe and _is_backed_off(name, h, set()):
            scheduling = "backed_off"
        elif settings.DISCOVERY_HEALTH_SCHEDULING_ENABLED and next_is_probe and _is_backed_off(name, h, set()):
            scheduling = "probing"
        elif name in active_names:
            scheduling = "running"
        else:
            scheduling = "other_region"
        items.append({
            "name": name,
            "kind": src.kind,
            "discoverable": src.discoverable,
            "in_region": in_region,
            "scheduling": scheduling,
            "flagged": bool(h and h.get("flagged")),
            "flag_reason": h.get("flag_reason") if h else None,
            "success_rate": h.get("success_rate") if h else None,
            "baseline_yield": h.get("baseline_yield") if h else None,
            "runs": c.get("runs", 0),
            "jobs_found": c.get("jobs_found", 0),
            "latest_status": (h.get("latest") or {}).get("status") if h else None,
        })

    active = [i for i in items if i["scheduling"] == "running"]
    return {
        "days": days,
        "region": region,
        "next_run_is_probe": next_is_probe,
        "totals": {
            "registered": len(items),
            "active": len(active),
            "backed_off": len([i for i in items if i["scheduling"] == "backed_off"]),
            "probing": len([i for i in items if i["scheduling"] == "probing"]),
            "dormant": len([i for i in items if i["scheduling"] == "dormant"]),
            "c_tier": len([i for i in items if i["scheduling"] == "c_tier"]),
            "flagged": len([i for i in items if i["flagged"]]),
        },
        "sources": items,
    }


def _user_region(user_id: str) -> str:
    """The user's discovery region — explicit choice first, else inferred."""
    from database import get_db
    from workers.job_discovery import resolve_region
    try:
        res = get_db().table("users").select(
            "preferred_locations, discovery_region"
        ).eq("id", user_id).single().execute()
        return resolve_region(res.data or {})
    except Exception:
        # Pre-migration: discovery_region may not exist — fall back to inference.
        try:
            res = get_db().table("users").select(
                "preferred_locations"
            ).eq("id", user_id).single().execute()
            return resolve_region(res.data or {})
        except Exception:
            return "india"


@router.get("/ai-usage")
async def ai_usage(days: int = 14, user_id: str = Depends(get_user_id)):
    """LLM usage rollups (today by provider/feature + daily series) and budget status."""
    days = max(1, min(days, 60))
    summary = telemetry.llm_usage_summary(days=days)
    token_budget = settings.LLM_DAILY_TOKEN_BUDGET
    usd_budget = settings.LLM_DAILY_BUDGET_USD
    today = summary["today"]
    summary["budget"] = {
        "token_budget": token_budget,
        "usd_budget": usd_budget,
        "tokens_used": today["tokens"],
        "cost_used": today["cost_usd"],
        "exceeded": bool(
            (token_budget and today["tokens"] >= token_budget)
            or (usd_budget and today["cost_usd"] >= usd_budget)
        ),
    }
    return summary
