"""Vlaams DTM-grid (EPSG:31370) en hoogteprofielhelpers."""
from __future__ import annotations

import io
import json
import math
import os
from pathlib import Path
import struct
import urllib.request
import urllib.parse
import http.cookiejar
import time
import tempfile
import zipfile
import zlib

import numpy as np

from . import config

NODATA = -32768
_GRID_CACHE = {}


def read_geotiff(path_or_bytes):
    data = Path(path_or_bytes).read_bytes() if isinstance(path_or_bytes, (str, Path)) else bytes(path_or_bytes)
    order = '<' if data[:2] == b'II' else '>' if data[:2] == b'MM' else None
    if order is None or struct.unpack_from(order + 'H', data, 2)[0] != 42:
        raise ValueError('ongeldig TIFF-bestand')
    def u16(p): return struct.unpack_from(order + 'H', data, p)[0]
    def u32(p): return struct.unpack_from(order + 'I', data, p)[0]
    offset = u32(4); tags = {}
    while offset:
        n = u16(offset); offset += 2
        for _ in range(n):
            tag, typ, count, val = struct.unpack_from(order + 'HHII', data, offset); offset += 12
            sizes = {1:1, 2:1, 3:2, 4:4, 5:8, 12:8}
            size = sizes.get(typ, 1) * count
            raw = data[val:val+size] if size > 4 else data[offset-4:offset-4+size]
            if typ == 2: value = raw.rstrip(b'\0').decode('ascii', 'replace')
            elif typ == 3: value = struct.unpack(order + 'H'*count, raw)
            elif typ == 4: value = struct.unpack(order + 'I'*count, raw)
            elif typ == 12: value = struct.unpack(order + 'd'*count, raw)
            else: value = raw
            tags[tag] = value[0] if isinstance(value, tuple) and len(value) == 1 else value
        break  # De eerste IFD is het volledige raster; latere directories zijn overzichten.
    w, h = int(tags[256]), int(tags[257]); bits = int(tags.get(258, 32)); sample = int(tags.get(339, 3))
    if bits != 32 or sample != 3: raise ValueError('alleen float32 GeoTIFF wordt ondersteund')
    tiled = 324 in tags
    offsets = tags[324] if tiled else tags[273]; counts = tags[325] if tiled else tags[279]
    offsets = (offsets,) if isinstance(offsets, int) else offsets
    counts = (counts,) if isinstance(counts, int) else counts
    compression = int(tags.get(259, 1)); predictor = int(tags.get(317, 1))
    if compression not in (1, 8, 32946) or predictor not in (1, 3): raise ValueError('niet-ondersteunde TIFF-compressie of predictor')
    tw, th = (int(tags[322]), int(tags[323])) if tiled else (w, int(tags.get(278, h)))
    out = np.full((h, w), np.nan, dtype=np.float32)
    for i, (pos, size) in enumerate(zip(offsets, counts)):
        raw = data[pos:pos+size]; raw = zlib.decompress(raw) if compression in (8, 32946) else raw
        if predictor == 3:
            b = np.frombuffer(raw, dtype=np.uint8).copy(); rowbytes = tw*4
            for y in range(th):
                row = b[y*rowbytes:(y+1)*rowbytes]
                for channel in range(4):
                    start=channel*tw
                    for j in range(1,tw): row[start+j] = (int(row[start+j])+int(row[start+j-1])) & 255
                # TIFF floating predictor transposes byte planes back to interleaved samples.
                b[y*rowbytes:(y+1)*rowbytes] = row.reshape(4, tw).T.reshape(-1)
            tile = np.frombuffer(b.tobytes(), dtype=order+'f4').reshape(th, tw)
        else: tile = np.frombuffer(raw, dtype=order+'f4').reshape(th, tw)
        if tiled: x, y = (i % math.ceil(w/tw))*tw, (i // math.ceil(w/tw))*th
        else: x, y = 0, i*th
        hh, ww = min(th, h-y), min(tw, w-x); out[y:y+hh, x:x+ww] = tile[:hh,:ww]
    scale = tags[33550]; tie = tags[33922]
    x0, y0 = tie[3], tie[4]
    nd = tags.get(42113); nd = float(nd) if nd not in (None, '') else None
    if nd is not None: out[out == nd] = np.nan
    return out, (float(x0), float(y0), float(scale[0])), nd


def wgs84_to_lambert72(lat, lon):
    # NGI seven-parameter Helmert, WGS84 to BD72; rotations in arcseconds.
    phi, lam = math.radians(lat), math.radians(lon)
    a, f = 6378137.0, 1/298.257223563; e2 = f*(2-f)
    n = a/math.sqrt(1-e2*math.sin(phi)**2); h = 0
    x=(n+h)*math.cos(phi)*math.cos(lam); y=(n+h)*math.cos(phi)*math.sin(lam); z=(n*(1-e2)+h)*math.sin(phi)
    tx,ty,tz=106.8686,-52.2978,103.7239; rx,ry,rz=0.3366,-0.457,1.8422; ds=-1.2747
    k=1+ds*1e-6; rx,ry,rz=[math.radians(v/3600) for v in (rx,ry,rz)]
    X=tx+k*x-rz*y+ry*z; Y=ty+rz*x+k*y-rx*z; Z=tz-ry*x+rx*y+k*z
    # Convert BD72 geocentric to Hayford geodetic.
    aa, ff=6378388.,1/297; ee=ff*(2-ff); p=math.hypot(X,Y); bp=math.atan2(Z,p*(1-ee))
    for _ in range(8): bp=math.atan2(Z+ee*(aa/math.sqrt(1-ee*math.sin(bp)**2))*math.sin(bp),p)
    ll=math.atan2(Y,X)
    return _lambert72(bp, ll)


def _lambert72(bp, ll):
    ee=(1/297)*(2-1/297); aa=6378388.; p1=math.radians(51+10/60+0.00204/3600); p2=math.radians(49+50/60+0.00204/3600); p0=math.pi/2; l0=math.radians(4+22/60+2.952/3600)
    m=lambda q: math.cos(q)/math.sqrt(1-ee*math.sin(q)**2)
    t=lambda q: math.tan(math.pi/4-q/2)/((1-math.sqrt(ee)*math.sin(q))/(1+math.sqrt(ee)*math.sin(q)))**(math.sqrt(ee)/2)
    nn=math.log(m(p1)/m(p2))/math.log(t(p1)/t(p2)); F=m(p1)/(nn*t(p1)**nn); rho0=aa*F*t(p0)**nn
    rho=aa*F*t(bp)**nn; theta=nn*(ll-l0)
    return 150000.013+rho*math.sin(theta), 5400088.438+rho0-rho*math.cos(theta)


def build_grid(sources, out_dir, cell_m=20):
    files=[]
    for source in map(Path, sources):
        if source.suffix.lower()=='.zip':
            with zipfile.ZipFile(source) as z:
                files.extend((source,name) for name in z.namelist() if name.lower().endswith('.tif'))
        else: files.append((source,None))
    def read(source,name):
        if name is None: return read_geotiff(source)
        # Keep only one source raster resident at a time; the zip member is spooled to disk.
        with zipfile.ZipFile(source) as archive, tempfile.NamedTemporaryFile(suffix='.tif') as temp:
            with archive.open(name) as member:
                while chunk:=member.read(1024*1024): temp.write(chunk)
            temp.flush(); return read_geotiff(temp.name)
    bounds=[]
    for source,name in files:
        arr,affine,_=read(source,name); bounds.append((arr.shape,affine)); del arr
    x0=min(a[0] for _,a in bounds); top=max(a[1] for _,a in bounds); pix=bounds[0][1][2]; factor=round(cell_m/pix)
    width=math.ceil((max(a[0]+shape[1]*a[2] for shape,a in bounds)-x0)/cell_m); height=math.ceil((top-min(a[1]-shape[0]*a[2] for shape,a in bounds))/cell_m)
    total=np.zeros((height,width),np.float64); count=np.zeros((height,width),np.uint32)
    for (source,name), (shape,(gx,gy,p)) in zip(files,bounds):
        arr,_,_=read(source,name)
        ox=round((gx-x0)/cell_m); oy=round((top-gy)/cell_m)
        padded=np.full((math.ceil(arr.shape[0]/factor)*factor,math.ceil(arr.shape[1]/factor)*factor),np.nan,np.float32)
        padded[:arr.shape[0],:arr.shape[1]]=arr
        blocks=padded.reshape(padded.shape[0]//factor,factor,padded.shape[1]//factor,factor)
        valid_pixels=np.isfinite(blocks)
        sums=np.where(valid_pixels,blocks,0).sum(axis=(1,3),dtype=np.float64)
        counts=valid_pixels.sum(axis=(1,3),dtype=np.uint32)
        ih,iw=sums.shape; total[oy:oy+ih,ox:ox+iw]+=sums; count[oy:oy+ih,ox:ox+iw]+=counts
    grid=np.full((height,width),NODATA,np.int16); valid=count>0; grid[valid]=np.rint(total[valid]/count[valid]*10).astype(np.int16)
    out=Path(out_dir); out.mkdir(parents=True,exist_ok=True); np.save(out/'dtm20.npy',grid)
    meta={'x0':x0,'y0':top,'cell':cell_m,'width':width,'height':height,'scale':0.1,'nodata':NODATA,'crs':'EPSG:31370','bron':'Bron: Digitaal Vlaanderen','licentie':'Modellicentie voor gratis hergebruik','product':938}
    (out/'dtm20.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n'); return meta


def fetch_tiles(dest_dir, kaartbladen=range(1,44)):
    dest=Path(dest_dir); dest.mkdir(parents=True,exist_ok=True)
    jar=http.cookiejar.CookieJar(); opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    headers={'User-Agent':config.USER_AGENT,'Content-Type':'application/json'}
    def request(url, data=None):
        req=urllib.request.Request(url,data=data,headers=headers)
        with opener.open(req,timeout=60) as response: return response.read()
    request('https://download.vlaanderen.be/')
    files=[f'938/DHMVIIDTMRAS5m_k{i:02d}_LB72.zip' for i in kaartbladen]
    orders=json.loads(request('https://download.vlaanderen.be/bff/v1/Orders',json.dumps({'productId':938,'format':None,'discreteVersionIds':[],'fileIds':files,'geographicalCrop':{'clip':False},'email':'','mailOnProcessed':False,'crs':'LB72'}).encode()))['member']
    for order in orders:
        oid=order['orderId']
        while True:
            state=json.loads(request(f'https://download.vlaanderen.be/bff/v1/Orders/{oid}'))
            if state.get('status')=='Completed': break
            if state.get('status') not in ('Queued','Processing','Pending'): raise RuntimeError(f"bestelling {oid} mislukt: {state.get('status')}")
            time.sleep(5)
        download=state['downloads'][0]; payload=request(f"https://download.vlaanderen.be/bff/v1/Orders/{oid}/download/{urllib.parse.quote(str(download['fileId']),safe='')}")
        (dest/Path(download['name']).name).write_bytes(payload)
    return {'bestanden':len(orders),'map':str(dest)}


def grid_dir():
    return Path(os.environ['LUSMAKER_TERRAIN_DIR']) if os.environ.get('LUSMAKER_TERRAIN_DIR') else config.get_region().root/'terrain'

def _grid():
    d=grid_dir(); key=str(d)
    if key not in _GRID_CACHE and (d/'dtm20.npy').exists() and (d/'dtm20.json').exists():
        _GRID_CACHE[key]=(np.load(d/'dtm20.npy',mmap_mode='r'),json.loads((d/'dtm20.json').read_text()))
    return _GRID_CACHE.get(key)

def available(): return _grid() is not None

def sample(points):
    grid_meta=_grid()
    if not grid_meta: return [None for _ in points]
    grid,meta=grid_meta; out=[]
    for lat,lon in points:
        x,y=wgs84_to_lambert72(lat,lon); fx=(x-meta['x0'])/meta['cell']-.5; fy=(meta['y0']-y)/meta['cell']-.5; ix,iy=math.floor(fx),math.floor(fy)
        vals=[]
        for xx,yy,ww in ((ix,iy,(1-fx%1)*(1-fy%1)),(ix+1,iy,(fx%1)*(1-fy%1)),(ix,iy+1,(1-fx%1)*(fy%1)),(ix+1,iy+1,(fx%1)*(fy%1))):
            if 0<=yy<meta['height'] and 0<=xx<meta['width'] and grid[yy,xx]!=NODATA: vals.append((float(grid[yy,xx])*meta['scale'],ww))
        out.append(sum(v*w for v,w in vals)/sum(w for _,w in vals) if vals and sum(w for _,w in vals) else None)
    return out

def ascent(coords):
    from .gh import ascend_with_hysteresis
    dense=[]
    for a,b in zip(coords,coords[1:]):
        if len(a)<3 or len(b)<3: continue
        distance=111000*math.hypot(b[0]-a[0],math.cos(math.radians(a[0]))*(b[1]-a[1])); steps=max(1,math.ceil(distance/20))
        for i in range(steps):
            fraction=i/steps
            elevation=(a[2]+(b[2]-a[2])*fraction) if a[2] is not None and b[2] is not None else (a[2] if a[2] is not None else b[2])
            dense.append((a[0]+(b[0]-a[0])*fraction,a[1]+(b[1]-a[1])*fraction,elevation))
    if coords: dense.append(coords[-1])
    heights=sample([(p[0],p[1]) for p in dense]); profile=[]
    for p,h in zip(dense,heights):
        # Missing DTM samples retain GraphHopper elevation.
        profile.append((p[0],p[1],h if h is not None else (p[2] if len(p)>2 else None)))
    up=ascend_with_hysteresis(profile,1.0)
    down=ascend_with_hysteresis([(p[0],p[1],-p[2] if p[2] is not None else None) for p in profile],1.0)
    return {'coords':profile,'ascend_m':up,'descend_m':down}
