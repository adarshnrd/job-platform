"""
Tests for run-record durability: a run that dies must leave evidence of where.
"""
import json

import pytest

from services import discovery_progress as progress


@pytest.fixture(autouse=True)
def isolated_history(tmp_path, monkeypatch):
    monkeypatch.setattr(progress, "_HISTORY_FILE", tmp_path / "discovery_runs.json")
    monkeypatch.setattr(progress, "_runs", {})
    monkeypatch.setattr(progress, "_history", [])
    monkeypatch.setattr(progress, "_loaded", False)
    monkeypatch.setattr(progress.telemetry, "record_discovery_run", lambda summary: None)
    yield


def test_failure_records_the_phase_it_actually_died_in():
    run_id = progress.start_run("u1", "india")
    progress.set_phase(run_id, "searching")
    progress.set_phase(run_id, "scoring")

    progress.finish_run(run_id, status="failed", error="[Errno 8] nodename nor servname provided")

    run = progress.snapshot("u1")["run"]
    # `phase` mirrors the status for backwards compatibility; `failed_phase` is
    # what the UI stepper needs so it stops blaming step 1 for a step-4 failure.
    assert run["status"] == "failed"
    assert run["failed_phase"] == "scoring"


def test_completed_run_has_no_failed_phase():
    run_id = progress.start_run("u1", "india")
    progress.set_phase(run_id, "saving")

    progress.finish_run(run_id)

    assert progress.snapshot("u1")["run"]["failed_phase"] is None


def test_run_is_recorded_on_disk_before_it_finishes(tmp_path):
    run_id = progress.start_run("u1", "india")
    progress.set_phase(run_id, "searching", "Searching 13 sources")

    # A crash here used to leave nothing at all — the run vanished from history.
    saved = json.loads(progress._HISTORY_FILE.read_text())
    assert saved[0]["run_id"] == run_id
    assert saved[0]["phase"] == "searching"


def test_phase_checkpoints_do_not_duplicate_the_run():
    run_id = progress.start_run("u1", "india")
    for phase in ("searching", "analyzing", "scoring", "saving"):
        progress.set_phase(run_id, phase)
    progress.finish_run(run_id)

    saved = json.loads(progress._HISTORY_FILE.read_text())
    assert [r["run_id"] for r in saved] == [run_id]


def test_interrupted_runs_are_closed_out_at_startup():
    run_id = progress.start_run("u1", "india")
    progress.set_phase(run_id, "analyzing")
    # Simulate a process restart: the in-memory run is gone, the file remains.
    progress._runs.clear()
    progress._loaded = False
    progress._history.clear()

    assert progress.recover_interrupted_runs() == 1

    run = progress.snapshot("u1")["run"]
    assert run["status"] == "interrupted"
    assert run["failed_phase"] == "analyzing"
    assert run["finished_at"]


def test_recovery_is_idempotent():
    run_id = progress.start_run("u1", "india")
    progress.set_phase(run_id, "analyzing")
    progress._runs.clear()

    assert progress.recover_interrupted_runs() == 1
    assert progress.recover_interrupted_runs() == 0


def test_saved_count_is_tracked_separately_from_evaluated():
    run_id = progress.start_run("u1", "india")
    progress.update_counts(run_id, evaluated=10, saved=7)

    counts = progress.snapshot("u1")["run"]["counts"]
    assert counts["evaluated"] == 10
    assert counts["saved"] == 7, "a partial save must be visible, not rounded up"
