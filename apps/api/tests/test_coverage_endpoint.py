"""Tests for the /telemetry/coverage endpoint (Phase 3 #16)."""
import pytest

from routers import telemetry as tel_router


@pytest.fixture(autouse=True)
def stub_telemetry(monkeypatch):
    # Deterministic health/contribution/region — no DB.
    monkeypatch.setattr(tel_router.telemetry, "source_health_map",
                        lambda uid, days=14: {
                            "foundit": {"flagged": True, "flag_reason": "consecutive_errors",
                                        "success_rate": 0.0, "baseline_yield": 0, "latest": {"status": "error"}},
                            "naukri": {"flagged": False, "flag_reason": None,
                                       "success_rate": 1.0, "baseline_yield": 40, "latest": {"status": "done"}},
                        })
    monkeypatch.setattr(tel_router.telemetry, "source_contribution",
                        lambda uid, days=14: {"naukri": {"runs": 5, "jobs_found": 120, "jobs_seen": 200}})
    monkeypatch.setattr(tel_router, "_user_region", lambda uid: "india")
    monkeypatch.setattr(tel_router.settings, "DISCOVERY_HEALTH_SCHEDULING_ENABLED", True)


@pytest.mark.asyncio
async def test_coverage_shape_and_totals(monkeypatch):
    monkeypatch.setattr(tel_router.telemetry, "discovery_run_count", lambda uid: 1)  # not a probe
    d = await tel_router.coverage(days=14, user_id="u1")

    assert d["region"] == "india"
    assert d["next_run_is_probe"] is False
    t = d["totals"]
    assert t["registered"] == len(d["sources"])
    assert t["active"] >= 1  # naukri and others run

    by_name = {s["name"]: s for s in d["sources"]}
    assert by_name["naukri"]["scheduling"] == "running"
    assert by_name["naukri"]["jobs_found"] == 120
    assert by_name["naukri"]["kind"] == "browser"
    # foundit is a discoverable API source now, so a health flag backs it off
    # (C-tier sources are excluded before health is ever consulted).
    assert by_name["foundit"]["scheduling"] == "backed_off"
    assert by_name["foundit"]["kind"] == "api"
    # C-tier (discoverable=False) stays display-only regardless of health.
    assert by_name["instahyre"]["scheduling"] == "c_tier"
    # keyed sources with no key are dormant
    assert by_name["careerjet"]["scheduling"] == "dormant"
    assert by_name["ats"]["kind"] == "ats"


@pytest.mark.asyncio
async def test_probe_run_flag(monkeypatch):
    monkeypatch.setattr(tel_router.telemetry, "discovery_run_count", lambda uid: 4)  # divisible by 4
    d = await tel_router.coverage(days=14, user_id="u1")
    assert d["next_run_is_probe"] is True
