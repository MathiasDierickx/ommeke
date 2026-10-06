"""Situationele vragencatalogus: vraag alleen wat in DEZE situatie telt.

Elke rij beschrijft voor welke activiteiten de vraag geldt (en hoe relevant
ze daar is), welke meting van de verkenningsroute ze triggert, de drempel,
en welke patch/aanpassing een antwoord oplevert. De engine rangschikt de
getriggerde rijen op impact (relevantie x hoe ver de meting boven de drempel
ligt) en geeft elke vraag een concrete reden met het gemeten getal.

Een voorkeur die al een waarde heeft (``vermijd``, ``ok``, ...) wordt nooit
opnieuw gevraagd; ``None`` betekent onbekend en mag gevraagd worden.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import activities, profiles

# Een doel dat de gebruiker al koos hoeft niet opnieuw bevraagd te worden.
_EXPLICIT_GOALS = {"hoogtemeters", "offroad", "kort"}


def fmt(value: float, digits: int = 1) -> str:
    """Nederlandse getalnotatie (komma als decimaalteken)."""
    return f"{value:.{digits}f}".replace(".", ",")


def _metric(probe: dict, terrain_key: str, quality_key: str | None = None, default=None):
    terrain = probe.get("terrein") or {}
    quality = probe.get("kwaliteit") or {}
    if terrain_key in terrain and terrain[terrain_key] is not None:
        return terrain[terrain_key]
    value = quality.get(quality_key or terrain_key)
    return default if value is None else value


@dataclass(frozen=True)
class Context:
    activity: str                # canonieke activiteitssleutel
    km: float
    hm: float
    cobble_m: float | None
    unpaved_m: float | None
    cycleway_pct: float | None
    crossings: float | None
    places: int
    goal: str | None
    preferences: dict

    @property
    def km_m(self) -> float:
        return self.km * 1000.0

    @property
    def hm_per_km(self) -> float | None:
        return self.hm / self.km if self.km > 0 else None

    @property
    def paved_m(self) -> float | None:
        if self.unpaved_m is None or self.km <= 0:
            return None
        return max(self.km_m - self.unpaved_m, 0.0)


def context(d: dict, profiel: dict, probe: dict) -> Context:
    activity = activities.canonical(profiel.get("activiteit")) or activities.DEFAULT
    return Context(
        activity=activity,
        km=float(probe.get("km") or 0.0),
        hm=float(probe.get("hm") or 0.0),
        cobble_m=_metric(probe, "kassei_aanwezig_m", "kassei_m"),
        unpaved_m=_metric(probe, "onverhard_m", "onverhard_m"),
        cycleway_pct=_metric(probe, "fietspad_pct", "fietspad_pct"),
        crossings=_metric(probe, "kruisingen", "steenweg_kruisingen"),
        places=len((probe.get("terrein") or {}).get("plaatskernen") or []),
        goal=(d.get("route_request") or {}).get("doel"),
        preferences=profiles.effective_preferences(profiel, activity),
    )


@dataclass(frozen=True)
class Row:
    id: str
    key: str                                   # sleutel in profiel["voorkeuren"]
    relevance: Callable[[Context], float]      # 0 = niet van toepassing
    measure: Callable[[Context], float | None]
    threshold: Callable[[Context], float]
    reason: Callable[[Context], str]
    question: Callable[[Context], str]
    options: Callable[[Context], dict]
    triggered: Callable[[Context], bool] = lambda ctx: True  # extra voorwaarde
    label: str = ""
    inclusive: bool = False                    # drempel zelf telt al mee (>=)

    def impact(self, ctx: Context) -> float | None:
        """Impactscore, of None wanneer de vraag nu niet gesteld hoort te worden."""
        if ctx.preferences.get(self.key) is not None:
            return None
        relevance = self.relevance(ctx)
        if relevance <= 0 or not self.triggered(ctx):
            return None
        measured = self.measure(ctx)
        if measured is None:
            return None
        threshold = self.threshold(ctx)
        if threshold <= 0 or measured < threshold:
            return None
        if measured == threshold and not self.inclusive:
            return None
        return relevance * (measured / threshold)


def _patch(key: str, value: str, **adjust) -> dict:
    option = {"patch": {"voorkeuren": {key: value}}}
    if adjust:
        option["adjust_route"] = adjust
    return option


# -- kasseien -------------------------------------------------------------

_COBBLE_RELEVANCE = {
    "koersfiets": 1.0, "wegloop": 0.8, "stadsfiets": 0.8, "toerfiets": 0.7,
}


def _cobble_threshold(ctx: Context) -> float:
    return max(300.0, 0.02 * ctx.km_m)


def _cobble_reason(ctx: Context) -> str:
    share = ctx.cobble_m / ctx.km_m * 100 if ctx.km_m else 0.0
    return (
        f"{fmt(ctx.cobble_m / 1000)} km kasseien op je verkenningsroute "
        f"({fmt(share, 0)}% van {fmt(ctx.km)} km); kasseivoorkeur onbekend"
    )


KASSEIEN = Row(
    id="kasseien",
    key="kasseien",
    label="kasseivraag",
    relevance=lambda ctx: _COBBLE_RELEVANCE.get(ctx.activity, 0.0),
    measure=lambda ctx: ctx.cobble_m,
    threshold=_cobble_threshold,
    reason=_cobble_reason,
    question=lambda ctx: (
        f"Op je verkenningsroute liggen {fmt(ctx.cobble_m / 1000)} km kasseien. "
        "Vind je die leuk, zijn ze oké, of vermijd je ze liever?"
    ),
    options=lambda ctx: {
        value: _patch("kasseien", value) for value in ("graag", "ok", "vermijd")
    },
)


# -- heuvels --------------------------------------------------------------

def _hills_threshold(ctx: Context) -> float:
    activity = activities.get(ctx.activity)
    return activity.hills_hm_per_km if activity else 8.0


HEUVELS = Row(
    id="heuvels",
    key="heuvels",
    label="heuvelvraag",
    relevance=lambda ctx: 1.0,
    measure=lambda ctx: ctx.hm_per_km,
    threshold=_hills_threshold,
    triggered=lambda ctx: ctx.goal not in _EXPLICIT_GOALS,
    inclusive=True,
    reason=lambda ctx: (
        f"je verkenningsroute heeft {fmt(ctx.hm, 0)} hoogtemeters over "
        f"{fmt(ctx.km)} km ({fmt(ctx.hm_per_km)} hm/km); heuvelvoorkeur onbekend"
    ),
    question=lambda ctx: (
        f"Het is hier heuvelachtig ({fmt(ctx.hm, 0)} hoogtemeters op "
        f"{fmt(ctx.km)} km). Zoek je de heuvels op, maakt het niet uit, of "
        "hou je het liever zo vlak mogelijk?"
    ),
    # 'vlak' valt voorlopig terug op toeren: een echte vlakrangschikking
    # vraagt een eigen objective in de optimizer (zie issue #29, vervolg).
    options=lambda ctx: {
        "zoek": _patch("heuvels", "zoek", doel="hoogtemeters"),
        "ok": _patch("heuvels", "ok", doel="toeren"),
        "vlak": _patch("heuvels", "vlak", doel="toeren"),
    },
)


# -- ondergrond -----------------------------------------------------------

_PAVED_RELEVANCE = {
    "koersfiets": 1.0, "stadsfiets": 1.0, "wegloop": 1.0, "toerfiets": 0.8,
}
_UNPAVED_RELEVANCE = {"gravel": 1.0, "mtb": 1.0}


def _ground_relevance(ctx: Context) -> float:
    return (_PAVED_RELEVANCE | _UNPAVED_RELEVANCE).get(ctx.activity, 0.0)


def _ground_measure(ctx: Context) -> float | None:
    return ctx.paved_m if ctx.activity in _UNPAVED_RELEVANCE else ctx.unpaved_m


def _ground_threshold(ctx: Context) -> float:
    if ctx.activity in _UNPAVED_RELEVANCE:
        return 0.5 * ctx.km_m          # meer dan de helft verhard
    return min(1000.0, 0.10 * ctx.km_m)  # >1 km of >10% onverhard


def _ground_reason(ctx: Context) -> str:
    if ctx.activity in _UNPAVED_RELEVANCE:
        share = ctx.paved_m / ctx.km_m * 100
        return (
            f"{fmt(ctx.paved_m / 1000)} km ({fmt(share, 0)}%) van je "
            "verkenningsroute is verhard; ondergrondvoorkeur onbekend"
        )
    share = ctx.unpaved_m / ctx.km_m * 100
    return (
        f"{fmt(ctx.unpaved_m / 1000)} km ({fmt(share, 0)}%) van je "
        "verkenningsroute is onverhard; ondergrondvoorkeur onbekend"
    )


def _ground_question(ctx: Context) -> str:
    if ctx.activity in _UNPAVED_RELEVANCE:
        return (
            f"{fmt(ctx.paved_m / 1000)} km van je verkenningsroute is verhard. "
            "Wil je zoveel mogelijk onverhard, of is asfalt tussendoor oké?"
        )
    return (
        f"{fmt(ctx.unpaved_m / 1000)} km van je verkenningsroute is onverhard. "
        "Blijf je liever op verharde wegen, is onverhard oké, of zoek je het juist op?"
    )


def _ground_options(ctx: Context) -> dict:
    if ctx.activity in _UNPAVED_RELEVANCE:
        return {
            "onverhard": _patch("ondergrond", "onverhard", doel="offroad"),
            "ok": _patch("ondergrond", "ok"),
        }
    return {
        "verhard": _patch("ondergrond", "verhard"),
        "ok": _patch("ondergrond", "ok"),
        "onverhard": _patch("ondergrond", "onverhard", doel="offroad"),
    }


ONDERGROND = Row(
    id="ondergrond",
    key="ondergrond",
    label="ondergrondvraag",
    relevance=_ground_relevance,
    measure=_ground_measure,
    threshold=_ground_threshold,
    reason=_ground_reason,
    question=_ground_question,
    options=_ground_options,
)


# -- fietspaden -----------------------------------------------------------

_CYCLEWAY_RELEVANCE = {"stadsfiets": 1.0, "toerfiets": 0.6}
_CYCLEWAY_MIN_PCT = 15.0   # minder fietspad dan dit telt als 'weinig'


def _noncycleway_pct(ctx: Context) -> float | None:
    return None if ctx.cycleway_pct is None else 100.0 - ctx.cycleway_pct


FIETSPADEN = Row(
    id="fietspaden",
    key="fietspaden",
    label="fietspadenvraag",
    relevance=lambda ctx: _CYCLEWAY_RELEVANCE.get(ctx.activity, 0.0),
    measure=_noncycleway_pct,
    threshold=lambda ctx: 100.0 - _CYCLEWAY_MIN_PCT,
    # Alleen door bebouwde kom: op het platteland is een fietspad geen maatstaf.
    triggered=lambda ctx: ctx.places >= 1,
    inclusive=True,
    reason=lambda ctx: (
        f"slechts {fmt(ctx.cycleway_pct, 0)}% van je verkenningsroute is fietspad, "
        f"terwijl je door {ctx.places} bebouwde kernen rijdt; fietspadvoorkeur onbekend"
    ),
    question=lambda ctx: (
        f"Slechts {fmt(ctx.cycleway_pct, 0)}% van je verkenningsroute is fietspad, "
        "terwijl je door bebouwde kom rijdt. Wil je zoveel mogelijk op fietspaden "
        "rijden, of maakt het niet uit?"
    ),
    options=lambda ctx: {
        "belangrijk": _patch("fietspaden", "belangrijk"),
        "ok": _patch("fietspaden", "ok"),
    },
)


# -- oversteken -----------------------------------------------------------

_CROSSING_RELEVANCE = {"wandelen": 1.0, "wegloop": 0.8}
_CROSSING_MAX = 3.0


OVERSTEKEN = Row(
    id="oversteken",
    key="oversteken",
    label="oversteekvraag",
    relevance=lambda ctx: _CROSSING_RELEVANCE.get(ctx.activity, 0.0),
    measure=lambda ctx: ctx.crossings,
    threshold=lambda ctx: _CROSSING_MAX,
    reason=lambda ctx: (
        f"je verkenningsroute steekt {fmt(ctx.crossings, 0)} keer een drukke "
        "steenweg over; oversteekvoorkeur onbekend"
    ),
    question=lambda ctx: (
        f"Je verkenningsroute steekt {fmt(ctx.crossings, 0)} keer een drukke weg over. "
        "Wil je oversteken zoveel mogelijk vermijden, of is dat oké?"
    ),
    options=lambda ctx: {
        "vermijd": _patch("oversteken", "vermijd"),
        "ok": _patch("oversteken", "ok"),
    },
)


ROWS = (KASSEIEN, HEUVELS, ONDERGROND, FIETSPADEN, OVERSTEKEN)
LABELS = {row.id: row.label for row in ROWS}


def ask(d: dict, profiel: dict, probe: dict) -> list[dict]:
    """Getriggerde vragen, op impact gerangschikt (hoogste eerst).

    Elke vraag krijgt ``prioriteit`` = positie in die rangschikking, zodat
    ze samen met de overige readiness-vragen op dezelfde manier sorteren.
    """
    ctx = context(d, profiel, probe)
    scored = []
    for row in ROWS:
        impact = row.impact(ctx)
        if impact is not None:
            scored.append((impact, row))
    scored.sort(key=lambda item: (-item[0], item[1].id))
    return [
        {
            "id": row.id,
            "prioriteit": rank,
            "impact": round(impact, 2),
            "reden": row.reason(ctx),
            "vraag": row.question(ctx),
            "opties": row.options(ctx),
        }
        for rank, (impact, row) in enumerate(scored, start=1)
    ]


def start_place(query: str, candidates: list[dict], target: str = "start") -> dict:
    """Plaatskeuze vóór de locatieafhankelijke terreinvragen."""
    return {
        "id": "startplaats", "prioriteit": 1,
        "vraag": f"Welke {query} bedoel je?",
        "reden": "Er zijn meerdere plaatsen met deze naam.",
        "opties": {
            str(index): {"label": point["label"], "patch": {
                target: {key: point[key] for key in ("lat", "lon", "label")}
            }} for index, point in enumerate(candidates[:4])
        },
    }
