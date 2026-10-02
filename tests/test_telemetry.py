import logging
from lusmaker import telemetry


def test_metrics_strip_personal_content_and_dynamic_identifiers():
    records = []
    class Handler(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())
    handler = Handler()
    telemetry.logger.addHandler(handler)
    try:
        telemetry.emit('chat', input_tokens=123, prompt='privéadres', access_token='geheim', geometry=[1, 2])
    finally:
        telemetry.logger.removeHandler(handler)
    assert '123' in records[0]
    assert 'privéadres' not in records[0] and 'geheim' not in records[0]
    assert telemetry.operation('/api/shared/secret') == '/api/shared/:token'
    assert telemetry.operation('/api/conversations/abc/requests/secret') == '/api/conversations/:id/requests/:id'
