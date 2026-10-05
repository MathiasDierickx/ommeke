"""Deterministische backstop voor zwakkere modellen.

Herkent een handvol ondubbelzinnige uitdrukkingen in de eerste vraag en vult
daarmee uitsluitend ontbrekende (``None``) plan_route-argumenten aan. Een
waarde die het model of de gebruiker al gaf wordt nooit overschreven, en bij
twijfel blijft het veld leeg: de situationele vragen doen de rest.
"""

from __future__ import annotations

import re
import unicodedata


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


# (patroon, argumenten die het oplevert); eerste treffer per groep wint.
_ACTIVITY_RULES = (
    (r"\b(mtb|mountainbike\w*|mountain bike)\b", "mtb"),
    (r"\b(racefiets\w*|koersfiets\w*|wielertoerist\w*)\b", "koersfiets"),
    (r"\bgravel\w*\b", "gravel"),
    (r"\bstadsfiets\w*\b", "stadsfiets"),
    (r"\b(toerfiets\w*)\b", "toerfiets"),
    (r"\b(traillus\w*|trailrun\w*|trail)\b", "trail"),
    (r"\b(wegloop\w*|hardlopen op asfalt)\b", "wegloop"),
    (r"\b(kinderwagen\w*|buggy|wandeling\w*|wandelen|wandel\w*)\b", "wandelen"),
)

_FLAT = r"\b(vlak|vlakke|zonder heuvels|geen heuvels|geen hellingen|zonder klimmen|geen klimmen)\b"
_HILLY = r"\b(heuvelachtig\w*|heuvelrit\w*|bergop|veel klimmen|zoveel mogelijk (hoogtemeters|klimmen))\b"
_NO_COBBLES = r"\b(geen|zonder|vermijd\w*|liever niet over|niet over) kasseien\b"
_STROLLER = r"\b(kinderwagen\w*|buggy)\b"


def hints(text: str) -> dict:
    """Leid veilige plan_route-argumenten af uit vrije tekst."""
    folded = _fold(text or "")
    found: dict = {}
    for pattern, activity in _ACTIVITY_RULES:
        if re.search(pattern, folded):
            found["activiteit"] = activity
            break
    if re.search(_FLAT, folded):
        found["heuvels"] = "vlak"
    elif re.search(_HILLY, folded):
        found["heuvels"] = "zoek"
    if re.search(_NO_COBBLES, folded):
        found["kasseien"] = False  # plan_route: False = vermijden
    if re.search(_STROLLER, folded):
        found["ondergrond"] = "verhard"
        found.setdefault("heuvels", "vlak")
    return found


def apply(values: dict, text: str) -> dict:
    """Vul alleen ontbrekende of ``None``-waarden aan; geef een kopie terug."""
    result = dict(values)
    for key, value in hints(text).items():
        if result.get(key) is None:
            result[key] = value
    return result
