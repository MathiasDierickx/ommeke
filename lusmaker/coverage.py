"""Dekkingscontrole: punten buiten de bbox van de actieve regiopack weigeren."""
from __future__ import annotations

import math

from . import config

CODE = "buiten_gebied"


class OutOfCoverage(RuntimeError):
    """Een start-, anker- of via-punt ligt buiten het gedekte gebied."""

    code = CODE

    def __init__(self, message: str, dekking: dict, punt: dict | None = None):
        super().__init__(message)
        self.dekking = dekking
        self.punt = punt

    def payload(self) -> dict:
        out = {"error": str(self), "code": self.code, "dekking": self.dekking}
        if self.punt:
            out["punt"] = self.punt
        return out


def error_payload(exc: BaseException) -> dict:
    """Foutpayload voor CLI/API/chat; gestructureerd bij ``buiten_gebied``."""
    if isinstance(exc, OutOfCoverage):
        return exc.payload()
    return {"error": str(exc)}


def _area_name(region) -> str:
    return region.slug.replace("-", " ").title()


def fetch_info() -> dict:
    """GraphHopper ``/info`` van de actieve router (vervangbaar in tests)."""
    from . import gh
    return gh.info()


_BBOX_CACHE: dict[str, tuple[float, float, float, float]] = {}


def graph_bbox() -> tuple[float, float, float, float] | None:
    """Gemeten bbox (minlat, minlon, maxlat, maxlon) van de geladen graph.

    Faalt open: is ``/info`` onbereikbaar of ontbreekt ``bbox``, dan ``None``
    en wordt er niet geweigerd. Alleen geslaagde metingen worden per
    GraphHopper-URL gecachet.
    """
    url = config.GH_URL
    if url in _BBOX_CACHE:
        return _BBOX_CACHE[url]
    try:
        raw = fetch_info().get("bbox")
        min_lon, min_lat, max_lon, max_lat = (float(v) for v in raw)
        if not all(math.isfinite(v) for v in (min_lon, min_lat, max_lon, max_lat)):
            return None
        if min_lat > max_lat or min_lon > max_lon:
            return None
    except Exception:
        return None
    _BBOX_CACHE[url] = (min_lat, min_lon, max_lat, max_lon)
    return _BBOX_CACHE[url]


def dekking(bbox, region=None) -> dict:
    """Beschrijf het gedekte gebied (gemeten graph-bbox) van de regio."""
    region = region or config.current_region()
    min_lat, min_lon, max_lat, max_lon = bbox
    return {
        "regio": region.slug,
        "naam": _area_name(region),
        "bbox": {
            "min_lat": min_lat, "min_lon": min_lon,
            "max_lat": max_lat, "max_lon": max_lon,
        },
    }


def message(bbox, region=None) -> str:
    d = dekking(bbox, region)
    b = d["bbox"]
    return (
        f"Ommeke dekt momenteel {d['naam']} ongeveer tussen "
        f"{b['min_lat']:.2f}°N en {b['max_lat']:.2f}°N en tussen "
        f"{b['min_lon']:.2f}°O en {b['max_lon']:.2f}°O."
    )


def contains(lat: float, lon: float, bbox) -> bool:
    min_lat, min_lon, max_lat, max_lon = bbox
    return (
        math.isfinite(lat) and math.isfinite(lon)
        and min_lat <= lat <= max_lat and min_lon <= lon <= max_lon
    )


def check_point(point: dict, role: str = "startpunt", region=None) -> None:
    """Gooi ``OutOfCoverage`` als het punt buiten de geladen graph valt.

    Zonder meetbare graph-bbox wordt niets geweigerd (fail open).
    """
    bbox = graph_bbox()
    if bbox is None:
        return
    lat, lon = point["lat"], point["lon"]
    if contains(lat, lon, bbox):
        return
    region = region or config.current_region()
    label = point.get("label") or f"{lat:.5f}, {lon:.5f}"
    raise OutOfCoverage(
        f"Het {role} '{label}' ligt buiten het gedekte gebied. "
        f"{message(bbox, region)} Kies een plaats binnen dat gebied.",
        dekking(bbox, region),
        {"rol": role, "lat": lat, "lon": lon, "label": point.get("label")},
    )
