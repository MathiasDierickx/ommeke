"""Request-lokale tenantcontext voor de hosted AWS-runtime."""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar


_current: ContextVar[str | None] = ContextVar("lusmaker_tenant", default=None)
_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def current() -> str:
    value = _current.get() or "anonymous"
    safe = _SAFE_RE.sub("-", value).strip("-._")
    return (safe or "anonymous")[:128]


@contextmanager
def use(value: str | None):
    token = _current.set(value)
    try:
        yield current()
    finally:
        _current.reset(token)
