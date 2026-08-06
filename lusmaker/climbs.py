"""Klim-database: OSM-straatnaammatch + DEM-oriëntatie en -statistieken."""
import json
import sys
from collections import defaultdict

import yaml

from . import config, dem, geo

JUNCTION_EXTENSION_M = 120.0
BLOCK_WARNING = "eindigt midden in een blok"


def _load_yaml():
    with open(config.climbs_yaml_path()) as f:
        return yaml.safe_load(f)


def _components(ways):
    """Groepeer wegen die een eindpunt delen (union-find op endpoint-refs)."""
    parent = {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent.setdefault(a, a)
        parent.setdefault(b, b)
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for k, (_wid, refs, _coords, _tags) in enumerate(ways):
        union(("w", k), ("n", refs[0]))
        union(("w", k), ("n", refs[-1]))

    comps = defaultdict(list)
    for k in range(len(ways)):
        comps[find(("w", k))].append(k)
    return list(comps.values())


def _order_chain(ways, idxs):
    """Langste doorlopende ketting binnen een component (begrensde DFS).

    De exhaustieve zoektocht is exponentieel op grid-achtige componenten
    (poldernetten met gelijknamige dijkwegen); een stappenbudget begrenst
    dat, met de greedy-tot-dan-toe-beste ketting als resultaat.
    """
    adj = defaultdict(list)  # endpoint-ref -> [(way_idx, begint_hier)]
    for k in idxs:
        _wid, refs, _coords, _tags = ways[k]
        adj[refs[0]].append((k, True))
        adj[refs[-1]].append((k, False))

    def way_len(k):
        return geo.path_length(ways[k][2])

    best_path = []
    best_len = -1.0
    budget = [20000]  # max DFS-uitbreidingen voor de hele component

    def dfs(cur_ref, used, path, plen):
        nonlocal best_path, best_len
        if plen > best_len:
            best_len = plen
            best_path = list(path)
        if budget[0] <= 0:
            return
        for k, first in adj[cur_ref]:
            if k in used:
                continue
            budget[0] -= 1
            if budget[0] <= 0:
                return
            refs = ways[k][1]
            nxt = refs[-1] if first else refs[0]
            used.add(k)
            path.append((k, first))
            dfs(nxt, used, path, plen + way_len(k))
            path.pop()
            used.remove(k)

    leaves = [r for r, lst in adj.items() if len(lst) == 1] or [ways[idxs[0]][1][0]]
    for leaf in leaves:
        if budget[0] <= 0:
            break
        dfs(leaf, set(), [], 0.0)

    merged, merged_refs, way_ids = [], [], []
    for k, first in best_path:
        wid, refs, coords, _tags = ways[k]
        if not first:
            coords = coords[::-1]
            refs = refs[::-1]
        way_ids.append(wid)
        merged.extend(coords if not merged else coords[1:])
        merged_refs.extend(refs if not merged_refs else refs[1:])
    return merged, merged_refs, way_ids


def _chain_index_for_resampled(merged, sampled, sample_index):
    """Map een resamplepunt op de dichtstbijzijnde originele ketenknoop."""
    point = sampled[sample_index]
    return min(
        range(len(merged)),
        key=lambda i: geo.haversine(point[0], point[1], merged[i][0], merged[i][1]),
    )


def _walk_to_junction(merged, refs, start, direction, junction_refs, cap_m):
    if refs[start] in junction_refs:
        return start, True
    distance = 0.0
    current = start
    while 0 <= current + direction < len(merged):
        nxt = current + direction
        distance += geo.haversine(
            merged[current][0], merged[current][1], merged[nxt][0], merged[nxt][1]
        )
        if distance > cap_m:
            break
        current = nxt
        if refs[current] in junction_refs:
            return current, True
    return start, False


def _extend_to_junctions(
    merged, merged_refs, foot_index, top_index, junction_refs, cap_m=JUNCTION_EXTENSION_M
):
    """Verleng de klim in beide richtingen langs de originele ketting."""
    uphill_direction = 1 if top_index > foot_index else -1
    foot_index, foot_found = _walk_to_junction(
        merged, merged_refs, foot_index, -uphill_direction, junction_refs, cap_m
    )
    top_index, top_found = _walk_to_junction(
        merged, merged_refs, top_index, uphill_direction, junction_refs, cap_m
    )
    if foot_index < top_index:
        geom = merged[foot_index : top_index + 1]
    else:
        geom = merged[top_index : foot_index + 1][::-1]
    warnings = [] if foot_found and top_found else [BLOCK_WARNING]
    return geom, warnings


def _core_indices(geom, core_foot, core_top):
    """Indices van de oorspronkelijke klimkern in de verlengde geometrie."""
    return geom.index(core_foot), geom.index(core_top)


def _best_segment(merged):
    """Steilste aaneengesloten klimsegment uit het hoogteprofiel van de ketting.

    De OSM-straat is vaak langer dan de eigenlijke helling (vlakke aanloop,
    afdaling na de top); dit knipt het echte klimstuk eruit.
    Returns (geom, gain, length, foot_index, top_index), waarbij de indices
    naar knopen in de originele ketting wijzen. None als er geen echte klim
    in zit.
    """
    step = 25.0
    pts, eles = dem.profile(merged, step=step)
    if len(pts) < 8:
        return None
    sm = dem.smooth(eles, 5)
    n = len(sm)

    best = None  # (gain, avg, i, j)
    for direction in (1, -1):
        prof = sm if direction == 1 else sm[::-1]
        for i in range(n - 6):
            dip_min = prof[i]
            for j in range(i + 6, n):
                dip_min = min(dip_min, prof[j])
                gain = prof[j] - prof[i]
                if gain < 10 or dip_min < prof[i] - 4:
                    continue
                length = (j - i) * step
                avg = gain / length * 100
                if avg < 2.0:
                    continue
                key = (round(gain), avg)
                if best is None or key > (round(best[0]), best[1]):
                    best = (gain, avg, i, j, direction)
    if best is None:
        return None
    gain, _avg, i, j, direction = best
    seq = pts if direction == 1 else pts[::-1]
    geom = seq[i : j + 1]
    foot_index = _chain_index_for_resampled(merged, seq, i)
    top_index = _chain_index_for_resampled(merged, seq, j)
    return geom, gain, (j - i) * step, foot_index, top_index


def _max_gradient(geom):
    _, eles = dem.profile(geom, step=25.0)
    sm = dem.smooth(eles, 5)
    max_pct = 0.0
    win = 4  # 100 m
    for i in range(len(sm) - win):
        max_pct = max(max_pct, (sm[i + win] - sm[i]) / (win * 25.0) * 100.0)
    return max_pct


def _town_coord(places, town):
    tl = town.lower()
    ranked = []
    for name, ptype, lat, lon in places:
        if name.lower() == tl:
            prio = {"city": 0, "town": 1, "municipality": 2, "village": 3}.get(ptype, 4)
            ranked.append((prio, lat, lon))
    if not ranked:
        return None
    ranked.sort()
    return ranked[0][1], ranked[0][2]


def resolve_all(extract: dict, force: bool = False) -> dict:
    """Match elke klim uit climbs.yaml op OSM-wegen en bepaal voet/top via DEM."""
    if config.current_region().slug != config.LEGACY_SLUG:
        raise RuntimeError(
            "de curated climbs.yaml is alleen voor regio 'vlaanderen'; "
            "gebruik `lus climbs detect`"
        )
    if config.CLIMBS_JSON.exists() and not force:
        with open(config.CLIMBS_JSON) as f:
            return json.load(f)

    by_name = defaultdict(list)
    for way in extract["ways"]:
        name = way[3].get("name")
        if name:
            by_name[name.lower()].append(way)

    resolved, failed = {}, []
    for entry in _load_yaml():
        names = [entry["name"]] + list(entry.get("match", []))
        cand = []
        seen = set()
        for nm in names:
            for way in by_name.get(nm.lower(), []):
                if way[0] not in seen:
                    seen.add(way[0])
                    cand.append(way)
        town_pt = _town_coord(extract["places"], entry.get("town", "")) if entry.get("town") else None
        if town_pt:
            cand = [
                w for w in cand
                if geo.haversine(w[2][0][0], w[2][0][1], town_pt[0], town_pt[1]) < 9000
            ]
        if not cand:
            failed.append({"id": entry["id"], "reden": "geen OSM-naammatch in de regio"})
            continue

        # per component het beste klimsegment; hoogste gain wint
        best = None  # (gain, kern_geom, merged, refs, foot_i, top_i, way_ids, kern_m)
        fallback = None  # langste ketting, voor vlakke sectoren (kasseistroken)
        for idxs in _components(cand):
            merged, merged_refs, way_ids = _order_chain(cand, idxs)
            if len(merged) < 2:
                continue
            length = geo.path_length(merged)
            if fallback is None or length > fallback[3]:
                fallback = (merged, merged_refs, way_ids, length)
            seg = _best_segment(merged)
            if seg:
                kern_geom, gain_m, kern_m, foot_i, top_i = seg
                if best is None or gain_m > best[0]:
                    best = (
                        gain_m,
                        kern_geom,
                        merged,
                        merged_refs,
                        foot_i,
                        top_i,
                        way_ids,
                        kern_m,
                    )

        warn = []
        if best is None:
            if fallback is None:
                failed.append({"id": entry["id"], "reden": "geen bruikbare geometrie"})
                continue
            merged, _merged_refs, way_ids, kern_m = fallback
            e0, e1 = dem.elevation(*merged[0]), dem.elevation(*merged[-1])
            if e0 is None or e1 is None:
                failed.append({"id": entry["id"], "reden": "geen DEM-dekking"})
                continue
            if e0 > e1:
                merged = merged[::-1]
            geom = merged
            kern_geom = geom
            gain_m = abs(e1 - e0)
            warn.append("vlak segment (kasseistrook?) — volledige straat gebruikt")
        else:
            (
                gain_m,
                kern_geom,
                merged,
                merged_refs,
                foot_i,
                top_i,
                way_ids,
                kern_m,
            ) = best
            geom, extension_warnings = _extend_to_junctions(
                merged, merged_refs, foot_i, top_i, extract["junction_refs"]
            )
            kern_van, kern_tot = _core_indices(
                geom, merged[foot_i], merged[top_i]
            )
            warn.extend(extension_warnings)
        if best is None:
            kern_van, kern_tot = 0, len(geom) - 1

        e0 = dem.elevation(*geom[0])
        e1 = dem.elevation(*geom[-1])
        max_pct = _max_gradient(kern_geom)
        length = geo.path_length(geom)
        merged = geom
        if length < 150:
            warn.append("erg kort")

        resolved[entry["id"]] = {
            "id": entry["id"],
            "name": entry["name"],
            "town": entry.get("town"),
            "length_m": round(length),
            "kern_m": round(kern_m),
            "kern_van": kern_van,
            "kern_tot": kern_tot,
            "gain_m": round(gain_m, 1),
            "avg_pct": round(gain_m / kern_m * 100, 1) if kern_m else 0,
            "max_pct": round(max_pct, 1),
            "ele_foot": round(e0, 1),
            "ele_top": round(e1, 1),
            "foot": [round(merged[0][0], 6), round(merged[0][1], 6)],
            "top": [round(merged[-1][0], 6), round(merged[-1][1], 6)],
            "mid": [round(geo.midpoint(merged)[0], 6), round(geo.midpoint(merged)[1], 6)],
            "geom": [[round(a, 6), round(b, 6)] for a, b in merged],
            "osm_way_ids": way_ids,
            "warnings": warn,
        }

    out = {"climbs": resolved, "failed": failed}
    # behoud eerder gedetecteerde auto-klimmen (resolve mag ze niet wissen)
    if config.CLIMBS_JSON.exists():
        try:
            with open(config.CLIMBS_JSON) as f:
                out["auto"] = json.load(f).get("auto", {})
        except (OSError, json.JSONDecodeError):
            pass
    config.ensure_dirs()
    with open(config.CLIMBS_JSON, "w") as f:
        json.dump(out, f, ensure_ascii=False)
    if failed:
        print(f"[climbs] niet opgelost: {[f['id'] for f in failed]}", file=sys.stderr)
    return out


def _slug(name: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-")


def _nearest_place(places, lat, lon):
    best = None
    for name, ptype, plat, plon in places:
        if ptype not in ("city", "town", "village", "municipality"):
            continue
        d = geo.haversine(lat, lon, plat, plon)
        if best is None or d < best[0]:
            best = (d, name)
    return best[1] if best else None


def detect_auto(extract: dict, min_gain: float = 18.0, min_avg: float = 3.0) -> dict:
    """DEM-sweep over alle benoemde wegen: vind klimmen die niet in de
    namenlijst staan (het 'low hanging fruit' zoals de Diepestraat)."""
    data = load()
    known_ways = set()
    for c in data["climbs"].values():
        known_ways.update(c.get("osm_way_ids", []))

    by_name = defaultdict(list)
    for way in extract["ways"]:
        name = way[3].get("name")
        hw = way[3].get("highway", "")
        if not name or hw in ("footway", "path", "steps", "pedestrian", "bridleway"):
            continue
        by_name[name].append(way)

    auto: dict[str, dict] = {}
    n_profiled = 0
    for name, ways in by_name.items():
        for idxs in _components(ways):
            merged, merged_refs, way_ids = _order_chain(ways, idxs)
            if len(merged) < 2 or geo.path_length(merged) < 250:
                continue
            if known_ways.intersection(way_ids):
                continue  # al gedekt door een bekende klim
            # goedkope prefilter: 3 hoogtesamples voor de dure profielstap
            e = [dem.elevation(*merged[0]), dem.elevation(*geo.midpoint(merged)), dem.elevation(*merged[-1])]
            if any(v is None for v in e) or max(e) - min(e) < min_gain * 0.6:
                continue
            n_profiled += 1
            seg = _best_segment(merged)
            if not seg:
                continue
            kern_geom, gain_m, kern_m, foot_i, top_i = seg
            geom, extension_warnings = _extend_to_junctions(
                merged, merged_refs, foot_i, top_i, extract["junction_refs"]
            )
            kern_van, kern_tot = _core_indices(
                geom, merged[foot_i], merged[top_i]
            )
            length = geo.path_length(geom)
            avg = gain_m / kern_m * 100 if kern_m else 0
            if gain_m < min_gain or avg < min_avg:
                continue
            max_pct = _max_gradient(kern_geom)
            town = _nearest_place(extract["places"], *geo.midpoint(geom))
            surfaces = {w[3].get("surface", "") for w in ways if w[0] in way_ids}
            cid = f"auto-{_slug(name)}"
            if cid in auto:
                cid = f"{cid}-{len([k for k in auto if k.startswith(cid)]) + 1}"
            auto[cid] = {
                "id": cid,
                "name": f"{name}",
                "town": town,
                "auto": True,
                "surface": sorted(s for s in surfaces if s) or None,
                "length_m": round(length),
                "kern_m": round(kern_m),
                "kern_van": kern_van,
                "kern_tot": kern_tot,
                "gain_m": round(gain_m, 1),
                "avg_pct": round(avg, 1),
                "max_pct": round(max_pct, 1),
                "ele_foot": round(dem.elevation(*geom[0]) or 0, 1),
                "ele_top": round(dem.elevation(*geom[-1]) or 0, 1),
                "foot": [round(geom[0][0], 6), round(geom[0][1], 6)],
                "top": [round(geom[-1][0], 6), round(geom[-1][1], 6)],
                "mid": [round(geo.midpoint(geom)[0], 6), round(geo.midpoint(geom)[1], 6)],
                "geom": [[round(a, 6), round(b, 6)] for a, b in geom],
                "osm_way_ids": way_ids,
                "warnings": extension_warnings,
            }

    data["auto"] = auto
    with open(config.CLIMBS_JSON, "w") as f:
        json.dump(data, f, ensure_ascii=False)
    print(f"[climbs] {n_profiled} kandidaten geprofileerd, {len(auto)} auto-klimmen", file=sys.stderr)
    return data


def load() -> dict:
    if not config.CLIMBS_JSON.exists():
        raise RuntimeError("klim-database ontbreekt — draai eerst `lus build`")
    with open(config.CLIMBS_JSON) as f:
        return json.load(f)


def all_climbs() -> dict:
    """Bekende + auto-gedetecteerde klimmen in één pool."""
    data = load()
    merged = dict(data["climbs"])
    merged.update(data.get("auto", {}))
    return merged


def summary(c: dict) -> dict:
    out = {k: c[k] for k in ("id", "name", "town", "length_m", "gain_m", "avg_pct", "max_pct", "warnings")}
    if "kern_m" in c:
        out["kern_m"] = c["kern_m"]
    if c.get("auto"):
        out["auto"] = True
    if c.get("surface"):
        out["surface"] = c["surface"]
    return out
