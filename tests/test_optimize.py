import os
import tempfile
from pathlib import Path

from lusmaker import draft, geo


def _climb(climb_id, foot, gain_m, length_m=500):
    return {
        "id": climb_id,
        "foot": foot,
        "gain_m": gain_m,
        "length_m": length_m,
    }


def _candidate(climb_id, extra_km, gain_m, position=0):
    return {
        "climb": {"id": climb_id},
        "extra_km": extra_km,
        "extra_hoogtemeters": gain_m,
        "invoegen_op_positie": position,
    }


def test_pick_anchor_chooses_highest_gain_that_fits():
    start = {"lat": 50.0, "lon": 4.0}
    climbs = {
        "near-low": _climb("near-low", [50.01, 4.0], 40),
        "near-high": _climb("near-high", [50.02, 4.0], 90),
        "far-highest": _climb("far-highest", [51.0, 4.0], 200),
    }

    anchor = draft._pick_anchor(start, climbs, max_km=10)

    assert anchor["id"] == "near-high"


def test_pick_anchor_returns_none_when_nothing_fits():
    start = {"lat": 50.0, "lon": 4.0}
    climbs = {"far": _climb("far", [51.0, 4.0], 200)}

    assert draft._pick_anchor(start, climbs, max_km=5) is None


def test_eligible_candidates_filters_ratio_budget_and_banned():
    candidates = [
        _candidate("good", 4.0, 40),
        _candidate("low-ratio", 4.0, 20),
        _candidate("over-margin", 8.6, 100),
        _candidate("banned", 2.0, 80),
        _candidate("short", 0.0, 3),
    ]

    eligible = draft._eligible_candidates(
        candidates, budget_km=10.0, min_ratio=8.0, banned={"banned"}
    )

    assert [candidate["climb"]["id"] for candidate in eligible] == ["good", "short"]


def test_select_candidate_uses_objective():
    candidates = [
        _candidate("most-gain", 5.0, 80),
        _candidate("best-ratio", 2.0, 50),
    ]

    # `hm` is sugar voor de genormaliseerde hoogtemetercomponent (hm/km).
    assert draft._select_candidate(candidates, "hm")["climb"]["id"] == "best-ratio"
    assert draft._select_candidate(candidates, "hm-per-km")["climb"]["id"] == "best-ratio"


def test_missing_profile_and_override_preserve_legacy_default_hm_selection():
    candidates = [
        _candidate("most-gain", 5.0, 80),
        _candidate("best-ratio", 2.0, 50),
    ]
    default_objective = draft.objective_for_draft({}, None)

    assert draft._select_candidate(candidates, default_objective)["climb"]["id"] == "most-gain"


def test_select_candidate_breaks_ties_deterministically():
    candidates = [
        _candidate("zeta", 3.0, 30),
        _candidate("alpha", 3.0, 30),
    ]

    assert draft._select_candidate(candidates, "hm")["climb"]["id"] == "alpha"


def test_weighted_mix_normalizes_and_can_choose_differently():
    climbing = _candidate("climbing", 2.0, 40)
    climbing["score_componenten"] = {"offroad": 0.0, "populair": 0.0, "kassei": 0.0}
    gravel = _candidate("gravel", 4.0, 40)
    gravel["score_componenten"] = {"offroad": 1.0, "populair": 0.0, "kassei": 0.0}
    candidates = [climbing, gravel]

    assert draft._select_candidate(candidates, {"hoogtemeters": 1})["climb"]["id"] == "climbing"
    mixed = draft._select_candidate(
        candidates,
        {"hoogtemeters": 3, "offroad": 7},
        budget_km=10,
    )
    scaled = draft._select_candidate(
        candidates,
        {"hoogtemeters": 30, "offroad": 70},
        budget_km=10,
    )

    assert mixed["climb"]["id"] == "gravel"
    assert scaled["climb"]["id"] == "gravel"
    assert mixed["score_componenten"]["kort"] == 0.6


def test_autovrij_component_measures_share_outside_busy_cells():
    coords = [(50.0, 4.0, 0), (50.0, 4.001, 0), (50.0, 4.002, 0)]
    routes = [{"coords": coords, "distance_m": 150, "details": {}}]
    sampled = geo.resample([(point[0], point[1]) for point in coords], 60.0)
    busy_cells = {geo.cell(*sampled[0])}

    available = draft._candidate_surface_components(
        routes, popular_cells=set(), busy_cells=busy_cells
    )
    unavailable = draft._candidate_surface_components(
        routes, popular_cells=set(), busy_cells=set()
    )

    assert 0 < available["autovrij"] < 1
    assert unavailable["autovrij"] == 0


def test_weighted_objective_rejects_negative_unknown_and_zero_sum():
    invalid = (
        {"hoogtemeters": -1},
        {"landschap": 1},
        {"hoogtemeters": 0, "offroad": 0},
    )
    for objective in invalid:
        try:
            draft._select_candidate([], objective)
        except draft.DraftError:
            pass
        else:
            raise AssertionError(f"ongeldige objective werd aanvaard: {objective}")


def test_kasseien_graag_adds_point_fifteen_bonus_above_mix():
    smooth = _candidate("smooth", 2.0, 20)
    smooth["score_componenten"] = {"offroad": 0, "populair": 0, "kassei": 0}
    cobbles = _candidate("cobbles", 2.0, 20)
    cobbles["score_componenten"] = {"offroad": 0, "populair": 0, "kassei": 1}

    selected = draft._select_candidate(
        [smooth, cobbles],
        {"hoogtemeters": 1},
        budget_km=5,
        prefer_cobbles=True,
    )

    assert selected["climb"]["id"] == "cobbles"
    assert selected["score"] == 0.65


