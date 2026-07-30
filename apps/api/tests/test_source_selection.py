"""Tests for discovery source selection, region inference, and search fan-out."""
from workers.job_discovery import (
    SOURCE_REGISTRY,
    build_search_pairs,
    infer_region,
    resolve_region,
    select_sources,
)


# ══════════════════════════════════════════════════════════════
#  SOURCE SELECTION (opt-out gating)
# ══════════════════════════════════════════════════════════════

def test_empty_preferences_selects_all_discoverable_regional_sources():
    names = {s.name for s in select_sources("india", [])}

    # Every discoverable india-region scraper runs without opt-in.
    for expected in ("naukri", "linkedin", "hirist", "iimjobs", "timesjobs", "shine"):
        assert expected in names, f"{expected} should run by default"
    # Keyless API sources too.
    assert {"remoteok", "remotive", "themuse"} <= names
    # Global-only sources are excluded from india runs.
    assert "ycombinator" not in names
    assert "dice" not in names
    # Keyed API sources stay dormant without keys (no keys in test env → absent
    # or present only if a key is configured).
    for keyed in ("adzuna", "jooble", "jsearch"):
        src = SOURCE_REGISTRY[keyed]
        has = getattr(src.cls, "has_key", None)
        if has and not has():
            assert keyed not in names


def test_ctier_sources_are_never_discovered():
    """Hard bot-walls stay registered (for display/apply) but skip discovery."""
    india = {s.name for s in select_sources("india", [])}
    glob = {s.name for s in select_sources("global", [])}
    for walled in (
        "indeed", "instahyre", "freshersworld", "cutshort", "wellfound",
        "peerlist", "flexjobs",
    ):
        assert walled in SOURCE_REGISTRY, f"{walled} should remain registered"
        assert SOURCE_REGISTRY[walled].discoverable is False
        assert walled not in india and walled not in glob

    # Even an explicit opt-in cannot force a C-tier source into a run.
    assert "wellfound" not in {s.name for s in select_sources("india", ["wellfound"])}


def test_foundit_is_discovered_as_an_api_source():
    """Foundit moved from a bot-walled browser scraper to the site's JSON API."""
    src = SOURCE_REGISTRY["foundit"]
    assert src.api_based is True
    assert src.discoverable is True
    assert {"india", "global"} <= src.regions
    # API sources run without opt-in, in both regions.
    assert "foundit" in {s.name for s in select_sources("india", [])}
    assert "foundit" in {s.name for s in select_sources("global", [])}


def test_new_global_sources_are_registered():
    for name in ("arc", "welcometothejungle"):
        assert name in SOURCE_REGISTRY
        assert SOURCE_REGISTRY[name].discoverable is True
        assert "global" in SOURCE_REGISTRY[name].regions

    glob = {s.name for s in select_sources("global", [])}
    assert {"arc", "welcometothejungle"} <= glob
    # Browser sources are opt-out, so an explicit narrow list excludes them.
    assert "arc" not in {s.name for s in select_sources("global", ["ycombinator"])}


def test_explicit_preferences_narrow_browser_sources():
    # naukri is a browser scraper; hirist is now API-based (always on).
    names = {s.name for s in select_sources("india", ["naukri"])}

    assert "naukri" in names
    assert "linkedin" not in names  # a browser scraper the user didn't pick
    # API sources (incl. the rewritten hirist/iimjobs/timesjobs) are always on.
    assert {"remoteok", "remotive", "themuse", "hirist", "iimjobs", "timesjobs"} <= names


def test_none_preferences_behave_like_empty():
    all_names = {s.name for s in select_sources("india", [])}
    none_names = {s.name for s in select_sources("india", None)}
    assert all_names == none_names


def test_global_region_selection():
    names = {s.name for s in select_sources("global", [])}
    assert {"ycombinator", "dice", "ziprecruiter", "weworkremotely", "arbeitnow"} <= names
    assert "naukri" not in names and "shine" not in names


