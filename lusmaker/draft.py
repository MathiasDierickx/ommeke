"""Draft-routes: opbouwen, routeren (met lus-constraint), suggesties, opslag."""
import json
import time
import uuid

from . import climbs as climbs_mod
from . import config, geo, gh


class DraftError(RuntimeError):
    pass


def _path(draft_id: str):
    return config.DRAFTS / f"{draft_id}.json"


def load(draft_id: str) -> dict:
    p = _path(draft_id)
    if not p.exists():
        raise DraftError(f"draft '{draft_id}' bestaat niet — zie `lus draft list`")
    with open(p) as f:
        return json.load(f)


def save(d: dict) -> None:
    config.ensure_dirs()
    with open(_path(d["id"]), "w") as f:
        json.dump(d, f, ensure_ascii=False)


def new(start: dict, name: str | None, loop: bool, end: dict | None) -> dict:
    d = {
        "id": uuid.uuid4().hex[:6],
        "name": name or "lus",
        "created": time.strftime("%Y-%m-%d %H:%M"),
        "start": start,  # {lat, lon, label}
        "end": end,      # None => zelfde als start bij loop
        "loop": loop,
        "climbs": [],    # geordende lijst klim-ids
        "computed": None,
    }
    save(d)
    return d


def list_all() -> list[dict]:
    out = []
    for p in sorted(config.DRAFTS.glob("*.json")):
        with open(p) as f:
            d = json.load(f)
        out.append(
            {
                "id": d["id"],
                "name": d["name"],
                "start": d["start"].get("label"),
                "loop": d["loop"],
                "climbs": d["climbs"],
                "total_km": (d.get("computed") or {}).get("total_km"),
            }
        )
    return out


def _waypoints(d: dict, climb_db: dict) -> list[dict]:
    """Reeks legs; een klim-leg krijgt [voet, midden, top] zodat de route
    effectief de helling zelf omhoog rijdt."""
    start = (d["start"]["lat"], d["start"]["lon"])
    legs = []
    prev_label, prev_pt = "start", start
    for cid in d["climbs"]:
        c = climb_db.get(cid)
        if not c:
            raise DraftError(f"klim '{cid}' niet in database (zie `lus climbs list`)")
        foot, mid, top = tuple(c["foot"]), tuple(c["mid"]), tuple(c["top"])
        legs.append({"from": prev_label, "to": f"{c['name']} (voet)", "points": [prev_pt, foot]})
        legs.append({"from": f"{c['name']} (voet)", "to": f"{c['name']} (top)",
                     "points": [foot, mid, top], "climb": cid})
        prev_label, prev_pt = f"{c['name']} (top)", top
    if d["loop"]:
        legs.append({"from": prev_label, "to": "start", "points": [prev_pt, start]})
    elif d.get("end"):
        end = (d["end"]["lat"], d["end"]["lon"])
        legs.append({"from": prev_label, "to": d["end"].get("label", "einde"), "points": [prev_pt, end]})
    return legs


