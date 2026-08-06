"""Gedeelde scenario-, fixture- en invariantlogica voor T9."""
import copy
import gzip
import json
import math
import os
from pathlib import Path

from lusmaker import config, geo


SCENARIOS = ("berendries_quiet", "trail_offroad", "zottegem_avoid")
FIXTURES = Path(__file__).with_name("fixtures")


def fixture_path(name: str) -> Path:
    return FIXTURES / f"{name}.json.gz"


def load_fixture(name: str) -> dict:
    with gzip.open(fixture_path(name), "rt", encoding="utf-8") as handle:
        return json.load(handle)


def write_fixture(name: str, fixture: dict) -> Path:
    path = fixture_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        fixture,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    with open(path, "wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as zipped:
            zipped.write(encoded)
    return path


def _base_draft(name: str, start: dict, *, profile: str = "quiet") -> dict:
    return {
        "id": f"reg-{name.replace('_', '-')}",
        "name": name,
        "created": "cassette",
        "region": config.current_region().slug,
        "start": copy.deepcopy(start),
        "end": None,
        "loop": True,
        "profile": profile,
        "strict": False,
        "avoid_cobbles": False,
        "avoid_concrete": False,
        "avoid_places": [],
        "climbs": [],
        "opvullingen": [],
        "computed": None,
    }


def _trail_source_draft() -> dict:
    """Vind de bestaande, handmatig gekalibreerde trail-offroad-draft."""
    requested_id = os.environ.get("LUSMAKER_TRAIL_DRAFT_ID")
    drafts = []
    for path in sorted(config.DRAFTS.glob("*.json")):
        with open(path, encoding="utf-8") as handle:
            candidate = json.load(handle)
        if requested_id and candidate.get("id") == requested_id:
            return candidate
        computed = candidate.get("computed") or {}
        if (
            candidate.get("profile") == "trail"
            and candidate.get("loop")
            and candidate.get("climbs")
            and 6 <= computed.get("total_km", 0) <= 9
        ):
            drafts.append(candidate)
    named = [
        candidate
        for candidate in drafts
        if "trail" in candidate.get("name", "").lower()
        and "offroad" in candidate.get("name", "").lower()
    ]
    if len(named) == 1:
        return named[0]
    if len(drafts) == 1:
        return drafts[0]
    detail = (
        f"{len(drafts)} passende drafts gevonden"
        if drafts
        else "geen passende draft gevonden"
    )
    raise RuntimeError(
        f"{detail}; zet LUSMAKER_TRAIL_DRAFT_ID op de id van de bestaande "
        "Wetteren trail-offroad-draft"
    )


def recording_scenarios() -> dict[str, tuple[dict, dict]]:
    """Bouw scenario-inputs uit de lokale default-regio voor handmatige opname."""
    from lusmaker import climbs, geocode

    wetteren, _alternatives = geocode.resolve("Wetteren")
    zottegem, _alternatives = geocode.resolve("Zottegem")
    climb_db = climbs.all_climbs()
    if "berendries" not in climb_db:
        raise RuntimeError("klim 'berendries' ontbreekt in de default-regio")

    quiet = _base_draft("berendries_quiet", wetteren)
    quiet["climbs"] = ["berendries"]

    avoid = _base_draft("zottegem_avoid", wetteren)
    avoid["climbs"] = ["berendries"]
    avoid["avoid_places"] = [
        {
            "label": zottegem["label"],
            "lat": zottegem["lat"],
            "lon": zottegem["lon"],
            "radius_km": 2.5,
            "factor": 0.35,
        }
    ]

    trail = copy.deepcopy(_trail_source_draft())
    trail["id"] = "reg-trail-offroad"
    trail["name"] = "trail_offroad"
    trail["computed"] = None
    trail.pop("_geometry", None)

    scenario_drafts = {
        "berendries_quiet": quiet,
        "trail_offroad": trail,
        "zottegem_avoid": avoid,
    }
    out = {}
    for name, scenario_draft in scenario_drafts.items():
        used = {}
        for climb_id in scenario_draft.get("climbs", []):
            try:
                used[climb_id] = copy.deepcopy(climb_db[climb_id])
            except KeyError as exc:
                raise RuntimeError(
                    f"klim '{climb_id}' uit scenario {name} ontbreekt in de klimdatabase"
                ) from exc
        out[name] = (scenario_draft, used)
    return out


def _quality(routed: dict) -> dict:
    return (routed.get("computed") or {}).get("kwaliteit") or {}


def metrics(name: str, routed: dict) -> dict:
    computed = routed.get("computed") or {}
    quality = _quality(routed)
    out = {
        "km": computed.get("total_km"),
        "hm": computed.get("ascend_m"),
        "heen_en_weer_m": quality.get("heen_en_weer_m"),
        "kassei_m": quality.get("kassei_m"),
        "offroad_pct": quality.get("offroad_pct"),
        "vermijd_marge_m": None,
    }
    if name == "zottegem_avoid" and routed.get("avoid_places"):
        place = routed["avoid_places"][0]
        points = [
            point
            for leg in routed.get("_geometry", [])
            for point in leg
        ]
        if points:
            minimum = min(
                geo.haversine(place["lat"], place["lon"], point[0], point[1])
                for point in points
            )
            out["vermijd_marge_m"] = round(
                minimum - place["radius_km"] * 1000
            )
    return out


def invariant_failures(name: str, routed: dict) -> list[str]:
    values = metrics(name, routed)
    missing = [
        key
        for key in ("km", "hm", "heen_en_weer_m", "kassei_m", "offroad_pct")
        if values[key] is None
    ]
    if missing:
        return [f"metrieken ontbreken: {', '.join(missing)}"]

    failures = []

    def require(condition: bool, message: str):
        if not condition:
            failures.append(message)

    if name == "berendries_quiet":
        require(54 <= values["km"] <= 64, "afstand niet binnen 54–64 km")
        require(600 <= values["hm"] <= 820, "hoogtemeters niet binnen 600–820 m")
        require(values["heen_en_weer_m"] < 300, "heen-en-weer is minstens 300 m")
        require(values["kassei_m"] < 200, "kassei is minstens 200 m")
    elif name == "trail_offroad":
        require(6 <= values["km"] <= 9, "afstand niet binnen 6–9 km")
        require(values["hm"] >= 80, "hoogtemeters zijn minder dan 80 m")
        require(values["heen_en_weer_m"] < 300, "heen-en-weer is minstens 300 m")
        require(values["offroad_pct"] >= 25, "offroad is minder dan 25%")
    elif name == "zottegem_avoid":
        require(values["km"] <= 70, "afstand is meer dan 70 km")
        require(
            values["vermijd_marge_m"] is not None
            and values["vermijd_marge_m"] >= -200,
            "route dringt meer dan 200 m binnen de Zottegem-cirkel",
        )
    else:
        raise ValueError(f"onbekend regressiescenario '{name}'")
    return failures


def format_metrics(rows: list[tuple[str, dict]]) -> str:
    headers = ("scenario", "km", "hm", "heen/weer", "kassei", "offroad", "vermijd")
    rendered = [headers]
    for name, values in rows:
        rendered.append(
            (
                name,
                _display(values["km"]),
                _display(values["hm"]),
                _display(values["heen_en_weer_m"]),
                _display(values["kassei_m"]),
                _display(values["offroad_pct"], suffix="%"),
                _display(values["vermijd_marge_m"]),
            )
        )
    widths = [max(len(str(row[i])) for row in rendered) for i in range(len(headers))]
    return "\n".join(
        "  ".join(str(value).ljust(widths[i]) for i, value in enumerate(row)).rstrip()
        for row in rendered
    )


def _display(value, suffix: str = "") -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return f"{value}{suffix}"
