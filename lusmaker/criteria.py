"""Criteria op maat: een gewogen scorelijst die het gesprek opstelt en de engine uitvoert.

Een criterium is klein en deterministisch::

    {"id": "rustig", "label": "Rustig, weinig auto's", "metriek": "stil",
     "richting": "hoog", "gewicht": 0.4, "hard": false, "drempel": 0.5}

``metriek`` komt altijd uit ``METRICS``; het taalmodel mag labels en gewichten
kiezen, geen metrieken. De score over kandidaten is de gewogen som van de
genormaliseerde metrieken (0..1), zachte criteria tellen mee, harde criteria
sluiten een kandidaat uit die zijn drempel niet haalt. Dezelfde lijst levert
de "waarom deze route"-regels op de eindroute.
"""

from __future__ import annotations

import math
import re

RICHTINGEN = ("hoog", "laag")
_ID_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
MAX_CRITERIA = 8


class CriteriaError(ValueError):
    """Ongeldige criterialijst."""


def _pct(key):
    return lambda q, c: None if q.get(key) is None else q[key] / 100.0


def _pct_text(q, key, suffix):
    return f"{q.get(key) or 0:g} % {suffix}".replace(".", ",")


def _meters(key):
    def value(q, c):
        km = c.get("total_km") or 0.0
        return None if q.get(key) is None or km <= 0 else min(1.0, q[key] / (km * 1000.0))
    return value


def _ascend_per_km(q, c):
    km = c.get("total_km") or 0.0
    if km <= 0 or c.get("ascend_m") is None:
        return None
    return min(1.0, c["ascend_m"] / km / 20.0)


def _poi_count(c, *kinds):
    pois = c.get("pois") or {}
    return sum(int(pois.get(kind) or 0) for kind in kinds)


def _poi_value(*kinds):
    return lambda q, c: None if c.get("pois") is None else min(1.0, _poi_count(c, *kinds) / 2.0)


def _poi_text(kind, singular, plural, *extra):
    def text(q, c):
        n = _poi_count(c, kind, *extra)
        return f"{n} {singular if n == 1 else plural} langs de route"
    return text


def _crossings(q, c):
    n = q.get("steenweg_kruisingen")
    return None if n is None else min(1.0, n / 10.0)


# id -> (label, kandidaatcomponent (None = alleen uitleg/hard op eindroute), waarde op eindroute, hoe te tonen)
METRICS = {
    "hoogtemeters": ("Hoogtemeters", "hoogtemeters", _ascend_per_km, lambda q, c: f"{round(c.get('ascend_m') or 0)} m"),
    "kort": ("Korte omweg", "kort", None, None),
    "offroad": ("Paden en onverharde wegen", "offroad", _pct("offroad_pct"), lambda q, c: _pct_text(q, "offroad_pct", "pad")),
    "onverhard": ("Onverhard", "onverhard", _meters("onverhard_m"), lambda q, c: f"{(q.get('onverhard_m') or 0) / 1000:.1f} km onverhard".replace(".", ",")),
    "populair": ("Populaire wegen", "populair", _pct("populair_pct"), lambda q, c: _pct_text(q, "populair_pct", "bekende wegen")),
    "autovrij": ("Autovrij", "autovrij", _pct("autovrij_pct"), lambda q, c: _pct_text(q, "autovrij_pct", "autovrij")),
    "stil": ("Rustige wegen", "stil", _pct("stil_pct"), lambda q, c: _pct_text(q, "stil_pct", "rustige wegen")),
    "kassei": ("Kasseien", "kassei", _meters("kassei_m"), lambda q, c: f"{(q.get('kassei_m') or 0) / 1000:.1f} km kassei".replace(".", ",")),
    "beton": ("Betonbanen", "beton", _meters("beton_m"), lambda q, c: f"{(q.get('beton_m') or 0) / 1000:.1f} km beton".replace(".", ",")),
    "steenweg": ("Steenwegen", "steenweg", _meters("steenweg_m"), lambda q, c: f"{(q.get('steenweg_m') or 0) / 1000:.1f} km steenweg".replace(".", ",")),
    "fietspad": ("Fietspaden", "fietspad", _pct("fietspad_pct"), lambda q, c: _pct_text(q, "fietspad_pct", "fietspad")),
    "oversteken": ("Drukke oversteken", None, _crossings, lambda q, c: f"{q.get('steenweg_kruisingen') or 0} drukke oversteken"),
    # Voorzieningen langs de route (Toerisme Vlaanderen-lagen), alleen uitleg/hard op de eindroute.
    "toilet": ("Toilet onderweg", None, _poi_value("toilet"), _poi_text("toilet", "toilet", "toiletten")),
    "speeltuin": ("Speeltuin onderweg", None, _poi_value("speeltuin"), _poi_text("speeltuin", "speeltuin", "speeltuinen")),
    "zitbank": ("Bankje onderweg", None, _poi_value("zitbank", "picknickbank"), _poi_text("zitbank", "bankje", "bankjes", "picknickbank")),
}
# Natuurlijke richting per metriek. Vast = de andere richting is nooit zinvol
# ('weinig rustige wegen' wil niemand); standaard = overschrijfbaar (kasseien graag, vlak).
FIXED_DIRECTION = {"stil": "hoog", "autovrij": "hoog", "fietspad": "hoog", "kort": "hoog",
                   "toilet": "hoog", "speeltuin": "hoog", "zitbank": "hoog"}
