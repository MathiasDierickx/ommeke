"""Composiet-intenties met compacte, LLM-gerichte route-output."""

from __future__ import annotations

import copy
import difflib
import re
import unicodedata
from pathlib import Path

from . import artifacts, climbs, config, draft, gpx, preview, profiles, readiness


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


def constraint_report(d: dict, request: dict | None = None) -> dict:
    """Maak streefafstand en hard budget expliciet controleerbaar."""
    request = request or d.get("route_request") or {}
    computed = d.get("computed") or {}
    actual = computed.get("total_km")
    target = request.get("target_km")
    tolerance = request.get("tolerance_km", 2.5)
    hard_max = request.get("max_km")
    within_target = (
        None
        if target is None or actual is None
        else abs(actual - target) <= tolerance
    )
    within_max = (
        None if hard_max is None or actual is None else actual <= hard_max
    )
    checks = [check for check in (within_target, within_max) if check is not None]
    warnings = []
    if within_target is False:
        warnings.append(
            f"route wijkt {abs(actual - target):.1f} km af van de doelafstand"
        )
    if within_max is False:
        warnings.append(
            f"route overschrijdt het harde maximum met {actual - hard_max:.1f} km"
        )
    return {
        "doel": request.get("doel"),
        "doel_km": target,
        "tolerantie_km": tolerance if target is not None else None,
        "minimum_km": target - tolerance if target is not None else None,
        "maximum_km": hard_max,
        "werkelijk_km": actual,
        "binnen_doelbereik": within_target,
        "binnen_maximum": within_max,
        "voldaan": all(checks) if checks else None,
        "waarschuwingen": warnings,
    }


def compact_result(
    d: dict, climb_db: dict, files: dict, request: dict | None = None
) -> dict:
    computed = d.get("computed")
    if not computed:
        raise IntentError("route heeft nog geen berekening")
    return {
        "status": "ready",
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
        "artifacts": artifacts.describe_all(d["id"]),
        "constraints": constraint_report(d, request),
    }


def _validate_request(
    *, target_km: float | None, max_km: float | None, tolerance_km: float
) -> None:
    if target_km is not None and target_km <= 0:
        raise IntentError("target-km moet groter dan 0 zijn")
    if max_km is not None and max_km <= 0:
        raise IntentError("max-km moet groter dan 0 zijn")
    if tolerance_km < 0:
        raise IntentError("tolerance-km mag niet negatief zijn")
    if target_km is not None and max_km is not None and target_km > max_km:
        raise IntentError("target-km mag max-km niet overschrijden")


def _route_request(
    *,
    doel: str,
    target_km: float | None,
    max_km: float | None,
    tolerance_km: float,
    geen_opvulling: bool,
    profiel_naam: str | None,
    activiteit: str,
    kasseien: bool | None,
    beton_vermijden: bool | None,
    strict: bool | None,
) -> dict:
    hard_max = max_km
    if target_km is not None and hard_max is None:
        hard_max = target_km + tolerance_km
    explicit_preferences = {}
    if kasseien is not None:
        explicit_preferences["kasseien"] = "ok" if kasseien else "vermijd"
    if beton_vermijden is not None:
        explicit_preferences["beton"] = "vermijd" if beton_vermijden else "ok"
    if strict is not None:
        explicit_preferences["steenwegen"] = "vermijd" if strict else "ok"
    return {
        "doel": doel,
        "target_km": target_km,
        "max_km": hard_max,
        "max_km_explicit": max_km is not None,
        "tolerance_km": tolerance_km,
        "geen_opvulling": geen_opvulling,
        "profiel_naam": profiel_naam,
        "activiteit": activiteit,
        "expliciete_voorkeuren": explicit_preferences,
        "toegestane_plaatsen": [],
    }


def _profile_for_request(request: dict, profile_load_fn) -> dict:
    profile = copy.deepcopy(profile_load_fn(request["profiel_naam"]))
    profile["activiteit"] = request["activiteit"]
    profile["voorkeuren"].update(request.get("expliciete_voorkeuren") or {})
    return profile


