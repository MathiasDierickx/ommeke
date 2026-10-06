"""OSM-punten langs een route, met afstand langs de werkelijke geometrie."""
import math
import re
from . import geo

KINDS = {'amenity:drinking_water':'water','amenity:cafe':'cafe','shop:bakery':'bakker',
         'amenity:toilets':'toilet','shop:bicycle':'fietsenmaker'}


STOP_KINDS = frozenset(KINDS.values())
from .tvl_places import KINDS as LODGING_KINDS
EXPORT_KINDS = STOP_KINDS | frozenset(LODGING_KINDS.values()) | {'logies'}


def parse_selection(value):
    """None = alle voorzieningen; lege set = expliciet verborgen."""
    if value is None:
        return None
    if value == 'geen':
        return frozenset()
    parts = value.split(',')
    kinds = frozenset(parts)
    # De kaart toont ook Toerisme Vlaanderen-types (zitbank, fietspomp_en_fietsherstel, ...);
    # filteren gebeurt op wat er langs de route ligt, dus valideer de vorm, geen vaste lijst.
    if (not value or '' in parts or kinds & {'alle', 'geen'} or len(kinds) > 20
            or not all(re.fullmatch(r'[a-z][a-z_]{1,39}', kind) for kind in kinds)):
        raise ValueError('Ongeldige keuze van voorzieningen; gebruik types zoals cafe,water of geen.')
    return kinds


def select(pois, kinds):
    return list(pois) if kinds is None else [p for p in pois if p['kind'] in kinds]


def project(point, track):
    """Dichtste segmentprojectie: afstand tot route, routeafstand, segment en fractie."""
    if len(track)<2: raise ValueError('Route heeft minstens twee punten nodig.')
    best, along = None, 0.0
    for index,(a,b) in enumerate(zip(track,track[1:])):
        scale=math.cos(math.radians(point[0]))
        ax,ay=(a[1]-point[1])*scale,a[0]-point[0]
        bx,by=(b[1]-point[1])*scale,b[0]-point[0]
        dx,dy=bx-ax,by-ay
        t=max(0,min(1,-(ax*dx+ay*dy)/(dx*dx+dy*dy))) if dx or dy else 0
        lat,lon=a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1])
        length=geo.haversine(*a[:2],*b[:2])
        candidate=(geo.haversine(*point[:2],lat,lon),along+t*length,index,t)
        if best is None or candidate[:2]<best[:2]: best=candidate
        along+=length
    return best


def along_route(track, places, *, radius_m=150, limit=100):
    if len(track)<2: return []
    result=[]
    south,north=min(p[0] for p in track)-.002,max(p[0] for p in track)+.002
    west,east=min(p[1] for p in track)-.004,max(p[1] for p in track)+.004
    for place in places:
        tags=place.get('tags',{})
        kind=next((value for key,value in KINDS.items() if tags.get(key.split(':')[0])==key.split(':')[1]),None)
        centre=place.get('center') or place
        lat,lon=centre.get('lat'),centre.get('lon')
        if not kind or lat is None or lon is None or tags.get('access') in ('private','no'): continue
        if not south<=lat<=north or not west<=lon<=east: continue
        offset,distance,_,_=project((lat,lon),track)
        if offset>radius_m: continue
        result.append({'id':f"{place['type']}/{place['id']}",'kind':kind,'name':tags.get('name') or kind,
                       'lat':lat,'lon':lon,'at_km':round(distance/1000,3),'offset_m':round(offset),
                       'opening_hours':tags.get('opening_hours'),'source':f"https://www.openstreetmap.org/{place['type']}/{place['id']}"})
    return sorted(result,key=lambda p:(p['at_km'],p['id']))[:limit]


def for_draft(d, *, gazetteer=None, source_pois=None, limit=100):
    from . import geocode, draft, tvl_places
    injected = gazetteer is not None
    try:
        from . import config
        config.get_region(draft.region_slug(d))
    except RuntimeError:
        return []  # oude/gedeelde routes kunnen een niet-geïnstalleerde regio hebben
    with draft.region_scope(d):
        if gazetteer is None:
            try:
                gazetteer = geocode._load()
            except (RuntimeError, OSError):
                gazetteer = {}
        if source_pois is None:
            source_pois = [] if injected else tvl_places.along_route(d.get('_geometry', []), limit=limit)
        # Onderbroken legs niet verbinden met een fictief pad.
        osm, distance = [], 0
        for leg in d.get('_geometry', []):
            for item in along_route(leg, gazetteer.get('nearby_places', []), limit=limit):
                osm.append({**item, 'at_km': round(item['at_km']+distance/1000, 3)})
            distance += geo.path_length(leg)
        result = list(source_pois)
        seen = {p['id'] for p in result}
        for item in osm:
            if item['id'] in seen:
                continue
            if any(item['kind'] == p['kind'] and geo.haversine(item['lat'], item['lon'], p['lat'], p['lon']) < 10
                   for p in result):
                continue
            result.append(item)
            seen.add(item['id'])
        return sorted(result, key=lambda p: (p['at_km'], p['id']))[:limit]
