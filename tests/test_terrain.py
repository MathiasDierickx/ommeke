import json
import os
from pathlib import Path
import struct
import tempfile
import zlib

import numpy as np

from lusmaker import terrain, gh


def _tiff(values, predictor=1, x0=100, y0=200):
    # Tiny little-endian, tiled, single-strip-compatible GeoTIFF writer.
    arr=np.asarray(values,dtype='<f4'); h,w=arr.shape
    entries=[]
    def tag(i,t,n,v): entries.append((i,t,n,v))
    tag(256,4,1,w); tag(257,4,1,h); tag(258,3,1,32); tag(259,3,1,8); tag(262,3,1,1)
    tag(277,3,1,1); tag(284,3,1,1); tag(317,3,1,predictor); tag(339,3,1,3)
    tag(322,4,1,w); tag(323,4,1,h); tag(324,4,1,0); tag(325,4,1,0)
    tag(33550,12,3,0); tag(33922,12,6,0); tag(42113,2,6,0)
    entries.sort(); ifd=8; extra=ifd+2+12*len(entries)+4; bits=bytearray()
    # Predictor 3 encoder: shuffle samples into four byte planes and delta-code each plane.
    raw=arr.tobytes()
    if predictor==3:
        encoded=[]
        for line in arr:
            planes=line.tobytes()
            planes=np.frombuffer(planes,dtype=np.uint8).reshape(-1,4).T.copy()
            for b in range(4):
                for i in range(w-1,0,-1): planes[b,i]=(int(planes[b,i])-int(planes[b,i-1]))&255
            encoded.append(planes.tobytes())
        raw=b''.join(encoded)
    compressed=zlib.compress(raw)
    scale_pos=extra; bits.extend(struct.pack('<3d',5,5,0)); tie_pos=scale_pos+24; bits.extend(struct.pack('<6d',0,0,0,x0,y0,0)); nd_pos=tie_pos+48; bits.extend(b'-9999\0')
    data_pos=nd_pos+6; bits.extend(compressed)
    values_map={324:data_pos,325:len(compressed),33550:scale_pos,33922:tie_pos,42113:nd_pos}
    out=bytearray(b'II'+struct.pack('<HI',42,ifd)); out.extend(struct.pack('<H',len(entries)))
    for i,t,n,v in entries:
        val=values_map.get(i,v)
        if i==258 or i==259 or i==262 or i==277 or i==284 or i==317 or i==339: field=struct.pack('<H',val)+b'\0\0'
        else: field=struct.pack('<I',val)
        out.extend(struct.pack('<HHI',i,t,n)+field)
    out.extend(struct.pack('<I',0)); out.extend(bits)
    return bytes(out)


def test_read_geotiff_predictors_and_projection():
    for pred in (1,3):
        arr, affine, _=terrain.read_geotiff(_tiff([[1,2],[3,4]],pred))
        assert np.allclose(arr,[[1,2],[3,4]]) and affine==(100.0,200.0,5.0)
    e,n=terrain._lambert72(np.deg2rad(50+40/60+46.461/3600),np.deg2rad(5+48/60+26.533/3600))
    assert abs(e-251763.20)<0.05 and abs(n-153034.13)<0.05


def test_build_grid_sample_and_gh_hook():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp); src=root/'tile.tif'; src.write_bytes(_tiff([[10,-9999],[10,10]]))
        second=root/'tile2.tif'; second.write_bytes(_tiff([[20,20],[20,20]],x0=110))
        terrain.build_grid([src,second],root/'grid',cell_m=5)
        meta=json.loads((root/'grid/dtm20.json').read_text()); grid=np.load(root/'grid/dtm20.npy')
        assert grid.shape==(2,4) and grid[0,1]==terrain.NODATA and grid[0,2]==200
        os.environ['LUSMAKER_TERRAIN_DIR']=str(root/'grid'); terrain._GRID_CACHE.clear()
        assert terrain.available()
        original=terrain.wgs84_to_lambert72
        terrain.wgs84_to_lambert72=lambda lat,lon:(102.5,197.5)
        value=terrain.sample([(50,4)])[0]
        assert value is not None
        result=gh._path_result({'paths':[{'distance':10,'time':1000,'ascend':100,'descend':90,'points':{'coordinates':[[4,50,30],[4.00001,50,35]]}}]})
        assert 'ascend_srtm_m' in result
        terrain.wgs84_to_lambert72=original
        os.environ.pop('LUSMAKER_TERRAIN_DIR',None); terrain._GRID_CACHE.clear()


def test_ascent_uses_dtm_and_falls_back_to_interpolated_srtm():
    original=terrain.sample
    try:
        terrain.sample=lambda points:[10.0 for _ in points]
        flat=terrain.ascent([(50,4,10),(50.001,4,12),(50.002,4,9)])
        assert flat['ascend_m']==0
        terrain.sample=lambda points:[10.0+i*0.5 for i,_ in enumerate(points)]
        slope=terrain.ascent([(50,4,10),(50.001,4,12)])
        assert slope['ascend_m']>0
        terrain.sample=lambda points:[None for _ in points]
        fallback=terrain.ascent([(50,4,10),(50.001,4,12)])
        assert fallback['ascend_m']>0
    finally: terrain.sample=original
