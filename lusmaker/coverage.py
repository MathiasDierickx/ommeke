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


def dekking(region=None) -> dict:
    """Beschrijf het gedekte gebied van de (actieve) regio."""
    region = region or config.current_region()
    min_lat, min_lon, max_lat, max_lon = region.bbox
    return {
        "regio": region.slug,
        "naam": _area_name(region),
        "bbox": {
            "min_lat": min_lat, "min_lon": min_lon,
            "max_lat": max_lat, "max_lon": max_lon,
        },
    }


def message(region=None) -> str:
    d = dekking(region)
    b = d["bbox"]
    return (
        f"Ommeke dekt momenteel {d['naam']} ongeveer tussen "
        f"{b['min_lat']:.2f}°N en {b['max_lat']:.2f}°N en tussen "
        f"{b['min_lon']:.2f}°O en {b['max_lon']:.2f}°O."
    )


def contains(lat: float, lon: float, region=None) -> bool:
    region = region or config.current_region()
    min_lat, min_lon, max_lat, max_lon = region.bbox
    return (
        math.isfinite(lat) and math.isfinite(lon)
        and min_lat <= lat <= max_lat and min_lon <= lon <= max_lon
    )


def check_point(point: dict, role: str = "startpunt", region=None) -> None:
    """Gooi ``OutOfCoverage`` als het punt buiten de bbox van de regio valt."""
    region = region or config.current_region()
    lat, lon = point["lat"], point["lon"]
    if contains(lat, lon, region):
        return
    label = point.get("label") or f"{lat:.5f}, {lon:.5f}"
    raise OutOfCoverage(
        f"Het {role} '{label}' ligt buiten het gedekte gebied. "
        f"{message(region)} Kies een plaats binnen dat gebied.",
        dekking(region),
        {"rol": role, "lat": lat, "lon": lon, "label": point.get("label")},
    )
