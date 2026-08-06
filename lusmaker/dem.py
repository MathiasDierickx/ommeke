"""Hoogtedata uit skadi/SRTM-tegels (.hgt), pure numpy."""
import math
from functools import lru_cache

import numpy as np

from . import config, geo

VOID = -32768


@lru_cache(maxsize=24)
def _tile(region_slug: str, lat_i: int, lon_i: int):
    name = f"{'N' if lat_i >= 0 else 'S'}{abs(lat_i):02d}{'E' if lon_i >= 0 else 'W'}{abs(lon_i):03d}"
    path = config.DATA / f"{name}.hgt"
    if not path.exists():
        return None
    arr = np.frombuffer(path.read_bytes(), dtype=">i2")
    n = int(math.isqrt(arr.size))
    return arr.reshape(n, n)


def elevation(lat: float, lon: float) -> float | None:
    lat_i, lon_i = math.floor(lat), math.floor(lon)
    t = _tile(config.current_region().slug, lat_i, lon_i)
    if t is None:
        return None
    n = t.shape[0] - 1  # 3600
    y = (lat_i + 1 - lat) * n
    x = (lon - lon_i) * n
    y0, x0 = min(int(y), n - 1), min(int(x), n - 1)
    fy, fx = y - y0, x - x0
    q = t[y0 : y0 + 2, x0 : x0 + 2].astype(float)
    if (q == VOID).any():
        valid = q[q != VOID]
        return float(valid.mean()) if valid.size else None
    top = q[0, 0] * (1 - fx) + q[0, 1] * fx
    bot = q[1, 0] * (1 - fx) + q[1, 1] * fx
    return float(top * (1 - fy) + bot * fy)


def profile(geom, step: float = 25.0):
    """(punten, hoogtes) langs een polyline; gaten voorwaarts opgevuld."""
    pts = geo.resample(geom, step)
    eles = []
    prev = 0.0
    for lat, lon in pts:
        e = elevation(lat, lon)
        if e is None:
            e = prev
        eles.append(e)
        prev = e
    return pts, eles


def smooth(values, window: int = 5):
    if len(values) < window:
        return list(values)
    arr = np.array(values, dtype=float)
    kernel = np.ones(window) / window
    pad = window // 2
    padded = np.concatenate([np.full(pad, arr[0]), arr, np.full(pad, arr[-1])])
    return list(np.convolve(padded, kernel, mode="valid"))


def gain(geom) -> float:
    """Totale positieve hoogtemeters langs een geometrie."""
    _, eles = profile(geom, step=30.0)
    sm = smooth(eles, 5)
    total = 0.0
    for i in range(1, len(sm)):
        d = sm[i] - sm[i - 1]
        if d > 0.15:
            total += d
    return round(total, 1)
