"""Geometrie-hulpfuncties: haversine, resampling, gridcellen."""
import math

R = 6371000.0

# Cellgrootte ~130 m in beide richtingen op deze breedtegraad
CELL_LAT = 0.0012
CELL_LON = 0.0019


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Afstand in meter."""
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def path_length(geom) -> float:
    total = 0.0
    for i in range(1, len(geom)):
        total += haversine(geom[i - 1][0], geom[i - 1][1], geom[i][0], geom[i][1])
    return total


def resample(geom, step: float):
    """Punten op vaste afstand (m) langs een polyline, incl. begin- en eindpunt."""
    if len(geom) < 2:
        return list(geom)
    out = [geom[0]]
    carry = 0.0
    for i in range(1, len(geom)):
        a, b = geom[i - 1], geom[i]
        seg = haversine(a[0], a[1], b[0], b[1])
        if seg <= 0:
            continue
        d = step - carry
        while d <= seg:
            t = d / seg
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            d += step
        carry = (carry + seg) % step
    if out[-1] != geom[-1]:
        out.append(geom[-1])
    return out


def cell(lat: float, lon: float):
    return (int(lat / CELL_LAT), int(lon / CELL_LON))


def cells_for_geom(geom, expand: int = 1):
    """Set van gridcellen die de polyline bedekt, met `expand` ringen eromheen."""
    cells = set()
    for lat, lon in resample(geom, 80.0):
        c = cell(lat, lon)
        for di in range(-expand, expand + 1):
            for dj in range(-expand, expand + 1):
                cells.add((c[0] + di, c[1] + dj))
    return cells


def midpoint(geom):
    return geom[len(geom) // 2]


def _offset(lat: float, lon: float, dnorth_m: float, deast_m: float):
    return (lat + dnorth_m / 111320.0, lon + deast_m / (111320.0 * math.cos(math.radians(lat))))


def corridor_polygons(geom, width_m: float = 90.0, seg_len_m: float = 1500.0,
                      protect=None, protect_radius_m: float = 400.0):
    """Buffer een route-geometrie tot een reeks korte corridor-polygonen.

    Elke polygon is een 'dikke lijn' rond een stuk van ~seg_len_m; korte stukken
    krijgen zelden zelf-intersecties. Segmenten binnen protect_radius_m van een
    beschermd punt (bv. start van een lus) worden overgeslagen zodat de route
    daar wel terug mag.
    Returns: lijst van GeoJSON-ringen [[lon, lat], ...].
    """
    protect = protect or []
    line = resample(geom, 150.0)
    if len(line) < 2:
        return []
    step_pts = max(2, int(seg_len_m / 150.0))
    polys = []
    for i in range(0, len(line) - 1, step_pts):
        chunk = line[i : i + step_pts + 1]
        if len(chunk) < 2:
            continue
        if protect and any(
            haversine(p[0], p[1], q[0], q[1]) < protect_radius_m for p in chunk for q in protect
        ):
            continue
        left, right = [], []
        for j, (lat, lon) in enumerate(chunk):
            a = chunk[max(0, j - 1)]
            b = chunk[min(len(chunk) - 1, j + 1)]
            dn = (b[0] - a[0]) * 111320.0
            de = (b[1] - a[1]) * 111320.0 * math.cos(math.radians(lat))
            norm = math.hypot(dn, de) or 1.0
            # normaal op de richting
            nn, ne = -de / norm, dn / norm
            left.append(_offset(lat, lon, nn * width_m, ne * width_m))
            right.append(_offset(lat, lon, -nn * width_m, -ne * width_m))
        ring = left + right[::-1] + [left[0]]
        polys.append([[round(lon, 6), round(lat, 6)] for lat, lon in ring])
    return polys
