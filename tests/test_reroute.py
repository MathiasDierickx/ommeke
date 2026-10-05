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


def _corridor_fixture():
    from lusmaker import geo
    out=[[51,3+i*0.004,0] for i in range(11)]            # heenweg, ~2,8 km
    back=[[51.003,3.04-i*0.004,0] for i in range(11)]   # terugweg ~330 m noordelijker
    original={'id':'abc123','revision':1,'name':'Route','start':{'lat':51,'lon':3,'label':'Start'},'profile':'standaard','climbs':[],
              '_geometry':[out+[[51.003,3.04,0]]+back],'loop':True,'computed':{'total_km':6}}
    seen={}
    def route(item,db):
        seen['avoid']=deepcopy(item['reroute_avoid']); seen['request']=deepcopy(item['route_request'])
        item['_geometry']=[[[51,3.02,0],[51,3.0,0]]]
    def save(item,**kw): item['revision']=2
    kw=dict(load_fn=lambda _:deepcopy(original),save_fn=save,route_fn=route,climbs_fn=lambda:{},export_fn=lambda *a:{})
    return geo,seen,kw


def test_reroute_corridor_penalises_only_the_ridden_part_and_spares_position_and_destination():
    geo,seen,kw=_corridor_fixture()
    reroute_from('abc123',51,3.02,'kortste',expected_revision=1,**kw)
    rings=[a['ring'] for a in seen['avoid']]
    assert rings and all(a['factor']==.3 for a in seen['avoid'])
    inside=lambda lat,lon:any(geo.point_in_ring(lat,lon,r) for r in rings)
    assert inside(51,3.008) and inside(51,3.014)          # reeds gereden stuk heeft strafzone
    assert not inside(51,3.03)                            # nog niet gereden
    assert not inside(51.003,3.01)                        # terugweg van de oorspronkelijke lus
    assert not inside(51,3.02) and not inside(51,3.0)     # huidige positie en bestemming beschermd
    assert seen['request']['max_km'] is None and seen['request']['doel']=='kort'


def test_reroute_closure_adds_a_zero_factor_zone_and_is_optional():
    geo,seen,kw=_corridor_fixture()
    reroute_from('abc123',51,3.02,'kortste',expected_revision=1,**kw)
    assert all(a['factor']>0 for a in seen['avoid'])
    reroute_from('abc123',51,3.02,'kortste',expected_revision=1,closure={'lat':51.002,'lon':3.03},**kw)
    closed=[a for a in seen['avoid'] if a['factor']==0]
    assert len(closed)==1
    assert geo.point_in_ring(51.002,3.03,closed[0]['ring'])
    assert not geo.point_in_ring(51.002,3.033,closed[0]['ring'])   # ~230 m verderop: buiten de ~100 m-zone
    for bad in ({'lat':91,'lon':3},{'lat':'x','lon':3},{'lat':51},'hier'):
        try: reroute_from('abc123',51,3.02,'kortste',expected_revision=1,closure=bad,**kw)
        except ValueError: pass
        else: raise AssertionError(f'ongeldige afsluiting geaccepteerd: {bad!r}')
