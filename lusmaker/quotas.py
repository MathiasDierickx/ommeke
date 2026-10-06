"""Tenantquota met conditionele S3-writes; lokaal standaard uitgeschakeld."""
from __future__ import annotations

from functools import wraps
import hashlib
import os
import time
import uuid

from . import aws_state

DEFAULTS = {"chat": 40, "route": 80, "provision": 0, "tokens": 300_000, "feedback": 20}


_WHAT = {
    "chat": "chatberichten",
    "route": "routeberekeningen",
    "tokens": "AI-budget voor de chat",
    "provision": "nieuwe regio's",
    "feedback": "feedbackberichten",
}
_STILL_WORKS = {
    "chat": " Het snelle routeformulier en je bestaande routes werken nog.",
    "tokens": " Het snelle routeformulier en je bestaande routes werken nog.",
    "route": " Je bestaande routes kun je nog openen en downloaden.",
}


def reset_label(retry_after: int, *, now: float | None = None) -> str:
    """Leesbaar resetmoment in Belgische tijd, bv. "vannacht om 02:00"."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("Europe/Brussels")
    current = datetime.fromtimestamp(time.time() if now is None else now, zone)
    reset = current + timedelta(seconds=retry_after)
    if reset.hour < 6:
        day = "vannacht"
    else:
        day = "vandaag" if reset.date() == current.date() else "morgen"
    return f"{day} om {reset:%H:%M}"


class QuotaExceeded(RuntimeError):
    def __init__(self, retry_after: int, kind: str = "", limit: int | None = None, *, now: float | None = None):
        what = _WHAT.get(kind, "gebruik")
        amount = f" ({limit})" if limit and kind not in {"tokens"} else ""
        super().__init__(
            f"Je daglimiet voor {what}{amount} is bereikt. De teller start opnieuw "
            f"{reset_label(retry_after, now=now)} (Belgische tijd).{_STILL_WORKS.get(kind, '')}"
        )
        self.retry_after = retry_after
        self.kind = kind
        self.limit = limit


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
            raise QuotaExceeded(retry_after, kind, maximum, now=now)
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
            rid = kwargs.get("request_id")
            consume(kind, request_id=f"{rid}:{kind}" if isinstance(rid, str) and rid else None)
            return fn(*args, **kwargs)
        return call
    return decorate
