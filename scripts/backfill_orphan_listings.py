#!/usr/bin/env python3
"""
Recover job listings that were stored but never scored.

Before the durable pipeline (database/16_pipeline_durability.sql), a discovery
run stored listings in Phase 3 and only wrote the user's match records in
Phase 5. A failure in between — the 7h47m run that died with
`[Errno 8] nodename nor servname provided` — left listings in the database with
no `job_applications` row pointing at them. They exist, but no UI shows them,
because every job view reads the `application_details` view.

This enqueues those orphans into `job_pipeline_items` so the normal pipeline
scores them. No scraping, no re-parsing of anything already done.

Usage (from the repo root):

    python scripts/backfill_orphan_listings.py --user <uuid>           # dry run
    python scripts/backfill_orphan_listings.py --user <uuid> --apply
    python scripts/backfill_orphan_listings.py --user <uuid> --apply --since 2026-07-25
    python scripts/backfill_orphan_listings.py --all-users --apply

Dry run by default: it prints what it would enqueue and changes nothing.
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent / "apps" / "api"
sys.path.insert(0, str(API_DIR))

from database import get_supabase_admin, select_in_batches  # noqa: E402
from services import job_pipeline as pipeline  # noqa: E402

PAGE = 1000


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def orphan_listings(db, user_id: str, since: str, limit: int) -> list[dict]:
    """Listings discovered since `since` that this user has no application for."""
    listings: list[dict] = []
    start = 0
    while len(listings) < limit:
        res = (
            db.table("job_listings")
            .select("id, title, company, source_platform, discovered_at")
            .gte("discovered_at", since)
            .order("discovered_at", desc=True)
            .range(start, start + PAGE - 1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            break
        listings.extend(rows)
        if len(rows) < PAGE:
            break
        start += PAGE
    listings = listings[:limit]
    if not listings:
        return []

    listing_ids = [row["id"] for row in listings]

    apps = select_in_batches(
        db, "job_applications", "job_listing_id", "job_listing_id", listing_ids
    )
    claimed = {a["job_listing_id"] for a in apps if a.get("job_listing_id")}

    # Already-queued listings are being handled by the pipeline; skip them.
    staged = set(pipeline.staged_listing_ids(user_id))

    return [row for row in listings if row["id"] not in claimed and row["id"] not in staged]


def enqueue(db, user_id: str, listings: list[dict]) -> int:
    items = [{
        "user_id": user_id,
        "run_id": "backfill",
        "job_listing_id": row["id"],
        "source_platform": row.get("source_platform") or "",
        "stage": pipeline.STAGE_SCRAPED,
        "stage_status": "pending",
    } for row in listings]
    if not items:
        return 0
    written = 0
    for i in range(0, len(items), 200):
        chunk = items[i:i + 200]
        db.table("job_pipeline_items").upsert(
            chunk, on_conflict="user_id,job_listing_id", ignore_duplicates=True
        ).execute()
        written += len(chunk)
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--user", help="user id to backfill")
    ap.add_argument("--all-users", action="store_true", help="every user in the database")
    ap.add_argument("--days", type=int, default=30, help="look back this many days (default 30)")
    ap.add_argument("--since", help="ISO date instead of --days, e.g. 2026-07-25")
    ap.add_argument("--limit", type=int, default=2000, help="max listings to scan (default 2000)")
    ap.add_argument("--apply", action="store_true", help="actually enqueue (default: dry run)")
    args = ap.parse_args()

    if not args.user and not args.all_users:
        ap.error("pass --user <uuid> or --all-users")

    db = get_supabase_admin()

    if not pipeline.pipeline_available():
        print("job_pipeline_items is not available — run database/16_pipeline_durability.sql first.")
        return 1

    since = args.since or _iso(args.days)

    if args.all_users:
        user_ids = [u["id"] for u in (db.table("users").select("id").execute().data or [])]
    else:
        user_ids = [args.user]

    total = 0
    for user_id in user_ids:
        orphans = orphan_listings(db, user_id, since, args.limit)
        if not orphans:
            print(f"{user_id}: no orphaned listings since {since[:10]}")
            continue

        print(f"\n{user_id}: {len(orphans)} orphaned listing(s) since {since[:10]}")
        for row in orphans[:10]:
            print(f"  · {row['title'][:60]:60} {row.get('company', '')[:30]}")
        if len(orphans) > 10:
            print(f"  … and {len(orphans) - 10} more")

        if args.apply:
            n = enqueue(db, user_id, orphans)
            print(f"  → enqueued {n} for processing")
            total += n
        else:
            total += len(orphans)

    if args.apply:
        print(f"\nEnqueued {total} listing(s). The pipeline drain picks them up within "
              f"{pipeline.settings.PIPELINE_DRAIN_INTERVAL_MINUTES} minutes.")
    else:
        print(f"\nDry run — {total} listing(s) would be enqueued. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
