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
