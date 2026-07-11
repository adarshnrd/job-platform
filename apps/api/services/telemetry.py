"""
Mission-control telemetry — durable run ledger, scraper health, LLM usage.

SQLite-backed (data/telemetry.db) so history survives restarts without any
new infrastructure. Three tables:

  runs         — one row per discovery/apply run (status, duration, counts)
  run_sources  — per-source outcome of a discovery run (yield, timing, error)
  llm_usage    — one row per LLM call (provider, feature, tokens, cost)

Writers open a short-lived connection per call (WAL mode), which is safe from
both the FastAPI threadpool and APScheduler worker threads. All recording
functions swallow their own errors — telemetry must never break a run.
"""
import json
import sqlite3
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from loguru import logger

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "telemetry.db"

# Source-health flagging thresholds (see source_health()).
HEALTH_MIN_RUNS = 3        # need at least this many runs before judging
HEALTH_BASELINE_MIN = 5    # baseline avg yield below this → too quiet to judge
HEALTH_DROP_RATIO = 0.3    # latest yield < 30% of baseline == ">70% drop"

_lock = threading.Lock()
_initialized_path: str | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,              -- discovery | apply
    user_id     TEXT NOT NULL,
    trigger     TEXT,
    region      TEXT,
    status      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    duration_ms INTEGER,
    counts      TEXT,                       -- JSON object of counters
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_user_time ON runs(user_id, started_at DESC);

CREATE TABLE IF NOT EXISTS run_sources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    source      TEXT NOT NULL,
    status      TEXT,
    jobs_found  INTEGER DEFAULT 0,          -- new jobs added to the DB
    jobs_seen   INTEGER DEFAULT 0,          -- raw scraper yield (pre-dedup)
    duration_ms INTEGER DEFAULT 0,
    error       TEXT,
    finished_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sources_user_time ON run_sources(user_id, finished_at DESC);

CREATE TABLE IF NOT EXISTS llm_usage (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,
    day           TEXT NOT NULL,
    provider      TEXT NOT NULL,
    model         TEXT,
    feature       TEXT NOT NULL DEFAULT 'other',
    input_tokens  INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd      REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_llm_day ON llm_usage(day);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_today() -> date:
    """All day-bucketing uses UTC dates — timestamps are recorded in UTC."""
    return datetime.now(timezone.utc).date()


def _conn() -> sqlite3.Connection:
    global _initialized_path
    path = Path(DB_PATH)
    if _initialized_path != str(path):
        with _lock:
            if _initialized_path != str(path):
                path.parent.mkdir(parents=True, exist_ok=True)
                con = sqlite3.connect(path, timeout=10)
                try:
                    con.execute("PRAGMA journal_mode=WAL")
                    con.executescript(_SCHEMA)
                    con.commit()
                finally:
                    con.close()
                _initialized_path = str(path)
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def _reset_for_tests():
    """Re-run schema init after DB_PATH is repointed (tests only)."""
    global _initialized_path, _today_cache
    _initialized_path = None
    _today_cache = None


# ══════════════════════════════════════════════════════════════
#  RUN LEDGER
# ══════════════════════════════════════════════════════════════

def _duration_ms(started_at: str, finished_at: str | None) -> int | None:
    if not finished_at:
        return None
    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(finished_at)
        return max(0, int((end - start).total_seconds() * 1000))
    except Exception:
        return None


def record_discovery_run(summary: dict):
    """Persist a finished discovery run (a discovery_progress summary dict)."""
    try:
        run_id = summary["run_id"]
        user_id = summary["user_id"]
        finished_at = summary.get("finished_at") or _now_iso()
        con = _conn()
        try:
            con.execute(
                "INSERT OR REPLACE INTO runs "
                "(run_id, kind, user_id, trigger, region, status, started_at, finished_at, duration_ms, counts, error) "
                "VALUES (?, 'discovery', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    user_id,
                    summary.get("trigger"),
                    summary.get("region"),
                    summary.get("status", "completed"),
                    summary["started_at"],
                    finished_at,
                    _duration_ms(summary["started_at"], finished_at),
                    json.dumps(summary.get("counts") or {}),
                    summary.get("error"),
                ),
            )
            con.execute("DELETE FROM run_sources WHERE run_id = ?", (run_id,))
            for name, src in (summary.get("sources") or {}).items():
                con.execute(
                    "INSERT INTO run_sources "
                    "(run_id, user_id, source, status, jobs_found, jobs_seen, duration_ms, error, finished_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        user_id,
                        name,
                        src.get("status"),
                        src.get("jobs_found", 0),
                        src.get("jobs_seen", 0),
                        src.get("duration_ms", 0),
                        src.get("error"),
                        finished_at,
                    ),
                )
            con.commit()
        finally:
            con.close()
    except Exception as e:
        logger.warning(f"Telemetry: failed to record discovery run: {e}")