def route(d: dict, climb_db: dict) -> dict:
    """Routeer alle legs; elke leg vermijdt de corridor van de vorige legs."""
    legs = _waypoints(d, climb_db)
    if not legs:
        raise DraftError("draft heeft geen doel: voeg een klim toe of zet een eindpunt")

    start_pt = (d["start"]["lat"], d["start"]["lon"])
    protect = [start_pt]
    avoid = []
    computed_legs = []
    total_m = ascend = descend = 0.0

    for leg in legs:
        is_climb = "climb" in leg
        # klim-legs niet blokkeren door de eigen corridor: zonder avoid routen
        res = gh.route(leg["points"], avoid_polygons=None if is_climb else avoid)
        coords_latlon = [(c[0], c[1]) for c in res["coords"]]
        seg_len = max(1500.0, res["distance_m"] / 25.0)
        avoid.extend(
            geo.corridor_polygons(coords_latlon, seg_len_m=seg_len, protect=protect)
        )
        total_m += res["distance_m"]
        ascend += res["ascend_m"]
        descend += res["descend_m"]
        computed_legs.append(
            {
                "from": leg["from"],
                "to": leg["to"],
                "km": round(res["distance_m"] / 1000, 2),
                "ascend_m": res["ascend_m"],
                "climb": leg.get("climb"),
                "coords": [[round(a, 6), round(b, 6), (round(e, 1) if e is not None else None)] for a, b, e in res["coords"]],
            }
        )

    d["computed"] = {
        "routed_at": time.strftime("%Y-%m-%d %H:%M"),
        "total_km": round(total_m / 1000, 1),
        "ascend_m": round(ascend),
        "descend_m": round(descend),
        "legs": [
            {k: v for k, v in leg.items() if k != "coords"} for leg in computed_legs
        ],
    }
    d["_geometry"] = [leg["coords"] for leg in computed_legs]
    save(d)
    return summary(d)


def summary(d: dict) -> dict:
    out = {
        "id": d["id"],
        "name": d["name"],
        "start": d["start"].get("label"),
        "loop": d["loop"],
        "climbs": d["climbs"],
        "computed": d.get("computed"),
    }
    return out


def suggest(d: dict, climb_db: dict, max_detour_km: float = 10.0, limit: int = 5) -> list[dict]:
    """Klimmen dicht bij de huidige route, gerangschikt op extra kilometers."""
    if not d.get("computed") or not d.get("_geometry"):
        raise DraftError("routeer eerst: `lus draft route <id>`")

    legs_geo = d["_geometry"]
    legs_meta = d["computed"]["legs"]

    candidates = []
    for cid, c in climb_db.items():
        if cid in d["climbs"]:
            continue
        foot = tuple(c["foot"])
        top = tuple(c["top"])
        best = None
        for i, (meta, coords) in enumerate(zip(legs_meta, legs_geo)):
            if meta.get("climb"):
                continue  # niet invoegen midden in een andere klim
            a = tuple(coords[0][:2])
            b = tuple(coords[-1][:2])
            est = (
                geo.haversine(a[0], a[1], foot[0], foot[1])
                + c["length_m"]
                + geo.haversine(top[0], top[1], b[0], b[1])
                - meta["km"] * 1000
            )
            if best is None or est < best[0]:
                best = (est, i, a, b)
        if best and best[0] / 1000 <= max_detour_km * 1.5:
            candidates.append((best[0], cid, c, best[1], best[2], best[3]))

    candidates.sort()
    out = []
    for _est, cid, c, leg_i, a, b in candidates[:8]:
        try:
            r1 = gh.route([a, tuple(c["foot"])])
            r2 = gh.route([tuple(c["foot"]), tuple(c["mid"]), tuple(c["top"])])
            r3 = gh.route([tuple(c["top"]), b])
        except gh.GhError:
            continue
        base = legs_meta[leg_i]["km"] * 1000
        extra_m = r1["distance_m"] + r2["distance_m"] + r3["distance_m"] - base
        extra_up = r1["ascend_m"] + r2["ascend_m"] + r3["ascend_m"] - legs_meta[leg_i]["ascend_m"]
        if extra_m / 1000 > max_detour_km:
            continue
        # positie in de klim-volgorde: aantal klimmen vóór deze leg
        pos = sum(1 for m in legs_meta[:leg_i] if m.get("climb"))
        out.append(
            {
                "climb": climbs_mod.summary(c),
                "extra_km": round(extra_m / 1000, 1),
                "extra_hoogtemeters": round(extra_up),
                "invoegen_op_positie": pos,
                "voorstel": f"lus draft add-climb {d['id']} {cid} --at {pos}",
            }
        )
        if len(out) >= limit:
            break
    out.sort(key=lambda s: s["extra_km"])
    return out
