"""Minimale globale index voor publieke, read-only routelinks.

Drafts blijven volledig in hun tenantpartitie. Alleen ``{uid, draft_id}`` staat
onder ``public/shares/`` zodat een oningelogde tokenlookup de juiste partitie
kan vinden zonder drafts van alle gebruikers te scannen.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from . import aws_state


_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,160}$")


def _path(token: str) -> str:
    if not isinstance(token, str) or not _TOKEN_RE.fullmatch(token):
        raise ValueError("ongeldige deel-token")
    return f"shares/{token}.json"


def store_reference(
    token: str,
    uid: str,
    draft_id: str,
    *,
    put_fn: Callable[..., object] = aws_state.put_public_json,
) -> dict[str, str]:
    reference = {"uid": uid, "draft_id": draft_id}
    put_fn(_path(token), reference, create_only=True)
    return reference


def load_reference(
    token: str,
    *,
    get_fn: Callable[[str], dict | None] = aws_state.get_public_json,
) -> dict[str, str] | None:
    value = get_fn(_path(token))
    if not value:
        return None
    uid, draft_id = value.get("uid"), value.get("draft_id")
    if not isinstance(uid, str) or not uid or not isinstance(draft_id, str):
        return None
    return {"uid": uid, "draft_id": draft_id}


def delete_reference(
    token: str,
    *,
    delete_fn: Callable[[str], object] = aws_state.delete_public,
) -> None:
    delete_fn(_path(token))