def _synthetic_routed_draft():
    return {
        "id": "fill01",
        "name": "opvultest",
        "start": {"lat": 50.0, "lon": 4.0, "label": "start"},
        "loop": True,
        "profile": "quiet",
        "strict": False,
        "avoid_cobbles": False,
        "avoid_concrete": False,
        "avoid_places": [],
        "climbs": ["testklim"],
        "opvullingen": [],
        "computed": {
            "total_km": 5.0,
            "ascend_m": 40,
            "descend_m": 40,
            "legs": [
                {"from": "start", "to": "top", "km": 2.5, "climb": None},
                {"from": "top", "to": "start", "km": 2.5, "climb": None},
            ],
            "kwaliteit": {"heen_en_weer_m": 0},
        },
        "_geometry": [
            [[50.0, 4.0, 0], [50.0, 4.02, 20]],
            [[50.0, 4.02, 20], [50.01, 4.0, 0]],
        ],
    }


def _synthetic_climb_db():
    return {
        "testklim": {
            "name": "Testklim",
            "foot": [50.0, 4.0],
            "top": [50.0, 4.02],
            "geom": [[50.0, 4.0], [50.0, 4.02]],
        }
    }


def test_waypoints_pin_only_core_but_keep_extended_endpoints():
    routed = _synthetic_routed_draft()
    geom = [[50.0, 4.0 + i * 0.002] for i in range(7)]
    climb_db = {
        "testklim": {
            "name": "Testklim",
            "foot": geom[0],
            "top": geom[-1],
            "geom": geom,
            "kern_van": 2,
            "kern_tot": 4,
        }
    }

    climb_leg = next(
        leg for leg in draft._waypoints(routed, climb_db) if leg.get("climb")
    )

    assert climb_leg["points"][0] == tuple(geom[0])
    assert climb_leg["points"][-1] == tuple(geom[-1])
    assert tuple(geom[1]) not in climb_leg["points"]
    assert tuple(geom[5]) not in climb_leg["points"]
    assert all(
        point in (tuple(geom[0]), tuple(geom[-1]))
        or geom[2][1] <= point[1] <= geom[4][1]
        for point in climb_leg["points"]
    )


def test_waypoints_without_core_indices_pin_full_geometry():
    routed = _synthetic_routed_draft()
    geom = [[50.0, 4.0 + i * 0.002] for i in range(7)]
    climb_db = {
        "testklim": {
            "name": "Testklim",
            "foot": geom[0],
            "top": geom[-1],
            "geom": geom,
        }
    }

    climb_leg = next(
        leg for leg in draft._waypoints(routed, climb_db) if leg.get("climb")
    )

    assert climb_leg["points"] == geo.resample(
        [tuple(point) for point in geom], 150.0
    )


def test_round_trip_anchor_chooses_farthest_route_waypoint():
    routed = _synthetic_routed_draft()

    point, label = draft._round_trip_anchor(routed, _synthetic_climb_db())

    assert point == (50.0, 4.02)
    assert label == "Testklim (top)"


def test_round_trip_anchor_is_start_without_climbs():
    routed = _synthetic_routed_draft()
    routed["climbs"] = []

    assert draft._round_trip_anchor(routed, {}) == ((50.0, 4.0), "start")


def test_requested_round_trip_anchor_takes_priority_and_is_a_route_waypoint():
    routed = _synthetic_routed_draft()
    routed["climbs"] = []
    routed["round_trip_anchor"] = {
        "label": "Blaarmeersen",
        "lat": 51.039,
        "lon": 3.700,
    }

    assert draft._round_trip_anchor(routed, {}) == (
        (51.039, 3.700),
        "Blaarmeersen",
    )
    legs = draft._waypoints(routed, {})
    assert legs[0]["from"] == "start"
    assert legs[0]["to"] == "Blaarmeersen"
    assert legs[0]["points"][-1] == (51.039, 3.700)
    assert legs[-1]["to"] == "start"


def test_round_trip_fill_uses_landmark_anchor_and_keeps_route_near_it():
    routed = _synthetic_routed_draft()
    routed["climbs"] = []
    routed["computed"] = {
        "total_km": 0.0,
        "ascend_m": 0,
        "descend_m": 0,
        "legs": [],
        "kwaliteit": {"heen_en_weer_m": 0},
    }
    routed["_geometry"] = []
    routed["round_trip_anchor"] = {
        "label": "Blaarmeersen",
        "lat": 51.039,
        "lon": 3.700,
    }
    calls = []

    def round_trip_fn(anchor, distance_m, seed, **_preferences):
        calls.append((anchor, distance_m, seed))
        return {
            "distance_m": 4_800,
            "ascend_m": seed,
            "coords": [
                [anchor[0], anchor[1], 0],
                [anchor[0] + 0.01, anchor[1], 5],
                [anchor[0], anchor[1] + 0.01, 5],
                [anchor[0], anchor[1], 0],
            ],
        }

    def router(current, climb_db):
        legs = draft._waypoints(current, climb_db)
        current["computed"] = {
            "total_km": 5.0,
            "ascend_m": current["opvullingen"][-1]["seed"],
            "descend_m": 0,
            "legs": [{"opvulling": leg.get("opvulling", False)} for leg in legs],
            "kwaliteit": {"heen_en_weer_m": 0},
        }
        current["_geometry"] = [
            [[point[0], point[1], 0] for point in leg["points"]]
            for leg in legs
        ]

    result = draft._fill_with_round_trip(
        routed,
        {},
        budget_m=7_500,
        router=router,
        round_trip_fn=round_trip_fn,
        objective="offroad",
        popular_cells=set(),
        target_total_m=5_000,
    )

    assert result["filled"] is True
    assert calls == [((51.039, 3.700), 5_000.0, seed) for seed in range(5)]
    route_points = [point for leg in routed["_geometry"] for point in leg]
    assert min(
        geo.haversine(51.039, 3.700, point[0], point[1])
        for point in route_points
    ) <= 300


