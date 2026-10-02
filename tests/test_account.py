import io
import json
import zipfile
from lusmaker import account, aws_state, tenant
from tests.test_aws_state import _FakeS3, _aws_bucket
from tests.test_aws_chat import FakeDynamo
from lusmaker.aws_chat import ConversationStore


def test_export_contains_private_files_and_all_conversations():
    with _aws_bucket(), aws_state.use_client(_FakeS3()), tenant.use('one'):
        store = ConversationStore(FakeDynamo(), 'chat')
        conversation = store.create('Mijn route')
        store.add_message(conversation['id'], 'user', 'Privébericht')
        aws_state.put_json('profiles/standaard.json', {'kasseien': False})
        payload = account.export_data(store)
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            assert json.loads(archive.read('profiles/standaard.json')) == {'kasseien': False}
            assert json.loads(archive.read('conversations.json'))[0]['messages'][0]['content'] == 'Privébericht'


def test_erasure_waits_for_requests_then_removes_shares_and_other_data():
    client = _FakeS3()
    with _aws_bucket(), aws_state.use_client(client), tenant.use('one'):
        store = ConversationStore(FakeDynamo(), 'chat')
        store.create('Mijn route')
        aws_state.put_json('drafts/a.json', {'share_token': 'a'*24})
        aws_state.put_json('profiles/a.json', {})
        aws_state.put_public_json('shares/'+'a'*24+'.json', {'uid': 'one', 'draft_id': 'a'})
        with tenant.use('two'):
            aws_state.put_json('drafts/b.json', {'id': 'b'})
        assert account.erase_data(store, clock=lambda: 100)['status'] == 'pending'
        assert account.deleting()['requested_at'] == 100
        assert aws_state.get_json('drafts/a.json')[0]
        assert account.erase_data(store, clock=lambda: 1061)['status'] == 'data_deleted'
        assert store.all_conversations() == []
        assert aws_state.get_json('drafts/a.json')[0] is None
        assert aws_state.get_public_json('shares/'+'a'*24+'.json') is None
        assert account.deleting()  # blijvende blokkade voor cached tokens
        with tenant.use('two'):
            assert aws_state.get_json('drafts/b.json')[0] == {'id': 'b'}


def test_conversation_export_and_delete_follow_all_dynamo_pages():
    class Paged(FakeDynamo):
        def query(self, **kwargs):
            response = super().query(**kwargs)
            items = response['Items']
            if len(items) > 1:
                if kwargs.get('ExclusiveStartKey'):
                    return {'Items': items[1:]}
                return {'Items': items[:1], 'LastEvaluatedKey': {'pk': items[0]['pk'], 'sk': items[0]['sk']}}
            return response
    with tenant.use('one'):
        store = ConversationStore(Paged(), 'chat')
        cid = store.create()['id']
        store.add_message(cid, 'user', 'een')
        store.add_message(cid, 'assistant', 'twee')
        assert len(store.export()[0]['messages']) == 2
        assert store.delete(cid) == 3
        assert not store.client.items
