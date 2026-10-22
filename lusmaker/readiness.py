"""Pure readiness-regels voor incrementele routevoorkeuren."""

from __future__ import annotations

import os

from . import activities
from . import questions as situational
from . import question_composer
from .conversation_context import USER_TEXT


def _metric(probe: dict, terrain_key: str, quality_key: str | None = None, default=0):
    terrain = probe.get("terrein") or {}
    quality = probe.get("kwaliteit") or {}
    if terrain_key in terrain:
        return terrain[terrain_key]
    return quality.get(quality_key or terrain_key, default)


def _paved_bike(activity: str | None) -> bool:
    spec = activities.get(activity)
    return bool(spec and spec.mode == "fiets" and spec.ground == "verhard")


def _default_weights(weights: dict) -> bool:
    return (
        weights.get("hoogtemeters") == 1.0
        and weights.get("offroad") == 0.0
        and weights.get("populair") == 0.0
        and weights.get("autovrij", 0.0) == 0.0
        and weights.get("kort") == 0.0
    )


def _weight_question(
    offroad_pct: float, heat_pct: float | None, activity: str = "fietsen"
) -> dict | None:
    has_offroad = offroad_pct > 20
    has_heat = heat_pct is not None
    if not has_offroad and not has_heat:
        return None

    if has_offroad and has_heat:
        reason = (
            f"de verkenningsroute bevat {offroad_pct:g}% offroad en heeft "
            f"{heat_pct:g}% heatdekking; de gewenste mix is onbekend"
        )
        options = {
            "vooral_klimmen": {
                "patch": {"gewichten": {"hoogtemeters": 0.7, "offroad": 0.3}}
            },
            "avontuurlijk": {
                "patch": {
                    "gewichten": {
                        "hoogtemeters": 0.4,
                        "offroad": 0.4,
                        "populair": 0.2,
                    }
                }
            },
            "populair_en_klimmen": {
                "patch": {
                    "gewichten": {"hoogtemeters": 0.6, "populair": 0.4}
                }
            },
        }
    elif has_offroad:
        reason = (
            f"de verkenningsroute bevat {offroad_pct:g}% offroad; "
            "de gewenste mix is onbekend"
        )
        options = {
            "vooral_klimmen": {
                "patch": {"gewichten": {"hoogtemeters": 0.7, "offroad": 0.3}}
            },
            "gelijk_verdeeld": {
                "patch": {"gewichten": {"hoogtemeters": 0.5, "offroad": 0.5}}
            },
            "vooral_offroad": {
                "patch": {"gewichten": {"hoogtemeters": 0.3, "offroad": 0.7}}
            },
        }
    else:
        reason = (
            f"de verkenningsroute heeft {heat_pct:g}% heatdekking; "
            "de gewenste mix is onbekend"
        )
        options = {
            "vooral_klimmen": {
                "patch": {"gewichten": {"hoogtemeters": 0.7, "populair": 0.3}}
            },
            "gelijk_verdeeld": {
                "patch": {"gewichten": {"hoogtemeters": 0.5, "populair": 0.5}}
            },
            "vooral_populair": {
                "patch": {"gewichten": {"hoogtemeters": 0.3, "populair": 0.7}}
            },
        }
    popularity_label = (
        "populaire wandelroutes" if activities.is_foot(activity) else "populaire fietswegen"
    )
    return {
        "id": "gewichten",
        "prioriteit": 4,
        "reden": reason,
        "vraag": (
            "Wat weegt voor jou het zwaarst: heuvels en hoogtemeters, de "
            f"beschikbare onverharde stukken, of {popularity_label}?"
        ),
        "opties": options,
    }