def test_waypoints_split_a_climb_at_an_interior_fill_anchor():
    routed = _synthetic_routed_draft()
    climb_db = _synthetic_climb_db()
    base_legs = draft._waypoints(routed, climb_db)
    climb_leg = next(leg for leg in base_legs if leg.get("climb"))
    anchor = climb_leg["points"][len(climb_leg["points"]) // 2]
    routed["opvullingen"] = [
        {
            "anchor": list(anchor),
            "label": "opvulpunt",
            "points": [list(anchor), [anchor[0] + 0.01, anchor[1]], list(anchor)],
            "seed": 0,
        }
    ]

    legs = draft._waypoints(routed, climb_db)
    fill_i = next(i for i, leg in enumerate(legs) if leg.get("opvulling"))

    assert legs[fill_i - 1]["points"][-1] == anchor
    assert legs[fill_i + 1]["points"][0] == anchor
    assert legs[fill_i + 1]["climb_segment"] == "testklim"


def test_fill_rejects_overlap_and_selects_most_ascend():
    routed = _synthetic_routed_draft()
    climb_db = _synthetic_climb_db()
    seen_seeds = []

    def round_trip_fn(anchor, distance_m, seed, **preferences):
        seen_seeds.append(seed)
        assert anchor == (50.0, 4.02)
        assert distance_m == 4500  # 90% van het restbudget (GH schiet vaak over)
        assert preferences["profile"] == "quiet"
        if seed == 0:
            # Ruim meer dan 300 m terug over de bestaande heenweg.
            coords = [anchor, (50.0, 4.0), anchor]
        else:
            offset = 0.01 + seed * 0.001
            coords = [anchor, (50.01, 4.02), (50.01, 4.02 + offset), anchor]
        return {
            "distance_m": 4000,
            "ascend_m": 100 if seed == 2 else 20 + seed,
            "coords": [(lat, lon, 0) for lat, lon in coords],
        }

    routed_legs = []

    def router(d, passed_climb_db):
        legs = draft._waypoints(d, passed_climb_db)
        routed_legs[:] = legs
        selected_seed = d["opvullingen"][-1]["seed"]
        d["computed"] = {
            "total_km": 9.0,
            "ascend_m": 140 if selected_seed == 2 else 60,
            "descend_m": 40,
            "legs": [
                {
                    "from": leg["from"],
                    "to": leg["to"],
                    "km": 4.0,
                    "opvulling": leg.get("opvulling", False),
                }
                for leg in legs
            ],
            "kwaliteit": {"heen_en_weer_m": 0},
        }
        d["_geometry"] = [
            [[point[0], point[1], 0] for point in leg["points"]]
            for leg in legs
        ]

    result = draft._fill_with_round_trip(
        routed,
        climb_db,
        budget_m=10000,
        router=router,
        round_trip_fn=round_trip_fn,
        popular_cells=set(),
    )

    assert seen_seeds == [0, 1, 2, 3, 4]
    assert result == {
        "filled": True,
        "seed": 2,
        "extra_km": 4.0,
        "extra_hoogtemeters": 100,
    }
    fill_leg = next(leg for leg in routed_legs if leg.get("opvulling"))
    assert fill_leg["from"] == fill_leg["to"] == "Testklim (top)"
    assert fill_leg["points"][0] == fill_leg["points"][-1]
    assert len(fill_leg["points"]) > 3


def test_optimize_without_fill_keeps_existing_budget_and_skips_round_trip():
    routed = _synthetic_routed_draft()

    def unexpected(*_args, **_kwargs):
        raise AssertionError("round_trip mag niet worden aangeroepen")

    from unittest import mock
    with tempfile.TemporaryDirectory() as root, mock.patch.dict(os.environ, LUSMAKER_HOME=root):
        result = draft._optimize(
            routed,
            {},
            max_km=10,
            max_rounds=0,
            fill=False,
            round_trip_fn=unexpected,
        )

    assert result["resultaat"]["computed"]["total_km"] == 5.0
    assert result["rondes"] == []
    assert routed["opvullingen"] == []


def test_tour_objective_targets_distance_without_adding_climbs():
    routed = _synthetic_routed_draft()
    routed["climbs"] = []
    routed["computed"] = None
    routed.pop("_geometry")
    requested_distances = []

    def unexpected_candidates(*_args, **_kwargs):
        raise AssertionError("een gewone toer mag geen klimkandidaten zoeken")

    def round_trip_fn(anchor, distance_m, seed, **_preferences):
        assert anchor == (50.0, 4.0)
        requested_distances.append(distance_m)
        return {
            "distance_m": 9_800,
            "ascend_m": seed,
            "coords": [
                [50.0, 4.0, 0],
                [50.02, 4.04 + seed * 0.001, 10],
                [50.0, 4.0, 0],
            ],
        }

    def router(current, _climb_db):
        assert current["climbs"] == []
        assert len(current["opvullingen"]) == 1
        current["computed"] = {
            "total_km": 9.8,
            "ascend_m": 4,
            "descend_m": 4,
            "legs": [{"opvulling": True}],
            "kwaliteit": {"heen_en_weer_m": 0},
        }
        current["_geometry"] = [
            [[point[0], point[1], 0] for point in current["opvullingen"][0]["points"]]
        ]

    previous_home = os.environ.get("LUSMAKER_HOME")
    with tempfile.TemporaryDirectory() as temp_dir:
        os.environ["LUSMAKER_HOME"] = str(Path(temp_dir))
        try:
            result = draft._optimize(
                routed,
                {},
                max_km=12,
                objective="toeren",
                route_fn=router,
                candidates_fn=unexpected_candidates,
                round_trip_fn=round_trip_fn,
                fill_target_km=10,
            )
        finally:
            if previous_home is None:
                os.environ.pop("LUSMAKER_HOME", None)
            else:
                os.environ["LUSMAKER_HOME"] = previous_home

    assert requested_distances == [10_000] * 5
    assert result["objective"] == "toeren"
    assert result["resultaat"]["computed"]["total_km"] == 9.8
    assert result["rondes"][0]["status"] == "opgevuld (round_trip)"
    assert routed["climbs"] == []


def test_fill_target_must_fit_inside_hard_budget():
    try:
        draft._optimize(
            _synthetic_routed_draft(),
            _synthetic_climb_db(),
            max_km=10,
            fill_target_km=11,
        )
    except draft.DraftError as exc:
        assert "afstandsbudget" in str(exc)
    else:
        raise AssertionError("fill-target boven hard budget werd aanvaard")


def test_landmark_access_distance_is_reserved_before_filling_and_replacing_old_loop():
    from unittest.mock import patch
    routed = _synthetic_routed_draft()
    routed['climbs'] = []
    routed['round_trip_anchor'] = {'lat': 50.01, 'lon': 4.0, 'label': 'strand'}
    routed['opvullingen'] = [{'obsolete': True}]
    requested = []

    def router(current, _db):
        fills = current['opvullingen']
        assert len(fills) <= 1
        current['computed'] = {'total_km': 3.0 if fills else 1.2,
                               'ascend_m': 0, 'descend_m': 0, 'legs': [],
                               'kwaliteit': {'heen_en_weer_m': 0}}
        current['_geometry'] = []

    def round_trip(anchor, distance_m, seed, **kwargs):
        requested.append(distance_m)
        return {'distance_m': 1800, 'ascend_m': 0,
                'coords': [anchor, (50.02, 4.0), (50.02, 4.01), anchor]}

    with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'LUSMAKER_HOME': root}):
        for _ in range(2):
            draft._optimize(routed, {}, max_km=3.3, objective='toeren', fill_target_km=3,
                            route_fn=router, round_trip_fn=round_trip)
    assert requested == [1800] * 10
    assert routed['computed']['total_km'] == 3
    assert len(routed['opvullingen']) == 1


