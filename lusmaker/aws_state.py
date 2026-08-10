"""S3-opslag voor Lambda: tenant-scoped, atomair en zonder vaste compute."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache

from . import tenant


class StateError(RuntimeError):
    pass


class StateConflict(StateError):
    pass


_override_client: ContextVar[object | None] = ContextVar(
    "lusmaker_s3_client", default=None
)


def bucket() -> str | None:
    return os.environ.get("LUSMAKER_STATE_BUCKET") or None


def enabled() -> bool:
    return bucket() is not None


@lru_cache(maxsize=1)
def _default_client():
    try:
        import boto3
    except ImportError as exc:
        raise StateError(
            "AWS-state is geconfigureerd maar boto3 ontbreekt in de runtime"
        ) from exc
    return boto3.client("s3")


def _client(explicit=None):
    return explicit or _override_client.get() or _default_client()


@contextmanager
def use_client(client):
    """Injecteer een S3-client voor tests of een specifieke requestcontext."""
    token = _override_client.set(client)
    try:
        yield client
    finally:
        _override_client.reset(token)


def key(relative: str) -> str:
    relative = relative.strip("/")
    if not relative or ".." in relative.split("/"):
        raise StateError("ongeldige state-sleutel")
    return f"tenants/{tenant.current()}/{relative}"


def public_key(relative: str) -> str:
    """Sleutel voor minimale, niet-tenantgebonden publieke indexdata."""
    relative = relative.strip("/")
    if not relative or ".." in relative.split("/"):
        raise StateError("ongeldige publieke state-sleutel")
    return f"public/{relative}"


def _error_code(exc: Exception) -> str | None:
    response = getattr(exc, "response", None) or {}
    return (response.get("Error") or {}).get("Code")


def get_bytes(relative: str, *, client=None) -> tuple[bytes | None, str | None, dict]:
    if not enabled():
        raise StateError("AWS-state is niet geconfigureerd")
    client = _client(client)
    try:
        response = client.get_object(Bucket=bucket(), Key=key(relative))
    except Exception as exc:
        if _error_code(exc) in {"NoSuchKey", "404", "NotFound"}:
            return None, None, {}
        raise StateError(f"S3-object lezen mislukt: {_error_code(exc) or exc}") from exc
    metadata = response.get("Metadata") or {}
    return response["Body"].read(), response.get("ETag"), metadata


def put_bytes(
    relative: str,
    payload: bytes,
    *,
    content_type: str = "application/octet-stream",
    metadata: dict[str, str] | None = None,
    etag: str | None = None,
    create_only: bool = False,
    client=None,
) -> dict:
    if not enabled():
        raise StateError("AWS-state is niet geconfigureerd")
    client = _client(client)
    kwargs = {
        "Bucket": bucket(),
        "Key": key(relative),
        "Body": payload,
        "ContentType": content_type,
        "Metadata": metadata or {},
    }
    if etag is not None:
        kwargs["IfMatch"] = etag
    elif create_only:
        kwargs["IfNoneMatch"] = "*"
    try:
        return client.put_object(**kwargs)
    except Exception as exc:
        if _error_code(exc) in {
            "PreconditionFailed",
            "ConditionalRequestConflict",
            "409",
            "412",
        }:
            raise StateConflict("S3-object is intussen gewijzigd") from exc
        raise StateError(f"S3-object schrijven mislukt: {_error_code(exc) or exc}") from exc


def get_json(relative: str, *, client=None) -> tuple[dict | None, str | None]:
    payload, etag, _metadata = get_bytes(relative, client=client)
    if payload is None:
        return None, None
    try:
        return json.loads(payload), etag
    except json.JSONDecodeError as exc:
        raise StateError(f"ongeldige JSON in S3-state '{relative}'") from exc


def get_public_json(relative: str, *, client=None) -> dict | None:
    """Lees publieke indexdata buiten een tenantpartitie."""
    if not enabled():
        raise StateError("AWS-state is niet geconfigureerd")
    try:
        response = _client(client).get_object(
            Bucket=bucket(), Key=public_key(relative)
        )
    except Exception as exc:
        if _error_code(exc) in {"NoSuchKey", "404", "NotFound"}:
            return None
        raise StateError(
            f"publieke S3-state lezen mislukt: {_error_code(exc) or exc}"
        ) from exc
    try:
        return json.loads(response["Body"].read())
    except json.JSONDecodeError as exc:
        raise StateError(f"ongeldige publieke JSON-state '{relative}'") from exc


def put_json(
    relative: str,
    value: dict,
    *,
    etag: str | None = None,
    create_only: bool = False,
    client=None,
) -> dict:
    payload = (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    return put_bytes(
        relative,
        payload,
        content_type="application/json",
        etag=etag,
        create_only=create_only,
        client=client,
    )


def put_public_json(
    relative: str, value: dict, *, create_only: bool = False, client=None
) -> dict:
    """Schrijf minimale publieke indexdata buiten een tenantpartitie."""
    if not enabled():
        raise StateError("AWS-state is niet geconfigureerd")
    payload = (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    kwargs = {
        "Bucket": bucket(),
        "Key": public_key(relative),
        "Body": payload,
        "ContentType": "application/json",
        "Metadata": {},
    }
    if create_only:
        kwargs["IfNoneMatch"] = "*"
    try:
        return _client(client).put_object(**kwargs)
    except Exception as exc:
        if _error_code(exc) in {
            "PreconditionFailed", "ConditionalRequestConflict", "409", "412"
        }:
            raise StateConflict("publieke S3-state is intussen gewijzigd") from exc
        raise StateError(
            f"publieke S3-state schrijven mislukt: {_error_code(exc) or exc}"
        ) from exc


def list_json(relative_prefix: str, *, client=None) -> list[dict]:
    if not enabled():
        raise StateError("AWS-state is niet geconfigureerd")
    client = _client(client)
    prefix = key(relative_prefix).rstrip("/") + "/"
    out = []
    token = None
    while True:
        kwargs = {"Bucket": bucket(), "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        response = client.list_objects_v2(**kwargs)
        for item in response.get("Contents", []):
            object_response = client.get_object(Bucket=bucket(), Key=item["Key"])
            out.append(json.loads(object_response["Body"].read()))
        if not response.get("IsTruncated"):
            return out
        token = response["NextContinuationToken"]


def delete(relative: str, *, client=None) -> None:
    """Verwijder exact één tenant-object."""
    if not enabled():
        raise StateError("AWS-state is niet geconfigureerd")
    client = _client(client)
    try:
        client.delete_object(Bucket=bucket(), Key=key(relative))
    except Exception as exc:
        raise StateError(
            f"S3-object verwijderen mislukt: {_error_code(exc) or exc}"
        ) from exc


def delete_public(relative: str, *, client=None) -> None:
    """Verwijder exact één object uit de publieke index."""
    if not enabled():
        raise StateError("AWS-state is niet geconfigureerd")
    try:
        _client(client).delete_object(Bucket=bucket(), Key=public_key(relative))
    except Exception as exc:
        raise StateError(
            f"publieke S3-state verwijderen mislukt: {_error_code(exc) or exc}"
        ) from exc


def delete_prefix(relative_prefix: str, *, client=None) -> int:
    """Verwijder alle tenant-objecten onder een niet-lege prefix."""
    if not enabled():
        raise StateError("AWS-state is niet geconfigureerd")
    client = _client(client)
    prefix = key(relative_prefix).rstrip("/") + "/"
    deleted = 0
    token = None
    while True:
        kwargs = {"Bucket": bucket(), "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        try:
            response = client.list_objects_v2(**kwargs)
            keys = [item["Key"] for item in response.get("Contents", [])]
            for offset in range(0, len(keys), 1000):
                batch = keys[offset : offset + 1000]
                client.delete_objects(
                    Bucket=bucket(),
                    Delete={"Objects": [{"Key": item} for item in batch]},
                )
                deleted += len(batch)
        except Exception as exc:
            raise StateError(
                f"S3-prefix verwijderen mislukt: {_error_code(exc) or exc}"
            ) from exc
        if not response.get("IsTruncated"):
            return deleted
        token = response["NextContinuationToken"]


def publish_artifact(
    draft_id: str, filename: str, payload: bytes, mime_type: str, *, client=None
) -> dict:
    digest = hashlib.sha256(payload).hexdigest()
    put_bytes(
        f"artifacts/{draft_id}/{filename}",
        payload,
        content_type=mime_type,
        metadata={"sha256": digest},
        client=client,
    )
    return {"bytes": len(payload), "sha256": digest}


def presigned_get_url(
    relative: str,
    *,
    expires_in: int = 900,
    content_type: str | None = None,
    download_name: str | None = None,
    client=None,
) -> str:
    """Maak een kortlevende GET-link voor exact één tenant-object."""
    if not enabled():
        raise StateError("AWS-state is niet geconfigureerd")
    if not 60 <= expires_in <= 3600:
        raise StateError("downloadlink moet 60 tot 3600 seconden geldig zijn")
    params = {"Bucket": bucket(), "Key": key(relative)}
    if content_type:
        params["ResponseContentType"] = content_type
    if download_name:
        safe_name = (
            download_name.replace('"', "").replace("\r", "").replace("\n", "")
        )
        params["ResponseContentDisposition"] = (
            f'attachment; filename="{safe_name}"'
        )
    try:
        return _client(client).generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=expires_in,
        )
    except Exception as exc:
        raise StateError(
            f"S3-downloadlink maken mislukt: {_error_code(exc) or exc}"
        ) from exc
