"""Automation control router — queue status, settings, blacklist."""
from auth import get_user_id
from fastapi import APIRouter, Depends, HTTPException

from pydantic import BaseModel
from database import get_db
from config import settings

router = APIRouter(prefix="/automation", tags=["automation"])

db = get_db()


@router.get("/queue")
async def get_queue_status(user_id: str = Depends(get_user_id)):
    result = db.table("apply_queue").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(20).execute()
    return result.data or []


@router.delete("/queue/{item_id}")
async def cancel_queue_item(item_id: str, user_id: str = Depends(get_user_id)):
    db.table("apply_queue").update({"status": "cancelled"}).eq("id", item_id).eq("user_id", user_id).execute()
    return {"success": True}


class AutomationSettings(BaseModel):
    auto_apply_enabled: bool
    auto_apply_threshold: int
    preferred_platforms: list[str]


@router.patch("/settings")
async def update_automation_settings(body: AutomationSettings, user_id: str = Depends(get_user_id)):
    db.table("users").update({
        "auto_apply_enabled": body.auto_apply_enabled,
        "auto_apply_threshold": max(60, min(100, body.auto_apply_threshold)),
        "preferred_platforms": body.preferred_platforms,
    }).eq("id", user_id).execute()
    return {"success": True}


# ─── Company Blacklist ────────────────────────────────────────────────────────

@router.get("/blacklist")
async def get_blacklist(user_id: str = Depends(get_user_id)):
    """Return the user's blacklisted companies."""
    result = db.table("company_blacklist").select("*").eq("user_id", user_id).order("company_name").execute()
    return result.data or []


class BlacklistEntry(BaseModel):
    company_name: str


@router.post("/blacklist")
async def add_to_blacklist(body: BlacklistEntry, user_id: str = Depends(get_user_id)):
    """Add a company to the blacklist so it is never auto-applied to."""
    name = body.company_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Company name is required")
    db.table("company_blacklist").upsert(
        {"user_id": user_id, "company_name": name},
        on_conflict="user_id,company_name"
    ).execute()
    return {"success": True, "company_name": name}


@router.delete("/blacklist/{company_name}")
async def remove_from_blacklist(company_name: str, user_id: str = Depends(get_user_id)):
    """Remove a company from the blacklist."""
    db.table("company_blacklist").delete().eq("user_id", user_id).eq("company_name", company_name).execute()
    return {"success": True}
