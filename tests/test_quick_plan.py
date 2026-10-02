from lusmaker.quick_plan import parameters, plan
from lusmaker import requests, aws_state


def test_quick_plan_validates_before_routing():
    assert parameters({'start': {'lat': 51, 'lon': 3}, 'target_km': 3})['start'] == '51.000000,3.000000'
    for patch in ({'start': {'lat': float('nan'), 'lon': 3}}, {'target_km': True}, {'target_km': 0}, {'target_km': float('inf')}, {'activiteit': 'auto'}, {'doel': 'random'}):
        try:
            parameters({'start': 'Bredene', 'target_km': 3, **patch})
        except ValueError:
            pass
        else:
            raise AssertionError(patch)


def test_quick_plan_retry_has_no_second_route_or_quota_charge():
    state, calls = {}, []
    def get(key): return (state.get(key), 'etag')
    def put(key, value, **kwargs):
        if kwargs.get('create_only') and key in state: raise aws_state.StateConflict('exists')
        state[key] = value
        return {'ETag': 'etag'}
    def once(*args): return requests.once(*args, get=get, put=put)
    def planner(**kwargs):
        calls.append(kwargs)
        return {'status': 'ready', 'draft': 'abc123'}
    body = {'start': 'Bredene', 'target_km': 3, 'request_id': 'request-123'}
    assert plan(body, planner=planner, once=once) == plan(body, planner=planner, once=once)
    assert len(calls) == 1 and calls[0]['check_readiness']
    try: plan({**body, 'target_km': 4}, planner=planner, once=once)
    except requests.RequestConflict: pass
    else: raise AssertionError('changed request replayed')


def test_quick_plan_questions_keep_draft_context():
    messages = []
    class Store:
        def create(self, title): return {'id': 'conversation'}
        def add_message(self, cid, role, content, **kwargs): messages.append(content)
    result = plan({'start':'Bredene', 'target_km':3,'request_id':'request-234'},
                  planner=lambda **kw: {'status':'needs_input','draft':'abc123','vragen':[{'vraag':'Kasseien?'}]},
                  once=lambda scope,rid,payload,operation: operation(), store_factory=Store)
    assert result['conversation_id'] == 'conversation'
    assert 'abc123' in messages[1] and '3 km' in messages[0]
