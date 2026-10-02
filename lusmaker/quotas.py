"""Tenantquota met conditionele S3-writes; lokaal standaard uitgeschakeld."""
from __future__ import annotations

from functools import wraps
import hashlib
import os
import time
import uuid

from . import aws_state

DEFAULTS = {"chat": 40, "route": 80, "provision": 0, "tokens": 200_000}


class QuotaExceeded(RuntimeError):
    def __init__(self, retry_after: int):
        super().__init__("Je daglimiet is bereikt. Probeer het later opnieuw.")
        self.retry_after = retry_after


def consume(kind: str, *, amount: int = 1, request_id: str | None = None,
            clock=time.time, get=None, put=None, limit: int | None = None) -> dict:
    if kind not in DEFAULTS or not isinstance(amount, int) or amount <= 0:
        raise ValueError("ongeldig quotum of bedrag")
    if get is None and not aws_state.enabled():
        return {"enabled": False}
    get, put = get or aws_state.get_json, put or aws_state.put_json
    maximum = limit if limit is not None else int(os.environ.get(f"LUSMAKER_QUOTA_{kind.upper()}", DEFAULTS[kind]))
    if maximum < 0:
        raise ValueError("quota mogen niet negatief zijn")
    now = int(clock())
    window = now // 86400
    retry_after = (window + 1) * 86400 - now
    # Eén document per soort; bounded opslag en geen dagelijkse cleanup nodig.
    path = f"usage/{kind}.json"
    receipt = hashlib.sha256((request_id or uuid.uuid4().hex).encode()).hexdigest()
    for _ in range(8):
        state, etag = get(path)
        current = state if state and state.get("window") == window else {"window": window, "used": 0, "receipts": {}}
        receipts = current.get("receipts", {})
        if receipt in receipts:
            if receipts[receipt] != amount:
                raise ValueError("request-id is al voor een ander quotumbedrag gebruikt")
            return {"enabled": True, "used": current['used'], "limit": maximum, "replayed": True}
        if current['used'] + amount > maximum or len(receipts) >= 10000:
            raise QuotaExceeded(retry_after)
        updated = {**current, "used": current['used'] + amount, "receipts": {**receipts, receipt: amount}}
        try:
            put(path, updated, etag=etag, create_only=state is None)
            return {"enabled": True, "used": updated['used'], "limit": maximum, "replayed": False}
        except aws_state.StateConflict:
            continue
    raise aws_state.StateConflict("quotum is druk bezet; probeer opnieuw")


def metered(kind):
    def decorate(fn):
        @wraps(fn)
        def call(*args, **kwargs):
            consume(kind)
            return fn(*args, **kwargs)
        return call
    return decorate
