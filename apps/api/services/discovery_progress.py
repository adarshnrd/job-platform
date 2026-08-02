"""
Discovery progress tracker — live, in-process state for job discovery runs.

Discovery executes via FastAPI BackgroundTasks inside this same process, so a
module-level store is visible to both the worker thread and request handlers
(guarded by a lock — the worker runs in a threadpool thread).

Live runs keep a capped event log that the Search Activity page tails via
polling. Finished runs are summarized (events dropped) into
data/discovery_runs.json so history survives restarts.
"""
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from services import telemetry

MAX_EVENTS_PER_RUN = 1000
MAX_LIVE_RUNS = 5       # full runs (with events) kept in memory
MAX_HISTORY = 50        # summaries persisted to disk

_HISTORY_FILE = Path(__file__).resolve().parent.parent / "data" / "discovery_runs.json"

_lock = threading.Lock()
_runs: dict[str, dict] = {}   # run_id -> live run (includes events), insertion-ordered
_history: list[dict] = []     # newest-first summaries (no events)
_loaded = False

# Ordered pipeline phases shown as a stepper in the UI.
PHASES = ["initializing", "searching", "analyzing", "scoring", "saving"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_history_locked():
    global _loaded, _history
    if _loaded:
        return
    _loaded = True
    try:
        if _HISTORY_FILE.exists():
            _history = json.loads(_HISTORY_FILE.read_text())[:MAX_HISTORY]
    except Exception as e:
        logger.warning(f"Could not load discovery run history: {e}")
        _history = []


def _persist_history_locked():
    try:
        _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _HISTORY_FILE.write_text(json.dumps(_history[:MAX_HISTORY], indent=2))
    except Exception as e:
        logger.warning(f"Could not persist discovery run history: {e}")


def _summary(run: dict) -> dict:
    """Run without its event log — what /status, /runs, and history return."""
    return {k: v for k, v in run.items() if k not in ("events", "_seq")}


def _upsert_history_locked(run: dict):
    """Record the run's current state on disk, replacing any earlier snapshot.

    Called on every phase transition, not only at the end: a run killed mid-flight
    used to vanish from history entirely, leaving no trace of the hours it spent
    scraping. The jobs it scraped are safe in the database either way — this is
    so the *run* is accounted for too.
    """
    _load_history_locked()
    summary = _summary(run)
    for i, entry in enumerate(_history):
        if entry.get("run_id") == run["run_id"]:
            _history[i] = summary
            break
    else:
        _history.insert(0, summary)
    del _history[MAX_HISTORY:]
    _persist_history_locked()


def recover_interrupted_runs() -> int:
    """Mark runs that were still 'running' when the process died as interrupted.

    Called at startup. Their scraped jobs are already persisted and their queue
    items are picked up by the pipeline drain, so this only corrects the record.
    """
    with _lock:
        _load_history_locked()
        n = 0
        for entry in _history:
            if entry.get("status") == "running":
                # Capture where it stopped before `phase` becomes the status.
                entry["failed_phase"] = entry.get("failed_phase") or entry.get("phase")
                entry["status"] = "interrupted"
                entry["phase"] = "interrupted"
                entry["error"] = "Interrupted by a server restart — saved jobs are being processed in the background"
                entry["finished_at"] = _now()
                n += 1
        if n:
            _persist_history_locked()
            logger.info(f"Marked {n} interrupted discovery run(s) from a previous process")
        return n


def _emit_locked(run: dict, message: str, level: str = "info"):
    run["_seq"] += 1
    run["events"].append({"seq": run["_seq"], "ts": _now(), "level": level, "message": message})
    if len(run["events"]) > MAX_EVENTS_PER_RUN:
        del run["events"][: len(run["events"]) - MAX_EVENTS_PER_RUN]


def start_run(user_id: str, region: str, trigger: str = "manual") -> str:
    run_id = uuid.uuid4().hex[:12]
    run = {
        "run_id": run_id,
        "user_id": user_id,
        "region": region,
        "trigger": trigger,
        "status": "running",
        "phase": "initializing",
        "failed_phase": None,   # the phase a failed/interrupted run died in
        "started_at": _now(),
        "finished_at": None,
        "current_source": None,
        "current_query": None,
        "sources": {},
        # `saved` tracks match records actually written — it can trail `evaluated`
        # when individual saves fail, which is what makes a partial run legible.
        "counts": {"scraped": 0, "evaluated": 0, "matched": 0, "queued": 0, "saved": 0},
        "error": None,
        "events": [],
        "_seq": 0,
    }
    with _lock:
        _load_history_locked()
        _runs[run_id] = run
        # Cap live runs, oldest first (never evict a still-running one).
        while len(_runs) > MAX_LIVE_RUNS:
            for rid in list(_runs):
                if _runs[rid]["status"] != "running":
                    del _runs[rid]
                    break
            else:
                break
        _emit_locked(run, f"Discovery started ({trigger}, region={region})")
    return run_id


def log(run_id: str, message: str, level: str = "info"):
    with _lock:
        run = _runs.get(run_id)
        if run:
            _emit_locked(run, message, level)


def set_phase(run_id: str, phase: str, message: str | None = None):
    with _lock:
        run = _runs.get(run_id)
        if not run:
            return
        run["phase"] = phase
        if phase != "searching":
            run["current_source"] = None
            run["current_query"] = None
        _emit_locked(run, message or f"Phase: {phase}")
        # Checkpoint the run record so a crash leaves evidence of how far it got.
        _upsert_history_locked(run)


def register_sources(run_id: str, names: list[str]):
    with _lock:
        run = _runs.get(run_id)
        if run:
            run["sources"] = {n: _new_source() for n in names}


def _new_source() -> dict:
    # jobs_found = new after dedup; jobs_seen = raw scraper yield (health signal)
    return {"status": "pending", "jobs_found": 0, "jobs_seen": 0, "duration_ms": 0, "error": None}


def source_started(run_id: str, source: str):
    with _lock:
        run = _runs.get(run_id)
        if not run:
            return
        run["current_source"] = source
        src = run["sources"].setdefault(source, _new_source())
        src["status"] = "searching"
        src["_t0"] = time.monotonic()
        _emit_locked(run, f"Searching {source}…")


def searching_query(run_id: str, source: str, query: str, location: str):
    with _lock:
        run = _runs.get(run_id)
        if not run:
            return
        run["current_query"] = query
        _emit_locked(run, f"{source}: searching '{query}' in {location}")


def query_result(run_id: str, source: str, query: str, found: int, new: int):
    with _lock:
        run = _runs.get(run_id)
        if not run:
            return
        src = run["sources"].setdefault(source, _new_source())
        src["jobs_found"] += new
        src["jobs_seen"] = src.get("jobs_seen", 0) + found
        run["counts"]["scraped"] += new
        _emit_locked(run, f"{source}: '{query}' → {found} jobs ({new} new)", "success" if new else "info")


def source_finished(run_id: str, source: str, error: str | None = None):
    with _lock:
        run = _runs.get(run_id)
        if not run:
            return
        src = run["sources"].setdefault(source, _new_source())
        t0 = src.pop("_t0", None)
        if t0 is not None:
            src["duration_ms"] = int((time.monotonic() - t0) * 1000)
        if error:
            src["status"] = "error"
            src["error"] = error
            _emit_locked(run, f"{source} failed: {error}", "error")
        else:
            src["status"] = "done"
            _emit_locked(run, f"{source} done — {src['jobs_found']} new jobs")


def update_counts(run_id: str, **counts: int):
    with _lock:
        run = _runs.get(run_id)
        if run:
            run["counts"].update(counts)


def finish_run(run_id: str, status: str = "completed", error: str | None = None):
    """Idempotent — the worker's normal exit and its exception handler both call this."""
    with _lock:
        run = _runs.get(run_id)
        if not run or run["status"] != "running":
            return
        run["status"] = status
        # Remember where it actually stopped before `phase` is overwritten with
        # the status — otherwise the UI stepper can only guess, and defaults to
        # blaming the first step for a failure that happened at the last one.
        if status != "completed":
            run["failed_phase"] = run["phase"]
        run["phase"] = status
        run["finished_at"] = _now()
        run["current_source"] = None
        run["current_query"] = None
        if error:
            run["error"] = error
            _emit_locked(run, f"Discovery failed: {error}", "error")
        else:
            c = run["counts"]
            _emit_locked(
                run,
                f"Discovery complete — {c['scraped']} scraped, {c['evaluated']} evaluated, "
                f"{c['matched']} matched, {c['queued']} queued for auto-apply",
                "success",
            )
        for src in run["sources"].values():
            src.pop("_t0", None)  # crashed mid-source — drop the timing marker
        _upsert_history_locked(run)
        telemetry.record_discovery_run(_summary(run))  # swallows its own errors


def active_run_id(user_id: str) -> str | None:
    with _lock:
        for r in reversed(_runs.values()):
            if r["user_id"] == user_id and r["status"] == "running":
                return r["run_id"]
        return None


def snapshot(user_id: str) -> dict:
    """The user's active run, or their most recent one — for GET /discovery/status."""
    with _lock:
        _load_history_locked()
        user_runs = [r for r in _runs.values() if r["user_id"] == user_id]
        active = [r for r in user_runs if r["status"] == "running"]
        if active:
            return {"active": True, "run": _summary(active[-1])}
        if user_runs:
            return {"active": False, "run": _summary(user_runs[-1])}
        for h in _history:
            if h["user_id"] == user_id:
                return {"active": False, "run": h}
        return {"active": False, "run": None}


def list_runs(user_id: str) -> list[dict]:
    """Newest-first run summaries: live runs plus persisted history, deduped."""
    with _lock:
        _load_history_locked()
        live = [_summary(r) for r in reversed(_runs.values()) if r["user_id"] == user_id]
        live_ids = {r["run_id"] for r in live}
        past = [h for h in _history if h["user_id"] == user_id and h["run_id"] not in live_ids]
        return (live + past)[:MAX_HISTORY]


def get_events(run_id: str, after: int = 0) -> dict:
    with _lock:
        run = _runs.get(run_id)
        if not run:
            return {"run_id": run_id, "events": [], "last_seq": after, "live": False}
        events = [e for e in run["events"] if e["seq"] > after]
        return {
            "run_id": run_id,
            "events": events,
            "last_seq": run["_seq"],
            "live": run["status"] == "running",
        }
