from lusmaker.model_evals import run


def test_live_eval_scores_wrong_first_tool_and_counts_actual_usage():
    cases = [{'id':'one','prompt':'Wandel 3km','expected_tool':'plan_route','expected_arguments':{'activiteit':'trail','profiel_naam':'standaard'},'required_arguments':['request_id']},
             {'id':'two','prompt':'Zoek','expected_tool':'lookup_place'}]
    class Client:
        def converse(self, **kwargs):
            return {'output':{'message':{'content':[{'toolUse':{'name':'plan_route','input':{'activiteit':'trail'}}}]}}, 'usage':{'inputTokens':100,'outputTokens':20}}
    out = run(cases,Client(),'test',system='s',tool_config={},input_rate=1,output_rate=5)
    assert out['score']['geslaagd'] == 1 and out['score']['totaal'] == 2
    assert abs(out['estimated_total_usd']-.0004) < 1e-9
    assert len(out['suite_sha256']) == 64


def test_live_eval_errors_are_failures_not_passes():
    class Client:
        def converse(self, **kwargs): raise RuntimeError('private provider detail')
    result=run([{'id':'x','prompt':'hi','expected_tool':'plan_route'}],Client(),'test',system='',tool_config={})
    assert result['score']['geslaagd'] == 0
    assert result['measurements'][0]['error'] == 'RuntimeError'
    assert 'private' not in str(result)


def test_chat_rejects_unknown_activity_key_before_routing():
    from lusmaker.aws_chat import RouteToolExecutor
    try: RouteToolExecutor().execute('plan_route',{'start':'Ronse','activity':'trail'},request_id='test-case')
    except ValueError as e: assert 'activity' in str(e)
    else: raise AssertionError('walking request silently became bicycle')