def test_failed_first_candidates_retry_bounded_extra_seeds():
    from lusmaker import gh
    routed = _synthetic_routed_draft()
    routed['climbs'] = []
    routed['computed']['total_km'] = 1.2
    routed['computed']['legs'] = []
    routed['_geometry'] = []
    attempts = []

    def round_trip(anchor, distance_m, seed, **kwargs):
        attempts.append(seed)
        if seed != 7:
            raise gh.GhError('geen kandidaat')
        return {'distance_m': 1800, 'ascend_m': 0,
                'coords': [anchor, (50.01, 4.0), (50.01, 4.01), anchor]}

    def router(current, _db):
        current['computed'] = {'total_km': 3.0, 'ascend_m': 40}

    result = draft._fill_with_round_trip(routed, {}, 3300, router=router,
                                       round_trip_fn=round_trip, target_total_m=3000,
                                       objective='toeren')
    assert result['filled'] and result['seed'] == 7
    assert sorted(attempts) == list(range(20))
    assert routed['computed']['total_km'] == 3


def test_short_first_batch_does_not_hide_a_matching_later_round_trip():
    from lusmaker import gh
    routed = _synthetic_routed_draft()
    routed['climbs'] = []
    routed['computed'] = {'total_km': 0, 'ascend_m': 0, 'legs': []}
    routed['_geometry'] = []
    routed['route_request'] = {'target_km': 3, 'tolerance_km': .3}
    attempts = []
    def round_trip(anchor, distance_m, seed, **kwargs):
        attempts.append(seed)
        if seed not in (0, 7): raise gh.GhError('geen kandidaat')
        return {'distance_m':1900 if seed == 0 else 3000, 'ascend_m':10,
                'coords':[anchor,(50.01,4.0),(50.01,4.01),anchor]}
    def router(current, _db):
        seed = current['opvullingen'][-1]['seed']
        current['computed'] = {'total_km':1.9 if seed == 0 else 3, 'ascend_m':10}
    result = draft._fill_with_round_trip(routed,{},3300,router=router,
        round_trip_fn=round_trip,target_total_m=3000,objective='toeren')
    assert result['seed']==7 and routed['computed']['total_km']==3
    assert sorted(attempts)==list(range(20))
    assert len(routed['opvullingen'])==1


