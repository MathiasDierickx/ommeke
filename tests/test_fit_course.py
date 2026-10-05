import struct
from lusmaker.fit_course import encode, crc


def _decode(data):
    assert data[8:12]==b'.FIT'
    length=struct.unpack_from('<I',data,4)[0]
    assert len(data)==14+length+2
    assert crc(data[:12])==struct.unpack_from('<H',data,12)[0]
    assert crc(data[:-2])==struct.unpack_from('<H',data,len(data)-2)[0]
    definitions, records={},[]
    offset=14
    while offset<14+length:
        header=data[offset]; offset+=1
        local=header&15
        if header&64:
            _,endian,number,count=struct.unpack_from('<BBHB',data,offset);offset+=5
            assert endian==0
            fields=[tuple(data[i:i+3]) for i in range(offset,offset+count*3,3)]
            offset+=count*3; definitions[local]=(number,fields)
        else:
            number,fields=definitions[local]; decoded={}
            for field,size,kind in fields:
                value=data[offset:offset+size]; offset+=size
                decoded[field]=value.rstrip(b'\0').decode('utf-8') if kind==7 else int.from_bytes(value,'little',signed=kind==0x85)
            records.append((number,decoded))
    assert offset==14+length
    return records


def test_fit_course_roundtrip_fields_distance_altitude_cues_and_crc():
    assert crc(b'123456789')==0xBB3D
    d={'name':'Kust & café','profile':'trail','climbs':[], '_geometry':[[[51,3,None],[51,3.01,12]]],
       'cues':[{'lat':51,'lon':3.005,'text':'Rechtsaf','sign':2}]}
    records=_decode(encode(d,{},timestamp=1760000000,pois=[]))
    assert records[0][0]==0 and records[0][1][0]==6
    course=next(r for n,r in records if n==31)
    assert course[4]==11 and course[5]=='Kust & café'
    points=[r for n,r in records if n==20]
    assert points[0][2]==65535 and points[1][2]==2560
    assert 69000<points[1][5]<71000
    cues=[r for n,r in records if n==32]
    assert cues[0][5]==7 and cues[0][6]=='Rechtsaf'
    lap=next(r for n,r in records if n==19)
    assert lap[9]==points[-1][5]


def _route(cues,climbs=None):
    # Rechte lijn van ~7 km oost; cues liggen verspreid langs de lijn.
    return {'name':'Test','profile':'fiets','climbs':climbs or [],
            '_geometry':[[[51,3,None],[51,3.1,10]]],'cues':cues}


def test_fit_sign_mapping_alle_graphhopper_signs():
    verwacht={-98:23,-8:23,-7:16,-3:20,-2:6,-1:19,0:8,1:21,2:7,3:22,4:0,5:0,6:0,7:17,8:23}
    cues=[{'lat':51,'lon':3+0.005*(i+1),'text':f'sign {s}','sign':s} for i,s in enumerate(verwacht)]
    records=_decode(encode(_route(cues),{},timestamp=1760000000,pois=[]))
    gevonden={r[6]:r[5] for n,r in records if n==32}
    for s,t in verwacht.items(): assert gevonden[f'sign {s}']==t,(s,gevonden[f'sign {s}'])
    assert gevonden['sign -7']!=23  # keep left is geen u-turn


def test_fit_header_crc_sport_afstand_en_timer_events():
    data=encode(_route([{'lat':51,'lon':3.05,'text':'Links','sign':-2}]),{},timestamp=1760000000,pois=[])
    records=_decode(data)  # controleert header- en bestands-CRC
    assert next(r for n,r in records if n==31)[4]==2
    punten=[r for n,r in records if n==20]
    lap=next(r for n,r in records if n==19)
    assert lap[9]==punten[-1][5] and 6900*100<lap[9]<7200*100
    events=[(i,r) for i,(n,r) in enumerate(records) if n==21]
    assert [(r[0],r[1]) for _,r in events]==[(0,0),(0,9)]
    record_idx=[i for i,(n,_) in enumerate(records) if n==20]
    assert events[0][0]<record_idx[0] and events[1][0]>record_idx[-1]
    assert events[0][1][253]==punten[0][253] and events[1][1][253]==punten[-1][253]


def test_fit_cues_gecapt_geordend_en_prioriteit():
    from lusmaker.fit_course import MAX_COURSE_POINTS
    n=MAX_COURSE_POINTS+60
    cues=[{'lat':51,'lon':3+0.1*(i+1)/(n+2),'text':f'afslag {i}','sign':2} for i in range(n)]
    pois=[{'lat':51,'lon':3.0001,'name':'Water vooraan','kind':'water'}]
    climbs={'kl':{'foot':(51,3.099),'name':'Klim'}}
    records=_decode(encode(_route(cues,['kl']),climbs,timestamp=1760000000,pois=pois))
    cps=[r for n_,r in records if n_==32]
    assert len(cps)==MAX_COURSE_POINTS
    assert [c[4] for c in cps]==sorted(c[4] for c in cps)
    assert [c[1] for c in cps]==sorted(c[1] for c in cps)
    teksten=[c[6] for c in cps]
    assert 'Klim' in teksten and 'Water vooraan' not in teksten


def test_fit_empty_route_rejected():
    try: encode({'_geometry':[]},{},pois=[])
    except ValueError: pass
    else: raise AssertionError('empty course')
