"""Pure readiness-regels voor incrementele routevoorkeuren."""

from __future__ import annotations


def _metric(probe: dict, terrain_key: str, quality_key: str | None = None, default=0):
    terrain = probe.get("terrein") or {}
    quality = probe.get("kwaliteit") or {}
    if terrain_key in terrain:
        return terrain[terrain_key]
    return quality.get(quality_key or terrain_key, default)


def _default_weights(weights: dict) -> bool:
    return (
        weights.get("hoogtemeters") == 1.0
        and weights.get("offroad") == 0.0
        and weights.get("populair") == 0.0
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
        "populaire wandelroutes" if activity == "trail" else "populaire fietswegen"
    )
    return {
        "id": "gewichten",
        "prioriteit": 4,
        "reden": reason,
        "vraag": (
            "Wat weegt voor jou het zwaarst: vooral klimmen, de beschikbare "
            f"onverharde stukken, of {popularity_label}?"
        ),
        "opties": options,
    }


def _passed_place(d: dict, probe: dict) -> dict | None:
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
    for place in (probe.get("terrein") or {}).get("plaatskernen", []):
        if str(place.get("label", "")).casefold() not in excluded:
            return place
    return None


def assess(d: dict, profiel: dict, climb_db: dict) -> dict:
    """Beoordeel welke routevoorkeuren nu materieel bevraagd moeten worden."""
    del climb_db  # de probe bevat de vooraf gefilterde klimpool al
    probe = d.get("_probe")
    if not isinstance(probe, dict):
        raise ValueError("draft heeft nog geen probe")

    preferences = profiel["voorkeuren"]
    questions = []
    cobble_m = _metric(probe, "kassei_aanwezig_m", "kassei_m")
    if preferences["kasseien"] is None and cobble_m > 300:
        questions.append(
            {
                "id": "kasseien",
                "prioriteit": 1,
                "reden": (
                    f"de verkenningsroute bevat {cobble_m / 1000:.1f} km "
                    "kasseien; kasseivoorkeur onbekend"
                ),
                "vraag": (
                    "Er liggen kasseistroken op het parcours. Vind je die leuk "
                    "(Flandrien!), oké, of vermijd je ze liever?"
                ),
                "opties": {
                    value: {"patch": {"voorkeuren": {"kasseien": value}}}
                    for value in ("graag", "ok", "vermijd")
                },
            }
        )

    concrete_m = _metric(probe, "beton_m", "beton_m")
    if (
        preferences["beton"] is None
        and profiel["activiteit"] == "fietsen"
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

    if _default_weights(profiel["gewichten"]):
        heat_pct = _metric(
            probe, "heat_dekking_pct", "populair_pct", default=None
        )
        if (
            profiel["activiteit"] == "trail"
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
        place = _passed_place(d, probe)
        if place is not None:
            label = place["label"]
            questions.append(
                {
                    "id": "vermijd_plaatsen",
                    "prioriteit": 5,
                    "reden": f"de verkenningsroute passeert de plaatskern van {label}",
                    "vraag": f"Is de doorgang door {label} oké, of wil je die plaats vermijden?",
                    "opties": {
                        "ok": {
                            "doel": "draft",
                            "patch": {"allow_place": label},
                        },
                        "vermijd": {
                            "doel": "draft",
                            "patch": {"avoid_place": label},
                        },
                    },
                }
            )

    questions.sort(key=lambda question: (question["prioriteit"], question["id"]))
    unknown = [question["id"] for question in questions]
    # ``klaar`` is een workflowbeslissing: zolang we nog een concrete vraag
    # teruggeven moet een MCP-client niet alvast gaan optimaliseren.
    ready = not questions
    visible = questions[:3]
    if not visible:
        advice = "profiel is klaar; routeer nu met optimize"
    else:
        labels = {
            "kasseien": "kasseivraag",
            "beton": "betonvraag",
            "steenwegen": "steenwegvraag",
            "gewichten": "gewichten",
            "vermijd_plaatsen": "plaatsvraag",
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
