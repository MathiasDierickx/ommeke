"""Import en integratie met volledig lokale WFS-fixtures; geen netwerk."""
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from lusmaker import analysis, config, draft, gh, heat, route_evidence, route_sources
from tests.test_heat import _isolated_home


def feature(identifier, *, lat=50.8, lon=3.7, properties=None, coordinates=None):
    return {"type": "Feature", "id": identifier, "properties": properties or {},
            "geometry": {"type": "LineString", "coordinates": coordinates or [[lon, lat], [lon + 0.004, lat]]}}


def collection(features, total=None):
    return {"type": "FeatureCollection", "features": features,
            "numberMatched": len(features) if total is None else total, "numberReturned": len(features)}


def fixture_fetch(url):
    query = parse_qs(urlparse(url).query)
    layer = query["typeNames"][0]
    if int(query["startIndex"][0]):
        return collection([], 1)
    if layer in {"routes:traject_fiets", "routes:icoonroute_trajecten"}:
        return collection([feature(layer + ".1", properties={"updatedate": "2026-10-01Z", "objectid": 1})])
    if layer == "routes:traject_wandel":
        return collection([feature(layer + ".1", lat=50.81)])
    if layer == "routes:wegdek_fiets":
        return collection([feature(layer + ".1", properties={"ground": "verhard"})])
    if layer == "routes:verkeersintensiteit_fiets":
        return collection([feature(layer + ".1", properties={"traffic": "niet-autovrij"})])
    return collection([])


def expect_error(fn, message):
    try:
        fn()
    except (ValueError, RuntimeError) as exc:
        assert message in str(exc), str(exc)
    else:
        raise AssertionError("verwachtte een duidelijke fout")


def test_wfs_paginates_server_cap_and_preserves_properties():
    calls = []
    items = [feature(f"route.{i}", properties={"eigenaar": "Provincie", "objectid": i}) for i in range(3)]

    def fetch(url):
        query = parse_qs(urlparse(url).query)
        calls.append(query)
        start = int(query["startIndex"][0])
        # Server retourneert minder dan gevraagd, maar heeft nog resultaten.
        return collection(items[start:start + 1], 3)

    document, metadata = route_sources.download_layer(route_sources.layers()[0], fetcher=fetch, page_size=2)
    assert len(document["features"]) == metadata["feature_count"] == 3
    assert document["features"][2]["properties"]["eigenaar"] == "Provincie"
    assert [c["startIndex"] for c in calls] == [["0"], ["1"], ["2"]]
    assert all(c["sortBy"] == ["objectid A"] and "bbox" not in c for c in calls)


def test_wfs_rejects_duplicate_truncated_and_wrong_coordinate_responses():
    spec = route_sources.layers()[0]
    expect_error(lambda: route_sources.download_layer(spec, fetcher=lambda _: collection([feature("a")], 2)), "dubbele")
    replies = iter([collection([feature("a")], 2), collection([], 2)])
    expect_error(lambda: route_sources.download_layer(spec, fetcher=lambda _: next(replies)), "onvolledige")
    expect_error(lambda: route_sources.download_layer(spec, fetcher=lambda _: collection([feature("a", lat=3.7, lon=50.8)])), "WGS84")
    expect_error(lambda: route_sources.download_layer(spec, fetcher=lambda _: b"<html>fout</html>"), "HTML/XML")


def test_sync_reuses_snapshots_offline_and_failed_refresh_keeps_current_build():
    with tempfile.TemporaryDirectory() as folder:
        base = Path(folder)
        with _isolated_home(base / "runtime"):
            first = route_sources.sync(base / "pack", fetcher=fixture_fetch)
            pointer = (base / "pack/current.json").read_bytes()
            never_fetch = lambda _: (_ for _ in ()).throw(AssertionError("geen netwerk verwacht"))
            second = route_sources.sync(base / "pack", offline=True, fetcher=never_fetch)
            assert first["build_id"] == second["build_id"]
            # Bouw echt opnieuw in een lege uitvoermap: niet alleen dezelfde
            # bestaande build teruggeven. Alle outputchecksums moeten kloppen.
            shutil.copytree(base / "pack/raw", base / "rebuilt/raw")
            rebuilt = route_sources.sync(base / "rebuilt", offline=True, fetcher=never_fetch)
            assert rebuilt["build_id"] == first["build_id"]
            assert (Path(first["build"]) / "checksums.json").read_bytes() == (Path(rebuilt["build"]) / "checksums.json").read_bytes()
            assert first["features"] == 5 and first["lagen"] == 18
            assert not first["runtime_geactiveerd"]
            assert not (base / "runtime").exists()
            expect_error(lambda: route_sources.sync(base / "pack", refresh=True, fetcher=lambda _: b"<html>fout"), "HTML/XML")
            assert (base / "pack/current.json").read_bytes() == pointer
            assert not (base / "pack/.sync.lock").exists()
            manifest = json.loads((Path(first["build"]) / "manifest.json").read_text())
            assert manifest["contains_personal_heat"] is False
            assert "niet_autovrij_tvl" in manifest["heat"]["areas"]
            with sqlite3.connect(first["database"]) as db:
                assert db.execute("select count(*) from source").fetchone()[0] == 18
                assert db.execute("select count(*) from feature").fetchone()[0] == 5


