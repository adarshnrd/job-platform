"""Registry, portal and enum wiring for the Phase 2 MENA sources."""
from pathlib import Path

import pytest

from models.job import Platform
from services.portals import PORTALS
from workers.job_discovery import SOURCE_REGISTRY, select_sources

NEW = ("sabbar", "emploitic", "keejob", "rekrute")


@pytest.mark.parametrize("name", NEW)
def test_new_board_wiring(name):
    src = SOURCE_REGISTRY[name]
    assert src.regions == {"mena"} and src.api_based and not src.requires_key and src.discoverable
    assert src.cls.platform is Platform(name)
    assert src.cls.regions == {"mena"}
    assert src.cls.rate_limit_per_minute <= 30                    # README §5.3 board ceiling
    cap = PORTALS[name]
    assert cap.tier == "C" and cap.regions == ("mena",) and cap.anti_bot == "low"
    assert not cap.auto_apply and cap.apply_label == "View only"


def test_mena_run_selects_the_new_boards_and_other_regions_do_not():
    mena_names = {s.name for s in select_sources("mena", [])}
    assert set(NEW) <= mena_names
    for region in ("india", "global"):
        names = {s.name for s in select_sources(region, [])}
        assert not (set(NEW) & names)


def test_every_mena_source_scraper_accepts_region_so_discovery_passes_it():
    import inspect
    for name, src in SOURCE_REGISTRY.items():
        if "mena" in src.regions and src.api_based:
            assert "region" in inspect.signature(src.cls.search_jobs).parameters, name


def test_migration_18_adds_exactly_the_new_enum_values():
    sql = (Path(__file__).resolve().parents[3] / "database" / "18_mena_sources.sql").read_text(encoding="utf-8")
    for name in NEW:
        assert f"ALTER TYPE platform ADD VALUE IF NOT EXISTS '{name}';" in sql
    assert sum(l.startswith("ALTER TYPE") for l in sql.splitlines()) == len(NEW)
    assert "on its own" in sql                                   # the run-alone note from file 15
