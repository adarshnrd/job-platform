"""Portals router — exposes the portal capability matrix to the frontend."""
from auth import get_user_id
from fastapi import APIRouter, Depends

from services.portals import list_portals, get_portal

router = APIRouter(prefix="/portals", tags=["portals"])


@router.get("")
async def get_portals(_: str = Depends(get_user_id)):
    """Return every portal with its tier and capability flags.

    Drives per-job tier badges (Auto / Assisted / View only) and the
    per-portal connect buttons on the settings page.
    """
    return {"portals": list_portals()}


@router.get("/{name}")
async def get_portal_detail(name: str, _: str = Depends(get_user_id)):
    """Return one portal's capabilities (accepts aliases like angel.co)."""
    cap = get_portal(name)
    if not cap:
        return {"found": False, "portal": None}
    from dataclasses import asdict
    d = asdict(cap)
    d["apply_label"] = cap.apply_label
    return {"found": True, "portal": d}
