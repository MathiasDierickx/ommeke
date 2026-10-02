"""Concrete gebruikerswensen en falende routerantwoorden, volledig offline."""
from lusmaker import intents


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
