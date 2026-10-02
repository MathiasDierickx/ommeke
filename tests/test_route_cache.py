from lusmaker.route_cache import RouteCache


def test_route_cache_separates_model_and_does_not_leak_mutations():
    calls=[]
    def router(points, **kwargs):
        calls.append(kwargs)
        return {'coords':[[51,3]],'distance_m':100}
    cache=RouteCache(router)
    a=cache([(51,3),(51.1,3)],profile='quiet',avoid_polygons=[])
    a['coords'].append([0,0])
    b=cache([(51,3),(51.1,3)],avoid_polygons=[],profile='quiet')
    assert len(b['coords'])==1 and len(calls)==1 and cache.hits==1
    cache([(51,3),(51.1,3)],profile='trail',avoid_polygons=[])
    cache([(51,3),(51.1,3)],profile='quiet',avoid_polygons=[{'factor':.3}])
    assert len(calls)==3
    RouteCache(router)([(51,3),(51.1,3)],profile='quiet',avoid_polygons=[])
    assert len(calls)==4


def test_route_cache_never_caches_failures_and_is_bounded():
    count=[0]
    def router(*args,**kwargs):
        count[0]+=1
        if count[0]==1: raise RuntimeError('unavailable')
        return {'distance_m':count[0]}
    cache=RouteCache(router,max_entries=1)
    try: cache([1])
    except RuntimeError: pass
    assert cache([1])['distance_m']==2
    cache([2]); cache([2])
    assert count[0]==4 and len(cache.values)==1
