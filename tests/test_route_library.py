"""Meet opslag-I/O en correctheid zonder AWS of netwerk."""
import base64
from datetime import datetime, UTC, timedelta
import json

from lusmaker import aws_state, draft, route_library, tenant
from tests.test_aws_state import _FakeS3, _aws_bucket


class LibraryS3(_FakeS3):
    def __init__(self):
        super().__init__()
        self.body_reads = 0
        self.head_reads = 0
        self.list_reads = 0
        self.modified = {}
        self.deleted_on_head = None
        self.page_size = 7
        self.bytes_read = 0
        self.max_parallel = 0
        self._active = 0

    def put_object(self, **kwargs):
        result = super().put_object(**kwargs)
        self.modified[kwargs['Key']] = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=self.counter)
        return result

    def get_object(self, **kwargs):
        self.body_reads += 1
        response = super().get_object(**kwargs)
        self.bytes_read += len(self.objects[kwargs['Key']]['Body'])
        return response

    def head_object(self, **kwargs):
        self.head_reads += 1
        if kwargs['Key'] == self.deleted_on_head:
            self.delete_object(Key=kwargs['Key'])
        response = super().get_object(**kwargs)
        self.bytes_read += sum(len(k) + len(v) for k, v in (response.get('Metadata') or {}).items())
        return {key: value for key, value in response.items() if key != 'Body'}

    def list_objects_v2(self, **kwargs):
        self.list_reads += 1
        rows = super().list_objects_v2(**kwargs)['Contents']
        # Kleine pagina's dwingen dezelfde codeweg als duizenden S3-objecten af.
        size = self.page_size
        offset = int(kwargs.get('ContinuationToken', 0))
        page = rows[offset:offset + size]
        more = offset + size < len(rows)
        self.bytes_read += sum(len(row['Key']) + 40 for row in page)
        return {'Contents': [{**row, 'LastModified': self.modified[row['Key']]} for row in page],
                'IsTruncated': more, 'NextContinuationToken': str(offset + size)}


def example(identifier):
    return {'id': identifier, 'revision': 1, 'name': 'Café aan de Schelde 🚲',
            'start': {'label': 'Openbaar startpunt', 'lat': 51, 'lon': 3},
            'computed': {'total_km': 35, 'ascend_m': 180},
            '_geometry': [[[51, 3, 20]] * 1000]}


def seed(client, identifier, *, legacy=False):
    value = example(identifier)
    aws_state.put_json(f'drafts/{identifier}.json', value,
                       metadata={} if legacy else route_library.summary_metadata(value))
    return value


def test_newest_pages_read_zero_geometries_and_isolate_tenants():
    client = LibraryS3()
    route_library.clear_snapshots()
    with _aws_bucket(), aws_state.use_client(client), tenant.use('one'):
        for n in range(100):
            seed(client, f'{n:03}')
        first = route_library.page(limit=10)
        second = route_library.page(limit=10, cursor=first['next_cursor'])
        assert [d['id'] for d in first['items'] + second['items']] == [f'{n:03}' for n in range(99, 79, -1)]
        assert client.body_reads == 0 and client.head_reads == 20
        assert client.list_reads == 15  # alleen de eerste pagina scant; page 2 hergebruikt de snapshot
        assert '_geometry' not in first['items'][0]
        assert first['items'][0]['name'] == 'Café aan de Schelde 🚲'
        with tenant.use('two'):
            try:
                route_library.page(cursor=first['next_cursor'])
            except ValueError:
                pass
            else:
                raise AssertionError('tenantvreemde cursor geaccepteerd')


def test_legacy_and_oversized_metadata_preserve_full_summary_contract():
    client = LibraryS3()
    route_library.clear_snapshots()
    with _aws_bucket(), aws_state.use_client(client):
        seed(client, 'legacy', legacy=True)
        value = example('long')
        value['name'] = 'é' * 4000
        assert route_library.summary_metadata(value) == {}
        aws_state.put_json('drafts/long.json', value)
        result = route_library.page()
        assert result['items'][0]['name'] == value['name']
        assert len(result['items']) == 2 and result['next_cursor'] is None
        assert client.body_reads == 2


