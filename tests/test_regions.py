"""Pure tests voor regioregister, paden en DEM-tegelberekening."""

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from lusmaker import config, draft, regions
from lusmaker import gh_config


@contextmanager
def _isolated_home(path: Path):
    previous_home = os.environ.get("LUSMAKER_HOME")
    previous_region = os.environ.pop("LUSMAKER_REGION", None)
    os.environ["LUSMAKER_HOME"] = str(path)
    try:
        yield
    finally:
        if previous_home is None:
            os.environ.pop("LUSMAKER_HOME", None)
        else:
            os.environ["LUSMAKER_HOME"] = previous_home
        if previous_region is not None:
            os.environ["LUSMAKER_REGION"] = previous_region


def test_dem_tiles_for_zeeland_bbox():
    assert config.dem_tiles_for_bbox((51.2, 3.4, 51.8, 4.3)) == [
        "N51E003",
        "N51E004",
    ]


def test_legacy_paths_stay_unchanged_without_registry():
    with tempfile.TemporaryDirectory() as temp_dir:
        home = Path(temp_dir)
        with _isolated_home(home):
            region = config.current_region()

            assert region.legacy is True
            assert region.slug == "vlaanderen"
            assert config.DATA == home / "data"
            assert config.CACHE == home / "cache"
            assert config.GH_DIR == home / "gh"
            assert config.HEAT_DIR == home / "heat"
            assert config.PBF_PATH == home / "data" / "belgium-latest.osm.pbf"
            assert config.GH_URL == "http://localhost:8989"


def test_register_list_default_and_port_assignment_are_pure():
    with tempfile.TemporaryDirectory() as temp_dir:
        home = Path(temp_dir)
        with _isolated_home(home):
            zeeland = regions.add(
                "zeeland",
                "europe/netherlands/zeeland",
                (51.2, 3.4, 51.8, 4.3),
                home=home,
                available=lambda port: True,
            )
            assert zeeland.gh_port == 8989
            limburg = regions.add(
                "limburg",
                "europe/netherlands/limburg",
                (50.7, 5.5, 51.8, 6.3),
                home=home,
                available=lambda port: True,
            )
            assert limburg.gh_port == 8990

            listed = regions.list_all(home=home, checker=lambda region: False)
            assert listed["default"] == "zeeland"
            assert [item["slug"] for item in listed["regions"]] == [
                "limburg",
                "zeeland",
            ]
            assert all(not item["graphhopper_bereikbaar"] for item in listed["regions"])

            assert regions.set_default("limburg", home=home) == {
                "default": "limburg"
            }
            assert config.get_region(home=home).slug == "limburg"
            with config.use_region("zeeland"):
                assert config.DATA == home / "regions" / "zeeland" / "data"
                assert config.PBF_PATH.name == "zeeland-latest.osm.pbf"


def test_region_gh_config_and_compose_use_assigned_port_and_paths():
    with tempfile.TemporaryDirectory() as temp_dir:
        home = Path(temp_dir)
        with _isolated_home(home):
            config.register_region(
                "zeeland",
                "europe/netherlands/zeeland",
                (51.2, 3.4, 51.8, 4.3),
                8993,
                home=home,
            )
            with config.use_region("zeeland"):
                files = gh_config.write_gh_files()
            gh_yml = Path(files[0]).read_text(encoding="utf-8")
            assert "datareader.file: /lus/data/zeeland-latest.osm.pbf" in gh_yml
            assert "port: 8993" in gh_yml
            assert "port: 8994" in gh_yml

            compose_path = home / "docker-compose.regions.yml"
            regions.write_compose(home=home, output_path=compose_path)
            compose = compose_path.read_text(encoding="utf-8")
            assert "container_name: lusmaker-gh-zeeland" in compose
            assert "8993:8993" in compose
            assert "/regions/zeeland:/lus" in compose
            assert "/gh/graph-cache:/data/default-gh" in compose


def test_draft_keeps_its_region_when_default_changes():
    with tempfile.TemporaryDirectory() as temp_dir:
        home = Path(temp_dir)
        with _isolated_home(home):
            for slug in ("zeeland", "limburg"):
                config.register_region(
                    slug,
                    f"europe/netherlands/{slug}",
                    (51.2, 3.4, 51.8, 4.3),
                    8989 if slug == "zeeland" else 8990,
                    home=home,
                )
            with config.use_region("zeeland"):
                config.ensure_dirs()
                climb = {
                    "id": "zeeuwsedijk",
                    "name": "Zeeuwse Dijk",
                    "town": "Middelburg",
                    "length_m": 500,
                    "gain_m": 10,
                    "avg_pct": 2,
                    "max_pct": 3,
                    "warnings": [],
                    "foot": [51.5, 3.6],
                    "mid": [51.501, 3.6],
                    "top": [51.502, 3.6],
                }
                config.CLIMBS_JSON.write_text(
                    json.dumps({"climbs": {"zeeuwsedijk": climb}, "failed": []}),
                    encoding="utf-8",
                )
                created = draft.create("51.5,3.6", region="zeeland")

            config.set_default_region("limburg", home=home)
            result = draft.add_climb(created["id"], "zeeuwsedijk")

            assert result["region"] == "zeeland"
            assert draft.load(created["id"])["region"] == "zeeland"


def test_legacy_draft_output_stays_compatible_but_file_stores_region():
    with tempfile.TemporaryDirectory() as temp_dir:
        home = Path(temp_dir)
        with _isolated_home(home):
            created = draft.create("50.8,3.7")

            assert "region" not in created
            assert draft.load(created["id"])["region"] == "vlaanderen"


def test_migrate_legacy_moves_only_regional_data_and_registers_vlaanderen():
    with tempfile.TemporaryDirectory() as temp_dir:
        home = Path(temp_dir)
        with _isolated_home(home):
            for name in ("data", "cache", "gh", "heat"):
                directory = home / name
                directory.mkdir()
                (directory / "marker").write_text(name, encoding="utf-8")
            drafts = home / "drafts"
            drafts.mkdir()
            (drafts / "keep.json").write_text("{}", encoding="utf-8")

            result = regions.migrate_legacy(
                home=home,
                compose_path=home / "docker-compose.regions.yml",
            )

            assert result["region"] == "vlaanderen"
            for name in ("data", "cache", "gh", "heat"):
                marker = home / "regions" / "vlaanderen" / name / "marker"
                assert marker.read_text(encoding="utf-8") == name
            assert (drafts / "keep.json").exists()
            assert config.get_region(home=home).slug == "vlaanderen"