# ══════════════════════════════════════════════════════════════
#  REGION INFERENCE
# ══════════════════════════════════════════════════════════════

def test_city_names_imply_india():
    assert infer_region(["Bangalore", "Pune"]) == "india"
    assert infer_region(["Gurgaon"]) == "india"
    assert infer_region(["Noida"]) == "india"
    assert infer_region(["Bengaluru, Karnataka"]) == "india"
    assert infer_region(["Remote - India"]) == "india"


def test_mixed_locations_prefer_india():
    assert infer_region(["London", "Bangalore"]) == "india"


def test_foreign_locations_are_global():
    assert infer_region(["London", "New York"]) == "global"


def test_empty_defaults_to_india():
    assert infer_region([]) == "india"
    assert infer_region(None) == "india"
    assert infer_region(["", None]) == "india"


# ══════════════════════════════════════════════════════════════
#  EXPLICIT REGION PREFERENCE
# ══════════════════════════════════════════════════════════════

def test_explicit_region_overrides_inference():
    """The whole point: an India-based user targeting roles abroad."""
    user = {"preferred_locations": ["Bangalore"], "discovery_region": "global"}
    assert resolve_region(user) == "global"
    assert infer_region(user["preferred_locations"]) == "india"  # inference alone would pin them


def test_explicit_india_is_honoured():
    assert resolve_region(
        {"preferred_locations": ["London"], "discovery_region": "india"}
    ) == "india"


def test_missing_or_invalid_preference_falls_back_to_inference():
    # India locations, so a fallback to inference is distinguishable from the
    # "global" a valid preference would have produced.
    for value in (None, "", "  ", "mars", "worldwide"):
        user = {"preferred_locations": ["Pune"], "discovery_region": value}
        assert resolve_region(user) == "india", f"{value!r} should fall back to inference"

    # Pre-migration row: the column simply isn't there.
    assert resolve_region({"preferred_locations": ["Pune"]}) == "india"
    assert resolve_region({"preferred_locations": ["London"]}) == "global"
    assert resolve_region({}) == "india"
    assert resolve_region(None) == "india"


def test_preference_is_case_and_whitespace_tolerant():
    assert resolve_region(
        {"preferred_locations": ["Pune"], "discovery_region": " Global "}
    ) == "global"


# ══════════════════════════════════════════════════════════════
#  SEARCH FAN-OUT
# ══════════════════════════════════════════════════════════════

def test_pairs_under_cap_are_complete():
    pairs = build_search_pairs(["node", "backend"], ["Bangalore", "Pune"], cap=6)
    assert len(pairs) == 4
    assert ("node", "Bangalore") in pairs
    assert ("backend", "Pune") in pairs


def test_pairs_are_capped_with_locations_outermost():
    queries = ["q1", "q2", "q3"]
    cities = ["Bangalore", "Pune", "Gurgaon", "Noida"]
    pairs = build_search_pairs(queries, cities, cap=6, offset=0)

    assert len(pairs) == 6
    # Outer loop is locations → first slice covers 2 full cities, not 1 city 6×.
    assert {loc for _, loc in pairs} == {"Bangalore", "Pune"}


def test_offset_rotates_through_the_matrix():
    queries = ["q1", "q2"]
    cities = ["A", "B", "C", "D"]
    all_pairs = [(q, c) for c in cities for q in queries]

    seen: set = set()
    for offset in range(len(all_pairs)):
        seen.update(build_search_pairs(queries, cities, cap=4, offset=offset))
    assert seen == set(all_pairs)  # every pair reachable across successive runs

    # Offsets wrap safely past the matrix size.
    assert len(build_search_pairs(queries, cities, cap=4, offset=23)) == 4


def test_pairs_empty_inputs():
    assert build_search_pairs([], ["Bangalore"], cap=6) == []
    assert build_search_pairs(["q"], [], cap=6) == []
