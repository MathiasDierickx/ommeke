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