def test_summary_is_updated_atomically_and_stale_save_cannot_replace_it():
    client = LibraryS3()
    route_library.clear_snapshots()
    with _aws_bucket(), aws_state.use_client(client):
        value = seed(client, 'atomic')
        value['name'] = 'Nieuwe naam'
        draft.save(value, expected_revision=1)
        assert route_library.page()['items'][0]['name'] == 'Nieuwe naam'
        value['name'] = 'Verouderde naam'
        try:
            draft.save(value, expected_revision=1)
        except draft.DraftError:
            pass
        else:
            raise AssertionError('verouderde revisie overschrijft samenvatting')
        item = route_library.page()['items'][0]
        assert item['name'] == 'Nieuwe naam' and item['revision'] == 2


def test_equal_timestamps_deleted_routes_and_invalid_cursors():
    client = LibraryS3()
    route_library.clear_snapshots()
    with _aws_bucket(), aws_state.use_client(client):
        for identifier in ('a', 'b', 'c'):
            seed(client, identifier)
        instant = datetime(2026, 1, 1, tzinfo=UTC)
        client.modified = {key: instant for key in client.modified}
        first = route_library.page(limit=1)
        assert first['items'][0]['id'] == 'a'
        client.deleted_on_head = aws_state.key('drafts/b.json')
        second = route_library.page(limit=1, cursor=first['next_cursor'])
        assert second['items'] == [] and second['next_cursor']
        assert route_library.page(limit=1, cursor=second['next_cursor'])['items'][0]['id'] == 'c'
        for cursor in ('invalid', base64.urlsafe_b64encode(json.dumps([1, aws_state.key('drafts')+'/', float('nan'), aws_state.key('drafts/a.json')]).encode()).decode()):
            try:
                route_library.page(cursor=cursor)
            except ValueError:
                pass
            else:
                raise AssertionError('ongeldige cursor aanvaard')


def test_web_page_preserves_legacy_fields_without_reading_geometry():
    import asyncio
    from starlette.requests import Request
    from lusmaker import aws_api
    client = LibraryS3()
    route_library.clear_snapshots()
    with _aws_bucket(), aws_state.use_client(client):
        original = seed(client, 'web')
        request = Request({'type': 'http', 'method': 'GET', 'path': '/api/routes',
                           'query_string': b'limit=25&order=updated', 'headers': []})
        response = asyncio.run(aws_api.routes_list(request))
        body = json.loads(response.body)
        assert response.status_code == 200 and body['order'] == 'updated'
        assert body['routes'] == [aws_api._route_item(original)]
        assert client.body_reads == 0


def test_route_detail_exposes_unmet_water_wish_without_public_request_leak():
    from lusmaker import aws_api
    item = example('constraints')
    item['route_request'] = {'target_km': 35, 'max_km': 37.5, 'max_km_explicit': False,
                             'langs_water': 'Schelde'}
    result = aws_api._route_detail_payload(item)
    assert not result['constraints']['maximum_is_hard']
    assert result['constraints']['langs_water_gepland'] is False
    assert result['constraints']['waarschuwingen']
    assert 'constraints' not in aws_api.public_route_payload(item)
    assert 'route_request' not in aws_api.public_route_payload(item)


def test_corrupt_summary_falls_back_and_new_save_moves_route_to_front():
    client = LibraryS3()
    route_library.clear_snapshots()
    with _aws_bucket(), aws_state.use_client(client):
        a = seed(client, 'a')
        seed(client, 'b')
        client.objects[aws_state.key('drafts/b.json')]['Metadata'] = {route_library.METADATA_KEY: 'bad base64'}
        assert route_library.page()['items'][0]['id'] == 'b'
        assert client.body_reads == 1
        draft.save(a, expected_revision=1)
        assert route_library.page()['items'][0]['id'] == 'a'


