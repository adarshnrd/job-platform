from supabase import create_client, Client
from config import settings
from functools import lru_cache


@lru_cache()
def get_supabase() -> Client:
    """Anon client — for user-scoped operations with their JWT."""
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)


@lru_cache()
def get_supabase_admin() -> Client:
    """Service-role client — for privileged operations (workers, scrapers)."""
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


def get_authed_client(user_jwt: str) -> Client:
    """Return a client scoped to the given user JWT for RLS enforcement."""
    client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
    client.auth.set_session(user_jwt, "")
    return client


class _LazyAdmin:
    """Proxy that defers get_supabase_admin() until first attribute access.
    Allows modules to write `db = get_db()` at the top level without
    crashing at import time if env vars are missing."""

    def __getattr__(self, name):
        return getattr(get_supabase_admin(), name)


def get_db() -> Client:
    """Return a lazy-initialized admin client safe for module-level assignment."""
    return _LazyAdmin()  # type: ignore[return-value]


def select_in_batches(
    db: Client,
    table: str,
    select: str,
    column: str,
    values: list,
    batch_size: int = 200,
) -> list[dict]:
    """Run `SELECT … WHERE column IN (values)` in chunks and concatenate results.

    PostgREST encodes `.in_()` filters into the URL, so a large value list can
    blow past server URL-length limits. Batching keeps each request bounded —
    use this instead of a raw `.in_()` whenever `values` can grow unbounded
    (e.g. per-user application/listing id sets).
    """
    if not values:
        return []
    rows: list[dict] = []
    for i in range(0, len(values), batch_size):
        chunk = values[i:i + batch_size]
        res = db.table(table).select(select).in_(column, chunk).execute()
        rows.extend(res.data or [])
    return rows
