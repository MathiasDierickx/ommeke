"""Offline tests voor de dekkingscontrole (`buiten_gebied`)."""

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from lusmaker import config, coverage, draft, intents

FAKE_BBOX = (51.0, 3.0, 51.5, 4.0)
BREDENE = (51.25097, 2.97303)  # net buiten FAKE_BBOX (lon 2.97 < 3.0)
INSIDE = (51.2, 3.5)


@contextmanager
def _fake_graph(info):
    """Vervang /info door een injecteerbare functie en leeg de cache."""
    original = coverage.fetch_info
    coverage.fetch_info = info
    coverage._BBOX_CACHE.clear()
    try:
        yield
    finally:
        coverage.fetch_info = original
        coverage._BBOX_CACHE.clear()


def _info():
    # GraphHopper /info: [minLon, minLat, maxLon, maxLat]
    return {"bbox": [FAKE_BBOX[1], FAKE_BBOX[0], FAKE_BBOX[3], FAKE_BBOX[2]]}


@contextmanager
def _fake_region():
    with tempfile.TemporaryDirectory() as temp_dir:
        home = Path(temp_dir)
        previous = {k: os.environ.pop(k, None) for k in ("LUSMAKER_HOME", "LUSMAKER_REGION")}
        os.environ["LUSMAKER_HOME"] = str(home)
        try:
            # De geconfigureerde bbox is bewust smaller: alleen de gemeten graph telt.
            config.register_region("vlaanderen", "europe/belgium", (50.68, 3.35, 51.10, 4.20), 8989, home=home)
            with _fake_graph(_info):
                yield
        finally:
            os.environ.pop("LUSMAKER_HOME", None)
            for key, value in previous.items():
                if value is not None:
                    os.environ[key] = value


def test_check_point_inside_ok_and_outside_buiten_gebied():
    with _fake_region():
        coverage.check_point({"lat": INSIDE[0], "lon": INSIDE[1]})
        # randen tellen mee: exact de geconfigureerde bbox
        coverage.check_point({"lat": FAKE_BBOX[0], "lon": FAKE_BBOX[1]})
        try:
            coverage.check_point({"lat": BREDENE[0], "lon": BREDENE[1], "label": "Bredene"})
        except coverage.OutOfCoverage as exc:
            payload = exc.payload()
            assert payload["code"] == "buiten_gebied"
            assert "Vlaanderen" in payload["error"] and "Bredene" in payload["error"]
            assert "51.00°N" in payload["error"] and "3.00°O" in payload["error"]
            assert payload["dekking"]["bbox"]["max_lon"] == 4.0
        else:
            raise AssertionError("buiten het gebied moet OutOfCoverage geven")


def test_draft_create_rejects_outside_start_without_saving_a_draft():
    with _fake_region():
        created = draft.create(f"{INSIDE[0]},{INSIDE[1]}")
        assert created["start_geocoded_als"]
        before = {item["id"] for item in draft.list_all()}
        try:
            draft.create(f"{BREDENE[0]},{BREDENE[1]}")
        except coverage.OutOfCoverage as exc:
            assert exc.code == "buiten_gebied"
        else:
            raise AssertionError("start buiten gebied moet falen")
        assert {item["id"] for item in draft.list_all()} == before


def test_plan_route_surfaces_buiten_gebied_instead_of_routing():
    with _fake_region():
        def unexpected(*args, **kwargs):
            raise AssertionError("er mag niet gerouteerd worden")
        try:
            intents.plan_route(
                f"{BREDENE[0]},{BREDENE[1]}", target_km=40, doel="toeren",
                profiel_naam="standaard", route_fn=unexpected, optimize_fn=unexpected,
            )
        except coverage.OutOfCoverage as exc:
            assert exc.payload()["code"] == "buiten_gebied"
        else:
            raise AssertionError("plan_route moet buiten_gebied geven")


