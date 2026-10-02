"""Terugkeren vanaf de huidige positie, met expliciet resterend budget."""
from copy import deepcopy
import math
from . import draft, climbs, geo, intents, quotas
from .route_pois import project


def _route_memory(item, db):
    return draft._route(item, db, save_fn=lambda *a, **kw: None)


def reroute_from(draft_id, lat, lon, rest_km='kortste', *, expected_revision=None, closure=None,
                 load_fn=draft.load, save_fn=draft.save, route_fn=_route_memory,
                 climbs_fn=climbs.all_climbs, export_fn=intents._export_files):
    if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in (lat,lon)) or not -90<=lat<=90 or not -180<=lon<=180:
        raise ValueError('Geef geldige coördinaten voor je huidige positie.')
    if rest_km!='kortste' and (isinstance(rest_km,bool) or not isinstance(rest_km,(int,float)) or not math.isfinite(rest_km) or not 0<rest_km<=300):
        raise ValueError('rest_km moet een positief kilometerbudget of kortste zijn.')
    original=load_fn(draft_id)
    draft.require_revision(original,expected_revision)
    points=[p for leg in original.get('_geometry',[]) for p in leg]
    offset,progress,index,t=project((lat,lon),points)
    if offset>2000: raise ValueError('Je locatie ligt meer dan 2 km van de route. Kies een nieuwe route vanaf hier.')
    quotas.consume('route')
    item=deepcopy(original)
    destination=original.get('return_destination') or original['start']
    item.update(start={'lat':lat,'lon':lon,'label':'Huidige positie'},end=deepcopy(destination),
                return_destination=deepcopy(destination),loop=False,climbs=[],computed=None,opvullingen=[])
    for key in ('water_via','round_trip_anchor','_geometry','cues'): item.pop(key,None)
    traveled=points[:index+1]+[[points[index][0]+t*(points[index+1][0]-points[index][0]),points[index][1]+t*(points[index+1][1]-points[index][1])]]
    item['reroute_avoid']=[{'ring':ring,'factor':.3} for ring in geo.corridor_polygons(traveled,width_m=45,seg_len_m=150,protect_radius_m=80,protect=[(lat,lon),(destination['lat'],destination['lon'])])]
    if closure is not None:
        if not isinstance(closure,dict): raise ValueError('Afsluiting moet coördinaten bevatten.')
        x,y=closure.get('lat'),closure.get('lon')
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (x,y)) or not -90<=x<=90 or not -180<=y<=180:
            raise ValueError('Ongeldige afsluitingslocatie.')
        item['reroute_avoid'].append({'ring':draft._circle_ring(x,y,.1),'factor':0})
    item['route_request']={'doel':'kort','activiteit':'trail' if item.get('profile')=='trail' else 'fietsen',
                           'max_km':None if rest_km=='kortste' else rest_km,'max_km_explicit':rest_km!='kortste'}
    with draft.region_scope(item):
        db=climbs_fn()
        route_fn(item,db)
        actual=geo.path_length([p[:2] for leg in item.get('_geometry',[]) for p in leg])/1000
        if actual<=0: raise ValueError('Geen bruikbare terugweg gevonden.')
        if rest_km!='kortste' and actual>rest_km:
            raise ValueError(f'De terugweg is {actual:.1f} km en past niet binnen {rest_km:g} km. De oorspronkelijke route is behouden.')
        item['reroute']={'from_revision':original.get('revision',0),'ridden_km':round(progress/1000,3),
                         'distance_from_route_m':round(offset),'mode':'kortste met behoud van routevoorkeuren'}
        save_fn(item,expected_revision=original.get('revision',0))
        files=export_fn(item,db)
    return {'status':'ready','draft':item['id'],'revision':item['revision'],'total_km':actual,'files':files,'reroute':item['reroute']}
