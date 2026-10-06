from lusmaker.route_pois import along_route, project


def test_poi_projects_to_segment_not_only_track_vertices():
    track=[[51,3],[51,3.02]]
    points=[{'type':'node','id':i,'lat':lat,'lon':3.01,'tags':{'amenity':'drinking_water',**tags}}
            for i,lat,tags in [(1,51.0001,{}),(2,51.01,{}),(3,51,{'access':'private'})]]
    found=along_route(track,points)
    assert len(found)==1 and found[0]['id']=='node/1'
    assert .69<found[0]['at_km']<.71 and found[0]['offset_m']<15
    assert found[0]['opening_hours'] is None


def test_projection_reports_progress_for_return_route():
    offset,metres,index,t=project((51,3.01),[[51,3],[51,3.02],[51.01,3.02]])
    assert offset<1 and index==0 and abs(t-.5)<1e-6 and metres>600


def test_export_selection_validates_known_kinds():
    from lusmaker.route_pois import parse_selection, select
    assert parse_selection(None) is None
    assert parse_selection('geen') == set()
    assert parse_selection('cafe,water,cafe') == {'cafe', 'water'}
    assert parse_selection('vakantiewoning') == {'vakantiewoning'}
    for bad in ('', 'alle', 'cafe,geen', 'Onbekend', 'cafe,'):
        try:
            parse_selection(bad)
        except ValueError:
            continue
        raise AssertionError(f'{bad!r} werd aanvaard')
    assert select([{'kind':'cafe'}, {'kind':'water'}], {'cafe'}) == [{'kind':'cafe'}]


def test_gpx_filters_saved_pois_preserving_climbs_track_and_cues():
    from lusmaker.gpx import filter_pois
    import xml.etree.ElementTree as ET
    payload = b'<gpx xmlns="http://www.topografix.com/GPX/1/1"><metadata><name>Route</name></metadata><wpt lat="51" lon="3"><name>Klim</name></wpt><wpt lat="51" lon="3"><type>cafe</type></wpt><wpt lat="51" lon="3"><type>water</type></wpt><rte><rtept lat="51" lon="3"/></rte><trk><trkseg><trkpt lat="51" lon="3"/></trkseg></trk></gpx>'
    ns = {'g': 'http://www.topografix.com/GPX/1/1'}
    assert filter_pois(payload, None) is payload
    for selection, count in [({'water'}, 2), (set(), 1), ({'water','cafe'}, 3)]:
        root = ET.fromstring(filter_pois(payload, selection))
        assert len(root.findall('g:wpt', ns)) == count
        assert root.find('g:wpt/g:name', ns).text == 'Klim'
        assert root.find('g:rte/g:rtept', ns) is not None
        assert root.find('g:trk/g:trkseg/g:trkpt', ns) is not None


def test_export_endpoints_reject_invalid_filter_before_loading():
    import asyncio, json
    from starlette.requests import Request
    from lusmaker.aws_api import route_gpx, route_fit
    for endpoint in (route_gpx, route_fit):
        response = asyncio.run(endpoint(Request({'type':'http', 'query_string':b'poi=Cafe;drop'})))
        assert response.status_code == 400
        assert json.loads(response.body)['code'] == 'invalid_poi'


def test_gpx_endpoint_serves_filtered_artifact_with_existing_headers():
    import asyncio
    from unittest.mock import patch
    from starlette.requests import Request
    from lusmaker import aws_api
    payload = b'<gpx xmlns="http://www.topografix.com/GPX/1/1"><wpt lat="51" lon="3"><type>cafe</type></wpt><wpt lat="51" lon="3"><type>water</type></wpt><trk/></gpx>'
    with patch.object(aws_api.draft, 'load', return_value={'id':'r1','name':'Test'}), patch.object(aws_api.artifacts, 'read', return_value=payload):
        for query, expected in [(b'', payload), (b'poi=geen', None), (b'poi=water', None)]:
            response = asyncio.run(aws_api.route_gpx(Request({'type':'http', 'query_string':query, 'path_params':{'draft_id':'r1'}})))
            assert response.status_code == 200
            assert response.headers['cache-control'] == 'private, no-store'
            assert 'attachment;' in response.headers['content-disposition']
            if expected:
                assert response.body == expected
            else:
                assert b'<type>cafe</type>' not in response.body
                assert (b'<type>water</type>' in response.body) == (query == b'poi=water')


def test_poi_limit_can_be_disabled_for_stop_search():
    points = [{'type':'node','id':i,'lat':51,'lon':3.0001+i*.0001,'tags':{'amenity':'cafe'}} for i in range(130)]
    assert len(along_route([[51,3],[51,3.02]], points)) == 100
    assert len(along_route([[51,3],[51,3.02]], points, limit=None)) == 130


def test_fit_endpoint_applies_poi_filter_and_preserves_headers():
    import asyncio
    from unittest.mock import patch
    from starlette.requests import Request
    from lusmaker import aws_api, fit_course
    from tests.test_fit_course import _decode
    item = {'id':'r1', 'name':'Test', 'climbs':[], '_geometry':[[[51,3],[51,3.02]]]}
    pois = [{'kind':kind, 'name':kind, 'lat':51, 'lon':3.01} for kind in ('water','cafe')]
    with patch.object(aws_api.draft, 'load', return_value=item), patch.object(aws_api.climbs, 'all_climbs', return_value={}), patch.object(fit_course, 'for_draft', return_value=pois):
        for query, expected in [(b'', {'water','cafe'}), (b'poi=geen', set()), (b'poi=cafe', {'cafe'})]:
            response = asyncio.run(aws_api.route_fit(Request({'type':'http', 'query_string':query, 'path_params':{'draft_id':'r1'}})))
            assert response.status_code == 200
            assert response.headers['cache-control'] == 'private, no-store'
            assert 'attachment;' in response.headers['content-disposition']
            assert {r[6] for n,r in _decode(response.body) if n == 32} == expected


def test_export_selection_accepts_tourism_flanders_kinds_and_rejects_garbage():
    from lusmaker.route_pois import parse_selection
    # Live (6 okt): de kaart toonde 'fietspomp_en_fietsherstel', de download gaf 400.
    assert parse_selection('fietspomp_en_fietsherstel,zitbank') == {'fietspomp_en_fietsherstel', 'zitbank'}
    for bad in ('', 'Cafe', 'cafe;drop', '../x', ','.join(f'k{i}x' for i in range(25))):
        try:
            parse_selection(bad)
            raise AssertionError(f'verwacht ValueError voor {bad!r}')
        except ValueError:
            pass
