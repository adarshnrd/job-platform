"""Tests for health-driven source scheduling (Phase 3 #13)."""
from types import SimpleNamespace

import pytest

from services import source_scheduler as sched


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(sched.settings, "DISCOVERY_HEALTH_SCHEDULING_ENABLED", True)
    monkeypatch.setattr(sched.settings, "SOURCE_ERROR_BACKOFF_PROBE_EVERY", 4)


def _src(name):
    return SimpleNamespace(name=name)


def _health(flagged=False, reason=None, baseline=0.0):
    return {"flagged": flagged, "flag_reason": reason, "baseline_yield": baseline}


HEALTHY = {"naukri": _health(baseline=40), "hirist": _health(baseline=20)}


def test_all_run_when_healthy():
    srcs = [_src("naukri"), _src("hirist")]
    plan = sched.plan_sources(srcs, HEALTHY, run_seq=1)
    assert {s.name for s in plan.to_run} == {"naukri", "hirist"}
    assert plan.skipped == {}


def test_backs_off_consecutive_error_source():
    srcs = [_src("naukri"), _src("foundit")]
    health = {"naukri": _health(baseline=40),
              "foundit": _health(flagged=True, reason="consecutive_errors")}
    plan = sched.plan_sources(srcs, health, run_seq=1)  # not a probe run
    assert [s.name for s in plan.to_run] == ["naukri"]
    assert plan.skipped == {"foundit": "backed_off_consecutive_errors"}


def test_yield_drop_source_still_runs():
    # A degraded-but-yielding source is NOT backed off — losing partial coverage
    # is worse than a wasted fetch.
    srcs = [_src("shine")]
    health = {"shine": _health(flagged=True, reason="yield_drop", baseline=15)}
    plan = sched.plan_sources(srcs, health, run_seq=1)
    assert [s.name for s in plan.to_run] == ["shine"]
    assert plan.skipped == {}


def test_probe_run_includes_backed_off_sources():
    srcs = [_src("foundit")]
    health = {"foundit": _health(flagged=True, reason="consecutive_errors")}
    # run_seq divisible by PROBE_EVERY (4) → probe run
    plan = sched.plan_sources(srcs, health, run_seq=4)
    assert plan.is_probe is True
    assert [s.name for s in plan.to_run] == ["foundit"]
    assert plan.skipped == {}


def test_explicit_pick_never_backed_off():
    srcs = [_src("foundit")]
    health = {"foundit": _health(flagged=True, reason="consecutive_errors")}
    plan = sched.plan_sources(srcs, health, run_seq=1, explicit_platforms=["foundit"])
    assert [s.name for s in plan.to_run] == ["foundit"]
    assert plan.skipped == {}


def test_insufficient_data_never_backed_off():
    # A brand-new source (insufficient_data) must not be skipped.
    srcs = [_src("newsource")]
    health = {"newsource": _health(flagged=False, reason="insufficient_data")}
    plan = sched.plan_sources(srcs, health, run_seq=1)
    assert [s.name for s in plan.to_run] == ["newsource"]


def test_orders_healthy_high_yield_first():
    srcs = [_src("low"), _src("high"), _src("broken")]
    health = {
        "low": _health(baseline=5),
        "high": _health(baseline=90),
        "broken": _health(flagged=True, reason="yield_drop", baseline=1),
    }
    plan = sched.plan_sources(srcs, health, run_seq=1)
    names = [s.name for s in plan.to_run]
    assert names[0] == "high"          # highest baseline yield first
    assert names[-1] == "broken"       # flagged sources last


def test_disabled_runs_everything(monkeypatch):
    monkeypatch.setattr(sched.settings, "DISCOVERY_HEALTH_SCHEDULING_ENABLED", False)
    srcs = [_src("foundit")]
    health = {"foundit": _health(flagged=True, reason="consecutive_errors")}
    plan = sched.plan_sources(srcs, health, run_seq=1)
    assert [s.name for s in plan.to_run] == ["foundit"]
    assert plan.skipped == {}


def test_unknown_health_source_kept_and_middle_ordered():
    srcs = [_src("known_high"), _src("unknown")]
    health = {"known_high": _health(baseline=50)}
    plan = sched.plan_sources(srcs, health, run_seq=1)
    assert {s.name for s in plan.to_run} == {"known_high", "unknown"}
    assert plan.to_run[0].name == "known_high"  # known high-yield ahead of unknown
