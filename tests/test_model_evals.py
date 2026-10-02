from lusmaker.model_evals import run


def test_live_eval_scores_wrong_first_tool_and_counts_actual_usage():
    cases = [{'id':'one','prompt':'Wandel 3km','expected_tool':'plan_route','expected_arguments':{'activiteit':'trail'},'required_arguments':[]},
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


def test_hosted_eval_rejects_unsupported_tools_before_calling_provider():
    from lusmaker.aws_chat import TOOL_CONFIG
    class Never:
        def converse(self, **kw): raise AssertionError('De provider mag niet worden aangeroepen')
    try: run([{'id':'region','prompt':'Maak regio','expected_tool':'ensure_region'}],Never(),'x',system='',tool_config=TOOL_CONFIG)
    except ValueError as exc: assert 'bestaat niet' in str(exc)
    else: raise AssertionError('MCP-only case misleidend als modelmisser gescoord')


def test_hosted_eval_rejects_unknown_arguments_even_when_intent_subset_matches():
    from lusmaker.aws_chat import TOOL_CONFIG
    from lusmaker.model_evals import score
    cases=[{'id':'walk','prompt':'wandel','expected_tool':'plan_route','expected_arguments':{'activiteit':'trail'}}]
    calls=[{'id':'walk','tool':'plan_route','arguments':{'start':'Ronse','activiteit':'trail','activity':'bike'}}]
    assert score(cases,calls,TOOL_CONFIG)['geslaagd']==0
    calls[0]['arguments']={'start':'Ronse','activiteit':'trail'}
    assert score(cases,calls,TOOL_CONFIG)['geslaagd']==1


def test_model_gate_recomputes_score_and_rejects_stale_or_partial_evidence():
    from copy import deepcopy
    from datetime import datetime, timezone
    from lusmaker.model_evals import fingerprint
    from lusmaker.model_gate import verify
    cases=[{'id':str(i),'prompt':'Zoek Wetteren','expected_tool':'lookup_place','required_arguments':['query']} for i in range(10)]
    tools={'tools':[{'toolSpec':{'name':'lookup_place','inputSchema':{'json':{'type':'object','required':['query'],'properties':{'query':{'type':'string'}}}}}}]}
    now=datetime(2026,10,2,tzinfo=timezone.utc)
    report={'model':'candidate','suite_sha256':fingerprint(cases,'prompt',tools),'created_at':'2026-10-02T00:00:00Z',
            'calls':[{'id':str(i),'tool':'lookup_place','arguments':{'query':'Wetteren'}} for i in range(10)],
            'measurements':[{'id':str(i),'seconds':1} for i in range(10)]}
    assert verify(report,'candidate',cases,'prompt',tools,now=now)['ok']
    variants=[]
    bad=deepcopy(report);bad['calls'][0]['tool']='plan_route';bad['score']={'score_pct':100};variants.append(bad)
    bad=deepcopy(report);bad['measurements']=bad['measurements'][:1];variants.append(bad)
    bad=deepcopy(report);bad['created_at']='2025-01-01T00:00:00Z';variants.append(bad)
    bad=deepcopy(report);bad['measurements'][0]['error']='AccessDenied';variants.append(bad)
    bad=deepcopy(report);bad['suite_sha256']='old-prompt';variants.append(bad)
    bad=deepcopy(report);bad['model']='other';variants.append(bad)
    for bad in variants:
        try: verify(bad,'candidate',cases,'prompt',tools,now=now)
        except ValueError: pass
        else: raise AssertionError('Ongeldig evalbewijs vrijgegeven')
