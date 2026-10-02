"""Persistente requestreceipts: eenmaal uitvoeren, daarna resultaat teruggeven.

Een onderbroken request wordt nooit automatisch opnieuw uitgevoerd: de side
 effects kunnen al bestaan. De caller kan status ophalen en gericht herstellen.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from . import aws_state


class RequestConflict(RuntimeError):
    pass


def request_path(scope: str, request_id: str) -> str:
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", request_id):
        raise ValueError("request_id moet 8–128 letters, cijfers, streepjes of underscores bevatten")
    digest = hashlib.sha256(f"{scope}:{request_id}".encode()).hexdigest()
    return f"requests/{digest}.json"


def once(scope, request_id, payload, operation, *, get=None, put=None, clock=time.time):
    if request_id is None or (get is None and not aws_state.enabled()):
        return operation()
    get, put = get or aws_state.get_json, put or aws_state.put_json
    path = request_path(scope, request_id)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    state = {"status": "running", "digest": digest, "created_at": int(clock())}
    try:
        result = put(path, state, create_only=True)
    except aws_state.StateConflict:
        existing, _ = get(path)
        if not existing or existing.get("digest") != digest:
            raise RequestConflict("Dit verzoeknummer is al gebruikt voor een andere opdracht.")
        if existing['status'] == 'complete':
            return existing['result']
        raise RequestConflict("Dit verzoek is nog bezig of werd onderbroken. Laad het gesprek opnieuw; start niet dubbel.")
    etag = result.get('ETag')
    try:
        value = operation()
    except Exception:
        # Geen exceptiontekst opslaan: die kan prompts of providergegevens bevatten.
        put(path, {**state, "status": "interrupted"}, etag=etag)
        raise
    put(path, {**state, "status": "complete", "result": value}, etag=etag)
    return value


def status(scope, request_id):
    state, _ = aws_state.get_json(request_path(scope, request_id))
    if not state:
        return {"status": "unknown"}
    return {k: state[k] for k in ('status', 'created_at', 'result') if k in state}
