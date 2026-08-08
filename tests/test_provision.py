"""Pure tests voor provisioningstatus en regiopacks."""

import json
import os
import tarfile
import tempfile
from contextlib import contextmanager
from pathlib import Path

from deploy.aws.prepare_region import prepare
from lusmaker import config, provision


@contextmanager
def _isolated_home(path: Path):
    previous = os.environ.get("LUSMAKER_HOME")
    os.environ["LUSMAKER_HOME"] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("LUSMAKER_HOME", None)
        else:
            os.environ["LUSMAKER_HOME"] = previous


def test_pack_location_escapes_nested_slugs():
    assert (
        provision.pack_location("https://packs.example/base/", "europe/benelux")
        == "https://packs.example/base/europe__benelux.tar.gz"
    )
    assert provision.pack_location(
        Path("/srv/packs"), "europe/benelux"
    ) == "/srv/packs/europe__benelux.tar.gz"


def test_provision_state_roundtrip_and_registered_fallback():
    with tempfile.TemporaryDirectory() as temp_dir:
        home = Path(temp_dir)
        state = provision.write_provision_state(
            "zeeland",
            "bouwen",
            42,
            home=home,
            message="gazetteer",
        )
        assert provision.read_provision_state("zeeland", home=home) == state
        assert provision.region_status("zeeland", home=home)["voortgang"] == 42

        config.register_region(
            "limburg",
            "europe/netherlands/limburg",
            (50.7, 5.5, 51.8, 6.3),
            8989,
            home=home,
        )
        fallback = provision.region_status("limburg", home=home)
        assert fallback["fase"] == "klaar"
        assert fallback["status"] == "klaar"


def test_background_provision_uses_injected_popen_and_writes_initial_state():
    with tempfile.TemporaryDirectory() as temp_dir:
        home = Path(temp_dir)
        calls = []

        def popen(command, **kwargs):
            calls.append((command, kwargs))
            return object()

        result = provision.provision(
            "zeeland",
            "https://download.geofabrik.de/europe/netherlands/"
            "zeeland-latest.osm.pbf",
            (51.2, 3.4, 51.8, 4.3),
            home=home,
            popen=popen,
        )
        assert result["gestart"] is True
        assert calls[0][0][:3] == [
            os.sys.executable,
            "-m",
            "lusmaker.provision",
        ]
        kwargs = calls[0][1]
        assert kwargs["start_new_session"] is True
        assert kwargs["stdout"].name.endswith("provision.log")
        assert kwargs["stderr"] is kwargs["stdout"]
        assert provision.region_status("zeeland", home=home)["fase"] == "downloaden"


def test_pack_contains_rebuild_outputs_but_not_pbf():
    with tempfile.TemporaryDirectory() as temp_dir:
        home = Path(temp_dir)
        with _isolated_home(home):
            region = config.register_region(
                "zeeland",
                "europe/netherlands/zeeland",
                (51.2, 3.4, 51.8, 4.3),
                8989,
                home=home,
            )
            (region.cache).mkdir(parents=True)
            (region.cache / "extract.pkl").write_bytes(b"extract")
            region.data.mkdir(parents=True)
            (region.data / "N51E003.hgt").write_bytes(b"dem")
            (region.data / region.pbf_name).write_bytes(b"large-pbf")
            (region.gh_dir / "graph-cache").mkdir(parents=True)
            (region.gh_dir / "graph-cache" / "edges").write_bytes(b"graph")
            (region.gh_dir / "custom_models").mkdir()
            (region.gh_dir / "custom_models" / "quiet.json").write_text("{}")
            (region.gh_dir / "custom_areas").mkdir()
            (region.gh_dir / "custom_areas" / "popular.geojson").write_text("{}")
            (region.gh_dir / "config.yml").write_text("graphhopper:")

            output = home / "pack.tar.gz"
            result = provision.create_pack("zeeland", output, home=home)

        assert result["manifest"]["geofabrik"] == "europe/netherlands/zeeland"
        with tarfile.open(output, "r:gz") as archive:
            names = set(archive.getnames())
            manifest = json.load(archive.extractfile("pack.json"))
        assert "cache/extract.pkl" in names
        assert "data/N51E003.hgt" in names
        assert "gh/graph-cache/edges" in names
        assert "gh/config.yml" in names
        assert "gh/custom_models/quiet.json" in names
        assert "gh/custom_areas/popular.geojson" in names
        assert not any(name.endswith(".osm.pbf") for name in names)
        assert manifest["slug"] == "zeeland"

        prepared = prepare(output, "zeeland", home / "docker-context")
        context = Path(prepared["destination"])
        registry = json.loads((context / "regions.json").read_text())
        assert registry["default"] == "zeeland"
        assert registry["regions"]["zeeland"]["bbox"] == [51.2, 3.4, 51.8, 4.3]
        assert (
            context / "regions" / "zeeland" / "gh" / "graph-cache" / "edges"
        ).read_bytes() == b"graph"


def test_foreground_provision_uses_injected_build_exec_and_health():
    with tempfile.TemporaryDirectory() as temp_dir:
        home = Path(temp_dir)
        commands = []
        previous_cache = os.environ.pop("LUSMAKER_PACK_CACHE", None)
        try:
            with _isolated_home(home):
                def build(region, pbf_url):
                    assert pbf_url.endswith("zeeland-latest.osm.pbf")
                    region.cache.mkdir(parents=True)
                    (region.cache / "extract.pkl").write_bytes(b"pure-test")
                    return {"gebouwd": True}

                def execute(command, check):
                    assert check is True
                    commands.append(command)

                result = provision.provision(
                    "zeeland",
                    "https://download.geofabrik.de/europe/netherlands/"
                    "zeeland-latest.osm.pbf",
                    (51.2, 3.4, 51.8, 4.3),
                    background=False,
                    home=home,
                    build_func=build,
                    exec_func=execute,
                    health_check=lambda url: url == "http://localhost:8989/health",
                    compose_path=home / "docker-compose.regions.yml",
                    port_available=lambda port: True,
                )
        finally:
            if previous_cache is not None:
                os.environ["LUSMAKER_PACK_CACHE"] = previous_cache

        assert result["provisioning"]["fase"] == "klaar"
        assert result["build"] == {"gebouwd": True}
        assert commands == [
            [
                "docker",
                "compose",
                "-f",
                str(home / "docker-compose.regions.yml"),
                "up",
                "-d",
                "graphhopper-zeeland",
            ]
        ]
