"""Composiet-intenties met compacte, LLM-gerichte route-output."""

from __future__ import annotations
from . import quotas

import copy
import math
import difflib
import re
import unicodedata
from pathlib import Path

from . import (
    activities,
    artifacts,
    aws_state,
    climbs,
    config,
    coverage,
    draft,
    funnel,
    geocode,
    gpx,
    heat,
    preview,
    profiles,
    readiness,
)
from . import proposals as proposals_mod


class IntentError(RuntimeError):
    """Gebruikersfout bij het uitvoeren van een composiet-intentie."""


ACTIVITY_PROFILES = {
    key: activities.graph_profile(key) for key in activities.ACCEPTED
}
_ACTIVITY_ERROR = "activiteit moet een van deze zijn: " + ", ".join(activities.KEYS)
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


def heat_activity_for(
    activiteit: str | None, profiel_naam: str | None
) -> str | None:
    """Leid de heat-taxonomie af uit activiteit en (voor fietsen) profielnaam."""
    activity = activities.get(activiteit)
    if activity is None:
        return None
    if activity.heat is not None:
        return activity.heat
    if activity.mode != "fiets":
        return None
    # Toerfiets en de oude naam "fietsen": het profiel kan nog een specialisatie noemen.
    profile = (profiel_naam or "").casefold()
    if "koers" in profile or "race" in profile:
        return "koersfiets"
    if "gravel" in profile:
        return "gravel"
    if "mtb" in profile:
        return "mtb"
    return "stadsfiets"


def suggest_route_name(
    start: str,
    *,
    target_km: float | None,
    max_km: float | None,
    doel: str,
    activiteit: str,
) -> str:
    """Bouw een compacte fallbacknaam uit de gestructureerde routewens."""
    parts = [part.strip() for part in start.split(",") if part.strip()]
    # "Markt, Oudenaarde" of "Stationsstraat 5, 9230 Wetteren": noem de gemeente,
    # niet de straat. Eén deel ("Wetteren station") blijft zoals het is.
    place = re.sub(r"^\d{4}\s+", "", parts[-1]) if len(parts) > 1 else (parts[0] if parts else "")
    if len(parts) == 2 and re.fullmatch(r"[-+]?\d+(?:\.\d+)?", parts[0] or ""):
        place = ""  # coördinaten "51.2,2.9"
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", place) or not place:
        place = "je startpunt"
    if activities.is_foot(activiteit):
        # Het voetprofiel dient wandelaars en lopers; alleen een uitdrukkelijk
        # onverharde wens of de trailactiviteit heet een traillus.
        if activiteit == "wegloop":
            kind = "Looplus"
        else:
            kind = "Traillus" if doel == "offroad" else "Wandellus"
    elif doel == "hoogtemeters":
        kind = "Heuvelrit"
    elif doel == "toeren":
        kind = "Rondrit"
    else:
        kind = "Fietslus"
    distance = target_km if target_km is not None else max_km
    suffix = f" · {distance:g} km" if distance is not None else ""
    return f"{kind} rond {place}{suffix}"[:80].rstrip()


