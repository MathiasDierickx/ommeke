"""Minimale routefeedback; geen analyticsdienst of externe requests."""
from datetime import datetime, UTC
import hashlib
import uuid
from . import aws_state, draft, quotas, telemetry

CATEGORIES = ('bruikbaar', 'verkeerde_weg', 'afstand', 'wens_gemist', 'anders')


def feedback(draft_id, category, comment='', *, request_id=None, load=draft.load, put=aws_state.put_json):
    if category not in CATEGORIES:
        raise ValueError('kies een geldige feedbackcategorie')
    if not isinstance(comment, str) or len(comment) > 1000:
        raise ValueError('toelichting mag maximaal 1000 tekens bevatten')
    item = load(draft_id)  # eigendomscheck via de bestaande tenant-scoped opslag
    quotas.consume('feedback', request_id=f'{request_id}:feedback' if request_id else None)
    key = hashlib.sha256(f'{item["id"]}:{request_id}'.encode()).hexdigest()[:32] if request_id else uuid.uuid4().hex
    value = {'id': key, 'draft_id': item['id'], 'revision': item.get('revision', 0),
             'category': category, 'comment': comment.strip(), 'created_at': datetime.now(UTC).isoformat()}
    try:
        put(f'feedback/{key}.json', value, create_only=True)
    except aws_state.StateConflict:
        if not request_id:
            raise
        return {'id': key, 'status': 'received'}  # retry met dezelfde request_id
    telemetry.emit('feedback', success=category == 'bruikbaar')
    return {'id': key, 'status': 'received'}
