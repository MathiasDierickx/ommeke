"""Lichte routepagina's: samenvatting atomair bij de draft, geometrie op aanvraag."""
from __future__ import annotations

import base64
import heapq
import json
import math

from . import aws_state

METADATA_KEY = 'route-summary-v2'


def summary_metadata(draft: dict) -> dict[str, str]:
    """Geen tweede indexwrite: S3 bewaart deze metadata met dezelfde CAS-write.

    Lange namen of klimlijsten vallen terug op de volledige draft; nooit data
    afkappen om binnen de S3-metadataheader te passen.
    """
    fields = ('id', 'revision', 'name', 'created', 'profile', 'region', 'climbs')
    small = {key: draft[key] for key in fields if key in draft}
    small['start'] = {'label': (draft.get('start') or {}).get('label')}
    computed = draft.get('computed')
    small['computed'] = {key: computed.get(key) for key in ('total_km', 'ascend_m')} if computed else None
    from .intents import constraint_report
    small['constraints'] = constraint_report(draft)
    encoded = base64.b64encode(json.dumps(small, ensure_ascii=False, separators=(',', ':')).encode()).decode()
    return {METADATA_KEY: encoded} if len(encoded) + len(METADATA_KEY) <= 1900 else {}


def _position(item):
    return (-item['LastModified'].timestamp(), item['Key'])


def _cursor(prefix, item):
    return base64.urlsafe_b64encode(json.dumps([1, prefix, *_position(item)]).encode()).decode()


def _decode_cursor(value, prefix):
    if not value:
        return None
    try:
        if len(value) > 2048:
            raise ValueError()
        version, scope, timestamp, key = json.loads(base64.b64decode(value, altchars=b'-_', validate=True))
        if (version != 1 or scope != prefix or not isinstance(timestamp, (int, float))
                or isinstance(timestamp, bool) or not math.isfinite(timestamp)
                or not isinstance(key, str) or not key.startswith(prefix)
                or '..' in key.split('/')):
            raise ValueError()
        return timestamp, key
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ValueError('ongeldige paginacursor; vernieuw je routebibliotheek') from exc


def _summary(client, key):
    try:
        header = client.head_object(Bucket=aws_state.bucket(), Key=key)
        encoded = (header.get('Metadata') or {}).get(METADATA_KEY)
        if encoded:
            try:
                small = json.loads(base64.b64decode(encoded, validate=True))
                if isinstance(small, dict) and small.get('id') == key.rsplit('/', 1)[-1].removesuffix('.json'):
                    return small
            except (ValueError, TypeError, UnicodeError):
                pass  # Oude/ongeldige metadata: lees de canonieke draft.
        response = client.get_object(Bucket=aws_state.bucket(), Key=key)
        return json.loads(response['Body'].read())
    except Exception as exc:
        if aws_state._error_code(exc) in {'NoSuchKey', 'NotFound', '404'}:
            return None  # Een andere sessie kan een route net verwijderd hebben.
        raise


def page(*, limit=25, cursor=None, client=None):
    """Meest recent opgeslagen eerst. Listing leest uitsluitend objectmetadata.

    S3 ondersteunt geen LastModified-index. We scannen de sleutellijst, houden
    maximaal limit+1 kandidaten en lezen alleen de geselecteerde samenvattingen.
    Bestaande drafts zonder metadata blijven leesbaar zonder migratiewrites.
    Dit is een levende lijst, geen snapshot van ondertussen gewijzigde routes.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError('limit moet tussen 1 en 100 liggen')
    if not aws_state.enabled():
        raise aws_state.StateError('AWS-state is niet geconfigureerd')
    client = aws_state._client(client)
    prefix = aws_state.key('drafts').rstrip('/') + '/'
    after = _decode_cursor(cursor, prefix)

    def candidates():
        token = None
        while True:
            kwargs = {'Bucket': aws_state.bucket(), 'Prefix': prefix, 'MaxKeys': 1000}
            if token:
                kwargs['ContinuationToken'] = token
            response = client.list_objects_v2(**kwargs)
            for item in response.get('Contents', []):
                if not item['Key'].startswith(prefix):
                    raise aws_state.StateError('object buiten de gebruikerpartitie')
                if item['Key'].endswith('.json') and (after is None or _position(item) > after):
                    yield item
            if not response.get('IsTruncated'):
                return
            following = response.get('NextContinuationToken')
            if not following or following == token:
                raise aws_state.StateError('ongeldige vervolgpagina van routeopslag')
            token = following

    selected = heapq.nsmallest(limit + 1, candidates(), key=_position)
    items = [item for row in selected[:limit] if (item := _summary(client, row['Key'])) is not None]
    return {'items': items, 'next_cursor': _cursor(prefix, selected[limit - 1]) if len(selected) > limit else None,
            'order': 'updated'}
