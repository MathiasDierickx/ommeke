"""Vat geëxporteerde JSON-events lokaal samen zonder cloudaansluiting."""
from collections import Counter, defaultdict
import json
import math
from pathlib import Path


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def _ratio(part, whole):
    return round(part / whole, 4) if whole else None


def funnel_summary(events):
    """Tel de pilotfunnel: aanvraag -> bruikbaar -> aanpassing -> export -> terugkeer."""
    requested = [e for e in events if e.get('event') == 'route_requested']
    ready_events = [e for e in events if e.get('event') == 'route_ready']
    usable = [e for e in ready_events if not e.get('needs_input')]
    asked = [e for e in ready_events if e.get('needs_input')]
    adjusted = [e for e in events if e.get('event') == 'route_adjusted']
    exported = [e for e in events if e.get('event') == 'route_exported']
    steps = {'requested': requested, 'ready': usable, 'adjusted': adjusted, 'exported': exported}

    def breakdown(field, names):
        result = {}
        for name in sorted({e.get(field) or 'unknown' for e in requested + usable + adjusted + exported}):
            counts = {step: sum((e.get(field) or 'unknown') == name for e in items) for step, items in steps.items() if step in names}
            counts['needs_input'] = sum((e.get(field) or 'unknown') == name for e in asked)
            if {'requested', 'ready'} <= names:
                counts['ready_ratio'] = _ratio(counts['ready'], counts['requested'])
            result[name] = counts
        return result

    by_actor = defaultdict(lambda: defaultdict(set))
    for e in events:
        if e.get('actor') and e.get('date'):
            by_actor[e['actor']]['all'].add(e['date'])
            by_actor[e['actor']][e.get('event')].add(e['date'])
    exporters = [a for a, v in by_actor.items() if v.get('route_exported')]
    returned = [a for a in exporters if any(d > min(by_actor[a]['route_exported']) for d in by_actor[a]['all'])]
    return {
        'requested': len(requested), 'ready': len(usable), 'needs_input': len(asked),
        'adjusted': len(adjusted), 'exported': len(exported),
        'ready_ratio': _ratio(len(usable), len(requested)),
        'needs_input_ratio': _ratio(len(asked), len(ready_events)),
        'adjusted_ratio': _ratio(len(adjusted), len(usable)),
        'exported_ratio': _ratio(len(exported), len(usable)),
        'by_channel': breakdown('channel', {'requested', 'ready', 'adjusted'}),
        'by_activity': breakdown('activity', {'requested', 'ready', 'exported'}),
        'adjustment_kinds': dict(Counter(e.get('kind') or 'unknown' for e in adjusted)),
        'export_formats': dict(Counter(e.get('format') or 'unknown' for e in exported)),
        'km_buckets': dict(Counter(e.get('km_bucket') for e in usable if e.get('km_bucket'))),
        'question_ids': dict(Counter(q for e in asked for q in e.get('question_ids') or [])),
        'actors': {'requested': sum(bool(v.get('route_requested')) for v in by_actor.values()),
                   'exported': len(exporters), 'returned_after_export': len(returned),
                   'returned_after_export_ratio': _ratio(len(returned), len(exporters))},
    }


def summarize(events, *, input_per_million=0.0, output_per_million=0.0):
    http = [e for e in events if e.get('event') == 'http']
    chat = [e for e in events if e.get('event') == 'chat']
    successful = sum(bool(e.get('success')) for e in chat)
    routes_ready = sum(int(e.get('routes_ready') or 0) for e in chat if e.get('success'))
    router = [e for e in http if e.get('router_calls')]
    paid = bool(input_per_million or output_per_million)
    tokens_in = sum(e.get('input_tokens', 0) for e in chat)
    tokens_out = sum(e.get('output_tokens', 0) for e in chat)
    operations = defaultdict(list)
    days = defaultdict(set)
    for event in http:
        if isinstance(event.get('seconds'), (int, float)):
            operations[event.get('operation', 'other')].append(event['seconds'])
        if event.get('actor') and event.get('date'):
            days[event['actor']].add(event['date'])
    cost = (tokens_in * input_per_million + tokens_out * output_per_million) / 1_000_000
    return {
        'http_requests': len(http), 'http_errors': sum(e.get('status', 200) >= 500 for e in http),
        'cold_requests': sum(bool(e.get('cold_start')) for e in http),
        'successful_chats': successful, 'failed_chats': len(chat) - successful,
        'chat_success_ratio': round(successful / len(chat), 4) if chat else None,
        'http_success_ratio': round(sum(bool(e.get('success', e.get('status', 200) < 400)) for e in http) / len(http), 4) if http else None,
        'ready_routes': routes_ready,
        'estimated_cost_per_successful_route': round(cost / routes_ready, 6) if routes_ready and paid else None,
        'router': {'requests': len(router), 'calls': sum(e['router_calls'] for e in router),
                   'total_ms': sum(e.get('router_ms', 0) for e in router),
                   'wait_ms': sum(e.get('router_wait_ms', 0) for e in http)} if router or any(e.get('router_wait_ms') for e in http) else None,
        'input_tokens': tokens_in, 'output_tokens': tokens_out,
        'estimated_model_cost': round(cost, 6) if input_per_million or output_per_million else None,
        'estimated_cost_per_successful_chat': round(cost / successful, 6) if successful and (input_per_million or output_per_million) else None,
        'latency': {op: {'count':len(values), 'p50_s': percentile(values, .5), 'p95_s':percentile(values,.95)} for op, values in operations.items()},
        'feedback': dict(Counter('bruikbaar' if e.get('success') else 'probleem' for e in events if e.get('event') == 'feedback')),
        'funnel': funnel_summary(events),
        'measured_users': len(days) if days else None,
        'users_on_multiple_days': sum(len(v) > 1 for v in days.values()) if days else None,
        'note': 'Kosten per geslaagde chat/route omvatten ook tokens van mislukte chats. Modelkosten zijn een schatting op expliciet opgegeven tarieven; retries, AWS en geocoding kunnen extra kosten veroorzaken. Gebruikersmeting vereist een geconfigureerde metrics-salt.',
    }


def read_events(path):
    text = Path(path).read_text()
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if 'events' in data:
            return [json.loads(event['message']) for event in data['events']]
        return [data]
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
