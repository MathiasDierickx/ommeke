"""Activiteitencatalogus: wandelen, lopen en fietsen zonder persoonlijke voorkeur.

Elke activiteit hoort bij een bestaand GraphHopper-profiel (``quiet`` voor
fietsen, ``trail`` voor te voet) en voegt per verzoek een klein stukje
custom model toe. Er zijn dus geen extra profielen of graph-herimport nodig.

Regels voor de fragmenten: uitsluitend ``priority``-straffen (factor <= 1,
nooit onder 0,3) op encoded values die al in de graph zitten (surface,
road_class, smoothness, track_type, mtb_rating, bike_network, max_speed).
Het ingebakken ``quiet.json`` straft onverhard al met 0,30; gravel en mtb
kunnen dat niet terugdraaien en straffen daarom het verharde alternatief,
zodat de verhouding verschuift. Echte profielen volgen met een graph-herbouw.
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_FACTOR = 0.3

# Hardwired gedrag van de oorspronkelijke ``trail``-activiteit: straten hard
# afstraffen zodat paden en tracks winnen.
TRAIL_PRIORITY = (
    {"if": "road_class == SECONDARY", "multiply_by": "0.25"},
    {"else_if": "road_class == TERTIARY", "multiply_by": "0.35"},
    {"else_if": "road_class == RESIDENTIAL", "multiply_by": "0.55"},
    {"else_if": "road_class == UNCLASSIFIED", "multiply_by": "0.70"},
)

_PAVED = "surface == ASPHALT || surface == CONCRETE || surface == PAVED"
_UNPAVED = (
    "surface == GRAVEL || surface == DIRT || surface == GRASS || "
    "surface == SAND || surface == GROUND"
)
_ROUGH = "smoothness == BAD || smoothness == VERY_BAD || smoothness == HORRIBLE"


# Extra zachte straffen voor een expliciete verharde rit, naast de activiteit.
PREFER_PAVED_PRIORITY = (
    {"if": _UNPAVED, "multiply_by": "0.30"},
    {"if": "track_type == GRADE2 || track_type == GRADE3 || track_type == GRADE4 || track_type == GRADE5", "multiply_by": "0.30"},
    {"if": _ROUGH, "multiply_by": "0.50"},
)


@dataclass(frozen=True)
class Activity:
    key: str
    label: str
    profile: str          # bestaand GraphHopper-profiel: "quiet" of "trail"
    mode: str             # "fiets" of "voet"
    ground: str           # "verhard", "onverhard" of "gemengd"
    heat: str | None      # sleutel in heat.ACTIVITIES, indien aanwezig
    priority: tuple = ()  # request-time custom-model fragmenten
    hills_hm_per_km: float = 8.0  # drempel voor de heuvelvraag


CATALOG: dict[str, Activity] = {
    activity.key: activity
    for activity in (
        Activity(
            "wandelen", "Wandelen", "trail", "voet", "gemengd", "wandelen",
            (
                {"if": "road_class == SECONDARY", "multiply_by": "0.40"},
                {"else_if": "road_class == TERTIARY", "multiply_by": "0.60"},
                {"if": "max_speed >= 70", "multiply_by": "0.50"},
            ),
            hills_hm_per_km=12.0,
        ),
        Activity(
            "trail", "Trail", "trail", "voet", "onverhard", "trail",
            TRAIL_PRIORITY, hills_hm_per_km=12.0,
        ),
        Activity(
            "wegloop", "Wegloop", "trail", "voet", "verhard", "wegloop",
            (
                {"if": _UNPAVED, "multiply_by": "0.50"},
                {"if": _ROUGH, "multiply_by": "0.60"},
            ),
            hills_hm_per_km=12.0,
        ),
        Activity(
            "stadsfiets", "Stadsfiets", "quiet", "fiets", "verhard", "stadsfiets",
            ({"if": _ROUGH, "multiply_by": "0.60"},),
        ),
        Activity(
            "toerfiets", "Toerfiets", "quiet", "fiets", "verhard", None, (),
        ),
        Activity(
            "koersfiets", "Koersfiets", "quiet", "fiets", "verhard", "koersfiets",
            ({"if": _ROUGH, "multiply_by": "0.50"},),
        ),
        Activity(
            "gravel", "Gravel", "quiet", "fiets", "onverhard", "gravel",
            (
                {"if": _PAVED, "multiply_by": "0.50"},
                {"if": "mtb_rating >= 3", "multiply_by": "0.50"},
            ),
        ),
        Activity(
            "mtb", "MTB", "quiet", "fiets", "onverhard", "mtb",
            ({"if": _PAVED, "multiply_by": "0.40"},),
        ),
    )
}

# Oudere verzoeken, profielen en clients gebruiken nog "fietsen".
LEGACY_ALIASES = {"fietsen": "toerfiets"}
KEYS = tuple(CATALOG)
ACCEPTED = KEYS + tuple(LEGACY_ALIASES)
DEFAULT = "toerfiets"


def canonical(key: str | None) -> str | None:
    """Zet een oude naam om naar de catalogussleutel (onbekend blijft None)."""
    if key is None:
        return None
    key = LEGACY_ALIASES.get(key, key)
    return key if key in CATALOG else None


def get(key: str | None) -> Activity | None:
    return CATALOG.get(canonical(key) or "")


def graph_profile(key: str | None) -> str:
    activity = get(key)
    return activity.profile if activity else "quiet"


def is_foot(key: str | None) -> bool:
    activity = get(key)
    return bool(activity and activity.mode == "voet")


def priority_fragment(key: str | None) -> list[dict]:
    """Custom-model regels voor deze activiteit (kopie, veilig om te muteren)."""
    activity = get(key)
    return [dict(rule) for rule in activity.priority] if activity else []


def options() -> list[dict]:
    return [
        {"waarde": a.key, "label": a.label, "profiel": a.profile}
        for a in CATALOG.values()
    ]
