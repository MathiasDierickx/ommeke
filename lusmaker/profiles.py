"""Persistente, regio-onafhankelijke gebruikersvoorkeuren."""

from __future__ import annotations

import copy
import json
import math
import re
from datetime import datetime

from . import activities, aws_state, config


WEIGHT_KEYS = ("hoogtemeters", "offroad", "populair", "autovrij", "kort")
PREFERENCE_VALUES = {None, "vermijd", "ok", "graag"}
AUTOVRIJ_VALUES = {None, "belangrijk", "ok"}
HEUVELS_VALUES = {None, "zoek", "ok", "vlak"}
ONDERGROND_VALUES = {None, "verhard", "ok", "onverhard"}
# Nullable situationele voorkeuren: null = onbekend (mag gevraagd worden),
# "ok" = expliciet onverschillig (nooit meer vragen, niets wijzigen).
OPTIONAL_PREFERENCES = ("heuvels", "ondergrond")
# Sleutels van ``voorkeuren`` die per activiteit kunnen verschillen
# (``vermijd_plaatsen`` is activiteitsneutraal en blijft bovenaan staan).
ACTIVITY_PREFERENCE_KEYS = (
    "kasseien", "beton", "steenwegen", "autovrij", "heuvels", "ondergrond",
)
_NAME_RE = re.compile(r"^[\w-]+$", re.UNICODE)


class ProfileError(RuntimeError):
    """Ongeldig profiel of ongeldige profielwijziging."""


def _path(name: str):
    if not isinstance(name, str) or not name or not _NAME_RE.fullmatch(name):
        raise ProfileError("profielnaam gebruikt alleen letters, cijfers, _ of -")
    return config.profiles_path() / f"{name}.json"


def default_document(name: str = "standaard") -> dict:
    _path(name)  # valideer ook namen van nog niet opgeslagen profielen
    return {
        "naam": name,
        "activiteit": "fietsen",
        "gewichten": {
            "hoogtemeters": 1.0,
            "offroad": 0.0,
            "populair": 0.0,
            "autovrij": 0.0,
            "kort": 0.0,
        },
        "voorkeuren": {
            "kasseien": None,
            "beton": None,
            "steenwegen": None,
            "autovrij": None,
            "heuvels": None,
            "ondergrond": None,
            "vermijd_plaatsen": [],
        },
        "voorkeuren_per_activiteit": {},
        "historiek": [],
    }


def normalize_weights(weights: dict) -> dict:
    if not isinstance(weights, dict) or not weights:
        raise ProfileError("gewichten moeten een niet-lege dict zijn")
    unknown = set(weights) - set(WEIGHT_KEYS)
    if unknown:
        raise ProfileError(f"onbekend gewicht: {sorted(unknown)[0]}")
    values = {}
    for key in WEIGHT_KEYS:
        raw = weights.get(key, 0.0)
        if isinstance(raw, bool):
            raise ProfileError(f"gewicht '{key}' moet een getal zijn")
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ProfileError(f"gewicht '{key}' moet een getal zijn") from exc
        if not math.isfinite(value):
            raise ProfileError(f"gewicht '{key}' moet eindig zijn")
        if value < 0:
            raise ProfileError("gewichten mogen niet negatief zijn")
        values[key] = value
    total = sum(values.values())
    if total <= 0:
        raise ProfileError("som van gewichten moet groter dan 0 zijn")
    return {key: value / total for key, value in values.items()}


def _check_preference_value(key: str, value) -> None:
    if key in ("kasseien", "beton", "steenwegen"):
        if key == "steenwegen" and value == "graag":
            raise ProfileError("steenwegen ondersteunt 'graag' niet")
        if value not in PREFERENCE_VALUES:
            raise ProfileError(f"{key}: ongeldige waarde {value!r}")
    elif key == "autovrij":
        if value not in AUTOVRIJ_VALUES:
            raise ProfileError(f"autovrij: ongeldige waarde {value!r}")
    elif key == "heuvels":
        if value not in HEUVELS_VALUES:
            raise ProfileError(f"heuvels: ongeldige waarde {value!r}")
    elif key == "ondergrond":
        if value not in ONDERGROND_VALUES:
            raise ProfileError(f"ondergrond: ongeldige waarde {value!r}")


