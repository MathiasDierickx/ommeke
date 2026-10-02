"""Modelvrij plannen met hetzelfde domeincontract en persistente receipts."""
from __future__ import annotations
import math
from . import intents, requests


def parameters(body: dict) -> dict:
    start = body.get('start')
    if isinstance(start, dict):
        lat, lon = start.get('lat'), start.get('lon')
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (lat, lon)) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError('Geef geldige breedte- en lengtecoördinaten.')
        start = f'{lat:.6f},{lon:.6f}'
    if not isinstance(start, str) or not start.strip() or len(start) > 160:
        raise ValueError('Geef een startplaats of gebruik je locatie.')
    km = body.get('target_km')
    if isinstance(km, bool) or not isinstance(km, (float, int)) or not math.isfinite(km) or not 1 <= km <= 300:
        raise ValueError('Kies een afstand tussen 1 en 300 km.')
    activity = body.get('activiteit', 'fietsen')
    goal = body.get('doel', 'toeren')
    if activity not in ('fietsen', 'trail') or goal not in ('hoogtemeters', 'toeren', 'offroad', 'kort'):
        raise ValueError('Kies een geldige activiteit en een geldig doel.')
    return dict(start=start.strip(), target_km=km, tolerance_km=min(2.5, km * .1),
                activiteit=activity, doel=goal, check_readiness=True, profiel_naam="standaard",
                kasseien=None, beton_vermijden=None, autovrij=None, strict=None)


def plan(body, *, planner=intents.plan_route, once=requests.once, store_factory=None):
    values = parameters(body)
    rid = body.get('request_id')
    requests.request_path('quick-plan', rid)  # ook lokaal verplicht en gevalideerd
    def execute():
        from .progress import emit
        emit("routing", "Ik zoek het vertrekpunt en bereken je lus.")
        result = planner(**values, request_id=rid)
        if store_factory is not None and result.get('status') == 'needs_input':
            store = store_factory()
            conversation = store.create('Routewensen aanvullen')
            cid = conversation['id']
            store.add_message(cid, 'user', f"Plan {values['activiteit']} vanaf {values['start']}, ongeveer {values['target_km']} km, doel {values['doel']}.")
            questions = '\n'.join(q['vraag'] for q in result.get('vragen', []))
            store.add_message(cid, 'assistant', f"Routeconcept {result['draft']} heeft nog aanvullende wensen nodig. {questions}", route_ids=[result['draft']])
            result = {**result, 'conversation_id': cid}
        return result
    return once('quick-plan', rid, values, execute)