def record_apply_run(
    user_id: str,
    started_at: str,
    finished_at: str,
    counts: dict,
    status: str = "completed",
    error: str | None = None,
):
    """Persist one apply-queue batch for a user."""
    try:
        con = _conn()
        try:
            con.execute(
                "INSERT INTO runs "
                "(run_id, kind, user_id, trigger, region, status, started_at, finished_at, duration_ms, counts, error) "
                "VALUES (?, 'apply', ?, 'scheduled', NULL, ?, ?, ?, ?, ?, ?)",
                (
                    uuid.uuid4().hex[:12],
                    user_id,
                    status,
                    started_at,
                    finished_at,
                    _duration_ms(started_at, finished_at),
                    json.dumps(counts or {}),
                    error,
                ),
            )
            con.commit()
        finally:
            con.close()
    except Exception as e:
        logger.warning(f"Telemetry: failed to record apply run: {e}")


def list_runs(user_id: str, kind: str | None = None, limit: int = 30) -> list[dict]:
    """Newest-first runs with their per-source breakdown attached."""
    con = _conn()
    try:
        q = "SELECT * FROM runs WHERE user_id = ?"
        params: list = [user_id]
        if kind:
            q += " AND kind = ?"
            params.append(kind)
        q += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        runs = [dict(r) for r in con.execute(q, params).fetchall()]
        if not runs:
            return []
        ids = [r["run_id"] for r in runs]
        placeholders = ",".join("?" * len(ids))
        src_rows = con.execute(
            f"SELECT * FROM run_sources WHERE run_id IN ({placeholders}) ORDER BY jobs_seen DESC",
            ids,
        ).fetchall()
        by_run: dict[str, list[dict]] = {}
        for row in src_rows:
            d = dict(row)
            d.pop("id", None)
            d.pop("user_id", None)
            by_run.setdefault(d.pop("run_id"), []).append(d)
        for r in runs:
            r["counts"] = json.loads(r["counts"] or "{}")
            r["sources"] = by_run.get(r["run_id"], [])
        return runs
    finally:
        con.close()


# ══════════════════════════════════════════════════════════════
#  SCRAPER HEALTH
# ══════════════════════════════════════════════════════════════