def test_round_trip_uses_integrated_distance_and_retains_best_effort_when_needed():
    from lusmaker import gh
    for integrated, expected in [({0:1.9,1:3.0},3.0), ({0:1.9,1:2.4},2.4)]:
        routed=_synthetic_routed_draft()
        routed['climbs']=[]
        routed['computed']={'total_km':0,'ascend_m':0,'legs':[]}
        routed['_geometry']=[]
        routed['route_request']={'target_km':3,'tolerance_km':.3}
        def round_trip(anchor, distance_m, seed, **kwargs):
            if seed not in integrated: raise gh.GhError('geen kandidaat')
            return {'distance_m':3000-seed*50,'ascend_m':10,
                    'coords':[anchor,(50.01,4.0),(50.01,4.01),anchor]}
        def router(current, _db):
            current['computed']={'total_km':integrated[current['opvullingen'][-1]['seed']], 'ascend_m':10}
        result=draft._fill_with_round_trip(routed,{},3300,router=router,
            round_trip_fn=round_trip,target_total_m=3000,objective='toeren')
        assert result['filled'] and routed['computed']['total_km']==expected
        assert len(routed['opvullingen'])==1


def _echo_post(bodies):
    def post(_path, body):
        bodies.append(body)
        return {"paths": [{
            "distance": 1000.0, "time": 1000, "ascend": 10.0, "descend": 5.0,
            "points": {"coordinates": [[lon, lat, 10.0] for lon, lat in body["points"]]},
            "details": {},
        }]}
    return post


def test_final_route_sends_aligned_point_hints_and_climb_headings():
    from lusmaker import gh

    routed = _synthetic_routed_draft()
    routed["computed"] = None
    routed.pop("_geometry")
    geom = [[50.0, 4.0 + i * 0.002] for i in range(4)]
    climb_db = {"testklim": {
        "name": "Testklim (west)", "foot": geom[0], "top": geom[-1], "geom": geom,
    }}
    bodies = []

    with tempfile.TemporaryDirectory() as home:
        previous = os.environ.get("LUSMAKER_HOME")
        os.environ["LUSMAKER_HOME"] = home
        try:
            draft._route(
                routed, climb_db, router=gh.route, post_fn=_echo_post(bodies),
                area_evs=set(), save_fn=lambda *_a, **_k: None,
            )
        finally:
            if previous is None:
                os.environ.pop("LUSMAKER_HOME", None)
            else:
                os.environ["LUSMAKER_HOME"] = previous

    assert len(bodies) == 3  # naar voet, klim, terug
    for body in bodies:
        n = len(body["points"])
        assert len(body.get("point_hints", [""] * n)) == n
        # GraphHopper: één heading = eerste punt; anders exact één per punt.
        assert len(body.get("headings", [0.0])) in (1, n)
        assert None not in body.get("headings", [])
    approach, climb, back = bodies
    assert approach["point_hints"] == ["", "Testklim"]
    assert "headings" not in approach  # eerste leg heeft nog geen vorige richting
    # Het eerste klimpunt krijgt de richting; GraphHopper weigert daar ook een hint.
    assert climb["point_hints"] == [""] + ["Testklim"] * (len(climb["points"]) - 1)
    # klim loopt naar het oosten: heading ~90 graden, enkel voor het eerste punt
    assert abs(climb["headings"][0] - 90.0) < 1.0
    assert len(climb["headings"]) == 1
    assert "point_hints" not in back
    assert back["headings"][0] is not None  # aankomstrichting top
    assert all(body["pass_through"] is True for body in bodies)


def test_gh_route_ignores_hints_and_headings_with_wrong_length():
    from lusmaker import gh

    bodies = []
    gh.route(
        [(50.0, 4.0), (50.0, 4.01)], point_hints=["a"], headings=[90.0],
        post_fn=_echo_post(bodies), area_evs=set(),
    )
    assert "point_hints" not in bodies[0] and "headings" not in bodies[0]


def test_replay_hash_ignores_snap_hints_so_old_cassettes_stay_valid():
    from lusmaker import recording

    base = {"points": [[4.0, 50.0], [4.1, 50.0]], "profile": "bike"}
    hinted = {**base, "point_hints": ["", "X"], "headings": [90.0, None]}
    assert recording.hash_body(base) == recording.hash_body(hinted)


def test_optimize_emits_budget_rollback_count_to_telemetry():
    import logging
    import json
    from lusmaker import telemetry

    records = []

    class Handler(logging.Handler):
        def emit(self, record):
            records.append(json.loads(record.getMessage()))

    original = draft._optimize
    draft._optimize = lambda *_a, **_k: {"rondes": [
        {"status": "teruggedraaid (budget)"}, {"status": "toegevoegd"},
        {"status": "teruggedraaid (budget)"},
    ]}
    handler = Handler()
    telemetry.logger.addHandler(handler)
    try:
        result = draft.optimize(_synthetic_routed_draft(), {}, 10)
    finally:
        telemetry.logger.removeHandler(handler)
        draft._optimize = original
    assert result["budget_rollbacks"] == 2
    event = next(r for r in records if r["event"] == "optimize")
    assert event["budget_rollbacks"] == 2 and event["rounds"] == 3


def _target_scenario(extras, start_km=30.0, target_km=45.0):
    """Draft + injected router/candidates: elke klim kost vast extra km."""
    from lusmaker import gh

    routed = _synthetic_routed_draft()
    routed["computed"]["total_km"] = start_km
    routed["computed"]["legs"] = []
    routed["_geometry"] = []
    routed["route_request"] = {"target_km": target_km, "tolerance_km": 2.5}

    def router(current, _db):
        extra = sum(extras[c][0] for c in current["climbs"] if c in extras)
        current["computed"] = {
            "total_km": start_km + extra,
            "ascend_m": sum(extras[c][1] for c in current["climbs"] if c in extras),
            "descend_m": 0,
            "legs": [],
            "kwaliteit": {"heen_en_weer_m": 0},
        }
        current["_geometry"] = [[[50.0, 4.0, 0], [50.0, 4.01, 0]]]

    def candidates(current, _db, max_detour_km=10.0, limit=10, banned=frozenset(), **_kw):
        return [
            _candidate(cid, km, hm)
            for cid, (km, hm) in extras.items()
            if cid not in current["climbs"] and cid not in banned and km <= max_detour_km
        ]

    def round_trip(anchor, distance_m, seed, **kwargs):
        raise gh.GhError("geen kandidaat")

    router.ids = list(extras)
    return routed, router, candidates, round_trip


