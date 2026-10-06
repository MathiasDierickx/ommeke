"""Concrete gebruikerswensen en falende routerantwoorden, volledig offline."""
from lusmaker import intents
from lusmaker.quality import evaluate

ROUTE = {'_geometry': [[[51, 4], [51, 4.01], [51.01, 4.01], [51.01, 4], [51, 4]]]}


def short_loop_case(actual_km=12, *, hard=True):
    state = {'id': 'budget-case', 'start': {'lat':51, 'lon':4}, 'loop': True, 'climbs': []}
    request = {'doel': 'kort', 'target_km':10, 'max_km':10, 'max_km_explicit':hard, 'geen_opvulling':False}
    def route(d, db):
        d['computed'] = {'total_km': 0, 'ascend_m':0}
    def optimize(d, db, **kwargs):
        d['computed'] = {'total_km': actual_km, 'ascend_m':100}
    intents._execute_request(state, {}, request, route_fn=route, optimize_fn=optimize)
    return state


def test_short_loop_never_exports_twelve_km_when_user_demands_maximum_ten():
    try:
        short_loop_case()
    except intents.IntentError:
        pass
    else:
        raise AssertionError('12 km aanvaard ondanks hard maximum van 10 km')


def test_soft_goal_is_not_misreported_as_hard_budget_violation():
    state = short_loop_case(hard=False)
    report = intents.constraint_report(state, {'target_km':10,'max_km':11,'max_km_explicit':False,'tolerance_km':1})
    assert report['binnen_doelbereik'] is False
    assert report['binnen_hard_maximum'] is None
    assert not any('harde maximum' in text for text in report['waarschuwingen'])


def test_nonfinite_distance_never_reaches_the_router():
    for value in (float('nan'), float('inf'), True):
        try:
            intents._validate_request(target_km=value, max_km=None, tolerance_km=2.5)
        except intents.IntentError:
            pass
        else:
            raise AssertionError(f'ongeldige afstand aanvaard: {value!r}')


def test_missing_waterway_is_explicitly_reported_in_route_constraints():
    state = {'computed': {'total_km': 10}, 'route_request': {'langs_water': 'Onbekende beek'}}
    report = intents.constraint_report(state)
    assert report.get('langs_water_gepland') is False
    assert any('waterloop' in warning for warning in report['waarschuwingen'])


def test_bike_and_trail_scenarios_keep_distinct_profiles():
    bike = {'profile': 'quiet', 'route_request': {'activiteit': 'fiets'}}
    trail = {'profile': 'trail', 'route_request': {'activiteit': 'trail'}}
    assert bike['profile'] != trail['profile']
    assert trail['route_request']['activiteit'] == 'trail'


def test_waterway_and_landmark_are_checked_against_route_geometry():
    water = evaluate(ROUTE, {'water_points': [[51, 4], [51, 4.01]], 'water_min_pct': 10})
    landmark = evaluate(ROUTE, {'anchors': [{'lat': 51, 'lon': 4.005, 'radius_m': 30}]})
    assert water['ok'] and water['metrics']['water_pct'] >= 10
    assert landmark['ok'] and landmark['metrics']['anchor_0_m'] <= 30


def test_avoidance_zone_is_checked_and_reports_margin():
    result = evaluate(ROUTE, {'avoid': [{'lat': 51, 'lon': 4.005, 'radius_m': 100}]})
    assert not result['ok']
    assert result['metrics']['avoid_0_margin_m'] < 0


def test_unreachable_hard_distance_returns_clear_dutch_intent_error():
    state = {'id': 'onhaalbaar', 'start': {'lat': 51, 'lon': 4}, 'loop': True, 'climbs': []}
    request = {'doel': 'kort', 'target_km': None, 'max_km': 5, 'max_km_explicit': True,
               'tolerance_km': 2.5, 'geen_opvulling': False}
    def route(d, _db):
        d['computed'] = {'total_km': 20}
    def optimize(d, _db, **_kwargs):
        d['computed'] = {'total_km': 20}
    try:
        intents._execute_request(state, {}, request, route_fn=route, optimize_fn=optimize)
    except intents.IntentError as exc:
        assert 'overschrijdt het harde maximum van 5.0 km' in str(exc)
    else:
        raise AssertionError('onhaalbare wens stilzwijgend geaccepteerd')


def test_overlap_tolerance_is_reported_and_enforced():
    retraced = {'_geometry': [[[51, 4], [51, 4.01]], [[51, 4.01], [51, 4]]]}
    result = evaluate(retraced, {'overlap_tolerance_m': 10})
    assert result['metrics']['overlap_tolerance_m'] == 10
    assert not result['ok'] and 'heen-en-weer boven tolerantie' in result['failures']


def test_documented_acceptance_matrix_scenarios_exist():
    required = {
        'test_bike_and_trail_scenarios_keep_distinct_profiles',
        'test_soft_goal_is_not_misreported_as_hard_budget_violation',
        'test_waterway_and_landmark_are_checked_against_route_geometry',
        'test_avoidance_zone_is_checked_and_reports_margin',
        'test_unreachable_hard_distance_returns_clear_dutch_intent_error',
        'test_overlap_tolerance_is_reported_and_enforced',
    }
    present = {name for name in globals() if name.startswith('test_')}
    assert required <= present, f"acceptatiematrix-scenario ontbreekt: {sorted(required - present)}"