def _passed_places(d: dict, probe: dict) -> list[dict]:
    excluded = {
        str(point.get("label", "")).casefold()
        for point in (d.get("start"), d.get("end"))
        if point
    }
    excluded.update(
        str(point.get("label", "")).casefold()
        for point in d.get("avoid_places", [])
    )
    excluded.update(
        str(label).casefold()
        for label in (d.get("route_request") or {}).get(
            "toegestane_plaatsen", []
        )
    )
    places = []
    seen = set(excluded)
    for place in (probe.get("terrein") or {}).get("plaatskernen", []):
        label = str(place.get("label", "")).strip()
        key = label.casefold()
        if label and key not in seen:
            places.append(place)
            seen.add(key)
    return places


# Vraag-id -> metrieken die ze dekt; een criterium op zo'n metriek beantwoordt de vraag al.
_QUESTION_METRICS = {
    "kasseien": {"kassei"}, "heuvels": {"hoogtemeters"}, "ondergrond": {"onverhard", "offroad"},
    "fietspaden": {"fietspad"}, "oversteken": {"oversteken"}, "stil": {"stil"}, "knooppunten": {"knooppunt"},
    "autovrij": {"autovrij", "stil"}, "beton": {"beton"},
    "speeltuin": {"speeltuin"}, "toilet": {"toilet"},
}


def place_round_trip_km(d: dict) -> float | None:
    """Ruwe afstand start -> rond-plek -> start over de weg (1,4x hemelsbreed)."""
    anchor, start = d.get("round_trip_anchor"), d.get("start") or {}
    if not anchor or start.get("lat") is None:
        return None
    from . import geo
    via = [tuple(p) for p in d.get("water_via") or []]
    if via:
        # Langs een meanderende rivier: Donkmeer via de Schelde gaf 41,5 en 46 km op schattingen
        # van 39 en 41 km met factor 1,8; 2,0 zit op beide metingen binnen 5 %.
        chain = [(start["lat"], start["lon"]), *via, (anchor["lat"], anchor["lon"])]
        return round(2 * 2.0 * geo.path_length(chain) / 1000.0)
    crow_km = geo.haversine(start["lat"], start["lon"], anchor["lat"], anchor["lon"]) / 1000.0
    return round(2 * 1.4 * crow_km)


def _place_distance_question(d: dict) -> dict | None:
    request = d.get("route_request") or {}
    target = request.get("target_km")
    estimate = place_round_trip_km(d)
    if not target or not estimate or request.get("max_km_explicit"):
        return None
    if estimate <= target + request.get("tolerance_km", 2.5):
        return None
    label = (d.get("round_trip_anchor") or {}).get("label") or request.get("rond_plaats") or "de plek"
    place = label.split(" (")[0]  # "Donkmeer (Donk, Overmere)" -> "Donkmeer": de keuze staat al vast
    return {
        "id": "plek_afstand",
        "prioriteit": 0,
        "reden": f"heen en terug is ongeveer {estimate} km, langer dan je gevraagde {target:g} km",
        "vraag": f"{place} ligt ver voor {target:g} km: heen en terug is ongeveer {estimate} km. Wat wil je?",
        "opties": {
            "ruimer": {"label": f"Naar {place}, ~{estimate} km", "antwoord": {"plek_afstand": "ruimer"}},
            "zonder": {"label": f"{target:g} km zonder {place}", "antwoord": {"plek_afstand": "zonder"}},
        },
    }