def source_health(user_id: str, days: int = 14) -> list[dict]:
    """Per-source health over the window: daily yields, error rate, degradation flag.

    Health is judged on jobs_seen (raw scraper yield) rather than jobs_found
    (new after dedup) — new-job counts naturally decay run over run, raw yield
    should not. A source is flagged when its last two runs both errored, or
    when both yielded <30% of the baseline average (a sustained >70% drop).
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    con = _conn()
    try:
        rows = con.execute(
            "SELECT source, status, jobs_seen, jobs_found, duration_ms, error, finished_at "
            "FROM run_sources WHERE user_id = ? AND finished_at >= ? ORDER BY finished_at ASC",
            (user_id, cutoff),
        ).fetchall()
    finally:
        con.close()

    by_source: dict[str, list[dict]] = {}
    for row in rows:
        by_source.setdefault(row["source"], []).append(dict(row))

    day_keys = [(_utc_today() - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]

    out = []
    for source, runs in by_source.items():
        daily = {d: {"day": d, "jobs_seen": 0, "errors": 0, "runs": 0} for d in day_keys}
        errors = 0
        for r in runs:
            day = (r["finished_at"] or "")[:10]
            if r["status"] == "error":
                errors += 1
            if day in daily:
                daily[day]["jobs_seen"] += r["jobs_seen"] or 0
                daily[day]["runs"] += 1
                if r["status"] == "error":
                    daily[day]["errors"] += 1

        total = len(runs)
        ok_runs = [r for r in runs if r["status"] != "error"]
        latest = runs[-1]
        prior = runs[:-1]
        prior_ok = [r for r in prior if r["status"] != "error"]
        baseline = (
            sum(r["jobs_seen"] or 0 for r in prior_ok) / len(prior_ok) if prior_ok else 0.0
        )

        flagged = False
        flag_reason = None
        if total < HEALTH_MIN_RUNS:
            flag_reason = "insufficient_data"
        elif len(runs) >= 2 and runs[-1]["status"] == "error" and runs[-2]["status"] == "error":
            flagged = True
            flag_reason = "consecutive_errors"
        elif (
            baseline >= HEALTH_BASELINE_MIN
            and len(runs) >= 2
            and all((r["jobs_seen"] or 0) < baseline * HEALTH_DROP_RATIO for r in runs[-2:])
        ):
            flagged = True
            flag_reason = "yield_drop"

        out.append({
            "source": source,
            "runs": total,
            "errors": errors,
            "success_rate": round(len(ok_runs) / total, 3) if total else None,
            "baseline_yield": round(baseline, 1),
            "flagged": flagged,
            "flag_reason": flag_reason,
            "latest": {
                "status": latest["status"],
                "jobs_seen": latest["jobs_seen"],
                "jobs_found": latest["jobs_found"],
                "duration_ms": latest["duration_ms"],
                "error": latest["error"],
                "finished_at": latest["finished_at"],
            },
            "daily": list(daily.values()),
        })

    out.sort(key=lambda s: (not s["flagged"], s["source"]))
    return out


def source_health_map(user_id: str, days: int = 14) -> dict[str, dict]:
    """source_health() keyed by source name — for the scheduler and coverage view."""
    return {s["source"]: s for s in source_health(user_id, days=days)}


def source_contribution(user_id: str, days: int = 14) -> dict[str, dict]:
    """Per-source totals over the window: new jobs contributed, raw yield, runs."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    con = _conn()
    try:
        rows = con.execute(
            "SELECT source, COUNT(*) AS runs, "
            "COALESCE(SUM(jobs_found),0) AS jobs_found, COALESCE(SUM(jobs_seen),0) AS jobs_seen "
            "FROM run_sources WHERE user_id = ? AND finished_at >= ? GROUP BY source",
            (user_id, cutoff),
        ).fetchall()
    finally:
        con.close()
    return {r["source"]: {"runs": r["runs"], "jobs_found": r["jobs_found"], "jobs_seen": r["jobs_seen"]}
            for r in rows}


def discovery_run_count(user_id: str) -> int:
    """Total completed discovery runs for a user — drives the scheduler's probe cadence."""
    con = _conn()
    try:
        row = con.execute(
            "SELECT COUNT(*) AS n FROM runs WHERE user_id = ? AND kind = 'discovery'",
            (user_id,),
        ).fetchone()
        return row["n"] if row else 0
    finally:
        con.close()


# ══════════════════════════════════════════════════════════════
#  LLM USAGE & BUDGET
# ══════════════════════════════════════════════════════════════

