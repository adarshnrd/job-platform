"""Guards for adapter registration and portal-tier gating of auto-apply."""
from services.sessions.adapters.registry import ADAPTERS, get_adapter
from services.portals import get_portal, resolve_portal_key
from workers.job_discovery import _portal_auto_appliable


def test_every_adapter_maps_to_an_auto_apply_portal():
    """No orphan adapters: anything registered must be a known Tier-A portal.
    (The reverse — every Tier-A portal having an adapter — is reached across the
    phased rollout; some auto_apply portals get their adapters in later phases.)"""
    for key in ADAPTERS:
        cap = get_portal(key)
        assert cap is not None, f"Adapter {key} has no portal registry entry"
        assert cap.auto_apply, f"Adapter {key} maps to a non-auto-apply portal"


def test_new_phase2_adapters_registered():
    for name in ("instahyre", "foundit", "hirist", "cutshort"):
        assert name in ADAPTERS
        assert hasattr(get_adapter(name), "apply_to_job")


def test_portal_auto_appliable_gating():
    # Tier A → auto-appliable.
    assert _portal_auto_appliable("naukri")
    assert _portal_auto_appliable("instahyre")
    # Tier B → assisted only, never auto-queued.
    assert not _portal_auto_appliable("wellfound")
    assert not _portal_auto_appliable("indeed")
    # Unknown → default True (preserves prior behavior).
    assert _portal_auto_appliable("some_new_board")


def test_angellist_aliases_to_wellfound():
    assert resolve_portal_key("angel.co") == "wellfound"
    assert resolve_portal_key("angellist") == "wellfound"
    assert get_portal("angel.co").key == "wellfound"


def test_cutshort_has_assessment_guard():
    from services.sessions.adapters.cutshort import CutshortAdapter
    assert hasattr(CutshortAdapter, "_pre_apply_block")


def test_ycombinator_adapter_registered():
    assert "ycombinator" in ADAPTERS
    assert get_adapter("ycombinator").platform_name == "ycombinator"


def test_normalize_job_url_angellist_to_wellfound():
    from services.portals import normalize_job_url
    assert normalize_job_url("https://angel.co/company/foo/jobs/123") == "https://wellfound.com/company/foo/jobs/123"
    assert normalize_job_url("https://www.angel.co/l/xyz") == "https://www.wellfound.com/l/xyz"

def test_normalize_job_url_strips_tracking():
    from services.portals import normalize_job_url
    assert normalize_job_url("https://boards.example.com/job/9?utm_source=x&ref=y") == "https://boards.example.com/job/9"
    assert normalize_job_url("https://x.com/job/9/") == "https://x.com/job/9"