def assess(d: dict, profiel: dict, climb_db: dict, *, composer=None, wens=None) -> dict:
    """Beoordeel welke routevoorkeuren nu materieel bevraagd moeten worden."""
    del climb_db  # de probe bevat de vooraf gefilterde klimpool al
    probe = d.get("_probe")
    if not isinstance(probe, dict):
        raise ValueError("draft heeft nog geen probe")

    from . import profiles

    preferences = profiles.effective_preferences(profiel, profiel["activiteit"])
    questions = []
    far_place = _place_distance_question(d)
    if far_place:
        questions.append(far_place)
    # Situationele vragen (kasseien, heuvels, ondergrond): zie questions.py.
    questions.extend(situational.ask(d, profiel, probe))

    concrete_m = _metric(probe, "beton_m", "beton_m")
    if (
        preferences["beton"] is None
        and _paved_bike(profiel["activiteit"])
        and concrete_m > 1000
    ):
        questions.append(
            {
                "id": "beton",
                "prioriteit": 2,
                "reden": (
                    f"de verkenningsroute bevat {concrete_m / 1000:.1f} km "
                    "betonbanen; betonvoorkeur onbekend"
                ),
                "vraag": "Rijd je graag op betonbanen, zijn ze oké, of vermijd je ze liever?",
                "opties": {
                    value: {"patch": {"voorkeuren": {"beton": value}}}
                    for value in ("graag", "ok", "vermijd")
                },
            }
        )

    crossings = _metric(probe, "kruisingen", "steenweg_kruisingen", default=0)
    crossings = 0 if crossings is None else crossings
    main_road_m = _metric(probe, "steenweg_m", "steenweg_m")
    if (
        preferences["steenwegen"] is None
        and (crossings > 8 or main_road_m > 1500)
    ):
        questions.append(
            {
                "id": "steenwegen",
                "prioriteit": 3,
                "reden": (
                    f"de verkenningsroute kruist {crossings:g} steenwegen en rijdt "
                    f"{main_road_m / 1000:.1f} km erop; steenwegvoorkeur onbekend"
                ),
                "vraag": "Wil je drukke steenwegen strikt vermijden, of zijn korte passages oké?",
                "opties": {
                    value: {"patch": {"voorkeuren": {"steenwegen": value}}}
                    for value in ("ok", "vermijd")
                },
            }
        )

    autovrij_pct = _metric(
        probe, "autovrij_pct", "autovrij_pct", default=None
    )
    if (
        preferences["autovrij"] is None
        and _metric(probe, "druk_data_beschikbaar", default=False)
        and autovrij_pct is not None
        and autovrij_pct < 40
    ):
        questions.append(
            {
                "id": "autovrij",
                "prioriteit": 3,
                "reden": (
                    f"de verkenningsroute is {autovrij_pct:g}% autovrij; "
                    "autovrije voorkeur onbekend"
                ),
                "vraag": (
                    "Wil je autovrije/verkeersarme wegen prioriteren? "
                    f"De verkenning zit op {autovrij_pct:g}% autovrij."
                ),
                "opties": {
                    value: {"patch": {"voorkeuren": {"autovrij": value}}}
                    for value in ("belangrijk", "ok")
                },
            }
        )

    if (_default_weights(profiel["gewichten"])
            and (d.get("route_request") or {}).get("doel") not in {"toeren", "kort"}):
        heat_pct = _metric(
            probe, "heat_dekking_pct", "populair_pct", default=None
        )
        if (
            activities.is_foot(profiel["activiteit"])
            and not _metric(
                probe, "wandelpopulariteit_beschikbaar", default=False
            )
        ):
            heat_pct = None
        weight_question = _weight_question(
            _metric(probe, "offroad_beschikbaar_pct", "offroad_pct"),
            heat_pct,
            profiel["activiteit"],
        )
        if weight_question is not None:
            questions.append(weight_question)

    if not preferences["vermijd_plaatsen"]:
        places = _passed_places(d, probe)
        if places:
            labels = [place["label"] for place in places]
            joined = ", ".join(labels)
            questions.append(
                {
                    "id": "vermijd_plaatsen",
                    "prioriteit": 5,
                    "reden": f"de verkenningsroute passeert deze plaatskernen: {joined}",
                    "vraag": (
                        f"Is de doorgang door {joined} overal oké, of wil je "
                        "zelf kiezen welke plaatsen de route vermijdt?"
                    ),
                    "opties": {
                        "ok": {
                            "doel": "draft",
                            "patch": {"allow_places": labels},
                        },
                        "kies_zelf": {
                            "doel": "draft",
                            "vervolg": (
                                "gebruik adjust_route met sta_plaatsen_toe en "
                                "vermijd_plaatsen"
                            ),
                        },
                    },
                }
            )

    request = d.get("route_request") or {}
    wens = USER_TEXT.get() if wens is None else wens
    composer_enabled = composer is not None or os.environ.get("LUSMAKER_QUESTION_COMPOSER", "regels") == "bedrock"
    if profiel["activiteit"] in {"wandelen", "wegloop", "stadsfiets"} and (wens or composer_enabled):
        pois = (probe.get("terrein") or {}).get("pois_langs_route") or {}
        for poi_id, label in (("speeltuin", "speeltuin"), ("toilet", "toilet")):
            count = pois.get(poi_id, 0)
            if isinstance(count, dict):
                count = count.get("aantal", 0)
            count = count or 0
            questions.append({
                "id": poi_id, "prioriteit": 6,
                "reden": f"de verkenning passeert {count} {label}{'en' if label == 'speeltuin' and count != 1 else ('ten' if label == 'toilet' and count != 1 else '')}",
                "vraag": f"Zijn {label}{'en' if label == 'speeltuin' else 'ten'} onderweg belangrijk?",
                "opties": {value: situational._patch(poi_id, value) for value in ("graag", "ok")},
            })

    # Wat de gebruiker al als criterium zei, vragen we niet opnieuw.
    known = {c["metriek"] for c in (d.get("route_request") or {}).get("criteria") or []}
    questions = [q for q in questions if not (_QUESTION_METRICS.get(q["id"], set()) & known)]
    questions.sort(key=lambda question: (question["prioriteit"], question["id"]))
    unknown = [question["id"] for question in questions]
    # ``klaar`` is een workflowbeslissing: zolang we nog een BLOKKERENDE vraag
    # teruggeven moet een MCP-client niet alvast gaan optimaliseren. De
    # plaatskern-vraag is niet-blokkerend: door een dorpskern rijden is normaal
    # voor een lus, dus die mag de eerste route (incl. preview) niet tegenhouden;
    # wie een plaats wil mijden zegt dat expliciet via adjust_route.
    non_blocking = {"vermijd_plaatsen"}
    blocking = [q for q in questions if q["id"] not in non_blocking]
    metrics = probe.get("terrein") or {}
    compose_context = {
        "activiteit": profiel.get("activiteit"), "doel": request.get("doel"),
        "doelafstand": request.get("target_km"), "wenstekst": wens,
        "metingen": {k: metrics[k] for k in ("pois_langs_route", "relief_m", "netwerk_in_buurt") if k in metrics},
    }
    visible = question_composer.compose(blocking, compose_context, provider=composer)
    visible = visible[:3]
    if blocking and blocking[0]["id"] == "plek_afstand" and (not visible or visible[0]["id"] != "plek_afstand"):
        visible = [blocking[0], *[q for q in visible if q["id"] != "plek_afstand"]][:3]
    selected_ids = {q["id"] for q in visible}
    for optional_id in ("speeltuin", "toilet"):
        if optional_id in unknown and optional_id not in selected_ids:
            unknown.remove(optional_id)
    ready = not any(q["id"] not in {"speeltuin", "toilet"} or q["id"] in selected_ids for q in blocking)
    if not visible:
        advice = "profiel is klaar; routeer nu met optimize"
    else:
        labels = {
            **situational.LABELS,
            "kasseien": "kasseivraag",
            "beton": "betonvraag",
            "steenwegen": "steenwegvraag",
            "autovrij": "autovrijvraag",
            "gewichten": "gewichten",
            "vermijd_plaatsen": "plaatsvraag",
            "plek_afstand": "afstandsvraag",
            "speeltuin": "speeltuinvraag",
            "toilet": "toiletvraag",
        }
        advice = f"stel de {labels[visible[0]['id']]} eerst"
        if len(visible) > 1:
            advice += "; " + ", ".join(
                f"{labels[question['id']]} daarna" for question in visible[1:]
            )

    return {
        "profiel": profiel["naam"],
        "onbekend": unknown,
        "vragen": visible,
        "klaar": ready,
        "advies": advice,
    }