def _nearby_place(start) -> str | None:
    label = start.get("label") if isinstance(start, dict) else None
    match = re.fullmatch(r"Nabij (.+?) \([-\d.]+, [-\d.]+\)", label or "")
    return match.group(1).strip() if match else None


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
    maximum_is_hard = request.get("max_km_explicit", True)
    within_max = (
        None if hard_max is None or actual is None else actual <= hard_max
    )
    within_hard_max = within_max if maximum_is_hard else None
    checks = [check for check in (within_target, within_hard_max) if check is not None]
    warnings = []
    km = lambda value: f"{value:.1f}".replace(".", ",")
    if within_target is False:
        direction = "korter" if actual < target else "langer"
        warnings.append(
            f"De route is {km(actual)} km, {km(abs(actual - target))} km {direction} dan je gevraagde {km(target)} km."
        )
        if d.get("optimize_note"):
            warnings.append(d["optimize_note"])
    if d.get('stop_warning'):
        warnings.append(d['stop_warning'])
    if d.get("fill_note"):
        warnings.append(d["fill_note"])
    if within_hard_max is False:
        warnings.append(
            f"De route is {km(actual - hard_max)} km langer dan je maximum van {km(hard_max)} km."
        )
    water_planned = bool(d.get("water_via")) if request.get("langs_water") else None
    if water_planned is False:
        warnings.append("de gevraagde waterloop is niet gevonden in de regiogegevens; de route garandeert geen traject langs water")
        checks.append(False)
    return {
        "binnen_hard_maximum": within_hard_max,
        "maximum_is_hard": maximum_is_hard if hard_max is not None else None,
        "langs_water_gepland": water_planned,
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
    proposals_fn=None,
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
    if d.get('stop_onderweg'):
        stop = d['stop_onderweg']
        result['stop_onderweg'] = {'soort': stop['kind'], 'naam': stop['name'], 'km': stop['at_km']}
    underway = underway_label(_route_poi_counts(d, feature_selector))
    if underway:
        result["onderweg"] = underway
    proposals = (proposals_fn or proposals_mod.build)(d, climb_db, request)
    if proposals:
        result["voorstellen"] = proposals
        result["vervolg"].append(
            "bied de voorstellen aan; elk voorstel bevat de adjust_route-argumenten"
        )
    return result


def _validate_request(
    *, target_km: float | None, max_km: float | None, tolerance_km: float
) -> None:
    for name, value in (("target-km", target_km), ("max-km", max_km), ("tolerance-km", tolerance_km)):
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise IntentError(f"{name} moet een eindig getal zijn")
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
    langs_water: str | None,
    input_signature: dict,
    heuvels: str | None = None,
    ondergrond: str | None = None,
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
    if heuvels is not None:
        explicit_preferences["heuvels"] = heuvels
    if ondergrond is not None:
        explicit_preferences["ondergrond"] = ondergrond
    return {
        "doel": doel,
        "target_km": target_km,
        "max_km": hard_max,
        "max_km_explicit": max_km is not None,
        "tolerance_km": tolerance_km,
        "geen_opvulling": geen_opvulling,
        "profiel_naam": profiel_naam,
        "activiteit": activiteit,
        "heat_activity": heat_activity_for(activiteit, profiel_naam),
        "expliciete_voorkeuren": explicit_preferences,
        "toegestane_plaatsen": [],
        "request_id": request_id,
        "rond_plaats": rond_plaats,
        "langs_water": langs_water,
        "input_signature": input_signature,
    }


def _tour_objective(request: dict, default: str = "toeren") -> str:
    """'vlak' als de rit expliciet vlak moet zijn, anders het gegeven doel."""
    explicit = request.get("expliciete_voorkeuren") or {}
    if explicit.get("heuvels") == "vlak" and default in ("toeren", "vlak"):
        return draft.FLAT
    return default


def _profile_for_request(request: dict, profile_load_fn) -> dict:
    profile = copy.deepcopy(profile_load_fn(request["profiel_naam"]))
    profile["activiteit"] = request["activiteit"]
    # Antwoorden gelden voor deze rit en deze activiteit: ze gaan in de
    # per-activiteit-laag zodat ze ook bij wandelen (zonder terugval op de
    # top-level fietsvoorkeuren) en boven profielwaarden winnen.
    explicit = request.get("expliciete_voorkeuren") or {}
    profile["voorkeuren"].update(explicit)
    if explicit:
        activity = activities.canonical(request["activiteit"]) or activities.DEFAULT
        per_activity = profile.setdefault("voorkeuren_per_activiteit", {})
        per_activity[activity] = {**(per_activity.get(activity) or {}), **explicit}
    return profile


def _needs_input(
    d: dict,
    climb_db: dict,
    request: dict,
    *,
    probe_fn,
    assess_fn,
    profile_load_fn,
    save_fn=None,
) -> dict | None:
    from .progress import emit
    emit("checking", "Ik controleer de ondergrond, drukke wegen en je voorkeuren.")
    probe_fn(d, climb_db)
    assessment = assess_fn(
        d, _profile_for_request(request, profile_load_fn), climb_db
    )
    if assessment["klaar"]:
        d.pop("open_vragen", None)
        return None
    d["open_vragen"] = assessment["vragen"]
    if save_fn is not None:
        save_fn(d)
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


def _plan_stop(d, climb_db, request, *, route_fn, pois_fn, persist_fn):
    from .route_pois import project
    from . import geo, gh
    wanted = request.get('stop_onderweg')
    if not wanted or d.get('stop_onderweg'):
        return
    candidates = [p for p in pois_fn(d) if p['kind'] == wanted['soort'] and p.get('offset_m', 0) <= 150]
    d.pop('stop_warning', None)
    if not candidates:
        d['stop_warning'] = f"Geen geschikte {wanted['soort']} binnen 150 m van de route gevonden."
    else:
        chosen = min(candidates, key=lambda p: (abs(p['at_km'] - wanted['rond_km']), p.get('offset_m', 0), p['id']))
        original = copy.deepcopy(d)
        legs = d.get('_geometry', [])
        # De routeafstand bepaalt op welke passage van een lus de stop ligt.
        distance = 0.0
        leg_index = 0
        for i, leg in enumerate(legs):
            leg_index = i
            distance += geo.path_length(leg) / 1000
            if distance >= chosen['at_km']:
                break
        d['stop_onderweg'] = {**chosen, 'leg_index': leg_index}
        try:
            route_fn(d, climb_db)
            actual = (d.get('computed') or {}).get('total_km')
            target, tolerance = request.get('target_km'), request.get('tolerance_km', 2.5)
            maximum = request.get('max_km') if request.get('max_km_explicit', True) else None
            if not isinstance(actual, (int, float)) or not math.isfinite(actual) or actual < 0.1 or (maximum is not None and actual > maximum) or (target is not None and abs(actual - target) > tolerance):
                raise draft.DraftError('De stop past niet binnen de gevraagde afstand en tolerantie.')
            progress = 0.0
            for i, leg in enumerate(d.get('_geometry', [])):
                if i == leg_index:
                    progress += project((chosen['lat'], chosen['lon']), leg)[1] / 1000
                    break
                progress += geo.path_length(leg) / 1000
            d['stop_onderweg']['at_km'] = round(progress, 3)
        except (draft.DraftError, gh.GhError) as exc:
            d.clear()
            d.update(original)
            d['stop_warning'] = f"Geen geschikte stop ingepland: {exc}"
    if persist_fn:
        persist_fn(d)


def _execute_request(d, climb_db, request, *, route_fn, optimize_fn, persist_fn=None, pois_fn=None, climb_adjustment=False):
    _route_for_request(d, climb_db, request, route_fn=route_fn, optimize_fn=optimize_fn, climb_adjustment=climb_adjustment)
    from .route_pois import for_draft
    _plan_stop(d, climb_db, request, route_fn=route_fn, pois_fn=pois_fn or (lambda item: for_draft(item, limit=None)), persist_fn=persist_fn)
    actual = (d.get("computed") or {}).get("total_km")
    problem = None
    if not isinstance(actual, (int, float)) or not math.isfinite(actual) or actual < 0.1:
        problem = "De router leverde geen bruikbare routeafstand op. Kies een andere afstand of startplek."
    elif not climb_adjustment and request.get("max_km_explicit", True) and request.get("max_km") is not None and actual > request["max_km"]:
        problem = f"route is {actual:.1f} km en overschrijdt het harde maximum van {request['max_km']:.1f} km"
    if problem:
        d['computed'] = None
        d.pop('_geometry', None)
        if persist_fn:
            persist_fn(d)
        raise IntentError(problem)


def _route_for_request(
    d: dict,
    climb_db: dict,
    request: dict,
    *,
    route_fn,
    optimize_fn,
    climb_adjustment=False,
) -> None:
    goal = request["doel"]
    target_km = request.get("target_km")
    hard_max = request.get("max_km")
    max_explicit = request.get("max_km_explicit", True)
    if climb_adjustment:
        # Expliciete klimkeuzes behouden; alleen de vervangbare rondrit opnieuw
        # opvullen. Geen greedy klimselectie die verwijderde klimmen terugzet.
        route_fn(d, climb_db)
        ceiling = target_km + request.get("tolerance_km", 2.5)
        if hard_max is not None:
            ceiling = min(hard_max, ceiling)
        if d["computed"]["total_km"] > ceiling:
            return  # constraint_report meldt de te lange route als waarschuwing
        if not d.get("water_via"):
            optimize_fn(
                d, climb_db, max_km=ceiling, max_rounds=0,
                fill=not request["geen_opvulling"], fill_target_km=target_km,
                objective="offroad" if goal == "offroad" else _tour_objective(request),
            )
        return
    if d.get("water_via"):
        route_fn(d, climb_db)
        actual = (d.get("computed") or {}).get("total_km") or 0.0
        if max_explicit and hard_max is not None and actual > hard_max:
            raise IntentError(
                f"route is {actual:.1f} km en overschrijdt het harde "
                f"maximum van {hard_max:.1f} km"
            )
        return
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
                objective=_tour_objective(request),
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
            "offroad" if request.get("activiteit") == "trail"
            else _tour_objective(request)
        )
    elif goal == "toeren":
        optimize_kwargs["objective"] = _tour_objective(request)
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
            objective=_tour_objective(request),
        )