def test_sync_detects_snapshot_tampering_and_refuses_active_runtime():
    with tempfile.TemporaryDirectory() as folder:
        base = Path(folder)
        with _isolated_home(base / "runtime"):
            expect_error(lambda: route_sources.sync(base / "runtime/cache"), "buiten de actieve")
            first = route_sources.sync(base / "pack", fetcher=fixture_fetch)
            snapshot = next((base / "pack/raw").glob("*.geojson"))
            snapshot.write_text("gewijzigd")
            expect_error(lambda: route_sources.sync(base / "pack", offline=True), "snapshot gewijzigd")
            Path(first["database"]).write_bytes(b"gewijzigd")
            expect_error(lambda: route_sources.verify(first["build"]), "buildbestand gewijzigd")


def test_matching_ignores_parallel_crossing_and_other_sport_and_caps_duplicates():
    with tempfile.TemporaryDirectory() as folder:
        base = Path(folder)
        with _isolated_home(base / "runtime"):
            result = route_sources.sync(base / "pack", fetcher=fixture_fetch)
            stats = lambda line, profile="quiet": route_evidence.route_stats([line], profile, database=result["database"])
            line = [(50.8, 3.7), (50.8, 3.704)]
            matched = stats(line)
            assert matched["gecureerd_pct"] == 100
            assert matched["curatie_score"] == 0.8  # netwerk + icoonroute niet optellen
            assert matched["niet_autovrij_pct"] == 100
            assert matched["bevestigd_autovrij_pct"] == 0
            assert matched["buggygeschiktheid"] == "onbekend"
            assert stats(line, "trail")["gecureerd_pct"] == 0
            parallel = stats([(50.8003, 3.7), (50.8003, 3.704)])
            assert parallel["gecureerd_pct"] == 0
            assert parallel["verkeer_onbekend_pct"] == 100
            crossing = stats([(50.799, 3.702), (50.801, 3.702)])
            assert crossing["gecureerd_pct"] == 0
            assert stats(list(reversed(line))) == matched


def test_scoring_is_length_weighted_and_does_not_join_separate_legs():
    with tempfile.TemporaryDirectory() as folder:
        base = Path(folder)
        with _isolated_home(base / "runtime"):
            result = route_sources.sync(base / "pack", fetcher=fixture_fetch)
            known = [(50.8, 3.7), (50.8, 3.704)]
            unknown = [(50.8, 4.0 + i * 0.00004) for i in range(101)]
            stats = route_evidence.route_stats([known, unknown], database=result["database"])
            assert 49.9 <= stats["gecureerd_pct"] <= 50.1
            assert stats["lengte_m"] < 600  # geen fictieve verbinding van 20 km
            assert stats["verkeer_onbekend_pct"] == 50


def test_pack_flows_through_real_quality_report_and_optimizer():
    with tempfile.TemporaryDirectory() as folder:
        base = Path(folder)
        with _isolated_home(base / "runtime"):
            result = route_sources.sync(base / "pack", fetcher=fixture_fetch)
        with route_sources._home(Path(result["home"])):
            line = [(50.8, 3.7), (50.8, 3.704)]
            report = analysis.route_stats([line], [{}])
            assert report["routedata"]["gecureerd_pct"] == 100
            assert report["autovrij_pct"] == 0
            unknown = analysis.route_stats([[(50.9, 3.7), (50.9, 3.704)]], [{}])
            assert unknown["autovrij_pct"] is None
            scored = draft._candidate_surface_components([{"coords": line}])
            assert scored["populair"] == 0.8
            assert scored["autovrij"] == 0
            walking = draft._candidate_surface_components([{"coords": line}], profile="trail")
            assert walking["populair"] == 0
            model = gh._custom_model(avoid_busy=True, area_evs={"in_niet_autovrij_tvl", "in_druk_tvl"})
            assert model["priority"] == [{"if": "in_niet_autovrij_tvl", "multiply_by": "0.85"}]


