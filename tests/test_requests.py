from lusmaker import aws_state, requests, tenant
from tests.test_aws_state import _FakeS3, _aws_bucket


def test_completed_request_replays_and_rejects_changed_content():
    calls = []
    def operation():
        calls.append(1)
        return {'route': 'abc'}
    with _aws_bucket(), aws_state.use_client(_FakeS3()), tenant.use('one'):
        for _ in range(2):
            assert requests.once('chat:a', 'request-123', {'text': 'hi'}, operation) == {'route': 'abc'}
        assert calls == [1]
        try:
            requests.once('chat:a', 'request-123', {'text': 'different'}, operation)
        except requests.RequestConflict:
            pass
        else:
            raise AssertionError('request-id hergebruikt voor andere inhoud')
        with tenant.use('two'):
            requests.once('chat:a', 'request-123', {'text': 'hi'}, operation)
        assert len(calls) == 2


def test_interrupted_request_never_repeats_partial_side_effects():
    calls = []
    def operation():
        calls.append(1)
        raise RuntimeError('providerfout met geheime inhoud')
    client = _FakeS3()
    with _aws_bucket(), aws_state.use_client(client):
        try:
            requests.once('chat:a', 'request-123', {}, operation)
        except RuntimeError:
            pass
        try:
            requests.once('chat:a', 'request-123', {}, operation)
        except requests.RequestConflict:
            pass
        else:
            raise AssertionError('onderbroken request opnieuw uitgevoerd')
        assert calls == [1]
        assert requests.status('chat:a', 'request-123')['status'] == 'interrupted'
        assert 'geheime inhoud' not in str(client.objects)
