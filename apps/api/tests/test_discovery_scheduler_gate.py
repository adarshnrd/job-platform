"""The automatic discovery cron must be opt-in (DISCOVERY_SCHEDULER_ENABLED,
default False) so an app restart/redeploy never starts scraping job platforms
on its own — only the explicit env flag arms it. Manual discovery from the UI
(POST /jobs/discover → BackgroundTasks) is a separate code path, untouched by
this flag either way (verified by inspection: routers/jobs.py never reads
DISCOVERY_SCHEDULER_ENABLED)."""
import pytest

import scheduler as scheduler_mod


@pytest.fixture(autouse=True)
def _stop_scheduler_after():
    yield
    scheduler_mod.stop_scheduler()


def test_discovery_cron_not_registered_by_default(monkeypatch):
    monkeypatch.setattr(scheduler_mod.settings, "DISCOVERY_SCHEDULER_ENABLED", False)
    scheduler_mod.start_scheduler()
    assert scheduler_mod.scheduler.get_job("discover_jobs") is None
    # Unrelated cron jobs still run — only discovery is gated.
    assert scheduler_mod.scheduler.get_job("process_apply_queue") is not None


def test_discovery_cron_registered_when_flag_enabled(monkeypatch):
    monkeypatch.setattr(scheduler_mod.settings, "DISCOVERY_SCHEDULER_ENABLED", True)
    monkeypatch.setattr(scheduler_mod.settings, "DISCOVERY_INTERVAL_HOURS", 6)
    scheduler_mod.start_scheduler()
    job = scheduler_mod.scheduler.get_job("discover_jobs")
    assert job is not None
    assert job.trigger.fields[5].expressions[0].step == 6  # CronTrigger "*/6" hour field
