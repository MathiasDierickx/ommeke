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


def test_fit_empty_route_rejected():
    try: encode({'_geometry':[]},{},pois=[])
    except ValueError: pass
    else: raise AssertionError('empty course')
