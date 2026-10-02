from copy import deepcopy
from lusmaker.reroute import reroute_from
from lusmaker import draft


def test_return_route_preserves_original_on_budget_failure_and_checks_revision():
    original={'id':'abc123','revision':4,'name':'Route','start':{'lat':51,'lon':3,'label':'Start'},'profile':'trail','climbs':[],
              '_geometry':[[[51,3,0],[51,3.01,0],[51.01,3.01,0],[51,3,0]]],'loop':True,'computed':{'total_km':3}}
    saved=[]
    def route(item,db):
        item['_geometry']=[[[51,3.01,0],[51,3,0]]]
        item['computed']={'total_km':.7}
        assert item['end']['label']=='Start' and not item['loop'] and item['profile']=='trail'
        assert item['reroute_avoid']
    def save(item,**kw):
        assert kw['expected_revision']==4
        item['revision']=5; saved.append(deepcopy(item))
    kw=dict(load_fn=lambda _:deepcopy(original), save_fn=save, route_fn=route, climbs_fn=lambda:{},export_fn=lambda *a:{})
    try: reroute_from('abc123',51,3.01,.2,expected_revision=4,**kw)
    except ValueError as e: assert 'oorspronkelijke route' in str(e)
    else: raise AssertionError('hard budget ignored')
    assert not saved and original['revision']==4
    result=reroute_from('abc123',51,3.01,1,expected_revision=4,**kw)
    assert result['revision']==5 and result['status']=='ready'
    try: reroute_from('abc123',51,3.01,1,expected_revision=3,**kw)
    except draft.DraftError: pass
    else: raise AssertionError('stale revision accepted')
