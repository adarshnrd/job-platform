"""Session-based authentication router.

Manages browser-login flows, session status, and platform connections.
"""

import asyncio
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from loguru import logger

from auth import get_user_id
from services.sessions.service import SessionService
from services.sessions.adapters.registry import list_platforms, get_adapter, PLATFORM_META

router = APIRouter(prefix="/sessions", tags=["sessions"])

_session_service = SessionService()


# ─── Platform Discovery ─────────────────────────────────────────────────────

@router.get("/platforms")
async def get_supported_platforms(user_id: str = Depends(get_user_id)):
    """List all supported platforms with metadata and adapter availability."""
    return list_platforms()


# ─── Session Status ──────────────────────────────────────────────────────────

@router.get("")
async def list_sessions(user_id: str = Depends(get_user_id)):
    """List all platform sessions for the current user (dashboard view)."""
    return {"sessions": _session_service.list_user_sessions(user_id)}


# ─── Handshake Polling (must be before /{platform} to avoid path collision) ──

@router.get("/handshake/{token}")
async def poll_handshake(token: str, user_id: str = Depends(get_user_id)):
    """Poll the status of a browser-login handshake."""
    status = _session_service.get_handshake_status(token, user_id)
    if not status:
        raise HTTPException(status_code=404, detail="Handshake not found")

    return {
        "status": status["status"],
        "platform": status["platform"],
        "session_id": status.get("session_id"),
        "error_message": status.get("error_message"),
    }


# ─── Audit Log (must be before /{platform} to avoid path collision) ──────────

@router.get("/audit")
async def get_audit_log(user_id: str = Depends(get_user_id)):
    """Get session audit events for the current user."""
    events = _session_service.audit.get_events(user_id, limit=100)
    return {"events": events}


@router.get("/{platform}")
async def get_session_status(platform: str, user_id: str = Depends(get_user_id)):
    """Get session status for a single platform."""
    if platform not in PLATFORM_META:
        raise HTTPException(status_code=400, detail=f"Unsupported platform: {platform}")
    return _session_service.get_status(user_id, platform)


# ─── Browser Login Flow ─────────────────────────────────────────────────────

@router.post("/{platform}/connect")
async def start_connect(
    platform: str,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_user_id),
):
    """Start a browser-login flow. Returns a handshake token for polling.

    The backend launches a visible Playwright browser. The user logs in
    manually. After login, cookies are captured and encrypted.
    """
    if platform not in PLATFORM_META:
        raise HTTPException(status_code=400, detail=f"Unsupported platform: {platform}")

    handshake = _session_service.create_handshake(user_id, platform)
    background_tasks.add_task(
        _run_browser_auth,
        handshake["handshake_token"],
        user_id,
        platform,
    )
    return handshake


# ─── Session Management ─────────────────────────────────────────────────────

@router.post("/{platform}/reconnect")
async def reconnect(
    platform: str,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_user_id),
):
    """Invalidate existing session and start a fresh login flow."""
    if platform not in PLATFORM_META:
        raise HTTPException(status_code=400, detail=f"Unsupported platform: {platform}")

    try:
        _session_service.revoke(user_id, platform)
    except Exception:
        pass

    handshake = _session_service.create_handshake(user_id, platform)
    background_tasks.add_task(
        _run_browser_auth,
        handshake["handshake_token"],
        user_id,
        platform,
    )
    return handshake


@router.post("/{platform}/refresh")
async def refresh_session(platform: str, user_id: str = Depends(get_user_id)):
    """Force a validation check on the current session."""
    if platform not in PLATFORM_META:
        raise HTTPException(status_code=400, detail=f"Unsupported platform: {platform}")

    status = _session_service.get_status(user_id, platform)
    if status["status"] == "not_connected":
        raise HTTPException(status_code=404, detail="No session to refresh")

    session = _session_service._load_session_record(user_id, platform)
    is_valid = await _session_service.health.validate_session(session["id"])

    return {
        "valid": is_valid,
        "status": _session_service.get_status(user_id, platform),
    }


@router.delete("/{platform}")
async def disconnect(platform: str, user_id: str = Depends(get_user_id)):
    """Disconnect a platform (delete session)."""
    if platform not in PLATFORM_META:
        raise HTTPException(status_code=400, detail=f"Unsupported platform: {platform}")
    return _session_service.revoke(user_id, platform)


# ─── Background Browser Auth Task ────────────────────────────────────────────

async def _run_browser_auth(handshake_token: str, user_id: str, platform: str):
    """Launch a visible Playwright browser for user to manually login.
    Captures cookies after login detection. Runs as a background task.
    """
    from playwright.async_api import async_playwright

    meta = PLATFORM_META.get(platform, {})
    login_url = meta.get("login_url", "")
    adapter = get_adapter(platform)

    if not login_url:
        _session_service.update_handshake(
            handshake_token, "failed",
            error_message=f"No login URL configured for {platform}",
        )
        return

    _session_service.update_handshake(handshake_token, "browser_opened")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto(login_url, wait_until="domcontentloaded")

            logger.info(f"[{platform}] Browser opened at {login_url}. Waiting for login...")

            # Poll for login completion (up to 10 minutes)
            login_detected = False
            deadline = datetime.now(timezone.utc) + timedelta(minutes=10)

            while datetime.now(timezone.utc) < deadline:
                try:
                    if adapter and await adapter.is_login_complete(page):
                        login_detected = True
                        break
                    elif not adapter and login_url not in page.url:
                        login_detected = True
                        break
                except Exception:
                    pass
                await asyncio.sleep(2)

            if not login_detected:
                _session_service.update_handshake(handshake_token, "timeout")
                _session_service.audit.log(
                    "reauth_required", user_id, platform,
                    metadata={"reason": "Login timeout (10 minutes)"},
                )
                await browser.close()
                return

            logger.info(f"[{platform}] Login detected! Capturing session...")

            await asyncio.sleep(2)

            cookies = await context.cookies()
            user_agent = await page.evaluate("navigator.userAgent")
            viewport = page.viewport_size

            platform_username = None
            platform_user_id_val = None

            if adapter:
                try:
                    captured = await adapter.capture_session(page)
                    cookies = captured.cookies
                    user_agent = captured.user_agent
                    viewport = captured.viewport
                    platform_username = captured.platform_username
                    platform_user_id_val = captured.platform_user_id
                except Exception as e:
                    logger.warning(f"[{platform}] Adapter capture_session failed, using raw cookies: {e}")

            metadata = {
                "user_agent": user_agent,
                "viewport": viewport or {"width": 1920, "height": 1080},
            }

            session = _session_service.store_session(
                user_id=user_id,
                platform=platform,
                cookies=cookies,
                metadata=metadata,
                platform_username=platform_username,
                platform_user_id=platform_user_id_val,
            )

            _session_service.update_handshake(
                handshake_token, "completed",
                session_id=session.get("id"),
            )

            _session_service.audit.log(
                "reauth_completed", user_id, platform,
                session_id=session.get("id"),
            )

            logger.info(f"[{platform}] Session captured successfully!")
            await browser.close()

    except Exception as e:
        logger.error(f"[{platform}] Browser auth failed: {e}")
        _session_service.update_handshake(
            handshake_token, "failed",
            error_message=str(e)[:500],
        )
