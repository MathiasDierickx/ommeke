"""Vat geëxporteerde JSON-events lokaal samen zonder cloudaansluiting."""
from collections import Counter, defaultdict
import json
import math
from pathlib import Path


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def summarize(events, *, input_per_million=0.0, output_per_million=0.0):
    http = [e for e in events if e.get('event') == 'http']
    chat = [e for e in events if e.get('event') == 'chat']
    successful = sum(bool(e.get('success')) for e in chat)
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
        'successful_chats': successful, 'input_tokens': tokens_in, 'output_tokens': tokens_out,
        'estimated_model_cost': round(cost, 6) if input_per_million or output_per_million else None,
        'estimated_cost_per_successful_chat': round(cost / successful, 6) if successful and (input_per_million or output_per_million) else None,
        'latency': {op: {'count':len(values), 'p50_s': percentile(values, .5), 'p95_s':percentile(values,.95)} for op, values in operations.items()},
        'feedback': dict(Counter('bruikbaar' if e.get('success') else 'probleem' for e in events if e.get('event') == 'feedback')),
        'measured_users': len(days) if days else None,
        'users_on_multiple_days': sum(len(v) > 1 for v in days.values()) if days else None,
        'note': 'Modelkosten zijn een schatting op expliciet opgegeven tarieven; retries, AWS en geocoding kunnen extra kosten veroorzaken. Gebruikersmeting vereist een geconfigureerde metrics-salt.',
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
