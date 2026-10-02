"""Exporteer en wis hosted gegevens, met een wachttijd voor lopende requests."""
import io
import json
import time
import zipfile
from . import aws_state, aws_sharing

MARKER = 'account/deleting.json'
DRAIN_SECONDS = 960  # langer dan de maximale Lambda-uitvoering (900 s) en tokencache
MAX_EXPORT_BYTES = 64 * 1024 * 1024


def deleting(*, get=aws_state.get_json):
    if not aws_state.enabled():
        return None
    return get(MARKER)[0]


def export_data(store, *, objects=aws_state.tenant_objects, read=aws_state.get_bytes):
    output = io.BytesIO()
    total = 0
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        chats = json.dumps(store.export(), ensure_ascii=False, indent=2).encode()
        total += len(chats)
        if total > MAX_EXPORT_BYTES:
            raise ValueError('Export is groter dan 64 MB; neem contact op voor een volledige export.')
        archive.writestr('conversations.json', chats)
        for relative, metadata in objects():
            if metadata.get('Size', 0) + total > MAX_EXPORT_BYTES:
                raise ValueError('Export is groter dan 64 MB; neem contact op voor een volledige export.')
            payload, _, _ = read(relative)
            if payload is None:
                continue
            total += len(payload)
            if total > MAX_EXPORT_BYTES:
                raise ValueError('Export is groter dan 64 MB; neem contact op voor een volledige export.')
            archive.writestr(relative, payload)
    return output.getvalue()


def erase_data(store, *, clock=time.time, get=aws_state.get_json, put=aws_state.put_json,
               objects=aws_state.tenant_objects, delete=aws_state.delete,
               unshare=aws_sharing.delete_reference):
    marker, _ = get(MARKER)
    if not marker:
        marker = {'requested_at': int(clock())}
        try:
            put(MARKER, marker, create_only=True)
        except aws_state.StateConflict:
            marker, _ = get(MARKER)
    wait = max(0, marker['requested_at'] + DRAIN_SECONDS - int(clock()))
    if wait:
        return {'status': 'pending', 'retry_after': wait}
    # Haal eerst alle sleutels op; verwijder nooit tijdens een gepagineerde listing.
    names = [relative for relative, _ in objects() if relative != MARKER]
    # Verwijder deelverwijzingen vóór de bijbehorende draft.
    for relative in names:
        if relative.startswith('drafts/'):
            item, _ = get(relative)
            if item and item.get('share_token'):
                unshare(item['share_token'])
    for conversation in store.all_conversations():
        store.delete(conversation['id'])
    for relative in names:
        delete(relative)
    # De marker blokkeert nog geldige/cached tokens en maakt hervatten veilig.
    return {'status': 'data_deleted', 'objects': len(names)}
