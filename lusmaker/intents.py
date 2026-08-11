"""Composiet-intenties met compacte, LLM-gerichte route-output."""

from __future__ import annotations

import copy
import difflib
import re
import unicodedata
from pathlib import Path

from . import (
    artifacts,
    aws_state,
    climbs,
    config,
    draft,
    geocode,
    gpx,
    heat,
    preview,
    profiles,
    readiness,
)


class IntentError(RuntimeError):
    """Gebruikersfout bij het uitvoeren van een composiet-intentie."""


ACTIVITY_PROFILES = {"fietsen": "quiet", "trail": "trail"}
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
POI_NAMES = {
    "picknickbank": ("picknickbank", "picknickbanken"),
    "uitkijktoren": ("uitkijktoren", "uitkijktorens"),
    "zitbank": ("zitbank", "zitbanken"),
    "fietspomp_en_fietsherstel": (
        "fietspomp/herstelpunt",
        "fietspompen/herstelpunten",
    ),
    "fietsverhuur": ("fietsverhuurpunt", "fietsverhuurpunten"),
    "speeltuin": ("speeltuin", "speeltuinen"),
    "ebike": ("e-bikepunt", "e-bikepunten"),
    "toilet": ("toilet", "toiletten"),
}


def suggest_route_name(
    start: str,
    *,
    target_km: float | None,
    max_km: float | None,
    doel: str,
    activiteit: str,
) -> str:
    """Bouw een compacte fallbacknaam uit de gestructureerde routewens."""
    place = start.strip().split(",", 1)[0]
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", place) or not place:
        place = "je startpunt"
    if activiteit == "trail":
        kind = "Traillus"
    elif doel == "hoogtemeters":
        kind = "Heuvelrit"
    elif doel == "toeren":
        kind = "Rondrit"
    else:
        kind = "Fietslus"
    distance = target_km if target_km is not None else max_km
    suffix = f" · {distance:g} km" if distance is not None else ""
    return f"{kind} rond {place}{suffix}"[:80].rstrip()


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


def underway_label(poi_counts: dict) -> str:
    """Formatteer aanwezige POI-aantallen als één compacte Nederlandse regel."""
    parts = []
    ordered_types = [
        *POI_NAMES,
        *sorted(set(poi_counts) - set(POI_NAMES), key=str.casefold),
    ]
    for poi_type in ordered_types:
        count = int(poi_counts.get(poi_type, 0))
        if count <= 0:
            continue
        singular, plural = POI_NAMES.get(
            poi_type,
            (poi_type.replace("_", " "), f"{poi_type.replace('_', ' ')}s"),
        )
        if poi_type == "toilet" and count == 1:
            parts.append(singular)
        else:
            parts.append(f"{count} {singular if count == 1 else plural}")
    return ", ".join(parts)