DEFAULT_DIRECTION = {"kassei": "laag", "beton": "laag", "steenweg": "laag", "oversteken": "laag",
                     "hoogtemeters": "hoog", "offroad": "hoog", "onverhard": "hoog", "populair": "hoog"}
# Standaarddrempel voor de uitleg wanneer het criterium er geen meegeeft.
_DEFAULT_THRESHOLD = {"hoog": 0.4, "laag": 0.1}


def parse(raw) -> list[dict]:
    """Valideer en normaliseer een criterialijst (gewichten op som 1)."""
    if not isinstance(raw, list) or not raw:
        raise CriteriaError("criteria moet een niet-lege lijst zijn")
    if len(raw) > MAX_CRITERIA:
        raise CriteriaError(f"maximaal {MAX_CRITERIA} criteria")
    out, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            raise CriteriaError("elk criterium moet een object zijn")
        metric = item.get("metriek")
        if metric not in METRICS:
            raise CriteriaError(f"onbekende metriek: {metric!r}; kies uit {', '.join(METRICS)}")
        cid = item.get("id") or metric
        if not isinstance(cid, str) or not _ID_RE.fullmatch(cid):
            raise CriteriaError("criterium-id gebruikt 1-32 kleine letters, cijfers, _ of -")
        if cid in seen:
            raise CriteriaError(f"criterium {cid} staat dubbel")
        seen.add(cid)
        direction = item.get("richting") or DEFAULT_DIRECTION.get(metric, "hoog")
        if direction not in RICHTINGEN:
            raise CriteriaError("richting moet 'hoog' of 'laag' zijn")
        direction = FIXED_DIRECTION.get(metric, direction)
        weight = item.get("gewicht", 1.0)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight) or weight < 0:
            raise CriteriaError("gewicht moet een getal >= 0 zijn")
        hard = item.get("hard", False)
        if not isinstance(hard, bool):
            raise CriteriaError("hard moet true of false zijn")
        threshold = item.get("drempel")
        if threshold is not None and (isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1):
            raise CriteriaError("drempel ligt tussen 0 en 1")
        if hard and threshold is None:
            raise CriteriaError(f"hard criterium {cid} vereist een drempel")
        label = item.get("label") or METRICS[metric][0]
        if not isinstance(label, str) or not 1 <= len(label) <= 80:
            raise CriteriaError("label is 1-80 tekens")
        out.append({"id": cid, "label": label, "metriek": metric, "richting": direction,
                    "gewicht": float(weight), "hard": hard, "drempel": threshold})
    # Alleen zachte, op kandidaten meetbare criteria normaliseren; een lijst met enkel
    # harde of uitleg-criteria (bv. alleen 'oversteken') is geldig en scoort 0 voor iedereen.
    total = sum(c["gewicht"] for c in out if not c["hard"] and METRICS[c["metriek"]][1])
    for c in out:
        c["gewicht"] = round(c["gewicht"] / total, 6) if total > 0 and not c["hard"] else c["gewicht"]
    return out


def from_weights(weights: dict) -> list[dict]:
    """Legacy profielgewichten (hoogtemeters/offroad/populair/autovrij/kort) als criteria."""
    return [{"id": k, "label": METRICS[k][0], "metriek": k, "richting": "hoog",
             "gewicht": float(v), "hard": False, "drempel": None}
            for k, v in weights.items() if v]


def from_goal(doel: str | None) -> list[dict]:
    """Het oude ``doel`` als criterialijst, voor de uitleg van routes zonder criteria."""
    metric = {"hoogtemeters": "hoogtemeters", "offroad": "offroad", "kort": "kort"}.get(doel)
    return [] if metric is None else from_weights({metric: 1.0})


# Antwoord op een situationele vraag -> criterium (id = vraagsleutel, zodat een
# nieuw antwoord het vorige vervangt). 'ok' betekent onverschillig: geen criterium.
ANSWER_CRITERIA = {
    ("kasseien", "vermijd"): {"metriek": "kassei", "richting": "laag", "gewicht": 1.0, "hard": True, "drempel": 0.05, "label": "Geen kasseien"},
    ("kasseien", "graag"): {"metriek": "kassei", "richting": "hoog", "gewicht": 0.5, "label": "Kasseien, graag"},
    ("heuvels", "zoek"): {"metriek": "hoogtemeters", "richting": "hoog", "gewicht": 1.0, "label": "Heuvels opzoeken"},
    ("heuvels", "vlak"): {"metriek": "hoogtemeters", "richting": "laag", "gewicht": 1.0, "label": "Zo vlak mogelijk"},
    ("ondergrond", "onverhard"): {"metriek": "onverhard", "richting": "hoog", "gewicht": 1.0, "label": "Onverharde paden"},
    ("ondergrond", "verhard"): {"metriek": "onverhard", "richting": "laag", "gewicht": 1.0, "label": "Verhard"},
    ("fietspaden", "belangrijk"): {"metriek": "fietspad", "richting": "hoog", "gewicht": 1.0, "label": "Fietspaden"},
    ("oversteken", "vermijd"): {"metriek": "oversteken", "richting": "laag", "gewicht": 1.0, "drempel": 0.3, "label": "Weinig drukke oversteken"},
    ("stil", "belangrijk"): {"metriek": "stil", "richting": "hoog", "gewicht": 1.0, "drempel": 0.6, "label": "Rustige wegen"},
}


