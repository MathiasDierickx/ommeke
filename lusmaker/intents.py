"""Composiet-intenties met compacte, LLM-gerichte route-output."""

from __future__ import annotations

import difflib
import re
import unicodedata
from pathlib import Path

from . import climbs, config, draft, gpx, preview


class IntentError(RuntimeError):
    """Gebruikersfout bij het uitvoeren van een composiet-intentie."""


ACTIVITY_PROFILES = {"fietsen": "quiet", "trail": "trail"}


def _normalise(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", value))


def _climb_names(climb: dict) -> set[str]:
    return {
        value
        for value in (
            _normalise(str(climb.get("id", ""))),
            _normalise(str(climb.get("name", ""))),
        )
        if value
    }


def match_climb(name: str, climb_db: dict) -> dict:
    """Match exact, daarna op prefix en pas daarna op substring."""
    query = _normalise(name)
    if not query:
        raise IntentError("klimnaam mag niet leeg zijn")

    ranked = (
        [climb for climb in climb_db.values() if query in _climb_names(climb)],
        [
            climb
            for climb in climb_db.values()
            if any(candidate.startswith(query) for candidate in _climb_names(climb))
        ],
        [
            climb
            for climb in climb_db.values()
            if any(query in candidate for candidate in _climb_names(climb))
        ],
    )
    for matches in ranked:
        unique = {climb["id"]: climb for climb in matches}
        if len(unique) == 1:
            return next(iter(unique.values()))
        if unique:
            candidates = sorted(
                (climb.get("name") or climb["id"] for climb in unique.values()),
                key=str.casefold,
            )[:3]
            raise IntentError(
                f"klimnaam '{name}' is niet eenduidig; kandidaten: "
                + ", ".join(candidates)
            )

    choices = {
        climb["id"]: climb.get("name") or climb["id"]
        for climb in climb_db.values()
    }
    close_ids = difflib.get_close_matches(
        query,
        list(choices),
        n=3,
        cutoff=0,
    )
    if len(close_ids) < 3:
        remaining = sorted(
            (climb for climb in climb_db.values() if climb["id"] not in close_ids),
            key=lambda climb: (
                -difflib.SequenceMatcher(
                    None, query, _normalise(climb.get("name") or climb["id"])
                ).ratio(),
                climb["id"],
            ),
        )
        close_ids.extend(climb["id"] for climb in remaining[: 3 - len(close_ids)])
    suggestions = [choices[climb_id] for climb_id in close_ids]
    suffix = f"; bedoelde je: {', '.join(suggestions)}?" if suggestions else ""
    raise IntentError(f"onbekende klim '{name}'{suffix}")


def climb_label(climb: dict) -> str:
    length_km = climb.get("length_m", 0) / 1000
    average = climb.get("avg_pct", 0)
    return f"{climb.get('name') or climb['id']} ({length_km:.1f} km @ {average:g}%)"


def quality_label(quality: dict) -> str:
    if quality.get("error"):
        return f"kwaliteit niet beschikbaar: {quality['error']}"
    crossings = quality.get("kruisingen", quality.get("steenweg_kruisingen", 0))
    parts = [
        f"{quality.get('kassei_m', 0):g} m kassei",
        f"{quality.get('steenweg_m', 0) / 1000:.1f} km steenweg",
        f"{crossings:g} kruisingen",
    ]
    if quality.get("populair_pct") is not None:
        parts.append(f"{quality['populair_pct']:g}% populaire wegen")
    return " · ".join(parts)


def summary_sentence(d: dict) -> str:
    computed = d["computed"]
    start = (d.get("start") or {}).get("label") or "het startpunt"
    km = f"{computed['total_km']:.1f}".replace(".", ",")
    sentence = (
        f"Lus vanuit {start}: {km} km / +{computed['ascend_m']:g} hm "
        f"langs {len(d.get('climbs', []))} klimmen"
    )
    if d.get("avoid_cobbles"):
        sentence += "; kasseien vermeden"
    return sentence + "."


def compact_result(d: dict, climb_db: dict, files: dict) -> dict:
    computed = d.get("computed")
    if not computed:
        raise IntentError("route heeft nog geen berekening")
    return {
        "draft": d["id"],
        "km": computed["total_km"],
        "hoogtemeters": computed["ascend_m"],
        "klimmen": [
            climb_label(climb_db[climb_id])
            for climb_id in d.get("climbs", [])
            if climb_id in climb_db
        ],
        "kwaliteit": quality_label(computed.get("kwaliteit") or {}),
        "bestanden": files,
        "samenvatting": summary_sentence(d),
        "vervolg": [
            "suggest_climbs voor extra klimmen (tot +8 km)",
            "adjust_route om te wijzigen",
        ],
    }


def _export_files(
    d: dict,
    climb_db: dict,
    *,
    export_gpx_fn=gpx.export,
    export_preview_fn=preview.export,
    exports_root: Path | None = None,
) -> dict:
    output_dir = (exports_root or config.home_path() / "exports") / d["id"]
    output_dir.mkdir(parents=True, exist_ok=True)
    gpx_path = output_dir / "route.gpx"
    preview_path = output_dir / "preview.html"
    export_gpx_fn(d, climb_db, str(gpx_path))
    export_preview_fn(d, climb_db, str(preview_path))
    return {"gpx": str(gpx_path), "preview": str(preview_path)}


def _resolve_climbs(names: list[str], climb_db: dict) -> list[dict]:
    resolved = []
    seen = set()
    for name in names:
        climb = match_climb(name, climb_db)
        if climb["id"] not in seen:
            resolved.append(climb)
            seen.add(climb["id"])
    return resolved


def plan_route(
    start: str,
    region: str | None = None,
    max_km: float | None = None,
    doel: str = "hoogtemeters",
    via_klimmen: list[str] = [],
    vermijd_plaatsen: list[str] = [],
    kasseien: bool = False,
    beton_vermijden: bool = True,
    strict: bool = False,
    naam: str | None = None,
    activiteit: str = "fietsen",
    geen_opvulling: bool = False,
    profiel_naam: str | None = None,
    *,
    create_fn=draft.create,
    load_fn=draft.load,
    add_climb_fn=draft.add_climb,
    avoid_place_fn=draft.avoid_place,
    route_fn=draft.route,
    optimize_fn=draft.optimize,
    climbs_fn=climbs.all_climbs,
    export_gpx_fn=gpx.export,
    export_preview_fn=preview.export,
    exports_root: Path | None = None,
) -> dict:
    """Maak, routeer en exporteer een lus in één intentie."""
    if doel not in {"hoogtemeters", "kort", "toeren"}:
        raise IntentError("doel moet 'hoogtemeters', 'kort' of 'toeren' zijn")
    if activiteit not in ACTIVITY_PROFILES:
        raise IntentError("activiteit moet 'fietsen' of 'trail' zijn")
    create_kwargs = dict(
        start=start,
        name=naam,
        strict=strict,
        avoid_cobbles=not kasseien,
        avoid_concrete=beton_vermijden,
        region=region,
        profile=ACTIVITY_PROFILES[activiteit],
    )
    if profiel_naam is not None:
        create_kwargs["profile_doc"] = profiel_naam
    created = create_fn(**create_kwargs)
    draft_id = created.get("id") or created.get("draft")
    d = load_fn(draft_id)
    with draft.region_scope(d):
        climb_db = climbs_fn()
        for place in vermijd_plaatsen:
            avoid_place_fn(draft_id, place)
        for climb in _resolve_climbs(via_klimmen, climb_db):
            add_climb_fn(draft_id, climb["id"])
        d = load_fn(draft_id)
        if doel == "hoogtemeters" and max_km is not None:
            optimize_fn(
                d,
                climb_db,
                max_km=max_km,
                fill=not geen_opvulling,
            )
        else:
            route_fn(d, climb_db)
        d = load_fn(draft_id)
        files = _export_files(
            d,
            climb_db,
            export_gpx_fn=export_gpx_fn,
            export_preview_fn=export_preview_fn,
            exports_root=exports_root,
        )
    return compact_result(d, climb_db, files)


def adjust_route(
    draft_id: str,
    voeg_klimmen_toe: list[str] = [],
    verwijder_klimmen: list[str] = [],
    vermijd_plaatsen: list[str] = [],
    niet_meer_vermijden: list[str] = [],
    max_km: float | None = None,
    *,
    load_fn=draft.load,
    add_climb_fn=draft.add_climb,
    remove_climb_fn=draft.remove_climb,
    avoid_place_fn=draft.avoid_place,
    unavoid_place_fn=draft.unavoid_place,
    route_fn=draft.route,
    optimize_fn=draft.optimize,
    climbs_fn=climbs.all_climbs,
    export_gpx_fn=gpx.export,
    export_preview_fn=preview.export,
    exports_root: Path | None = None,
) -> dict:
    """Pas meerdere routewensen toe, routeer eenmaal en exporteer opnieuw."""
    d = load_fn(draft_id)
    with draft.region_scope(d):
        climb_db = climbs_fn()
        for climb in _resolve_climbs(verwijder_klimmen, climb_db):
            remove_climb_fn(draft_id, climb["id"])
        for climb in _resolve_climbs(voeg_klimmen_toe, climb_db):
            add_climb_fn(draft_id, climb["id"])
        for place in vermijd_plaatsen:
            avoid_place_fn(draft_id, place)
        for place in niet_meer_vermijden:
            unavoid_place_fn(draft_id, place)
        d = load_fn(draft_id)
        if max_km is not None:
            optimize_fn(d, climb_db, max_km=max_km)
        else:
            route_fn(d, climb_db)
        d = load_fn(draft_id)
        files = _export_files(
            d,
            climb_db,
            export_gpx_fn=export_gpx_fn,
            export_preview_fn=export_preview_fn,
            exports_root=exports_root,
        )
    return compact_result(d, climb_db, files)


def route_details(draft_id: str, *, load_fn=draft.load) -> dict:
    """Geef legs en volledige kwaliteitsmetrieken van een gerouteerde draft."""
    d = load_fn(draft_id)
    computed = d.get("computed")
    if not computed:
        raise IntentError(
            f"draft '{draft_id}' heeft nog geen berekende route; routeer eerst"
        )
    return {
        "draft": d["id"],
        "km": computed["total_km"],
        "hoogtemeters": computed["ascend_m"],
        "legs": computed.get("legs", []),
        "kwaliteit": computed.get("kwaliteit", {}),
    }
