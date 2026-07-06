"""Tests for mission-control telemetry: run ledger, source health, LLM usage & budget."""
from datetime import datetime, timedelta, timezone

import pytest

from services import telemetry
from services.ai import provider


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry, "DB_PATH", tmp_path / "telemetry.db")
    telemetry._reset_for_tests()
    yield
    telemetry._reset_for_tests()


def _iso(offset_days: float = 0, offset_minutes: float = 0) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(days=offset_days, minutes=offset_minutes)
    ).isoformat()


def _discovery_summary(run_id="run1", user_id="u1", sources=None, **overrides) -> dict:
    summary = {
        "run_id": run_id,
        "user_id": user_id,
        "region": "india",
        "trigger": "manual",
        "status": "completed",
        "phase": "completed",
        "started_at": _iso(offset_minutes=-5),
        "finished_at": _iso(),
        "counts": {"scraped": 12, "evaluated": 10, "matched": 4, "queued": 1},
        "error": None,
        "sources": sources or {
            "linkedin": {"status": "done", "jobs_found": 8, "jobs_seen": 30, "duration_ms": 4200, "error": None},
            "naukri": {"status": "error", "jobs_found": 0, "jobs_seen": 0, "duration_ms": 900, "error": "timeout"},
        },
    }
    summary.update(overrides)
    return summary


# ══════════════════════════════════════════════════════════════
#  RUN LEDGER
# ══════════════════════════════════════════════════════════════

def test_discovery_run_roundtrip():
    telemetry.record_discovery_run(_discovery_summary())

    runs = telemetry.list_runs("u1")
    assert len(runs) == 1
    run = runs[0]
    assert run["kind"] == "discovery"
    assert run["status"] == "completed"
    assert run["counts"]["matched"] == 4
    assert run["duration_ms"] and run["duration_ms"] >= 4 * 60 * 1000

    by_name = {s["source"]: s for s in run["sources"]}
    assert by_name["linkedin"]["jobs_seen"] == 30
    assert by_name["linkedin"]["duration_ms"] == 4200
    assert by_name["naukri"]["status"] == "error"
    assert by_name["naukri"]["error"] == "timeout"


def test_discovery_run_record_is_idempotent():
    telemetry.record_discovery_run(_discovery_summary())
    telemetry.record_discovery_run(_discovery_summary())  # finish_run may fire twice

    runs = telemetry.list_runs("u1")
    assert len(runs) == 1
    assert len(runs[0]["sources"]) == 2


def test_apply_run_and_kind_filter():
    telemetry.record_discovery_run(_discovery_summary())
    telemetry.record_apply_run(
        "u1", _iso(offset_minutes=-2), _iso(),
        {"attempted": 3, "applied": 2, "rate_limited": 1, "failed": 0},
    )

    assert len(telemetry.list_runs("u1")) == 2
    apply_runs = telemetry.list_runs("u1", kind="apply")
    assert len(apply_runs) == 1
    assert apply_runs[0]["counts"]["applied"] == 2
    assert apply_runs[0]["sources"] == []
    # other users see nothing
    assert telemetry.list_runs("someone-else") == []


# ══════════════════════════════════════════════════════════════
#  SOURCE HEALTH
# ══════════════════════════════════════════════════════════════

def _seed_source_runs(source: str, yields: list, user_id="u1"):
    """Each entry: int jobs_seen for an ok run, or the string 'error'."""
    for i, y in enumerate(yields):
        offset = -(len(yields) - 1 - i)  # oldest first, one run per day
        src = (
            {"status": "error", "jobs_found": 0, "jobs_seen": 0, "duration_ms": 100, "error": "boom"}
            if y == "error"
            else {"status": "done", "jobs_found": y, "jobs_seen": y, "duration_ms": 100, "error": None}
        )
        telemetry.record_discovery_run(_discovery_summary(
            run_id=f"{source}-{i}",
            user_id=user_id,
            sources={source: src},
            started_at=_iso(offset_days=offset, offset_minutes=-5),
            finished_at=_iso(offset_days=offset),
        ))


def test_health_flags_sustained_yield_drop():
    _seed_source_runs("linkedin", [20, 22, 18, 21, 1, 0])

    health = {s["source"]: s for s in telemetry.source_health("u1")}
    assert health["linkedin"]["flagged"] is True
    assert health["linkedin"]["flag_reason"] == "yield_drop"
    assert health["linkedin"]["baseline_yield"] > 15


