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