def test_install_requires_explicit_apply_and_preserves_original_runtime_files():
    with tempfile.TemporaryDirectory() as folder:
        base = Path(folder)
        with _isolated_home(base / "runtime"):
            result = route_sources.sync(base / "pack", fetcher=fixture_fetch)
            plan = route_sources.install(result["build"])
            assert not plan["toegepast"] and not (base / "runtime").exists()
            config.ensure_dirs()
            config.HEAT_PKL.write_bytes(b"bestaande cache blijft behouden")
            gh_config = config.GH_DIR / "config.yml"
            gh_config.write_text("bestaande graph-config")
            applied = route_sources.install(result["build"], apply=True)
            assert applied["toegepast"]
            assert config.HEAT_PKL.read_bytes() == b"bestaande cache blijft behouden"
            assert gh_config.read_text() == "bestaande graph-config"
            assert heat.vlaanderen_data()["version"] == 3
            assert heat.popular_cells()
            assert heat.status()["actief"]["cellen"] > 0
            stats = route_evidence.route_stats([[(50.8, 3.7), (50.8, 3.704)]])
            assert stats["gecureerd_pct"] == 100
            second = route_sources.install(result["build"], apply=True)
            assert second["vorige_versie"]["build_id"] == result["build_id"]


def test_evaluation_ignores_unrouted_and_zero_length_drafts_without_writes():
    with tempfile.TemporaryDirectory() as folder:
        base = Path(folder)
        with _isolated_home(base / "runtime"):
            result = route_sources.sync(base / "pack", fetcher=fixture_fetch)
            drafts = base / "drafts"
            drafts.mkdir()
            (drafts / "a.json").write_text('{"_geometry": [[]]}')
            (drafts / "b.json").write_text(json.dumps({"profile": "quiet", "_geometry": [[[50.8, 3.7], [50.8, 3.704]]]}))
            before = {p.name: p.read_bytes() for p in drafts.iterdir()}
            evaluated = route_sources.evaluate(result["build"], drafts, limit=1)
            assert evaluated["live_router_aanroepen"] == 0
            assert len(evaluated["routes"]) == 1
            assert evaluated["routes"][0]["draft_id"] == "b"
            assert before == {p.name: p.read_bytes() for p in drafts.iterdir()}


def test_virtual_networks_in_the_main_layer_get_no_signposted_bonus():
    def virtual_fetch(url):
        response = fixture_fetch(url)
        if parse_qs(urlparse(url).query)["typeNames"] == ["routes:traject_wandel"]:
            response["features"][0]["properties"]["virtual"] = "Virtual network"
        return response

    with tempfile.TemporaryDirectory() as folder:
        base = Path(folder)
        with _isolated_home(base / "runtime"):
            result = route_sources.sync(base / "pack", fetcher=virtual_fetch)
        with route_sources._home(Path(result["home"])):
            assert not heat.vlaanderen_data()["wandel"]
            evidence = route_evidence.route_stats([[(50.81, 3.7), (50.81, 3.704)]], "trail")
            assert evidence["gecureerd_pct"] == 0


def test_exact_surface_fallback_respects_known_gh_surface_and_parallel_roads():
    def cobble_fetch(url):
        response = fixture_fetch(url)
        if parse_qs(urlparse(url).query)["typeNames"] == ["routes:wegdek_fiets"]:
            response["features"][0]["properties"]["ground"] = "kassei"
        return response

    with tempfile.TemporaryDirectory() as folder:
        base = Path(folder)
        with _isolated_home(base / "runtime"):
            result = route_sources.sync(base / "pack", fetcher=cobble_fetch)
        with route_sources._home(Path(result["home"])):
            line = [(50.8, 3.7), (50.8, 3.704)]
            assert analysis.route_stats([line], [{"surface": [[0, 1, "missing"]]}])["kassei_m"] > 250
            assert analysis.route_stats([line], [{"surface": [[0, 1, "asphalt"]]}])["kassei_m"] == 0
            parallel = [(50.8003, 3.7), (50.8003, 3.704)]
            assert analysis.route_stats([parallel], [{"surface": [[0, 1, "missing"]]}])["kassei_m"] == 0
