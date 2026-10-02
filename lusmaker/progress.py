"""Requestgebonden voortgang; geen globale toestand of netwerkafhankelijkheid."""
from contextlib import contextmanager
from contextvars import ContextVar

_sink = ContextVar('route_progress', default=None)


@contextmanager
def capture(sink):
    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


def emit(stage, message):
    sink = _sink.get()
    if sink is not None:
        sink({'stage': stage, 'message': message})