def _run_target(routed, router, candidates, round_trip, max_km=54.0):
    from unittest.mock import patch

    db = _synthetic_climb_db()
    for cid in routed["climbs"] + list(getattr(router, "ids", [])):
        db.setdefault(cid, db["testklim"])
    with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"LUSMAKER_HOME": root}):
        return draft._optimize(
            routed, db, max_km=max_km, objective="hm-per-km", route_fn=router,
            candidates_fn=candidates, round_trip_fn=round_trip, fill_target_km=45.0,
        )


def test_target_distance_tops_up_with_low_ratio_climbs_when_fill_fails():
    # Lage hm/km-klim (ratio 4 < min_ratio 8) is de enige weg naar het doel.
    extras = {"hoog": (6.5, 130), "laag1": (6.5, 26), "laag2": (6.5, 26)}
    routed, router, candidates, round_trip = _target_scenario(extras)

    result = _run_target(routed, router, candidates, round_trip)

    total = routed["computed"]["total_km"]
    assert 42.5 <= total <= 47.5, total
    assert "hoog" in routed["climbs"] and "laag1" in routed["climbs"]
    assert any(r.get("fase") == "aanvulling" for r in result["rondes"])
    assert "optimize_note" not in routed


def test_target_distance_caps_climbs_at_tolerance_window_not_one_point_two_times_target():
    # Zonder cap groeide de route tot 50 km (ceiling 54), buiten 45 +- 2,5.
    extras = {f"k{i}": (5.0, 100) for i in range(4)}
    routed, router, candidates, round_trip = _target_scenario(extras)

    _run_target(routed, router, candidates, round_trip)

    assert 42.5 <= routed["computed"]["total_km"] <= 47.5


def test_infeasible_target_is_reported_clearly_in_constraint_report():
    from lusmaker import intents

    routed, router, candidates, round_trip = _target_scenario({})
    result = _run_target(routed, router, candidates, round_trip)

    assert routed["computed"]["total_km"] == 30.0
    assert "doelafstand niet haalbaar" in result["gestopt_omdat"]
    report = intents.constraint_report(routed)
    assert report["binnen_doelbereik"] is False and report["voldaan"] is False
    # Voor de gebruiker: gewone taal met Nederlandse decimalen, geen interne termen.
    assert any("korter dan je gevraagde" in w for w in report["waarschuwingen"])
    assert any(w.startswith(("Er ", "De rekentijd")) for w in report["waarschuwingen"])
    import re
    assert not any("round_trip" in w or re.search(r"\d\.\d", w) for w in report["waarschuwingen"])


def test_exact_candidate_evaluation_is_capped_and_reports_progress():
    from lusmaker import draft, progress
    d = {"id": "abc123", "climbs": [], "computed": {"total_km": 40.0, "legs": [{"km": 20.0}, {"km": 20.0}]},
         "_geometry": [[(50.80, 3.60), (50.90, 3.60)], [(50.90, 3.60), (50.80, 3.60)]]}
    climb_db = {f"k{i}": {"id": f"k{i}", "name": f"Klim {i}", "town": "", "avg_pct": 7.0, "max_pct": 10.0, "warnings": [],
                          "foot": [50.85, 3.60 + i * 0.002], "mid": [50.851, 3.60 + i * 0.002],
                          "top": [50.852, 3.60 + i * 0.002], "length_m": 800, "gain_m": 60} for i in range(30)}
    calls, events = [], []

    def router(points, **_kwargs):
        calls.append(points)
        return {"distance_m": 1000.0, "ascend_m": 10.0, "coords": [(p[0], p[1], 0.0) for p in points]}

    with progress.capture(events.append):
        draft._candidates(d, climb_db, max_detour_km=8.0, limit=10, router=router, max_eval=5)
    climbs_routed = {tuple(points[1]) for points in calls if len(points) == 3}
    assert len(climbs_routed) <= 5
    texts = [e["message"] for e in events if e["stage"] == "optimizing"]
    assert len(texts) == 5
    assert all(any(text.endswith(f"({index} van 5).") for text in texts) for index in range(1, 6))


def test_optimize_stops_at_the_time_budget_and_keeps_the_route():
    from lusmaker import draft
    ticks = iter([0.0] + [1000.0] * 50)  # eerste meting zet de deadline; daarna is ze verstreken
    d = {"id": "abc123", "climbs": ["k"], "computed": {"total_km": 30.0, "legs": [{"km": 30.0}]}, "_geometry": [[(50.8, 3.6), (50.8, 3.6)]],
         "loop": True, "start": {"lat": 50.8, "lon": 3.6}}
    climb_db = {"k": {"id": "k", "name": "K", "foot": [50.8, 3.6], "mid": [50.8, 3.6], "top": [50.8, 3.6], "length_m": 500, "gain_m": 40}}
    asked = []
    from unittest import mock
    with mock.patch.object(draft, "save", lambda *_a, **_k: None), mock.patch.object(draft, "summary", lambda _d: {}):
        result = draft._optimize(d, climb_db, max_km=60.0, route_fn=lambda *_a, **_k: None,
                                 candidates_fn=lambda *_a, **_k: asked.append(1) or [],
                                 fill=False, time_budget_s=360.0, clock=lambda: next(ticks))
    assert "tijdslimiet" in result["gestopt_omdat"]
    assert asked == []  # geen dure kandidaatronde meer na de deadline
    assert d["computed"]["total_km"] == 30.0  # bestaande route blijft