def _route_poi_counts(d: dict, feature_selector) -> dict:
    terrain = ((d.get("_probe") or {}).get("terrein") or {})
    if "pois_langs_route" in terrain:
        return terrain["pois_langs_route"] or {}
    route_coords = [
        (point[0], point[1])
        for leg in d.get("_geometry", [])
        for point in leg
    ]
    if not route_coords:
        return {}
    with draft.region_scope(d):
        features = feature_selector(route_coords)
    counts = {}
    for poi in features["pois"]:
        poi_type = poi["type"]
        counts[poi_type] = counts.get(poi_type, 0) + 1
    return counts


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
    d: dict,
    climb_db: dict,
    files: dict,
    request: dict | None = None,
    *,
    feature_selector=heat.features_near_route,
) -> dict:
    computed = d.get("computed")
    if not computed:
        raise IntentError("route heeft nog geen berekening")
    result = {
        "status": "ready",
        "draft": d["id"],
        "revision": int(d.get("revision", 0)),
        "request_id": (request or d.get("route_request") or {}).get(
            "request_id"
        ),
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
    underway = underway_label(_route_poi_counts(d, feature_selector))
    if underway:
        result["onderweg"] = underway
    return result


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
    autovrij: bool | None,
    strict: bool | None,
    request_id: str | None,
    rond_plaats: str | None,
    input_signature: dict,
) -> dict:
    hard_max = max_km
    if target_km is not None and hard_max is None:
        hard_max = target_km + tolerance_km
    explicit_preferences = {}
    if kasseien is not None:
        explicit_preferences["kasseien"] = "ok" if kasseien else "vermijd"
    if beton_vermijden is not None:
        explicit_preferences["beton"] = "vermijd" if beton_vermijden else "ok"
    if autovrij is not None:
        explicit_preferences["autovrij"] = "belangrijk" if autovrij else "ok"
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
        "request_id": request_id,
        "rond_plaats": rond_plaats,
        "input_signature": input_signature,
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
        "revision": int(d.get("revision", 0)),
        "request_id": request.get("request_id"),
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
    max_explicit = request.get("max_km_explicit", True)
    if (goal == "kort" or hard_max is None) and not request.get("rond_plaats"):
        route_fn(d, climb_db)
        actual = (d.get("computed") or {}).get("total_km") or 0.0
        # Degenererende lus: een lus zonder klimmen of waypoints routeert tot
        # 0 km (start == eind). Is er een afstandsdoel, maak er dan een echte
        # round-trip-lus van i.p.v. een lege 0 km-route terug te geven. We
        # gebruiken 'toeren' zodat er puur een rondrit komt, zonder klim-hunting.
        wants_distance = target_km is not None or hard_max is not None
        if d.get("loop") and not d.get("climbs") and wants_distance and actual < 0.3:
            fill_target = target_km if target_km is not None else hard_max
            ceiling = hard_max if (hard_max is not None and max_explicit) else max(hard_max or 0.0, fill_target * 1.2)
            optimize_fn(
                d,
                climb_db,
                max_km=ceiling,
                fill=True,
                fill_target_km=fill_target,
                objective="toeren",
            )
            actual = (d.get("computed") or {}).get("total_km") or 0.0
            if actual < 0.3:
                raise IntentError(
                    f"Ik kon geen lus van ~{fill_target:.0f} km maken vanaf deze "
                    "startplaats. Probeer een iets grotere afstand of een andere start."
                )
            return
        if hard_max is not None and actual > hard_max:
            raise IntentError(
                f"kortste route is {actual:.1f} km en overschrijdt het harde "
                f"maximum van {hard_max:.1f} km"
            )
        return

    # Een 'target_km' is een zacht doel ("ongeveer N km"), geen harde limiet.
    # Zonder expliciete max_km is hard_max afgeleid als target+tolerance, maar
    # een GraphHopper round-trip overschrijdt dat doel van nature licht. Geef de
    # optimizer daarom extra marge zodat hij niet hard faalt op zo'n overschot;
    # fill_target_km blijft het doel, dus de route wordt niet onnodig opgerekt.
    optimize_ceiling = hard_max
    if not max_explicit and target_km is not None:
        optimize_ceiling = max(hard_max, target_km * 1.2)

    optimize_kwargs = {
        "max_km": optimize_ceiling,
        "fill": True if request.get("rond_plaats") else not request["geen_opvulling"],
    }
    if request.get("rond_plaats") and not d.get("climbs"):
        optimize_kwargs["objective"] = (
            "offroad" if request.get("activiteit") == "trail" else "toeren"
        )
    elif goal == "toeren":
        optimize_kwargs["objective"] = "toeren"
    elif goal == "offroad":
        optimize_kwargs["objective"] = "offroad"
    if target_km is not None:
        optimize_kwargs["fill_target_km"] = target_km
    try:
        optimize_fn(d, climb_db, **optimize_kwargs)
    except draft.DraftError:
        # Bij een hard budget (expliciete max_km) is falen terecht. Bij een zacht
        # doel schoot een ver klim-anker de basisroute over het doel; val dan
        # terug op een pure round-trip-lus richting het doel (geen klim-hunting)
        # zodat de gebruiker altijd een route krijgt i.p.v. een fout.
        if max_explicit:
            raise
        fill_target = target_km if target_km is not None else hard_max
        d["climbs"] = []
        d["computed"] = None
        d.pop("_geometry", None)
        optimize_fn(
            d,
            climb_db,
            max_km=max(optimize_ceiling, (fill_target or 0.0) * 1.6),
            fill=True,
            fill_target_km=fill_target,
            objective="toeren",
        )


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
    if aws_state.enabled():
        artifacts.publish(d["id"], "route.gpx")
        artifacts.publish(d["id"], "preview.html")
    return {
        "gpx": artifacts.output_reference(
            gpx_path, d["id"], "route.gpx"
        ),
        "preview": artifacts.output_reference(
            preview_path, d["id"], "preview.html"
        ),
    }


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
    autovrij: bool | None = None,
    strict: bool | None = False,
    naam: str | None = None,
    activiteit: str = "fietsen",
    geen_opvulling: bool = False,
    profiel_naam: str | None = None,
    check_readiness: bool = False,
    request_id: str | None = None,
    rond_plaats: str | None = None,
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
    find_request_fn=draft.find_by_request_id,
    resolve_fn=geocode.resolve,
    exports_root: Path | None = None,
) -> dict:
    """Maak en routeer een lus, eventueel na een readiness-gesprek."""
    if doel not in {"hoogtemeters", "kort", "toeren"}:
        raise IntentError("doel moet 'hoogtemeters', 'kort' of 'toeren' zijn")
    if activiteit not in ACTIVITY_PROFILES:
        raise IntentError("activiteit moet 'fietsen' of 'trail' zijn")
    if request_id is not None and not _REQUEST_ID_RE.fullmatch(request_id):
        raise IntentError(
            "request-id gebruikt 1-128 letters, cijfers, '.', '_', ':' of '-'"
        )
    if rond_plaats is not None:
        rond_plaats = rond_plaats.strip()
        if not rond_plaats:
            raise IntentError("rond-plaats mag niet leeg zijn")
    if rond_plaats and target_km is None and max_km is None:
        target_km = 5.0
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
    input_signature = {
        "start": start.strip(),
        "region": region,
        "rond_plaats": rond_plaats,
        "via_klimmen": list(via_klimmen),
        "vermijd_plaatsen": list(vermijd_plaatsen),
        "naam": naam,
        "doel": doel,
        "target_km": target_km,
        "max_km": max_km,
        "tolerance_km": tolerance_km,
        "geen_opvulling": geen_opvulling,
        "profiel_naam": profiel_naam,
        "activiteit": activiteit,
        "kasseien": kasseien,
        "beton_vermijden": beton_vermijden,
        "autovrij": autovrij,
        "strict": strict,
    }
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
        autovrij=autovrij,
        strict=strict,
        request_id=request_id,
        rond_plaats=rond_plaats,
        input_signature=input_signature,
    )
    existing = find_request_fn(request_id) if request_id is not None else None
    if existing is not None:
        stored_request = existing.get("route_request") or {}
        stored_signature = stored_request.get("input_signature")
        comparable_signature = input_signature
        if isinstance(stored_signature, dict):
            # Oudere workflows blijven idempotent hervatbaar zolang later
            # toegevoegde optionele invoer niet expliciet werd opgegeven.
            for optional_key in ("autovrij", "rond_plaats"):
                if (
                    optional_key not in stored_signature
                    and input_signature[optional_key] is None
                ):
                    comparable_signature = {
                        key: value
                        for key, value in comparable_signature.items()
                        if key != optional_key
                    }
        if stored_signature != comparable_signature:
            raise IntentError(
                f"request-id '{request_id}' is al gebruikt voor een andere routewens"
            )
        request = stored_request
        d = existing
        with draft.region_scope(d):
            climb_db = climbs_fn()
            if not d.get("computed") and check_readiness:
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
            if not d.get("computed"):
                _execute_request(
                    d,
                    climb_db,
                    request,
                    route_fn=route_fn,
                    optimize_fn=optimize_fn,
                )
                d = load_fn(d["id"])
            files = _export_files(
                d,
                climb_db,
                export_gpx_fn=export_gpx_fn,
                export_preview_fn=export_preview_fn,
                exports_root=exports_root,
            )
        return compact_result(d, climb_db, files, request)
    route_name = naam.strip() if naam else suggest_route_name(
        rond_plaats or start,
        target_km=target_km,
        max_km=max_km,
        doel=doel,
        activiteit=activiteit,
    )
    if not route_name:
        raise IntentError("naam mag niet leeg zijn")
    create_kwargs = dict(
        start=start,
        name=route_name,
        strict=bool(strict),
        avoid_cobbles=kasseien is False,
        avoid_concrete=beton_vermijden is True,
        avoid_busy=autovrij is True,
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
        if rond_plaats:
            anchor, _alternatives = resolve_fn(rond_plaats)
            d["round_trip_anchor"] = anchor
            d["opvullingen"] = []
            d["computed"] = None
            d.pop("_geometry", None)
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
    expected_revision: int | None = None,
    rond_plaats: str | None = None,
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
    resolve_fn=geocode.resolve,
    exports_root: Path | None = None,
) -> dict:
    """Pas meerdere routewensen toe, routeer eenmaal en exporteer opnieuw."""
    d = load_fn(draft_id)
    draft.require_revision(d, expected_revision)
    previous_request = d.get("route_request") or {}
    if rond_plaats is not None:
        rond_plaats = rond_plaats.strip()
        if not rond_plaats:
            raise IntentError("rond-plaats mag niet leeg zijn")
    effective_round_place = (
        rond_plaats
        if rond_plaats is not None
        else previous_request.get("rond_plaats")
    )
    effective_target = (
        target_km if target_km is not None else previous_request.get("target_km")
    )
    effective_tolerance = (
        tolerance_km
        if tolerance_km is not None
        else previous_request.get("tolerance_km", 2.5)
    )
    defaulted_round_distance = False
    if (
        effective_round_place
        and effective_target is None
        and max_km is None
        and previous_request.get("max_km") is None
    ):
        effective_target = 5.0
        defaulted_round_distance = True
    if max_km is not None:
        effective_max = max_km
        max_is_explicit = True
    elif (
        (target_km is not None or defaulted_round_distance)
        and not previous_request.get("max_km_explicit", False)
    ):
        effective_max = effective_target + effective_tolerance
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
    if effective_goal not in {"hoogtemeters", "offroad", "kort", "toeren"}:
        raise IntentError(
            "doel moet 'hoogtemeters', 'offroad', 'kort' of 'toeren' zijn"
        )
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
        "rond_plaats": effective_round_place,
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
        if effective_round_place:
            anchor, _alternatives = resolve_fn(effective_round_place)
            if d.get("round_trip_anchor") != anchor:
                d["round_trip_anchor"] = anchor
                d["opvullingen"] = []
                d["computed"] = None
                d.pop("_geometry", None)
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
