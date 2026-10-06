"""FIT-course writer (protocol 2.0); geen Garmin-account of SDK-dependency nodig.

Veldnummers en schalen: Garmin FIT global profile, file_id/course/lap/record/course_point.
https://developer.garmin.com/fit/articles/fit-protocol/fit_protocol.html
"""
import struct
import time
from pathlib import Path
from . import geo
from .route_pois import for_draft, project


def crc(data):
    value=0
    for byte in data:
        value ^= byte
        for _ in range(8): value=(value>>1)^0xA001 if value&1 else value>>1
    return value


def _text(value,size=64):
    raw=str(value).encode('utf-8')[:size-1].decode('utf-8','ignore').encode('utf-8')
    return raw+b'\0'*(size-len(raw))


# GraphHopper-instructiesign -> FIT course_point-type (FIT SDK Profile).
# 4 finish, 5 via en 6 rotonde worden generic; de tekst van de cue blijft staan.
SIGN_NAAR_FIT={-98:23,-8:23,-7:16,-3:20,-2:6,-1:19,0:8,1:21,2:7,3:22,4:0,5:0,6:0,7:17,8:23}
FIT_GENERIC=0
# Veilige bovengrens: Garmin-apparaten weigeren of vertragen cursussen met te veel punten.
MAX_COURSE_POINTS=200
_PRIORITEIT={'klim':0,'afslag':1,'poi':2}


def beperk_cues(cues,limit=MAX_COURSE_POINTS):
    """Houd maximaal `limit` cues: klimstarts eerst, dan afslagen, dan POI's; gesorteerd op afstand."""
    if len(cues)>limit:
        cues=sorted(cues,key=lambda c:(_PRIORITEIT[c['soort']],c['distance_m']))[:limit]
    return sorted(cues,key=lambda c:c['distance_m'])


def encode(d, climb_db, *, timestamp=None, pois=None, poi_types=None):
    points=[p for leg in d.get('_geometry',[]) for p in leg]
    if len(points)<2: raise ValueError('Routeer eerst de route voor FIT-export.')
    timestamp=int(time.time() if timestamp is None else timestamp)-631065600
    payload=bytearray()
    def message(number,fields,values):
        # Eén lokale definitie per bericht; bewust eenvoudig en interoperabel.
        payload.extend(struct.pack('<BBBH',0x40,0,0,number)+bytes([len(fields)]))
        for field,size,kind in fields: payload.extend(bytes([field,size,kind]))
        payload.append(0)
        payload.extend(values)
    message(0,[(0,1,0),(1,2,0x84),(4,4,0x86)],struct.pack('<BHI',6,255,timestamp))
    message(31,[(4,1,0),(5,64,7)],bytes([11 if d.get('profile')=='trail' else 2])+_text(d.get('name','Ommeke')))
    distances=[0.0]
    for a,b in zip(points,points[1:]): distances.append(distances[-1]+geo.haversine(*a[:2],*b[:2]))
    semi=lambda value: round(value*(2**31)/180)
    pace=1.4 if d.get('profile')=='trail' else 5.0
    duration=round(distances[-1]/pace)
    message(19,[(253,4,0x86),(2,4,0x86),(3,4,0x85),(4,4,0x85),(5,4,0x85),(6,4,0x85),(7,4,0x86),(8,4,0x86),(9,4,0x86)],
            struct.pack('<IIiiiiIII',timestamp+duration,timestamp,semi(points[0][0]),semi(points[0][1]),semi(points[-1][0]),semi(points[-1][1]),duration*1000,duration*1000,round(distances[-1]*100)))
    cues=[{**c,'type':SIGN_NAAR_FIT.get(c.get('sign'),FIT_GENERIC),'soort':'afslag'} for c in d.get('cues',[])]
    for cid in d.get('climbs',[]):
        c=climb_db.get(cid)
        if c: cues.append({'lat':c['foot'][0],'lon':c['foot'][1],'text':c['name'],'type':43,'soort':'klim'})
    from .route_pois import select
    for p in select(for_draft(d) if pois is None else pois, poi_types):
        cues.append({**p,'text':p['name'],'type':{'water':3,'cafe':4,'bakker':4,'toilet':39,'fietsenmaker':31}.get(p['kind'],0),'soort':'poi'})
    for cue in cues:
        cue['distance_m']=project((cue['lat'],cue['lon']),points)[1]
    cues=beperk_cues(cues)
    cue_index=0
    def cue_message(c):
        m=c['distance_m']
        message(32,[(1,4,0x86),(2,4,0x85),(3,4,0x85),(4,4,0x86),(5,1,0),(6,64,7)],
                struct.pack('<IiiIB',timestamp+round(m/pace),semi(c['lat']),semi(c['lon']),round(m*100),c['type'])+_text(c['text']))
    event=lambda ts,kind: message(21,[(253,4,0x86),(0,1,0),(1,1,0)],struct.pack('<IBB',ts,0,kind))
    event(timestamp,0)  # timer start bij het eerste record
    for point,distance in zip(points,distances):
        while cue_index<len(cues) and cues[cue_index]['distance_m']<=distance:
            cue_message(cues[cue_index]); cue_index+=1
        ele=point[2] if len(point)>2 else None
        altitude=65535 if ele is None else max(0,min(65534,round((ele+500)*5)))
        message(20,[(253,4,0x86),(0,4,0x85),(1,4,0x85),(2,2,0x84),(5,4,0x86)],
                struct.pack('<IiiHI',timestamp+round(distance/pace),semi(point[0]),semi(point[1]),altitude,round(distance*100)))
    for c in cues[cue_index:]: cue_message(c)  # veiligheidsnet voor afrondingsverschillen
    event(timestamp+round(distances[-1]/pace),9)  # timer stop_disable_all bij het laatste record
    header=struct.pack('<BBHI4s',14,0x20,21217,len(payload),b'.FIT')
    header+=struct.pack('<H',crc(header))
    body=header+payload
    return body+struct.pack('<H',crc(body))


def export(d, climb_db, path):
    data=encode(d,climb_db)
    Path(path).write_bytes(data)
    return {'file':str(path),'bytes':len(data),'timing':'geschat; geen opgenomen activiteit'}