def _export_files(
    d: dict,
    climb_db: dict,
    *,
    export_gpx_fn=gpx.export,
    export_preview_fn=preview.export,
    exports_root: Path | None = None,
) -> dict:
    from .progress import emit
    emit("exporting", "Ik maak de kaart en je routebestand klaar.")
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


def _set_water_via(d: dict, request: dict, water_fn) -> bool:
    """Zet persistente water-via-punten, of schakel de feature stil uit."""
    previous_via = d.pop("water_via", None)
    if previous_via:
        d["computed"] = None
        d.pop("_geometry", None)
    name = request.get("langs_water")
    distance_km = request.get("target_km") or request.get("max_km")
    if not name or distance_km is None:
        return False
    segments = water_fn(name)
    via = draft.water_via_points(
        (d["start"]["lat"], d["start"]["lon"]),
        segments,
        distance_km,
    )
    if not via:
        return False
    for point in via:
        lat, lon = (point["lat"], point["lon"]) if isinstance(point, dict) else point
        coverage.check_point({"lat": lat, "lon": lon}, "via-punt")
    d["water_via"] = via
    # Een waterloop en rond-plek zijn alternatieve lusankers; water wint.
    d.pop("round_trip_anchor", None)
    d["opvullingen"] = []
    d["computed"] = None
    d.pop("_geometry", None)
    return True


