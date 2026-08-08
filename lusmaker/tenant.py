"""Request-lokale tenantcontext voor de hosted AWS-runtime."""

from __future__ import annotations

import hashlib
import re
from contextlib import contextmanager
from contextvars import ContextVar


_current: ContextVar[str | None] = ContextVar("lusmaker_tenant", default=None)
_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def current() -> str:
    value = _current.get() or "anonymous"
    safe = _SAFE_RE.sub("-", value).strip("-._") or "anonymous"
    if safe == value and len(value) <= 128:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
    prefix = safe[: 128 - len(digest) - 1].rstrip("-._") or "anonymous"
    return f"{prefix}-{digest}"


@contextmanager
def use(value: str | None):
    token = _current.set(value)
    try:
        yield current()
    finally:
        _current.reset(token)
