"""Privacyvriendelijke funnel-events voor de pilot.

Events dragen alleen vaste labels (kanaal, activiteit, kilometerklasse,
vraag-id's, soort aanpassing, exportformaat) en de gehashte actor van
``telemetry``; nooit prompts, plaatsnamen, coördinaten of draft-id's.

Schema (event -> velden):
  route_requested  channel, activity
  route_ready      channel, activity, stage (plan|adjust), km_bucket,
                   needs_input, question_ids
  route_adjusted   channel, kind (distance|answers|climbs|avoid|reroute)
  route_exported   activity, format (gpx|fit|share)
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import re

from . import telemetry

CHANNELS = ('quick', 'chat', 'mcp')
channel_var = ContextVar('funnel_channel', default='unknown')
kind_override = ContextVar('funnel_kind', default=None)
_ID_RE = re.compile(r'[a-z0-9_]{1,40}')
sink = None  # tests injecteren hier een functie(event, **values)


@contextmanager
def channel(name):
    token = channel_var.set(name)
    try:
        yield
    finally:
        channel_var.reset(token)


@contextmanager
def adjust_kind(kind):
    token = kind_override.set(kind)
    try:
        yield
    finally:
        kind_override.reset(token)


def emit(event, **values):
    (sink or telemetry.emit)(event, **values)


def km_bucket(km):
    if not isinstance(km, (int, float)) or isinstance(km, bool):
        return None
    for limit, label in ((10, '<10'), (25, '10-25'), (50, '25-50'), (100, '50-100')):
        if km < limit:
            return label
    return '100+'


def _safe(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except Exception:  # meten mag een route nooit breken
        pass


def _ready_event(result, activity, stage):
    needs_input = result.get('status') == 'needs_input'
    ids = [q.get('id') for q in (result.get('vragen') or []) if isinstance(q, dict)] if needs_input else []
    emit('route_ready', channel=channel_var.get(), activity=activity, stage=stage,
         km_bucket=None if needs_input else km_bucket(result.get('km')),
         needs_input=needs_input,
         question_ids=[i for i in ids if isinstance(i, str) and _ID_RE.fullmatch(i)])


def tracked_plan(fn):
    """Meet aanvraag en eerste resultaat van ``plan_route``."""
    @wraps(fn)
    def call(*args, **kwargs):
        activity = kwargs.get('activiteit')
        _safe(emit, 'route_requested', channel=channel_var.get(), activity=activity)
        result = fn(*args, **kwargs)
        if isinstance(result, dict) and result.get('status') in {'ready', 'needs_input'}:
            _safe(_ready_event, result, activity, 'plan')
        return result
    return call


def adjustment_kind(kwargs):
    forced = kind_override.get()
    if forced:
        return forced
    if kwargs.get('vermijd_plaatsen') or kwargs.get('niet_meer_vermijden') or kwargs.get('sta_plaatsen_toe'):
        return 'avoid'
    if kwargs.get('voeg_klimmen_toe') or kwargs.get('verwijder_klimmen'):
        return 'climbs'
    if any(kwargs.get(k) is not None for k in ('target_km', 'max_km', 'tolerance_km')):
        return 'distance'
    return 'reroute'


def tracked_adjust(fn):
    """Meet elke aanpassing; na beantwoorde vragen telt een klaar resultaat als bruikbaar."""
    @wraps(fn)
    def call(*args, **kwargs):
        result = fn(*args, **kwargs)
        kind = adjustment_kind(kwargs)
        _safe(emit, 'route_adjusted', channel=channel_var.get(), kind=kind)
        if kind == 'answers' and isinstance(result, dict) and result.get('status') == 'ready':
            _safe(_ready_event, result, None, 'adjust')
        return result
    return call


def exported(fmt, item):
    activity = ((item or {}).get('route_request') or {}).get('activiteit')
    _safe(emit, 'route_exported', format=fmt, activity=activity)
