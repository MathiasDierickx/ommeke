"""Vertaal meetbare routecriteria naar GraphHopper-prioriteiten."""

from __future__ import annotations

from . import activities

_UNPAVED = "surface == GRAVEL || surface == DIRT || surface == GRASS || surface == SAND || surface == GROUND || surface == UNPAVED || surface == COMPACTED || surface == FINE_GRAVEL"


def priority_rules(criteria: list[dict] | None, *, profile: str) -> list[dict]:
    """Maak zachte routevoorkeuren; criteria zonder passende EV blijven score-only."""
    rules = []
    for item in criteria or []:
        metric, direction = item["metriek"], item["richting"]
        weight = min(1.0, max(0.0, float(item.get("gewicht", 0))))
        factor = 0.15 if item.get("hard") else max(0.35, 1 - 0.6 * weight)
        conditions = {
            ("stil", "hoog"): [("road_class == PRIMARY || road_class == SECONDARY", factor), ("road_class == TERTIARY", 1 - (1 - factor) / 2)],
            ("autovrij", "hoog"): [("road_class == PRIMARY || road_class == SECONDARY", factor), ("road_class == TERTIARY", 1 - (1 - factor) / 2)],
            ("steenweg", "laag"): [("road_class == PRIMARY || road_class == SECONDARY", factor)],
            ("kassei", "laag"): [("surface == COBBLESTONE", factor)],
            ("beton", "laag"): [("surface == CONCRETE", factor)],
            ("onverhard", "laag"): [(_UNPAVED, factor)],
            ("onverhard", "hoog"): [("surface == ASPHALT || surface == CONCRETE || surface == PAVED", 0.15 if item.get("hard") else max(0.6, 1 - 0.4 * weight))],
            ("offroad", "hoog"): [("surface == ASPHALT || surface == CONCRETE || surface == PAVED", 0.15 if item.get("hard") else max(0.6, 1 - 0.4 * weight))],
            ("fietspad", "hoog"): [("road_class != CYCLEWAY && bike_network == MISSING", factor)],
        }.get((metric, direction), [])
        if metric == "knooppunt" and direction == "hoog" and profile == "quiet":
            conditions = [("bike_network == MISSING", factor)]
        rules.extend({"if": condition, "multiply_by": f"{value:.6g}"} for condition, value in conditions)
    return rules
