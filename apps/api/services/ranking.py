"""Job ranking service — recency bucketing, relevance filtering, skill rescue.

Shared by jobs and applications routers. All logic runs in Python over
pre-fetched rows because PostgREST can't do bucket-sorts or OR-rescue queries.
"""
from datetime import datetime, timezone
from config import settings


BUCKET_LABELS = {0: "Today", 1: "2 days", 2: "This week", 3: "Older"}


def _row_age_hours(row: dict) -> float | None:
    """Hours since the row's best-known timestamp (posted > discovered > created)."""
    ts = row.get("job_posted_at") or row.get("job_discovered_at") or row.get("created_at")
    if not ts:
        return None
    try:
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 3600
    except Exception:
        return None


def recency_bucket(row: dict) -> int:
    """Assign a recency bucket: 0=24h, 1=2d, 2=1w, 3=older."""
    age_hours = _row_age_hours(row)
    if age_hours is None:
        return 3
    if age_hours <= 24:
        return 0
    if age_hours <= 48:
        return 1
    if age_hours <= 168:
        return 2
    return 3


def posted_within(rows: list[dict], days: int) -> list[dict]:
    """Keep rows whose best-known timestamp falls within the last `days`."""
    limit_hours = days * 24
    return [r for r in rows if (age := _row_age_hours(r)) is not None and age <= limit_hours]


def filter_and_rank(
    rows: list[dict],
    user_skills: set[str],
    min_score: int | None = None,
    show_archived: bool = False,
    rescue: bool = True,
) -> list[dict]:
    """Filter by relevance, sort by recency then score.

    When `rescue` is True (the Jobs/dashboard browse experience), a job below
    min_score is still surfaced if its required skills overlap the user's
    profile — worth seeing even though it scored low. When `rescue` is False
    (an explicit user-chosen score filter, e.g. the Applications page), the
    cutoff is a hard boundary: nothing below min_score is included, full stop.

    Returns rows annotated with recency_bucket, recency_label, skill_rescued, rescue_skills.
    """
    if min_score is None:
        min_score = settings.DASHBOARD_MIN_SCORE

    core_skills_lower = {s.lower() for s in user_skills}
    visible = []

    for r in rows:
        # Hide listings marked dead by the revalidation worker. `job_is_active`
        # is absent pre-migration (defaults to visible), so only False hides.
        if r.get("job_is_active") is False and not show_archived:
            continue

        score = r.get("match_score") or 0
        tier = r.get("match_tier", "")

        rescued = False
        rescue_skills_list = []

        below_cutoff = score < min_score and not show_archived
        archived_below_cutoff = not show_archived and tier == "archived" and score < min_score

        if below_cutoff or archived_below_cutoff:
            if not rescue:
                continue
            job_skills = {s.lower() for s in (r.get("job_required_skills") or [])}
            overlap = job_skills & core_skills_lower
            if overlap:
                rescued = True
                rescue_skills_list = sorted(
                    s for s in (r.get("job_required_skills") or [])
                    if s.lower() in core_skills_lower
                )
            else:
                continue

        bucket = recency_bucket(r)
        r["recency_bucket"] = bucket
        r["recency_label"] = BUCKET_LABELS.get(bucket, "Older")
        r["skill_rescued"] = rescued
        r["rescue_skills"] = rescue_skills_list
        visible.append(r)

    visible.sort(key=lambda r: (
        r["recency_bucket"],
        r.get("skill_rescued", False),
        -(r.get("match_score") or 0),
    ))

    return visible


def paginate(rows: list[dict], offset: int, limit: int) -> dict:
    """Slice a ranked list and return paginated response."""
    page = rows[offset:offset + limit]
    return {
        "matched": page,
        "total": len(rows),
        "offset": offset,
        "limit": limit,
    }