def _needs_input(
    d: dict,
    climb_db: dict,
    request: dict,
    *,
    probe_fn,
    assess_fn,
    profile_load_fn,
) -> dict | None:
    probe_fn(d, climb_db)
    assessment = assess_fn(
        d, _profile_for_request(request, profile_load_fn), climb_db
    )
    if assessment["klaar"]:
        return None
    return {
        "status": "needs_input",
        "draft": d["id"],
        "profiel": assessment["profiel"],
        "onbekend": assessment["onbekend"],
        "vragen": assessment["vragen"],
        "advies": assessment["advies"],
        "constraints": constraint_report(d, request),
        "next_action": {
            "antwoord_profielvragen_met": "update_profile",
            "antwoord_plaatsvragen_met": "adjust_route",
            "ga_daarna_verder_met": "adjust_route",
            "draft_id": d["id"],
        },
    }


def _execute_request(
    d: dict,
    climb_db: dict,
    request: dict,
    *,
    route_fn,
    optimize_fn,
) -> None:
    goal = request["doel"]
    target_km = request.get("target_km")
    hard_max = request.get("max_km")
    if goal == "kort" or hard_max is None:
        route_fn(d, climb_db)
        actual = (d.get("computed") or {}).get("total_km")
        if hard_max is not None and actual is not None and actual > hard_max:
            raise IntentError(
                f"kortste route is {actual:.1f} km en overschrijdt het harde "
                f"maximum van {hard_max:.1f} km"
            )
        return

    optimize_kwargs = {
        "max_km": hard_max,
        "fill": not request["geen_opvulling"],
    }
    if goal == "toeren":
        optimize_kwargs["objective"] = "toeren"
    if target_km is not None:
        optimize_kwargs["fill_target_km"] = target_km
    optimize_fn(d, climb_db, **optimize_kwargs)


