"""Veilige route-artifacts en MCP-resourcebeschrijvingen."""

from __future__ import annotations

import hashlib
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import quote, urlsplit

from . import aws_state, config


class ArtifactError(RuntimeError):
    """Ongeldig of ontbrekend route-artifact."""


_DRAFT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ARTIFACTS = {
    "route.gpx": ("gpx", "application/gpx+xml", "GPX-route"),
    "preview.html": ("preview", "text/html", "Routepreview"),
}
_http_delivery: ContextVar[bool] = ContextVar(
    "lusmaker_http_artifact_delivery", default=False
)
_public_url_override: ContextVar[str | None] = ContextVar(
    "lusmaker_public_url_override", default=None
)


def validate_draft_id(draft_id: str) -> str:
    if not isinstance(draft_id, str) or not _DRAFT_ID_RE.fullmatch(draft_id):
        raise ArtifactError("ongeldig draft-id voor artifact")
    return draft_id


@contextmanager
def delivery_mode(http: bool, *, public_url: str | None = None):
    """Selecteer per request lokale paden of publieke HTTP-bestands-URL's."""
    mode_token = _http_delivery.set(bool(http))
    url_token = _public_url_override.set(public_url)
    try:
        yield
    finally:
        _public_url_override.reset(url_token)
        _http_delivery.reset(mode_token)


def public_base_url(explicit: str | None = None) -> str:
    value = (
        explicit
        or _public_url_override.get()
        or os.environ.get("LUSMAKER_PUBLIC_URL", "")
    ).rstrip("/")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        raise ArtifactError(
            "LUSMAKER_PUBLIC_URL moet een absolute HTTP(S)-basis-URL zijn"
        )
    return value


def file_url(
    draft_id: str,
    filename: str,
    *,
    uid: str | None = None,
    public_url: str | None = None,
) -> str:
    """Bouw een token-gebonden URL voor een canoniek route-artifact."""
    if filename not in _ARTIFACTS:
        raise ArtifactError(f"onbekend artifact '{filename}'")
    user_id = config.validate_user_id(uid or config.current_user_id())
    draft_id = validate_draft_id(draft_id)
    return (
        f"{public_base_url(public_url)}/files/{quote(user_id, safe='')}/"
        f"{quote(draft_id, safe='')}/{quote(filename, safe='')}"
    )


def output_reference(
    path: str | Path,
    draft_id: str,
    filename: str,
    *,
    http_mode: bool | None = None,
    uid: str | None = None,
    public_url: str | None = None,
) -> str:
    """Geef in HTTP-modus een URL en anders het ongewijzigde lokale pad."""
    use_http = _http_delivery.get() if http_mode is None else http_mode
    if use_http:
        return file_url(draft_id, filename, uid=uid, public_url=public_url)
    return str(path)


def content_type(filename: str) -> str:
    try:
        return _ARTIFACTS[filename][1]
    except KeyError as exc:
        raise ArtifactError(f"onbekend artifact '{filename}'") from exc


def root() -> Path:
    if aws_state.enabled():
        temporary_home = Path(os.environ.get("LUSMAKER_TMP", "/tmp/lusmaker"))
        return config.exports_path(temporary_home)
    return config.exports_path()


def draft_dir(draft_id: str, *, create: bool = False) -> Path:
    artifact_root = root().resolve()
    path = artifact_root / validate_draft_id(draft_id)
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
    item = {
        "type": key,
        "title": title,
        "uri": (
            file_url(draft_id, filename)
            if _http_delivery.get()
            else uri_for(draft_id, filename)
        ),
        "mime_type": mime_type,
    }
    if aws_state.enabled():
        payload, _etag, metadata = aws_state.get_bytes(
            f"artifacts/{draft_id}/{filename}"
        )
        if payload is not None:
            item["bytes"] = len(payload)
            item["sha256"] = metadata.get("sha256") or hashlib.sha256(
                payload
            ).hexdigest()
    else:
        path = path_for(draft_id, filename)
        if path.exists():
            payload = path.read_bytes()
            item["bytes"] = len(payload)
            item["sha256"] = hashlib.sha256(payload).hexdigest()
    return item


def describe_all(draft_id: str) -> list[dict]:
    return [describe(draft_id, filename) for filename in _ARTIFACTS]


def temporary_download_url(
    draft_id: str,
    filename: str,
    *,
    download_name: str | None = None,
    expires_in: int = 900,
) -> str:
    """Geef hosted een tijdelijke S3-link en lokaal de MCP-resource-URI."""
    validate_draft_id(draft_id)
    if filename not in _ARTIFACTS:
        raise ArtifactError(f"onbekend artifact '{filename}'")
    if aws_state.enabled():
        return aws_state.presigned_get_url(
            f"artifacts/{draft_id}/{filename}",
            expires_in=expires_in,
            content_type=content_type(filename),
            download_name=download_name or filename,
        )
    return uri_for(draft_id, filename)


def read(draft_id: str, filename: str) -> bytes:
    if aws_state.enabled():
        payload, _etag, _metadata = aws_state.get_bytes(
            f"artifacts/{draft_id}/{filename}"
        )
        if payload is None:
            raise ArtifactError(
                f"artifact '{filename}' voor draft '{draft_id}' bestaat niet; "
                "routeer eerst"
            )
        return payload
    path = path_for(draft_id, filename)
    if not path.is_file():
        raise ArtifactError(
            f"artifact '{filename}' voor draft '{draft_id}' bestaat niet; routeer eerst"
        )
    return path.read_bytes()


def publish(draft_id: str, filename: str) -> dict:
    """Publiceer een lokaal gegenereerd artifact naar de hosted state-store."""
    path = path_for(draft_id, filename)
    if not path.is_file():
        raise ArtifactError(f"artifact '{filename}' werd niet gegenereerd")
    payload = path.read_bytes()
    if not aws_state.enabled():
        return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    _kind, mime_type, _title = _ARTIFACTS[filename]
    return aws_state.publish_artifact(
        draft_id, filename, payload, mime_type
    )