def test_round_trip_fill_stops_trying_extra_seeds_after_the_deadline():
    from lusmaker import gh
    routed = _synthetic_routed_draft()
    routed['climbs'] = []
    routed['computed'] = {'total_km': 0, 'ascend_m': 0, 'legs': []}
    routed['_geometry'] = []
    routed['route_request'] = {'target_km': 3, 'tolerance_km': .3}
    attempts = []
    def round_trip(anchor, distance_m, seed, **kwargs):
        attempts.append(seed)
        raise gh.GhError('geen kandidaat')
    result = draft._fill_with_round_trip(routed, {}, 3300, router=lambda *_a: None,
        round_trip_fn=round_trip, target_total_m=3000, objective='toeren',
        deadline=10.0, clock=lambda: 100.0)
    assert not result['filled']
    assert attempts == [0, 5]  # één poging per reeks, geen 20 varianten na de deadline


def test_round_trip_fill_falls_back_to_least_overlap_instead_of_failing():
    from unittest import mock
    from lusmaker import geo
    routed = _synthetic_routed_draft()
    routed['climbs'] = []
    routed['route_request'] = {'target_km': 30, 'tolerance_km': 2.5}
    start_km = routed['computed']['total_km']
    def round_trip(anchor, distance_m, seed, **kwargs):
        return {'distance_m': distance_m, 'ascend_m': 50, 'coords': [anchor, (50.01, 4.0), (50.01, 4.01), anchor]}
    def router(current, _db):
        current['computed'] = {'total_km': 30.0, 'ascend_m': 300, 'legs': []}
    with mock.patch.object(geo, 'retrace_m', lambda *_a: 800.0):
        result = draft._fill_with_round_trip(routed, {}, 40000, router=router, round_trip_fn=round_trip,
                                             target_total_m=30000, objective='toeren')
    assert start_km < 30 and result['filled'] and routed['computed']['total_km'] == 30.0
    assert 'dezelfde wegen' in routed['fill_note'] and '0,8 km' in routed['fill_note']


def _parallel_candidate_fixture():
    routed = {
        'id': 'parallel', 'climbs': [],
        'computed': {'total_km': 40.0, 'legs': [{'km': 20.0}, {'km': 20.0}]},
        '_geometry': [[(50.80, 3.60), (50.90, 3.60)],
                      [(50.90, 3.60), (50.80, 3.60)]],
    }
    climbs = {
        f'k{i}': {
            'id': f'k{i}', 'name': f'Klim {i}', 'town': '',
            'avg_pct': 7.0, 'max_pct': 10.0, 'warnings': [],
            'foot': [50.85, 3.60 + i * .002],
            'mid': [50.851, 3.60 + i * .002],
            'top': [50.852, 3.60 + i * .002],
            'length_m': 800, 'gain_m': 60,
        } for i in range(8)
    }
    return routed, climbs


