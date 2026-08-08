"""Veilige route-artifacts en MCP-resourcebeschrijvingen."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from . import config


class ArtifactError(RuntimeError):
    """Ongeldig of ontbrekend route-artifact."""


_DRAFT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ARTIFACTS = {
    "route.gpx": ("gpx", "application/gpx+xml", "GPX-route"),
    "preview.html": ("preview", "text/html", "Routepreview"),
}


def _validate_draft_id(draft_id: str) -> str:
    if not isinstance(draft_id, str) or not _DRAFT_ID_RE.fullmatch(draft_id):
        raise ArtifactError("ongeldig draft-id voor artifact")
    return draft_id


def root() -> Path:
    return config.home_path() / "exports"


def draft_dir(draft_id: str, *, create: bool = False) -> Path:
    artifact_root = root().resolve()
    path = artifact_root / _validate_draft_id(draft_id)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    resolved = path.resolve(strict=False)
    if resolved.parent != artifact_root:
        raise ArtifactError("artifactmap wijst buiten de Lusmaker exportmap")
    return resolved


def path_for(draft_id: str, filename: str) -> Path:
    if filename not in _ARTIFACTS:
        raise ArtifactError(f"onbekend artifact '{filename}'")
    directory = draft_dir(draft_id)
    path = (directory / filename).resolve(strict=False)
    if path.parent != directory:
        raise ArtifactError("artifactpad wijst buiten de draftmap")
    return path


def safe_output_path(
    draft_id: str,
    filename: str,
    requested: str | None = None,
) -> Path:
    """Beperk MCP-writes tot de artifactmap van de betrokken draft."""
    directory = draft_dir(draft_id, create=True)
    candidate = Path(requested) if requested is not None else Path(filename)
    if not candidate.is_absolute():
        candidate = directory / candidate
    candidate = candidate.resolve(strict=False)
    if candidate.parent != directory:
        raise ArtifactError(
            "output_path moet een bestandsnaam in de artifactmap van de draft zijn"
        )
    return candidate


def uri_for(draft_id: str, filename: str) -> str:
    path_for(draft_id, filename)
    return f"lusmaker://drafts/{draft_id}/{filename}"


def describe(draft_id: str, filename: str) -> dict:
    key, mime_type, title = _ARTIFACTS[filename]
    path = path_for(draft_id, filename)
    item = {
        "type": key,
        "title": title,
        "uri": uri_for(draft_id, filename),
        "mime_type": mime_type,
    }
    if path.exists():
        payload = path.read_bytes()
        item["bytes"] = len(payload)
        item["sha256"] = hashlib.sha256(payload).hexdigest()
    return item


def describe_all(draft_id: str) -> list[dict]:
    return [describe(draft_id, filename) for filename in _ARTIFACTS]


def read(draft_id: str, filename: str) -> bytes:
    path = path_for(draft_id, filename)
    if not path.is_file():
        raise ArtifactError(
            f"artifact '{filename}' voor draft '{draft_id}' bestaat niet; routeer eerst"
        )
    return path.read_bytes()