def from_answers(antwoorden: dict) -> list[dict]:
    """Criteria die uit knopantwoorden volgen (zonder normalisatie)."""
    out = []
    for key, value in antwoorden.items():
        spec = ANSWER_CRITERIA.get((key, value))
        if spec:
            out.append({"id": key, **spec})
    return out


def merge(existing: list[dict] | None, extra: list[dict], dropped: set[str] = frozenset()) -> list[dict] | None:
    """Voeg criteria samen op id (nieuw wint), laat `dropped` ids weg en normaliseer opnieuw."""
    by_id = {c["id"]: c for c in (existing or [])}
    for criterion in extra:
        by_id[criterion["id"]] = criterion
    for cid in dropped:
        by_id.pop(cid, None)
    return parse(list(by_id.values())) if by_id else None


GOAL_WEIGHT = 2.0  # een uitgesproken doel (zoveel mogelijk hoogtemeters) weegt dubbel t.o.v. een knopantwoord


def with_goal(spec: list[dict] | None, doel: str | None) -> list[dict] | None:
    """Zorg dat het routedoel (hoogtemeters/offroad/kort) in de criteria zit.

    Een antwoord als 'rustig' mag het doel niet verdringen: zonder deze stap
    koos de optimizer bij doel=hoogtemeters een vlakke, stille polderlus.
    """
    goal = from_goal(doel)
    if not goal:
        return spec
    if not spec:
        return parse(goal)
    metric = goal[0]["metriek"]
    if any(c["metriek"] == metric for c in spec):
        return spec
    goal[0]["gewicht"] = GOAL_WEIGHT * max((c["gewicht"] for c in spec if not c["hard"]), default=1.0)
    return merge(spec, goal)


def _value(criterion: dict, components: dict) -> float | None:
    component = METRICS[criterion["metriek"]][1]
    if component is None or components.get(component) is None:
        return None
    raw = min(1.0, max(0.0, float(components[component])))
    return raw if criterion["richting"] == "hoog" else 1.0 - raw


def passes(criterion: dict, value: float | None) -> bool | None:
    """Haalt een (al naar richting gedraaide) waarde de drempel? None = onbekend."""
    if value is None:
        return None
    threshold = criterion["drempel"]
    if threshold is None:
        threshold = _DEFAULT_THRESHOLD[criterion["richting"]]
    # Voor 'laag' is de gedraaide waarde 1 - raw, dus raw <= drempel <=> value >= 1 - drempel.
    return value >= threshold if criterion["richting"] == "hoog" else value >= 1.0 - threshold


def score(criteria: list[dict], components: dict) -> float | None:
    """Gewogen score van één kandidaat; None als een hard criterium faalt."""
    total = 0.0
    for criterion in criteria:
        value = _value(criterion, components)
        if criterion["hard"]:
            if passes(criterion, value) is False:
                return None
            continue
        if value is not None:
            total += criterion["gewicht"] * value
    return total


def weights(criteria: list[dict]) -> dict:
    """Legacy gewichtendict over de profielsleutels (voor bestaande checks)."""
    from .profiles import WEIGHT_KEYS

    out = {key: 0.0 for key in WEIGHT_KEYS}
    for criterion in criteria:
        if criterion["metriek"] in out and not criterion["hard"]:
            out[criterion["metriek"]] += criterion["gewicht"]
    return out


def is_pure(criteria: list[dict], metric: str) -> bool:
    soft = [c for c in criteria if not c["hard"]]
    return len(soft) == 1 and soft[0]["metriek"] == metric and soft[0]["richting"] == "hoog"


def explain(criteria: list[dict], quality: dict | None, computed: dict | None) -> list[dict]:
    """'Waarom deze route'-regels: per criterium gemeten waarde en of hij gehaald is."""
    quality, computed = quality or {}, computed or {}
    lines = []
    for criterion in criteria:
        _label, _component, final_value, shown = METRICS[criterion["metriek"]]
        if final_value is None:
            continue
        raw = final_value(quality, computed)
        value = None if raw is None else (raw if criterion["richting"] == "hoog" else 1.0 - min(1.0, max(0.0, raw)))
        ok = passes(criterion, value)
        lines.append({
            "id": criterion["id"], "label": criterion["label"], "hard": criterion["hard"],
            "waarde": None if raw is None else round(raw, 3),
            "tekst": "niet gemeten" if raw is None else shown(quality, computed),
            "ok": ok,
        })
    return lines
