"""
Minimal in-memory stand-in for the Supabase/PostgREST client.

Supports the query chains the discovery pipeline actually uses, plus a fault
injection hook (`fail_on`) so tests can prove that a transient database error
degrades one item instead of destroying a run.

Not a general PostgREST emulator — it implements exactly what these tests need.
"""
from __future__ import annotations

import uuid
from typing import Any, Callable


class Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db: "FakeDB", table: str):
        self.db = db
        self.table_name = table
        self._filters: list[Callable[[dict], bool]] = []
        self._op: str | None = None
        self._payload: Any = None
        self._limit: int | None = None
        self._single = False
        self._on_conflict: str = ""
        self._ignore_duplicates = False

    # ── filters ──
    def eq(self, col, val):
        self._filters.append(lambda r, c=col, v=val: r.get(c) == v)
        return self

    def in_(self, col, vals):
        vset = set(vals)
        self._filters.append(lambda r, c=col, v=vset: r.get(c) in v)
        return self

    def lte(self, col, val):
        self._filters.append(lambda r, c=col, v=val: (r.get(c) or "") <= v)
        return self

    def lt(self, col, val):
        self._filters.append(lambda r, c=col, v=val: (r.get(c) or "") < v)
        return self

    def gte(self, col, val):
        self._filters.append(lambda r, c=col, v=val: (r.get(c) or "") >= v)
        return self

    def ilike(self, col, pattern):
        needle = pattern.replace("\\%", "%").replace("\\_", "_").lower()
        self._filters.append(lambda r, c=col, n=needle: (r.get(c) or "").lower() == n)
        return self

    def or_(self, _expr):
        return self

    def order(self, *_a, **_kw):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def single(self):
        self._single = True
        return self

    def maybe_single(self):
        self._single = True
        return self

    # ── operations ──
    def select(self, *_cols, **_kw):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def upsert(self, payload, on_conflict="", ignore_duplicates=False, **_kw):
        self._op = "upsert"
        self._payload = payload
        self._on_conflict = on_conflict
        self._ignore_duplicates = ignore_duplicates
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    # ── execution ──
    def _rows(self) -> list[dict]:
        return self.db.tables.setdefault(self.table_name, [])

    def _matching(self) -> list[dict]:
        rows = [r for r in self._rows() if all(f(r) for f in self._filters)]
        return rows[: self._limit] if self._limit else rows

    def execute(self) -> Result:
        self.db.check_fault(self.table_name, self._op or "select")
        self.db.calls.append((self.table_name, self._op))

        if self._op in (None, "select"):
            rows = [dict(r) for r in self._matching()]
            if self._single:
                if not rows:
                    raise RuntimeError(f"no rows for single() on {self.table_name}")
                return Result(rows[0])
            return Result(rows)

        if self._op == "insert":
            payloads = self._payload if isinstance(self._payload, list) else [self._payload]
            created = []
            for p in payloads:
                row = {"id": str(uuid.uuid4()), **p}
                self._rows().append(row)
                created.append(dict(row))
            return Result(created)

        if self._op == "upsert":
            payloads = self._payload if isinstance(self._payload, list) else [self._payload]
            keys = [k.strip() for k in self._on_conflict.split(",") if k.strip()]
            out = []
            for p in payloads:
                existing = None
                if keys:
                    for row in self._rows():
                        if all(row.get(k) == p.get(k) for k in keys):
                            existing = row
                            break
                if existing is not None:
                    if not self._ignore_duplicates:
                        existing.update(p)
                    out.append(dict(existing))
                else:
                    row = {"id": str(uuid.uuid4()), **p}
                    self._rows().append(row)
                    out.append(dict(row))
            return Result(out)

        if self._op == "update":
            updated = []
            for row in self._matching():
                row.update(self._payload)
                updated.append(dict(row))
            return Result(updated)

        if self._op == "delete":
            targets = self._matching()
            rows = self._rows()
            for t in targets:
                rows.remove(t)
            return Result([dict(t) for t in targets])

        raise AssertionError(f"unsupported op {self._op}")


class FakeDB:
    """In-memory tables plus a fault-injection hook.

    fail_on: {(table, op): countdown} — raises once per unit of countdown, so
    `{("job_applications", "upsert"): 1}` fails exactly the next upsert.
    """

    def __init__(self, tables: dict[str, list[dict]] | None = None):
        self.tables: dict[str, list[dict]] = tables or {}
        self.fail_on: dict[tuple[str, str], int] = {}
        self.calls: list[tuple[str, str | None]] = []
        self.rpc_handlers: dict[str, Callable[[dict], list]] = {}
        self.missing_tables: set[str] = set()

    def check_fault(self, table: str, op: str):
        if table in self.missing_tables:
            raise RuntimeError(f'relation "public.{table}" does not exist')
        key = (table, op)
        remaining = self.fail_on.get(key, 0)
        if remaining:
            self.fail_on[key] = remaining - 1
            raise RuntimeError("[Errno 8] nodename nor servname provided, or not known")

    def table(self, name: str) -> _Query:
        return _Query(self, name)

    def rpc(self, name: str, params: dict | None = None):
        handler = self.rpc_handlers.get(name)
        if handler is None:
            raise RuntimeError(f"function public.{name} does not exist")

        class _Rpc:
            def execute(_self):
                return Result(handler(params or {}))

        return _Rpc()

    def rows(self, table: str) -> list[dict]:
        return self.tables.setdefault(table, [])
