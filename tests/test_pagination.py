from lusmaker import aws_state, tenant
from tests.test_aws_state import _FakeS3, _aws_bucket


def test_keyset_pagination_is_bounded_and_tenant_scoped():
    class Paged(_FakeS3):
        reads = 0
        def get_object(self, **kwargs):
            self.reads += 1
            return super().get_object(**kwargs)
        def list_objects_v2(self, **kwargs):
            rows = super().list_objects_v2(**kwargs)['Contents']
            rows = [r for r in rows if r['Key'] > kwargs.get('StartAfter', '')]
            return {'Contents': rows[:kwargs.get('MaxKeys', len(rows))]}
    client = Paged()
    with _aws_bucket(), aws_state.use_client(client), tenant.use('one'):
        for n in range(100):
            aws_state.put_json(f'drafts/{n:03}.json', {'id': n})
        first = aws_state.json_page('drafts', limit=10)
        second = aws_state.json_page('drafts', limit=10, cursor=first['next_cursor'])
        assert [v['id'] for v in first['items']+second['items']] == list(range(20))
        assert client.reads == 20
        with tenant.use('two'):
            try:
                aws_state.json_page('drafts', cursor=first['next_cursor'])
            except ValueError:
                pass
            else:
                raise AssertionError('cursor van andere gebruiker aanvaard')
