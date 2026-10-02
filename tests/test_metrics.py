from lusmaker.metrics import summarize


def test_summary_reports_tail_latency_cost_and_returning_users():
    events = [{'event': 'http', 'operation': '/mcp', 'seconds': n, 'status': 200, 'actor': 'a', 'date': f'2026-10-{n:02}'} for n in range(1, 21)]
    events += [{'event': 'chat', 'success': True, 'input_tokens': 1_000_000, 'output_tokens': 500_000}]
    result = summarize(events, input_per_million=1, output_per_million=2)
    assert result['latency']['/mcp']['p95_s'] == 19
    assert result['estimated_model_cost'] == 2
    assert result['users_on_multiple_days'] == 1
    assert summarize([])['measured_users'] is None
    assert summarize([])['estimated_model_cost'] is None