# today-totals cache: (day, expires_monotonic, totals) — budget checks run per
# LLM call, so avoid a DB hit for each one during batch scoring.
_today_cache: tuple[str, float, dict] | None = None
_TODAY_CACHE_TTL = 2.0


def record_llm_call(
    provider: str,
    model: str | None,
    feature: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
):
    global _today_cache
    try:
        now = datetime.now(timezone.utc)
        con = _conn()
        try:
            con.execute(
                "INSERT INTO llm_usage (ts, day, provider, model, feature, input_tokens, output_tokens, cost_usd) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (now.isoformat(), now.date().isoformat(), provider, model, feature,
                 input_tokens, output_tokens, cost_usd),
            )
            con.commit()
        finally:
            con.close()
        _today_cache = None
    except Exception as e:
        logger.warning(f"Telemetry: failed to record LLM call: {e}")


def llm_today_totals() -> dict:
    """Today's aggregate LLM usage — cheap enough to call before every LLM request."""
    global _today_cache
    today = datetime.now(timezone.utc).date().isoformat()
    if _today_cache and _today_cache[0] == today and _today_cache[1] > time.monotonic():
        return _today_cache[2]
    con = _conn()
    try:
        row = con.execute(
            "SELECT COUNT(*) AS calls, COALESCE(SUM(input_tokens),0) AS inp, "
            "COALESCE(SUM(output_tokens),0) AS out, COALESCE(SUM(cost_usd),0) AS cost "
            "FROM llm_usage WHERE day = ?",
            (today,),
        ).fetchone()
    finally:
        con.close()
    totals = {
        "calls": row["calls"],
        "input_tokens": row["inp"],
        "output_tokens": row["out"],
        "tokens": row["inp"] + row["out"],
        "cost_usd": round(row["cost"], 6),
    }
    _today_cache = (today, time.monotonic() + _TODAY_CACHE_TTL, totals)
    return totals


def llm_usage_summary(days: int = 14) -> dict:
    """Usage rollups for the AI-usage dashboard: today by provider/feature + daily series."""
    today = _utc_today().isoformat()
    cutoff = (_utc_today() - timedelta(days=days - 1)).isoformat()
    con = _conn()
    try:
        def _group(field: str) -> dict:
            rows = con.execute(
                f"SELECT {field} AS k, COUNT(*) AS calls, "
                "COALESCE(SUM(input_tokens),0) AS inp, COALESCE(SUM(output_tokens),0) AS out, "
                "COALESCE(SUM(cost_usd),0) AS cost "
                f"FROM llm_usage WHERE day = ? GROUP BY {field} ORDER BY cost DESC, inp+out DESC",
                (today,),
            ).fetchall()
            return {
                r["k"]: {
                    "calls": r["calls"],
                    "input_tokens": r["inp"],
                    "output_tokens": r["out"],
                    "cost_usd": round(r["cost"], 6),
                }
                for r in rows
            }

        providers = _group("provider")
        features = _group("feature")

        daily_rows = con.execute(
            "SELECT day, COUNT(*) AS calls, "
            "COALESCE(SUM(input_tokens),0) + COALESCE(SUM(output_tokens),0) AS tokens, "
            "COALESCE(SUM(cost_usd),0) AS cost "
            "FROM llm_usage WHERE day >= ? GROUP BY day",
            (cutoff,),
        ).fetchall()
    finally:
        con.close()

    by_day = {r["day"]: r for r in daily_rows}
    daily = []
    for i in range(days - 1, -1, -1):
        d = (_utc_today() - timedelta(days=i)).isoformat()
        r = by_day.get(d)
        daily.append({
            "day": d,
            "calls": r["calls"] if r else 0,
            "tokens": r["tokens"] if r else 0,
            "cost_usd": round(r["cost"], 6) if r else 0.0,
        })

    return {
        "date": today,
        "today": llm_today_totals(),
        "providers": providers,
        "features": features,
        "daily": daily,
    }