def _validate_per_activity(raw) -> dict:
    """Valideer {activiteit: {voorkeur: waarde}} en zet namen om naar catalogussleutels."""
    if not isinstance(raw, dict):
        raise ProfileError("voorkeuren_per_activiteit moet een object zijn")
    result: dict = {}
    for activity, preferences in raw.items():
        key = activities.canonical(activity)
        if key is None:
            raise ProfileError(f"onbekende activiteit in voorkeuren_per_activiteit: {activity}")
        if not isinstance(preferences, dict):
            raise ProfileError(f"voorkeuren voor {activity} moeten een object zijn")
        unknown = set(preferences) - set(ACTIVITY_PREFERENCE_KEYS)
        if unknown:
            raise ProfileError(f"onbekende voorkeur voor {activity}: {sorted(unknown)[0]}")
        for name, value in preferences.items():
            _check_preference_value(name, value)
        result.setdefault(key, {}).update(preferences)
    return result


def effective_preferences(profile: dict, activity: str | None = None) -> dict:
    """Voorkeuren die voor ``activity`` gelden.

    De top-level ``voorkeuren`` zijn de terugval voor fietsactiviteiten
    (zo werkten bestaande profielen altijd); voor wandelen en lopen lekken
    ze niet door. ``voorkeuren_per_activiteit`` wint altijd. Plaatsen om te
    vermijden zijn activiteitsneutraal en blijven altijd gelden.
    """
    key = activities.canonical(activity or profile.get("activiteit")) or activities.DEFAULT
    base = profile["voorkeuren"]
    if activities.is_foot(key):
        effective = {name: None for name in ACTIVITY_PREFERENCE_KEYS}
        effective["vermijd_plaatsen"] = list(base.get("vermijd_plaatsen", []))
    else:
        effective = copy.deepcopy(base)
    overrides = (profile.get("voorkeuren_per_activiteit") or {}).get(key) or {}
    effective.update(overrides)
    return effective


def _validate(profile: dict, expected_name: str | None = None) -> dict:
    if not isinstance(profile, dict):
        raise ProfileError("profiel moet een object zijn")
    # T16 voegt velden toe aan bestaande profielbestanden. Vul uitsluitend
    # deze nieuwe defaults aan; de overige exacte-schema-validatie blijft.
    profile = copy.deepcopy(profile)
    if isinstance(profile.get("gewichten"), dict):
        profile["gewichten"].setdefault("autovrij", 0.0)
    if isinstance(profile.get("voorkeuren"), dict):
        profile["voorkeuren"].setdefault("autovrij", None)
        for key in OPTIONAL_PREFERENCES:
            profile["voorkeuren"].setdefault(key, None)
    # Optioneel in oudere bestanden: ontbrekend betekent geen overrides.
    profile.setdefault("voorkeuren_per_activiteit", {})
    required = {
        "naam", "activiteit", "gewichten", "voorkeuren",
        "voorkeuren_per_activiteit", "historiek",
    }
    if set(profile) != required:
        raise ProfileError("profiel bevat ontbrekende of onbekende velden")
    name = profile["naam"]
    _path(name)
    if expected_name is not None and name != expected_name:
        raise ProfileError("profielnaam komt niet overeen met de bestandsnaam")
    if profile["activiteit"] not in activities.ACCEPTED:
        raise ProfileError(
            "activiteit moet een van deze zijn: " + ", ".join(activities.KEYS)
        )
    normalized = normalize_weights(profile["gewichten"])
    preferences = profile["voorkeuren"]
    if not isinstance(preferences, dict) or set(preferences) != {
        "kasseien", "beton", "steenwegen", "autovrij", "heuvels",
        "ondergrond", "vermijd_plaatsen",
    }:
        raise ProfileError("voorkeuren bevatten ontbrekende of onbekende velden")
    for key in ("kasseien", "beton", "steenwegen"):
        if preferences[key] not in PREFERENCE_VALUES:
            raise ProfileError(f"{key} moet null, 'vermijd', 'ok' of 'graag' zijn")
    if preferences["steenwegen"] == "graag":
        raise ProfileError("steenwegen ondersteunt 'graag' niet")
    if preferences["autovrij"] not in AUTOVRIJ_VALUES:
        raise ProfileError("autovrij moet null, 'belangrijk' of 'ok' zijn")
    if preferences["heuvels"] not in HEUVELS_VALUES:
        raise ProfileError("heuvels moet null, 'zoek', 'ok' of 'vlak' zijn")
    if preferences["ondergrond"] not in ONDERGROND_VALUES:
        raise ProfileError("ondergrond moet null, 'verhard', 'ok' of 'onverhard' zijn")
    per_activity = _validate_per_activity(profile["voorkeuren_per_activiteit"])
    places = preferences["vermijd_plaatsen"]
    if not isinstance(places, list) or not all(
        isinstance(place, str) and place.strip() for place in places
    ):
        raise ProfileError("vermijd_plaatsen moet een lijst met plaatsnamen zijn")
    if not isinstance(profile["historiek"], list):
        raise ProfileError("historiek moet een lijst zijn")
    checked = copy.deepcopy(profile)
    checked["gewichten"] = normalized
    checked["voorkeuren_per_activiteit"] = per_activity
    checked["voorkeuren"]["vermijd_plaatsen"] = [place.strip() for place in places]
    return checked


