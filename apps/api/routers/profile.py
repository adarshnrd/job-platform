"""Application Profile router — reusable info needed when applying to jobs.
Reads/writes a focused set of fields on the users table."""
from auth import get_user_id
from fastapi import APIRouter, Depends, Body, HTTPException
from loguru import logger
from database import get_db

router = APIRouter(prefix="/profile", tags=["profile"])

db = get_db()

MIGRATION_HINT = (
    "Database is missing required columns. Run database/03_application_tracking.sql "
    "in the Supabase SQL Editor, then try again."
)


def _is_missing_column_error(e: Exception) -> bool:
    msg = str(e).lower()
    return "could not find" in msg or ("column" in msg and "does not exist" in msg)

# The reusable Application-Profile fields (all live on the users table).
PROFILE_FIELDS = [
    "full_name", "email", "phone", "location",
    "work_authorization", "willing_to_relocate",
    "notice_period_days", "expected_salary_min", "expected_salary_max",
    "experience_years", "linkedin_url", "github_url", "portfolio_url",
]


@router.get("/application")
async def get_application_profile(user_id: str = Depends(get_user_id)):
    """Return the reusable application profile + which required fields are missing."""
    try:
        res = db.table("users").select(",".join(PROFILE_FIELDS)).eq("id", user_id).maybe_single().execute()
    except Exception as e:
        if _is_missing_column_error(e):
            logger.error(f"Profile read failed — schema migration not applied. ({e})")
            raise HTTPException(status_code=503, detail=MIGRATION_HINT)
        raise
    data = (res.data if res else None) or {}

    required = ["full_name", "email", "phone", "location", "work_authorization",
               "notice_period_days", "expected_salary_min"]
    missing = [f for f in required if data.get(f) in (None, "", 0, [])]
    return {"profile": data, "missing": missing, "is_complete": len(missing) == 0}


@router.get("/skill-experience")
async def get_skill_experience(user_id: str = Depends(get_user_id)):
    """Return per-skill years of experience (stored in users.tech_stack)."""
    res = db.table("users").select("skills,tech_stack").eq("id", user_id).maybe_single().execute()
    data = (res.data if res else None) or {}
    return {"skills": data.get("skills") or [], "skill_experience": data.get("tech_stack") or {}}


@router.put("/skill-experience")
async def update_skill_experience(body: dict = Body(default={}), user_id: str = Depends(get_user_id)):
    """Replace/merge per-skill years of experience into users.tech_stack.
    Body: {"TypeScript": 3, "Node.js": 4}. Only real, user-provided values."""
    res = db.table("users").select("tech_stack").eq("id", user_id).maybe_single().execute()
    current = dict(((res.data if res else None) or {}).get("tech_stack") or {})
    for skill, years in body.items():
        if years in (None, ""):
            current.pop(skill, None)
        else:
            try:
                current[skill] = int(years)
            except (ValueError, TypeError):
                current[skill] = years
    db.table("users").update({"tech_stack": current}).eq("id", user_id).execute()
    return {"success": True, "skill_experience": current}


@router.put("/application")
async def update_application_profile(body: dict = Body(default={}), user_id: str = Depends(get_user_id)):
    """Update the reusable application profile. Accepts the standard profile fields
    plus skill_exp::<skill> keys (routed into tech_stack). Only provided values."""
    # Route per-skill experience keys into tech_stack.
    skill_updates = {k.split("::", 1)[1]: v for k, v in body.items()
                     if k.startswith("skill_exp::") and v not in (None, "")}
    if skill_updates:
        res = db.table("users").select("tech_stack").eq("id", user_id).maybe_single().execute()
        current = dict(((res.data if res else None) or {}).get("tech_stack") or {})
        for skill, years in skill_updates.items():
            try:
                current[skill] = int(years)
            except (ValueError, TypeError):
                current[skill] = years
        db.table("users").update({"tech_stack": current}).eq("id", user_id).execute()

    allowed = {"full_name", "phone", "location", "work_authorization", "willing_to_relocate",
               "notice_period_days", "expected_salary_min", "expected_salary_max",
               "experience_years", "linkedin_url", "github_url", "portfolio_url"}
    updates = {k: v for k, v in body.items() if k in allowed and v is not None}
    if not updates:
        return {"success": True, "updated": list(skill_updates.keys())}
    try:
        db.table("users").update(updates).eq("id", user_id).execute()
    except Exception as e:
        if _is_missing_column_error(e):
            logger.error(f"Profile update failed — schema migration not applied. ({e})")
            raise HTTPException(status_code=503, detail=MIGRATION_HINT)
        raise
    return {"success": True, "updated": list(updates.keys())}
