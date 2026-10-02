from lusmaker.quality import evaluate

SQUARE = {'_geometry': [[[51, 4], [51, 4.01], [51.01, 4.01], [51.01, 4], [51, 4]]]}


def test_budget_closure_and_landmark_acceptance_use_geometry_not_claimed_stats():
    route = {**SQUARE, 'computed': {'total_km': 1}}
    assert evaluate(route, {'max_km': 4, 'anchors': [{'lat': 51, 'lon': 4.005, 'radius_m': 30}]})['ok']
    result = evaluate(route, {'max_km': 1})
    assert not result['ok'] and 'hard afstandsbudget overschreden' in result['failures']
    assert not evaluate({'_geometry': [[[51,4],[51,4.01]]]}, {})['ok']


def test_avoidance_samples_segment_interior_and_water_share_is_measured():
    result = evaluate(SQUARE, {'avoid': [{'lat': 51, 'lon': 4.005, 'radius_m': 100}]})
    assert not result['ok']
    near = evaluate(SQUARE, {'water_points': [[51,4],[51,4.01]], 'water_min_pct': 10})
    assert near['ok'] and 10 < near['metrics']['water_pct'] < 60
    assert not evaluate(SQUARE, {'water_points': [[52,5],[52,5.01]], 'water_min_pct': 10})['ok']


def test_invalid_and_disconnected_routes_fail_instead_of_reporting_ready():
    assert not evaluate({'_geometry': [[[float('nan'),4]]]}, {})['ok']
    assert not evaluate({'_geometry': [[[51,4],[51,4.01]], [[52,4],[51,4]]]}, {})['ok']
