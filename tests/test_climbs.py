from lusmaker import climbs, osm


def _chain():
    coords = [(50.0 + i * 0.00045, 4.0) for i in range(7)]
    refs = list(range(100, 107))
    return coords, refs


def test_junction_refs_require_different_way_ids():
    ways = [
        (1, [10, 20], [], {}),
        (2, [20, 30], [], {}),
        (3, [40, 40, 50], [], {}),
    ]

    assert osm._junction_refs(ways) == {20}


def test_order_chain_keeps_refs_parallel_to_coordinates():
    ways = [
        (11, [100, 101], [(50.0, 4.0), (50.001, 4.0)], {}),
        (12, [101, 102], [(50.001, 4.0), (50.002, 4.0)], {}),
    ]

    merged, refs, way_ids = climbs._order_chain(ways, [0, 1])

    assert way_ids in ([11, 12], [12, 11])
    assert list(zip(refs, merged)) in (
        [
            (100, (50.0, 4.0)),
            (101, (50.001, 4.0)),
            (102, (50.002, 4.0)),
        ],
        [
            (102, (50.002, 4.0)),
            (101, (50.001, 4.0)),
            (100, (50.0, 4.0)),
        ],
    )


def test_resampled_point_maps_to_nearest_original_chain_index():
    merged, _refs = _chain()
    sampled = [merged[0], (50.00091, 4.0), merged[-1]]

    assert climbs._chain_index_for_resampled(merged, sampled, 1) == 2


def test_extension_moves_both_endpoints_to_junction_nodes():
    merged, refs = _chain()

    geom, warnings = climbs._extend_to_junctions(
        merged, refs, foot_index=2, top_index=4, junction_refs={refs[1], refs[5]}
    )

    assert geom == merged[1:6]
    assert warnings == []


def test_extension_preserves_reverse_uphill_direction():
    merged, refs = _chain()

    geom, warnings = climbs._extend_to_junctions(
        merged, refs, foot_index=4, top_index=2, junction_refs={refs[1], refs[5]}
    )

    assert geom == merged[1:6][::-1]
    assert warnings == []


def test_extension_respects_120_meter_cap():
    merged, refs = _chain()

    geom, warnings = climbs._extend_to_junctions(
        merged, refs, foot_index=3, top_index=4, junction_refs={refs[0], refs[4]}
    )

    assert geom == merged[3:5]
    assert warnings == [climbs.BLOCK_WARNING]


def test_extension_warns_when_no_junction_exists():
    merged, refs = _chain()

    geom, warnings = climbs._extend_to_junctions(
        merged, refs, foot_index=2, top_index=4, junction_refs=set()
    )

    assert geom == merged[2:5]
    assert warnings == ["eindigt midden in een blok"]
