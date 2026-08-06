from lusmaker import draft


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

    assert draft._select_candidate(candidates, "hm")["climb"]["id"] == "most-gain"
    assert draft._select_candidate(candidates, "hm-per-km")["climb"]["id"] == "best-ratio"


def test_select_candidate_breaks_ties_deterministically():
    candidates = [
        _candidate("zeta", 3.0, 30),
        _candidate("alpha", 3.0, 30),
    ]

    assert draft._select_candidate(candidates, "hm")["climb"]["id"] == "alpha"


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


def test_round_trip_anchor_chooses_farthest_route_waypoint():
    routed = _synthetic_routed_draft()

    point, label = draft._round_trip_anchor(routed, _synthetic_climb_db())

    assert point == (50.0, 4.02)
    assert label == "Testklim (top)"


def test_round_trip_anchor_is_start_without_climbs():
    routed = _synthetic_routed_draft()
    routed["climbs"] = []

    assert draft._round_trip_anchor(routed, {}) == ((50.0, 4.0), "start")


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
        assert distance_m == 5000
        assert preferences["profile"] == "quiet"
        if seed == 0:
            # Meer dan 120 m terug over de bestaande heenweg.
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