def test_parallel_candidates_are_faster_with_identical_ordered_results():
    import time
    from threading import Lock
    from unittest import mock
    routed, climbs = _parallel_candidate_fixture()
    active = peak = 0
    lock = Lock()

    def slow_router(points, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(.05)
            return {'distance_m': 1000.0, 'ascend_m': 10.0}
        finally:
            with lock:
                active -= 1

    results, durations = [], []
    for concurrency in (1, 4):
        peak = 0
        with mock.patch.dict(os.environ, LUSMAKER_ROUTER_CONCURRENCY=str(concurrency)):
            began = time.monotonic()
            results.append(draft._candidates(routed, climbs, 8.0, 10,
                                            router=slow_router, max_eval=8))
            durations.append(time.monotonic() - began)
        assert peak == concurrency
    assert len(results[0]) >= 3
    assert results[0] == results[1]
    assert durations[1] < durations[0] * .65, durations
    print(f'Kandidaten: sequentieel {durations[0]:.3f}s, parallel {durations[1]:.3f}s')


def test_candidate_workers_keep_progress_and_telemetry_context():
    import threading
    from unittest import mock
    from lusmaker import progress, telemetry
    routed, climbs = _parallel_candidate_fixture()
    main_thread = threading.get_ident()
    events, worker_ids = [], []
    stats = {'calls': 0, 'ms': 0.0, 'wait_ms': 0.0}
    token = telemetry.router_stats.set(stats)
    request_token = telemetry.request_id.set('parallel-request')

    def sink(event):
        worker_ids.append(threading.get_ident())
        events.append(event)

    def router(points, **kwargs):
        assert telemetry.router_stats.get() is stats
        assert telemetry.request_id.get() == 'parallel-request'
        progress.emit('router', 'Routercall in worker.')
        telemetry.router_record(calls=1, ms=2, wait_ms=1)
        return {'distance_m': 1000, 'ascend_m': 10}

    try:
        with mock.patch.dict(os.environ, LUSMAKER_ROUTER_CONCURRENCY='4'), progress.capture(sink):
            draft._candidates(routed, climbs, 8, 10, router=router, max_eval=8)
    finally:
        telemetry.router_stats.reset(token)
        telemetry.request_id.reset(request_token)
    optimizing = [event for event in events if event['stage'] == 'optimizing']
    assert len(optimizing) == 8
    assert len([event for event in events if event['stage'] == 'router']) == 32
    assert main_thread not in worker_ids
    assert stats == {'calls': 32, 'ms': 64.0, 'wait_ms': 32.0}


def test_concurrency_one_keeps_candidate_call_and_progress_order():
    import threading
    from unittest import mock
    from lusmaker import progress
    routed, climbs = _parallel_candidate_fixture()
    selected = draft._candidate_prefilter(routed, climbs, 8)[:8]
    expected_calls = []
    for _est, _cid, climb, _leg, a, b in selected:
        expected_calls.extend([[a, tuple(climb['foot'])],
                               [tuple(climb['foot']), tuple(climb['mid']), tuple(climb['top'])],
                               [tuple(climb['top']), b], [a, b]])
    calls, events = [], []
    main_thread = threading.get_ident()

    def router(points, **kwargs):
        assert threading.get_ident() == main_thread
        calls.append(points)
        return {'distance_m': 1000, 'ascend_m': 10}

    with mock.patch.dict(os.environ, LUSMAKER_ROUTER_CONCURRENCY='1'), progress.capture(events.append):
        result = draft._candidates(routed, climbs, 8, 10, router=router, max_eval=8)
    assert calls == expected_calls
    assert [event['message'] for event in events] == [
        f"Ik bereken de omweg via {climb['name']} ({index} van 8)."
        for index, (_est, _cid, climb, _leg, _a, _b) in enumerate(selected, 1)
    ]
    ids = list(dict.fromkeys(item[1] for item in selected))
    assert [candidate['id'] for candidate in result] == ids
    assert all(candidate['extra_km'] == 2 and candidate['extra_hm'] == 20 for candidate in result)


def test_parallel_candidate_errors_are_local_to_the_candidate():
    from unittest import mock
    from lusmaker import gh
    routed, climbs = _parallel_candidate_fixture()
    failures = {tuple(climbs['k0']['foot']): gh.GhError,
                tuple(climbs['k1']['foot']): draft.DraftError}

    def router(points, **kwargs):
        if points[-1] in failures:
            raise failures[points[-1]]('geen route')
        return {'distance_m': 1000, 'ascend_m': 10}

    results = []
    for concurrency in (1, 4):
        with mock.patch.dict(os.environ, LUSMAKER_ROUTER_CONCURRENCY=str(concurrency)):
            results.append(draft._candidates(routed, climbs, 8, 10, router=router, max_eval=8))
    assert results[0] == results[1] and results[0]
    assert not {'k0', 'k1'} & {candidate['id'] for candidate in results[0]}


def test_round_trip_batches_keep_seed_tiebreak_and_context():
    import copy
    import threading
    import time
    from unittest import mock
    from lusmaker import progress, telemetry
    source = _synthetic_routed_draft()
    source['climbs'] = []
    source['computed'] = {'total_km': 0, 'ascend_m': 0, 'legs': []}
    source['_geometry'] = []
    results, final_drafts = [], []
    main_thread = threading.get_ident()
    for concurrency in (1, 4):
        routed = copy.deepcopy(source)
        events, worker_ids = [], []
        stats = {'calls': 0, 'ms': 0.0, 'wait_ms': 0.0}
        token = telemetry.router_stats.set(stats)

        def round_trip(anchor, distance_m, seed, **kwargs):
            worker_ids.append(threading.get_ident())
            assert telemetry.router_stats.get() is stats
            telemetry.router_record(calls=1)
            # Laat latere seeds eerder eindigen; seed 0 moet de tie blijven winnen.
            time.sleep(.01 * (5 - seed))
            return {'distance_m': 2000, 'ascend_m': 20,
                    'coords': [anchor, (50.01, 4.0), (50.01, 4.01), anchor]}

        def router(current, _db):
            assert threading.get_ident() == main_thread
            current['computed'] = {'total_km': 2, 'ascend_m': 20}

        try:
            with mock.patch.dict(os.environ, LUSMAKER_ROUTER_CONCURRENCY=str(concurrency)), progress.capture(events.append):
                results.append(draft._fill_with_round_trip(routed, {}, 3000,
                                                          router=router, round_trip_fn=round_trip))
        finally:
            telemetry.router_stats.reset(token)
        final_drafts.append(routed)
        assert len(events) == 5 and all(event['stage'] == 'variants' for event in events)
        assert stats['calls'] == 5
        assert (main_thread in worker_ids) == (concurrency == 1)
    assert results[0] == results[1] and results[0]['seed'] == 0
    assert final_drafts[0] == final_drafts[1]


def test_round_trip_deadline_prevents_a_new_parallel_batch():
    from unittest import mock
    from lusmaker import gh
    routed = _synthetic_routed_draft()
    routed['climbs'] = []
    attempts = []

    def round_trip(anchor, distance_m, seed, **kwargs):
        attempts.append(seed)
        raise gh.GhError('geen kandidaat')

    with mock.patch.dict(os.environ, LUSMAKER_ROUTER_CONCURRENCY='4'):
        result = draft._fill_with_round_trip(routed, {}, 40000,
            round_trip_fn=round_trip, deadline=10,
            clock=lambda: 100 if attempts else 0)
    assert not result['filled']
    assert sorted(attempts) == [0, 1, 2, 3]


def test_router_concurrency_defaults_and_invalid_values():
    from unittest import mock
    with mock.patch.dict(os.environ):
        os.environ.pop('LUSMAKER_ROUTER_CONCURRENCY', None)
        assert draft._router_concurrency() == 4
        for value, expected in [('1', 1), ('4', 4), ('0', 1), ('-2', 1), ('bad', 4)]:
            os.environ['LUSMAKER_ROUTER_CONCURRENCY'] = value
            assert draft._router_concurrency() == expected
