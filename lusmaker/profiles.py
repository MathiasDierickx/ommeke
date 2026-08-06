"""Persistente, regio-onafhankelijke gebruikersvoorkeuren."""

from __future__ import annotations

import copy
import json
import math
import re
from datetime import datetime

from . import config


WEIGHT_KEYS = ("hoogtemeters", "offroad", "populair", "kort")
PREFERENCE_VALUES = {None, "vermijd", "ok", "graag"}
_NAME_RE = re.compile(r"^[\w-]+$", re.UNICODE)


class ProfileError(RuntimeError):
    """Ongeldig profiel of ongeldige profielwijziging."""


def _path(name: str):
    if not isinstance(name, str) or not name or not _NAME_RE.fullmatch(name):
        raise ProfileError("profielnaam gebruikt alleen letters, cijfers, _ of -")
    return config.home_path() / "profiles" / f"{name}.json"


def default_document(name: str = "standaard") -> dict:
    _path(name)  # valideer ook namen van nog niet opgeslagen profielen
    return {
        "naam": name,
        "activiteit": "fietsen",
        "gewichten": {
            "hoogtemeters": 1.0,
            "offroad": 0.0,
            "populair": 0.0,
            "kort": 0.0,
        },
        "voorkeuren": {
            "kasseien": None,
            "beton": None,
            "steenwegen": None,
            "vermijd_plaatsen": [],
        },
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


def _validate(profile: dict, expected_name: str | None = None) -> dict:
    if not isinstance(profile, dict):
        raise ProfileError("profiel moet een object zijn")
    required = {"naam", "activiteit", "gewichten", "voorkeuren", "historiek"}
    if set(profile) != required:
        raise ProfileError("profiel bevat ontbrekende of onbekende velden")
    name = profile["naam"]
    _path(name)
    if expected_name is not None and name != expected_name:
        raise ProfileError("profielnaam komt niet overeen met de bestandsnaam")
    if profile["activiteit"] not in {"fietsen", "trail"}:
        raise ProfileError("activiteit moet 'fietsen' of 'trail' zijn")
    normalized = normalize_weights(profile["gewichten"])
    preferences = profile["voorkeuren"]
    if not isinstance(preferences, dict) or set(preferences) != {
        "kasseien", "beton", "steenwegen", "vermijd_plaatsen"
    }:
        raise ProfileError("voorkeuren bevatten ontbrekende of onbekende velden")
    for key in ("kasseien", "beton", "steenwegen"):
        if preferences[key] not in PREFERENCE_VALUES:
            raise ProfileError(f"{key} moet null, 'vermijd', 'ok' of 'graag' zijn")
    if preferences["steenwegen"] == "graag":
        raise ProfileError("steenwegen ondersteunt 'graag' niet")
    places = preferences["vermijd_plaatsen"]
    if not isinstance(places, list) or not all(
        isinstance(place, str) and place.strip() for place in places
    ):
        raise ProfileError("vermijd_plaatsen moet een lijst met plaatsnamen zijn")
    if not isinstance(profile["historiek"], list):
        raise ProfileError("historiek moet een lijst zijn")
    checked = copy.deepcopy(profile)
    checked["gewichten"] = normalized
    checked["voorkeuren"]["vermijd_plaatsen"] = [place.strip() for place in places]
    return checked


def load(name: str = "standaard") -> dict:
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
    directory = config.home_path() / "profiles"
    if not directory.exists():
        return []
    return [load(path.stem) for path in sorted(directory.glob("*.json"))]


def apply_patch(name: str, patch: dict, bron: str) -> dict:
    if not isinstance(patch, dict):
        raise ProfileError("patch moet een object zijn")
    unknown = set(patch) - {"activiteit", "gewichten", "voorkeuren"}
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


def routing_prefs(profile: dict) -> dict:
    checked = _validate(profile)
    preferences = checked["voorkeuren"]
    return {
        "avoid_cobbles": preferences["kasseien"] == "vermijd",
        "avoid_concrete": preferences["beton"] == "vermijd",
        "strict": preferences["steenwegen"] == "vermijd",
        "profile": "trail" if checked["activiteit"] == "trail" else config.GH_PROFILE,
    }