def test_zero_length_and_invalid_drafts_are_not_downloadable_routes():
    from lusmaker import aws_api
    for distance in (0, -1, float('nan'), float('inf'), True, None):
        item = example('empty')
        item['computed']['total_km'] = distance
        result = aws_api._route_detail_payload(item)
        assert result['ready'] is False
        assert result['download_url'] is None and result['geometry'] is None


def test_library_summary_keeps_unmet_distance_visible_without_geometry_reads():
    from lusmaker import aws_api
    item=example('short')
    item['computed']['total_km']=1.9
    item['route_request']={'target_km':3,'tolerance_km':.3,'max_km':3.3,'max_km_explicit':False}
    metadata=route_library.summary_metadata(item)
    compact=json.loads(base64.b64decode(metadata[route_library.METADATA_KEY]))
    result=aws_api._route_item(compact)
    assert result['constraints']['binnen_doelbereik'] is False
    assert result['constraints']['waarschuwingen']
    assert '_geometry' not in compact and 'route_request' not in compact


def test_io_cost_for_10_100_and_1000_routes_is_bounded_by_page_size():
    for count in (10, 100, 1000):
        client = LibraryS3()
        client.page_size = 1000  # echte S3-paginagrootte
        route_library.clear_snapshots()
        with _aws_bucket(), aws_state.use_client(client), tenant.use(f'load{count}'):
            for n in range(count):
                seed(client, f'{n:04}')
            client.bytes_read = 0
            first = route_library.page(limit=10)
            if count > 10:
                route_library.page(limit=10, cursor=first['next_cursor'])
            print(f'  routes={count}: list={client.list_reads} head={client.head_reads} '
                  f'body={client.body_reads} bytes={client.bytes_read}')
            assert client.body_reads == 0  # nooit een volledige geometrie
            assert client.list_reads == 1  # pagina 2 lijst niet opnieuw
            assert client.head_reads == (10 if count == 10 else 20)
            geometry_bytes = len(client.objects[aws_state.key('drafts/0000.json')]['Body'])
            assert geometry_bytes > 10000
            # Payload = sleutellijst + samenvattingsmetadata, nooit geometrie.
            assert client.bytes_read < count * 120 + 20 * 2000


def test_snapshot_expires_and_first_page_always_rescans():
    client = LibraryS3()
    route_library.clear_snapshots()
    with _aws_bucket(), aws_state.use_client(client), tenant.use('ttl'):
        for n in range(30):
            seed(client, f'{n:03}')
        client.page_size = 1000
        first = route_library.page(limit=10)
        assert client.list_reads == 1
        route_library.page(limit=10, cursor=first['next_cursor'])
        assert client.list_reads == 1
        original = route_library._clock
        route_library._clock = lambda: original() + route_library.SNAPSHOT_TTL_SECONDS + 1
        try:
            route_library.page(limit=10, cursor=first['next_cursor'])
        finally:
            route_library._clock = original
        assert client.list_reads == 2  # verlopen snapshot: nieuwe scan
        seed(client, 'zzz-new')
        newest = route_library.page(limit=10)
        assert newest['items'][0]['id'] == 'zzz-new' and client.list_reads == 3


def test_unpaginated_fallback_reads_each_draft_once_with_bounded_concurrency():
    import asyncio
    import threading
    import time
    from starlette.requests import Request
    from lusmaker import aws_api
    client = LibraryS3()
    lock = threading.Lock()
    original = client.get_object

    def tracked(**kwargs):
        with lock:
            client._active += 1
            client.max_parallel = max(client.max_parallel, client._active)
        try:
            time.sleep(0.005)
            return original(**kwargs)
        finally:
            with lock:
                client._active -= 1
    client.get_object = tracked
    client.page_size = 1000
    with _aws_bucket(), aws_state.use_client(client):
        for n in range(40):
            seed(client, f'{n:02}')
        response = asyncio.run(aws_api.routes_list(Request(
            {'type': 'http', 'method': 'GET', 'path': '/api/routes', 'query_string': b'', 'headers': []})))
        body = json.loads(response.body)
        assert len(body['routes']) == 40
        assert client.body_reads == 40  # eerder 80: list_all + load per route
        assert 1 < client.max_parallel <= aws_state.READ_CONCURRENCY