@funnel.tracked_plan
@quotas.metered("route")
def plan_route(
    start: str,
    region: str | None = None,
    max_km: float | None = None,
    target_km: float | None = None,
    tolerance_km: float = 2.5,
    doel: str = "toeren",
    via_klimmen: list[str] = [],
    vermijd_plaatsen: list[str] = [],
    kasseien: bool | None = None,
    beton_vermijden: bool | None = None,
    autovrij: bool | None = None,
    strict: bool | None = None,
    naam: str | None = None,
    activiteit: str = activities.DEFAULT,
    geen_opvulling: bool = False,
    profiel_naam: str | None = None,
    check_readiness: bool = False,
    request_id: str | None = None,
    rond_plaats: str | None = None,
    langs_water: str | None = None,
    heuvels: str | None = None,
    ondergrond: str | None = None,
    stop_onderweg: dict | None = None,
    *,
    pois_fn=None,
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
    water_fn=geocode.waterway_segments,
    exports_root: Path | None = None,
) -> dict:
    """Maak en routeer een lus, eventueel na een readiness-gesprek."""
    if stop_onderweg is not None:
        from .chat_contracts import STOP_SCHEMA, validate_arguments
        try:
            validate_arguments(stop_onderweg, STOP_SCHEMA, 'stop_onderweg')
        except ValueError as exc:
            raise IntentError(str(exc)) from exc
    if doel not in {"hoogtemeters", "offroad", "kort", "toeren"}:
        raise IntentError("doel moet 'hoogtemeters', 'offroad', 'kort' of 'toeren' zijn")
    if activities.canonical(activiteit) is None:
        raise IntentError(_ACTIVITY_ERROR)
    activiteit = activities.canonical(activiteit)
    if heuvels not in profiles.HEUVELS_VALUES:
        raise IntentError("heuvels moet 'zoek', 'ok' of 'vlak' zijn")
    if ondergrond not in profiles.ONDERGROND_VALUES:
        raise IntentError("ondergrond moet 'verhard', 'ok' of 'onverhard' zijn")
    if request_id is not None and not _REQUEST_ID_RE.fullmatch(request_id):
        raise IntentError(
            "request-id gebruikt 1-128 letters, cijfers, '.', '_', ':' of '-'"
        )
    if rond_plaats is not None:
        rond_plaats = rond_plaats.strip()
        if not rond_plaats:
            raise IntentError("rond-plaats mag niet leeg zijn")
    if langs_water is not None:
        langs_water = langs_water.strip()
        if not langs_water:
            raise IntentError("langs-water mag niet leeg zijn")
    if rond_plaats and not langs_water and target_km is None and max_km is None:
        target_km = 5.0
    _validate_request(
        target_km=target_km,
        max_km=max_km,
        tolerance_km=tolerance_km,
    )
    if doel == "toeren" and not via_klimmen and target_km is None and max_km is None:
        raise IntentError("doel 'toeren' vereist target-km of max-km")
    if doel in {"hoogtemeters", "offroad"} and not via_klimmen and target_km is None and max_km is None:
        raise IntentError(
            "een lege hoogtemeterlus vereist target-km, max-km of een via-klim"
        )
    input_signature = {
        "start": start.strip(),
        "region": region,
        "rond_plaats": rond_plaats,
        "langs_water": langs_water,
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
    # Nieuwe optionele invoer komt alleen in de signatuur als ze gegeven is,
    # zodat bestaande request-id's idempotent hervatbaar blijven.
    for key, value in (("heuvels", heuvels), ("ondergrond", ondergrond), ("stop_onderweg", stop_onderweg)):
        if value is not None:
            input_signature[key] = value
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
        langs_water=langs_water,
        input_signature=input_signature,
        heuvels=heuvels,
        ondergrond=ondergrond,
    )
    if stop_onderweg is not None:
        request['stop_onderweg'] = dict(stop_onderweg)
    existing = find_request_fn(request_id) if request_id is not None else None
    if existing is not None:
        stored_request = existing.get("route_request") or {}
        stored_signature = stored_request.get("input_signature")
        if isinstance(stored_signature, dict) and stored_signature.get("activiteit"):
            # "fietsen" is de oude naam van "toerfiets".
            stored_signature = {
                **stored_signature,
                "activiteit": activities.canonical(stored_signature["activiteit"])
                or stored_signature["activiteit"],
            }
        comparable_signature = input_signature
        if isinstance(stored_signature, dict):
            # Oudere workflows blijven idempotent hervatbaar zolang later
            # toegevoegde optionele invoer niet expliciet werd opgegeven.
            for optional_key in ("autovrij", "rond_plaats", "langs_water"):
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
                    save_fn=save_fn,
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
                    persist_fn=save_fn,
                    pois_fn=pois_fn,
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
        profile=activities.graph_profile(activiteit),
    )
    if profiel_naam is not None:
        create_kwargs["profile_doc"] = profiel_naam
    created = create_fn(**create_kwargs)
    draft_id = created.get("id") or created.get("draft")
    d = load_fn(draft_id)
    nearby = _nearby_place(d.get("start"))
    if not naam and nearby and "rond je startpunt" in route_name:
        # Een start uit coördinaten (Mijn locatie) krijgt de dichtste plaatsnaam.
        d["name"] = route_name.replace("rond je startpunt", f"rond {nearby}", 1)[:80]
        save_fn(d)
    with draft.region_scope(d):
        climb_db = climbs_fn()
        for place in vermijd_plaatsen:
            avoid_place_fn(draft_id, place)
        for climb in _resolve_climbs(via_klimmen, climb_db):
            add_climb_fn(draft_id, climb["id"])
        d = load_fn(draft_id)
        water_active = _set_water_via(d, request, water_fn)
        if rond_plaats and not water_active:
            anchor, _alternatives = resolve_fn(rond_plaats)
            coverage.check_point(anchor, "ankerpunt")
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
                save_fn=save_fn,
            )
            if needs_input is not None:
                return needs_input
        _execute_request(
            d,
            climb_db,
            request,
            route_fn=route_fn,
            optimize_fn=optimize_fn,
            persist_fn=save_fn,
            pois_fn=pois_fn,
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


# Antwoorden op de situationele vragen (lusmaker/questions.py).
ANSWER_VALUES = {
    "kasseien": {"graag", "ok", "vermijd"},
    "heuvels": {"zoek", "ok", "vlak"},
    "ondergrond": {"verhard", "ok", "onverhard"},
    "fietspaden": {"belangrijk", "ok"},
    "oversteken": {"vermijd", "ok"},
}


def apply_answers(
    draft_id: str,
    antwoorden: dict,
    *,
    expected_revision: int | None = None,
    load_fn=draft.load,
    save_fn=draft.save,
    adjust_fn=None,
) -> dict:
    """Pas antwoorden op situationele vragen toe zonder taalmodel en routeer opnieuw.

    De antwoorden gelden voor deze rit (expliciete voorkeuren), niet voor het
    profiel: een racefietser die hier 'verhard' kiest, wil dat niet voor elke
    wandeling.
    """
    if not isinstance(antwoorden, dict) or not antwoorden:
        raise IntentError("geef minstens één antwoord")
    for key, value in antwoorden.items():
        if key not in ANSWER_VALUES or value not in ANSWER_VALUES[key]:
            raise IntentError(f"onbekend antwoord: {key}={value}")
    d = load_fn(draft_id)
    draft.require_revision(d, expected_revision)
    request = dict(d.get("route_request") or {})
    if not request:
        raise IntentError("deze route heeft geen routewens om aan te vullen")
    request["expliciete_voorkeuren"] = {**(request.get("expliciete_voorkeuren") or {}), **antwoorden}
    d["route_request"] = request
    if "kasseien" in antwoorden:
        d["avoid_cobbles"] = antwoorden["kasseien"] == "vermijd"
    # fietspaden (custom-modelstraf) en oversteken (strict) volgen uit de
    # expliciete voorkeuren van de rit; draft.routing_preferences leest ze daar.
    goal = request.get("doel") or "toeren"
    if antwoorden.get("heuvels") == "zoek":
        goal = "hoogtemeters"
    elif antwoorden.get("ondergrond") == "onverhard":
        goal = "offroad"
    elif antwoorden.get("heuvels") == "vlak" and goal == "hoogtemeters":
        goal = "toeren"
    save_fn(d)
    adjust = adjust_fn or adjust_route
    with funnel.adjust_kind("answers"):
        return adjust(draft_id, doel=goal, check_readiness=True)


@funnel.tracked_adjust
@quotas.metered("route")
def _once_per_request(fn):
    """Laat een `request_id` een retry van `adjust_route` het opgeslagen resultaat geven.

    Zonder S3-state (lokaal) of zonder `request_id` verandert er niets; de
    revisiecheck blijft daar de bescherming. Dezelfde id met andere invoer geeft
    `requests.RequestConflict`.
    """
    import functools
    import inspect
    from . import requests

    signature = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        request_id = kwargs.get("request_id")
        if request_id is None:
            return fn(*args, **kwargs)
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        values = bound.arguments
        payload = {
            key: value for key, value in values.items()
            if key not in {"request_id", "exports_root"} and not key.endswith("_fn")
        }
        return requests.once(
            f"adjust:{values['draft_id']}", request_id, payload,
            lambda: fn(*args, **kwargs),
        )

    return wrapper


@_once_per_request
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
    langs_water: str | None = None,
    request_id: str | None = None,
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
    water_fn=geocode.waterway_segments,
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
    if langs_water is not None:
        langs_water = langs_water.strip()
        if not langs_water:
            raise IntentError("langs-water mag niet leeg zijn")
    effective_water = (
        langs_water
        if langs_water is not None
        else previous_request.get("langs_water")
    )
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
    effective_goal = doel or previous_request.get("doel", "toeren")
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
        "activiteit": previous_request.get("activiteit", activities.DEFAULT),
        "rond_plaats": effective_round_place,
        "langs_water": effective_water,
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
    request["heat_activity"] = heat_activity_for(
        request["activiteit"], effective_profile
    )
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
        climb_adjustment = bool(voeg_klimmen_toe or verwijder_klimmen) and effective_target is not None
        if climb_adjustment:
            d["opvullingen"] = []
            d["computed"] = None
            d.pop("_geometry", None)
            d.pop("fill_note", None)
            d.pop("optimize_note", None)
        water_active = _set_water_via(d, request, water_fn)
        if effective_round_place and not water_active:
            anchor, _alternatives = resolve_fn(effective_round_place)
            coverage.check_point(anchor, "ankerpunt")
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
                save_fn=save_fn,
            )
            if needs_input is not None:
                return needs_input
        _execute_request(
            d,
            climb_db,
            request,
            route_fn=route_fn,
            optimize_fn=optimize_fn,
            persist_fn=save_fn,
            climb_adjustment=climb_adjustment,
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


def route_details(draft_id: str, *, load_fn=draft.load, include_unrouted=False) -> dict:
    """Geef legs en volledige kwaliteitsmetrieken van een gerouteerde draft."""
    d = load_fn(draft_id)
    computed = d.get("computed")
    if not computed:
        if not include_unrouted:
            raise IntentError(f"draft '{draft_id}' heeft nog geen berekende route; routeer eerst")
        return {"draft": d["id"], "revision": int(d.get("revision", 0)),
                "status": "needs_input", "km": None, "hoogtemeters": None,
                "legs": [], "kwaliteit": {},
                "advies": "Routeconcept: gebruik deze revisie om de routewensen aan te vullen en te routeren."}
    return {
        "draft": d["id"],
        "revision": int(d.get("revision", 0)),
        "status": "ready",
        "km": computed["total_km"],
        "hoogtemeters": computed["ascend_m"],
        "legs": computed.get("legs", []),
        "kwaliteit": computed.get("kwaliteit", {}),
    }