def test_anchor_outside_coverage_is_rejected_in_plan_route():
    with _fake_region():
        def resolve(query):
            return {"lat": BREDENE[0], "lon": BREDENE[1], "label": "Bredene"}, []
        try:
            intents.plan_route(
                f"{INSIDE[0]},{INSIDE[1]}", target_km=40, doel="toeren",
                rond_plaats="Bredene", profiel_naam="standaard", resolve_fn=resolve, climbs_fn=lambda: {},
            )
        except coverage.OutOfCoverage as exc:
            assert exc.punt["rol"] == "ankerpunt"
        else:
            raise AssertionError("anker buiten gebied moet falen")


def test_zero_km_route_is_an_error_not_success():
    d = {"computed": {"total_km": 0.0}}
    saved = []
    try:
        intents._execute_request(
            d, {}, {"doel": "toeren"},
            route_fn=lambda *a, **k: None, optimize_fn=lambda *a, **k: None,
            persist_fn=saved.append,
        )
    except intents.IntentError as exc:
        assert "geen bruikbare routeafstand" in str(exc)
    else:
        raise AssertionError("0 km moet een fout zijn")
    assert d["computed"] is None and saved


def test_error_payload_is_structured_only_for_coverage_and_chat_keeps_it():
    assert coverage.error_payload(ValueError("x")) == {"error": "x"}
    with _fake_region():
        try:
            coverage.check_point({"lat": 0.0, "lon": 0.0})
        except coverage.OutOfCoverage as exc:
            out = coverage.error_payload(exc)
            json.dumps(out, ensure_ascii=False)
            assert set(out) >= {"error", "code", "dekking"}


def test_api_returns_422_with_code_and_dekking():
    from lusmaker import aws_api

    with _fake_region():
        try:
            coverage.check_point({"lat": 0.0, "lon": 0.0})
        except coverage.OutOfCoverage as exc:
            response = aws_api._coverage_error(exc)
    assert response.status_code == 422
    body = json.loads(response.body)
    assert body["code"] == "buiten_gebied" and body["dekking"]["regio"] == "vlaanderen"


def test_configured_region_bbox_is_not_used_graph_bbox_is():
    with _fake_region():
        # binnen de graph maar buiten de geconfigureerde bbox (lat 51.4 > 51.10)
        coverage.check_point({"lat": 51.4, "lon": 3.5})


def test_missing_or_unavailable_info_fails_open():
    def down():
        raise OSError("niet bereikbaar")
    for info in (down, lambda: {}, lambda: {"bbox": [1, 2]}, lambda: {"bbox": None}):
        with _fake_region():
            with _fake_graph(info):
                coverage.check_point({"lat": 0.0, "lon": 0.0})


def test_graph_bbox_is_cached_per_gh_url():
    calls = []
    def info():
        calls.append(1)
        return _info()
    with _fake_region():
        with _fake_graph(info):
            coverage.graph_bbox()
            coverage.graph_bbox()
            assert len(calls) == 1


def test_a_point_without_roads_becomes_a_structured_out_of_area_error():
    import io
    import json
    import urllib.error
    from unittest import mock
    from lusmaker import coverage, gh
    body = json.dumps({"message": "Cannot find point 0: 50.6370193,3.0636696"}).encode()
    error = urllib.error.HTTPError("http://gh/route", 400, "Bad Request", {}, io.BytesIO(body))
    def opener(*_a, **_k):
        raise error
    with mock.patch.object(coverage, "graph_bbox", lambda: None):
        try:
            gh._post_request("/route", {}, opener=opener)
            raise AssertionError("verwacht een fout")
        except coverage.OutOfCoverage as exc:
            assert isinstance(exc, gh.GhError)  # kandidaatlussen blijven dit overslaan
            payload = exc.payload()
            assert payload["code"] == "buiten_gebied"
            assert payload["punt"]["lat"] == 50.6370193
            assert "buiten het gebied" in payload["error"]
