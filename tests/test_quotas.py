from copy import deepcopy
from lusmaker import aws_state, quotas, tenant
from tests.test_aws_state import _FakeS3, _aws_bucket


def test_quota_replays_and_isolates_tenants_and_windows():
    client = _FakeS3()
    with _aws_bucket(), aws_state.use_client(client), tenant.use('one'):
        kwargs = dict(clock=lambda: 100, limit=2)
        assert quotas.consume('route', request_id='first', **kwargs)['used'] == 1
        assert quotas.consume('route', request_id='first', **kwargs)['replayed']
        assert quotas.consume('route', request_id='second', **kwargs)['used'] == 2
        try:
            quotas.consume('route', request_id='third', **kwargs)
        except quotas.QuotaExceeded as exc:
            assert exc.retry_after == 86300
        else:
            raise AssertionError('quotum niet afgedwongen')
        with tenant.use('two'):
            assert quotas.consume('route', **kwargs)['used'] == 1
        assert quotas.consume('route', clock=lambda: 86401, limit=2)['used'] == 1


def test_quota_rechecks_limit_after_competing_conditional_write():
    state = None
    def get(path):
        return deepcopy(state), 'etag' if state else None
    def put(path, value, **kwargs):
        nonlocal state
        state = value
        raise aws_state.StateConflict('andere request won')
    try:
        quotas.consume('route', get=get, put=put, clock=lambda: 1, limit=1, request_id='caller')
    except quotas.QuotaExceeded:
        # Competing receipt must be different from ours.
        raise AssertionError('dezelfde receipt zou gereplayed moeten worden')
    assert state['used'] == 1
    state = {'window': 0, 'used': 0, 'receipts': {}}
    def competing_put(path, value, **kwargs):
        state.update(used=1, receipts={'competitor': 1})
        raise aws_state.StateConflict('andere request won')
    try:
        quotas.consume('route', get=get, put=competing_put, clock=lambda: 1, limit=1)
    except quotas.QuotaExceeded:
        pass
    else:
        raise AssertionError('twee requests verbruiken laatste quotumeenheid')


def test_provision_is_disabled_by_default_for_hosted_users():
    with _aws_bucket(), aws_state.use_client(_FakeS3()):
        try:
            quotas.consume('provision')
        except quotas.QuotaExceeded:
            pass
        else:
            raise AssertionError('onbeperkte provisioning')


def test_quota_error_names_the_limit_reset_time_and_what_still_works():
    # 2 oktober 2026 21:00 UTC = 23:00 in Brussel; reset om 00:00 UTC = 02:00.
    now = 1790974800
    error = quotas.QuotaExceeded(86400 - now % 86400, 'chat', 40, now=now)
    message = str(error)
    assert 'chatberichten (40)' in message
    assert 'vannacht om 02:00' in message
    assert 'snelle routeformulier' in message
    route = str(quotas.QuotaExceeded(3600, 'route', 80, now=now))
    assert 'routeberekeningen' in route and 'downloaden' in route
    tokens = str(quotas.QuotaExceeded(3600, 'tokens', 200000, now=now))
    assert 'AI-budget' in tokens and '200000' not in tokens