def _export_files(
    d: dict,
    climb_db: dict,
    *,
    export_gpx_fn=gpx.export,
    export_preview_fn=preview.export,
    exports_root: Path | None = None,
) -> dict:
    output_dir = (exports_root or artifacts.root()) / d["id"]
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
    target_km: float | None = None,
    tolerance_km: float = 2.5,
    doel: str = "hoogtemeters",
    via_klimmen: list[str] = [],
    vermijd_plaatsen: list[str] = [],
    kasseien: bool | None = False,
    beton_vermijden: bool | None = True,
    strict: bool | None = False,
    naam: str | None = None,
    activiteit: str = "fietsen",
    geen_opvulling: bool = False,
    profiel_naam: str | None = None,
    check_readiness: bool = False,
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
    save_fn=draft.save,
    probe_fn=draft.probe,
    assess_fn=readiness.assess,
    profile_load_fn=profiles.load,
    exports_root: Path | None = None,
) -> dict:
    """Maak en routeer een lus, eventueel na een readiness-gesprek."""
    if doel not in {"hoogtemeters", "kort", "toeren"}:
        raise IntentError("doel moet 'hoogtemeters', 'kort' of 'toeren' zijn")
    if activiteit not in ACTIVITY_PROFILES:
        raise IntentError("activiteit moet 'fietsen' of 'trail' zijn")
    _validate_request(
        target_km=target_km,
        max_km=max_km,
        tolerance_km=tolerance_km,
    )
    if doel == "toeren" and target_km is None and max_km is None:
        raise IntentError("doel 'toeren' vereist target-km of max-km")
    if doel == "hoogtemeters" and not via_klimmen and target_km is None and max_km is None:
        raise IntentError(
            "een lege hoogtemeterlus vereist target-km, max-km of een via-klim"
        )
    request = _route_request(
        doel=doel,
        target_km=target_km,
        max_km=max_km,
        tolerance_km=tolerance_km,
        geen_opvulling=geen_opvulling,
        profiel_naam=profiel_naam,
        activiteit=activiteit,
        kasseien=kasseien,
        beton_vermijden=beton_vermijden,
        strict=strict,
    )
    create_kwargs = dict(
        start=start,
        name=naam,
        strict=bool(strict),
        avoid_cobbles=kasseien is False,
        avoid_concrete=beton_vermijden is True,
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
        d["route_request"] = request
        save_fn(d)
        if check_readiness:
            if profiel_naam is None:
                raise IntentError(
                    "readiness vereist een profiel-naam, bijvoorbeeld 'standaard'"
                )
            needs_input = _needs_input(
                d,
                climb_db,
                request,
                probe_fn=probe_fn,
                assess_fn=assess_fn,
                profile_load_fn=profile_load_fn,
            )
            if needs_input is not None:
                return needs_input
        _execute_request(
            d,
            climb_db,
            request,
            route_fn=route_fn,
            optimize_fn=optimize_fn,
        )
        d = load_fn(draft_id)
        files = _export_files(
            d,
            climb_db,
            export_gpx_fn=export_gpx_fn,
            export_preview_fn=export_preview_fn,
            exports_root=exports_root,
        )
    return compact_result(d, climb_db, files, request)


def adjust_route(
    draft_id: str,
    voeg_klimmen_toe: list[str] = [],
    verwijder_klimmen: list[str] = [],
    vermijd_plaatsen: list[str] = [],
    niet_meer_vermijden: list[str] = [],
    sta_plaatsen_toe: list[str] = [],
    max_km: float | None = None,
    target_km: float | None = None,
    tolerance_km: float | None = None,
    doel: str | None = None,
    geen_opvulling: bool | None = None,
    profiel_naam: str | None = None,
    check_readiness: bool = False,
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
    save_fn=draft.save,
    probe_fn=draft.probe,
    assess_fn=readiness.assess,
    profile_load_fn=profiles.load,
    exports_root: Path | None = None,
) -> dict:
    """Pas meerdere routewensen toe, routeer eenmaal en exporteer opnieuw."""
    d = load_fn(draft_id)
    previous_request = d.get("route_request") or {}
    effective_target = (
        target_km if target_km is not None else previous_request.get("target_km")
    )
    effective_tolerance = (
        tolerance_km
        if tolerance_km is not None
        else previous_request.get("tolerance_km", 2.5)
    )
    if max_km is not None:
        effective_max = max_km
        max_is_explicit = True
    elif target_km is not None and not previous_request.get("max_km_explicit", False):
        effective_max = target_km + effective_tolerance
        max_is_explicit = False
    elif (
        tolerance_km is not None
        and effective_target is not None
        and not previous_request.get("max_km_explicit", False)
    ):
        effective_max = effective_target + effective_tolerance
        max_is_explicit = False
    else:
        effective_max = previous_request.get("max_km")
        max_is_explicit = previous_request.get("max_km_explicit", False)
    effective_goal = doel or previous_request.get("doel", "hoogtemeters")
    effective_profile = (
        profiel_naam
        if profiel_naam is not None
        else previous_request.get("profiel_naam")
    )
    effective_no_fill = (
        geen_opvulling
        if geen_opvulling is not None
        else previous_request.get("geen_opvulling", False)
    )
    _validate_request(
        target_km=effective_target,
        max_km=effective_max,
        tolerance_km=effective_tolerance,
    )
    if effective_goal not in {"hoogtemeters", "kort", "toeren"}:
        raise IntentError("doel moet 'hoogtemeters', 'kort' of 'toeren' zijn")
    request = {
        **previous_request,
        "doel": effective_goal,
        "target_km": effective_target,
        "max_km": effective_max,
        "max_km_explicit": max_is_explicit,
        "tolerance_km": effective_tolerance,
        "geen_opvulling": effective_no_fill,
        "profiel_naam": effective_profile,
        "activiteit": previous_request.get("activiteit", "fietsen"),
        "expliciete_voorkeuren": previous_request.get(
            "expliciete_voorkeuren", {}
        ),
        "toegestane_plaatsen": sorted(
            {
                *previous_request.get("toegestane_plaatsen", []),
                *(place.strip() for place in sta_plaatsen_toe if place.strip()),
            },
            key=str.casefold,
        ),
    }
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
        d["route_request"] = request
        save_fn(d)
        if check_readiness:
            if effective_profile is None:
                raise IntentError(
                    "readiness vereist een profiel-naam, bijvoorbeeld 'standaard'"
                )
            needs_input = _needs_input(
                d,
                climb_db,
                request,
                probe_fn=probe_fn,
                assess_fn=assess_fn,
                profile_load_fn=profile_load_fn,
            )
            if needs_input is not None:
                return needs_input
        _execute_request(
            d,
            climb_db,
            request,
            route_fn=route_fn,
            optimize_fn=optimize_fn,
        )
        d = load_fn(draft_id)
        files = _export_files(
            d,
            climb_db,
            export_gpx_fn=export_gpx_fn,
            export_preview_fn=export_preview_fn,
            exports_root=exports_root,
        )
    return compact_result(d, climb_db, files, request)


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