def load(name: str = "standaard") -> dict:
    _path(name)
    if aws_state.enabled():
        data, _etag = aws_state.get_json(f"profiles/{name}.json")
        return (
            default_document(name)
            if data is None
            else _validate(data, expected_name=name)
        )
    path = _path(name)
    if not path.exists():
        return default_document(name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfileError(f"profiel '{name}' kan niet worden gelezen: {exc}") from exc
    return _validate(data, expected_name=name)


def save(profile: dict) -> dict:
    checked = _validate(profile)
    if aws_state.enabled():
        relative = f"profiles/{checked['naam']}.json"
        current, etag = aws_state.get_json(relative)
        try:
            aws_state.put_json(
                relative,
                checked,
                etag=etag,
                create_only=current is None,
            )
        except aws_state.StateConflict as exc:
            raise ProfileError(
                "profiel is gelijktijdig gewijzigd; laad het opnieuw"
            ) from exc
        return checked
    path = _path(checked["naam"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(checked, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return checked


def list_all() -> list[dict]:
    if aws_state.enabled():
        return sorted(
            (_validate(item) for item in aws_state.list_json("profiles")),
            key=lambda profile: profile["naam"],
        )
    directory = config.profiles_path()
    if not directory.exists():
        return []
    return [load(path.stem) for path in sorted(directory.glob("*.json"))]


def apply_patch(name: str, patch: dict, bron: str) -> dict:
    if not isinstance(patch, dict):
        raise ProfileError("patch moet een object zijn")
    unknown = set(patch) - {
        "activiteit", "gewichten", "voorkeuren", "voorkeuren_per_activiteit",
    }
    if unknown:
        raise ProfileError(f"onbekend profielveld: {sorted(unknown)[0]}")
    if not isinstance(bron, str) or not bron.strip():
        raise ProfileError("bron mag niet leeg zijn")
    profile = load(name)
    updated = copy.deepcopy(profile)
    if "activiteit" in patch:
        updated["activiteit"] = patch["activiteit"]
    if "gewichten" in patch:
        if not isinstance(patch["gewichten"], dict):
            raise ProfileError("gewichten-patch moet een object zijn")
        unknown_weights = set(patch["gewichten"]) - set(WEIGHT_KEYS)
        if unknown_weights:
            raise ProfileError(f"onbekend gewicht: {sorted(unknown_weights)[0]}")
        updated["gewichten"].update(patch["gewichten"])
    if "voorkeuren" in patch:
        if not isinstance(patch["voorkeuren"], dict):
            raise ProfileError("voorkeuren-patch moet een object zijn")
        unknown_preferences = set(patch["voorkeuren"]) - set(updated["voorkeuren"])
        if unknown_preferences:
            raise ProfileError(f"onbekende voorkeur: {sorted(unknown_preferences)[0]}")
        updated["voorkeuren"].update(patch["voorkeuren"])
    if "voorkeuren_per_activiteit" in patch:
        extra = patch["voorkeuren_per_activiteit"]
        if not isinstance(extra, dict):
            raise ProfileError("voorkeuren_per_activiteit-patch moet een object zijn")
        merged = copy.deepcopy(updated.get("voorkeuren_per_activiteit") or {})
        for activity, preferences in _validate_per_activity(extra).items():
            merged.setdefault(activity, {}).update(preferences)
        updated["voorkeuren_per_activiteit"] = merged
    updated["historiek"].append(
        {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "bron": bron.strip(),
            "patch": copy.deepcopy(patch),
        }
    )
    saved = save(updated)
    # Een profielwijziging beïnvloedt zowel routering als scoring. Gekoppelde
    # drafts mogen daarom geen oude route- of probe-afgeleiden behouden.
    from . import draft

    draft.invalidate_profile(name)
    return saved


def routing_prefs(profile: dict, activity: str | None = None) -> dict:
    checked = _validate(profile)
    preferences = effective_preferences(checked, activity)
    return {
        "avoid_cobbles": preferences["kasseien"] == "vermijd",
        "avoid_concrete": preferences["beton"] == "vermijd",
        "avoid_busy": preferences["autovrij"] == "belangrijk",
        "strict": preferences["steenwegen"] == "vermijd",
        "profile": activities.graph_profile(checked["activiteit"]),
    }