def test_health_ignores_single_bad_run():
    _seed_source_runs("naukri", [20, 22, 18, 21, 0])  # one bad run, not sustained

    health = {s["source"]: s for s in telemetry.source_health("u1")}
    assert health["naukri"]["flagged"] is False


def test_health_flags_consecutive_errors():
    _seed_source_runs("shine", [15, 14, "error", "error"])

    health = {s["source"]: s for s in telemetry.source_health("u1")}
    assert health["shine"]["flagged"] is True
    assert health["shine"]["flag_reason"] == "consecutive_errors"
    assert health["shine"]["success_rate"] == 0.5


def test_health_needs_minimum_runs():
    _seed_source_runs("dice", [10, "error"])

    health = {s["source"]: s for s in telemetry.source_health("u1")}
    assert health["dice"]["flagged"] is False
    assert health["dice"]["flag_reason"] == "insufficient_data"


def test_health_daily_series_has_full_window():
    _seed_source_runs("remotive", [5, 6, 7])

    src = telemetry.source_health("u1", days=14)[0]
    assert len(src["daily"]) == 14
    assert sum(d["jobs_seen"] for d in src["daily"]) == 18
    assert src["daily"][-1]["day"] == datetime.now(timezone.utc).date().isoformat()


# ══════════════════════════════════════════════════════════════
#  LLM USAGE & BUDGET
# ══════════════════════════════════════════════════════════════

def test_llm_usage_recording_and_summary():
    telemetry.record_llm_call("groq", "llama-3.3", "job_scoring", 1000, 200, 0.0)
    telemetry.record_llm_call("groq", "llama-3.3", "job_scoring", 500, 100, 0.0)
    telemetry.record_llm_call("anthropic", "sonnet", "cover_letter", 800, 400, 0.0084)

    totals = telemetry.llm_today_totals()
    assert totals["calls"] == 3
    assert totals["tokens"] == 3000
    assert totals["cost_usd"] == pytest.approx(0.0084)

    summary = telemetry.llm_usage_summary(days=7)
    assert summary["providers"]["groq"]["calls"] == 2
    assert summary["features"]["job_scoring"]["input_tokens"] == 1500
    assert summary["features"]["cover_letter"]["cost_usd"] == pytest.approx(0.0084)
    assert len(summary["daily"]) == 7
    assert summary["daily"][-1]["tokens"] == 3000


def test_budget_hard_stop(monkeypatch):
    monkeypatch.setattr(provider.settings, "LLM_DAILY_TOKEN_BUDGET", 1000)
    monkeypatch.setattr(provider.settings, "LLM_DAILY_BUDGET_USD", 0.0)

    provider._check_budget()  # under budget — fine
    telemetry.record_llm_call("groq", "llama-3.3", "job_scoring", 900, 200, 0.0)

    with pytest.raises(provider.BudgetExceededError):
        provider._check_budget()
    # the choke point every LLM request goes through raises before any HTTP
    with pytest.raises(provider.BudgetExceededError):
        provider._call_provider("groq", "system", "user")


def test_budget_unlimited_by_default(monkeypatch):
    monkeypatch.setattr(provider.settings, "LLM_DAILY_TOKEN_BUDGET", 0)
    monkeypatch.setattr(provider.settings, "LLM_DAILY_BUDGET_USD", 0.0)
    telemetry.record_llm_call("groq", "llama-3.3", "other", 10**9, 10**9, 999.0)
    provider._check_budget()  # no budget configured — never raises


def test_cost_budget_hard_stop(monkeypatch):
    monkeypatch.setattr(provider.settings, "LLM_DAILY_TOKEN_BUDGET", 0)
    monkeypatch.setattr(provider.settings, "LLM_DAILY_BUDGET_USD", 1.0)
    telemetry.record_llm_call("anthropic", "sonnet", "copilot", 100000, 50000, 1.05)

    with pytest.raises(provider.BudgetExceededError):
        provider._check_budget()


def test_llm_feature_attribution():
    @provider.llm_feature("test_feature")
    def sync_fn():
        return provider._FEATURE.get()

    @provider.llm_feature("async_feature")
    async def async_fn():
        return provider._FEATURE.get()

    assert provider._FEATURE.get() == "other"
    assert sync_fn() == "test_feature"
    assert provider._FEATURE.get() == "other"

    import asyncio
    assert asyncio.run(async_fn()) == "async_feature"

    with provider.llm_feature_scope("scoped"):
        assert provider._FEATURE.get() == "scoped"
    assert provider._FEATURE.get() == "other"
