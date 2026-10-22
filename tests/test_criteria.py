from lusmaker import criteria, profiles
from lusmaker.chat_contracts import PLAN_ROUTE_SCHEMA, validate_arguments


def _raises(fn, *args):
    try:
        fn(*args)
    except criteria.CriteriaError as exc:
        return str(exc)
    raise AssertionError("CriteriaError verwacht")


def test_parse_normaliseert_gewichten_en_vult_defaults():
    spec = criteria.parse([{"metriek": "stil", "gewicht": 3}, {"metriek": "kassei", "richting": "laag", "gewicht": 1}])
    assert [c["id"] for c in spec] == ["stil", "kassei"]
    assert spec[0]["gewicht"] == 0.75 and spec[1]["gewicht"] == 0.25
    assert spec[0]["label"] == "Rustige wegen" and spec[0]["richting"] == "hoog" and spec[0]["hard"] is False


def test_parse_weigert_onbekende_metriek_dubbel_id_en_hard_zonder_drempel():
    assert "onbekende metriek" in _raises(criteria.parse, [{"metriek": "onbekend"}])
    assert "dubbel" in _raises(criteria.parse, [{"metriek": "stil"}, {"metriek": "stil"}])
    assert "drempel" in _raises(criteria.parse, [{"metriek": "kassei", "hard": True}])
    assert "niet-lege lijst" in _raises(criteria.parse, [])
    assert "maximaal" in _raises(criteria.parse, [{"metriek": "stil", "id": f"c{i}"} for i in range(9)])


def test_score_is_gewogen_som_en_laag_draait_de_waarde():
    spec = criteria.parse([{"metriek": "stil", "gewicht": 1}, {"metriek": "kassei", "richting": "laag", "gewicht": 1}])
    assert criteria.score(spec, {"stil": 0.8, "kassei": 0.1}) == 0.5 * 0.8 + 0.5 * 0.9
    # ontbrekende component telt als 0, breekt niet
    assert criteria.score(spec, {"stil": 0.8}) == 0.4


def test_hard_criterium_sluit_kandidaat_uit():
    spec = criteria.parse([{"metriek": "hoogtemeters"}, {"metriek": "kassei", "richting": "laag", "hard": True, "drempel": 0.05}])
    assert criteria.score(spec, {"hoogtemeters": 0.9, "kassei": 0.2}) is None
    assert criteria.score(spec, {"hoogtemeters": 0.9, "kassei": 0.01}) == 0.9
    assert criteria.score(spec, {"hoogtemeters": 0.9}) == 0.9  # onbekend = niet uitsluiten


def test_from_weights_geeft_dezelfde_score_als_de_oude_formule():
    weights = profiles.normalize_weights({"hoogtemeters": 0.5, "offroad": 0.3, "kort": 0.2})
    components = {"hoogtemeters": 0.4, "offroad": 1.0, "populair": 0.2, "autovrij": 0.7, "kort": 0.5, "kassei": 0.0}
    old = sum(weights[name] * components[name] for name in profiles.WEIGHT_KEYS)
    assert abs(criteria.score(criteria.from_weights(weights), components) - old) < 1e-9
    assert criteria.weights(criteria.from_weights(weights)) == weights
    assert criteria.is_pure(criteria.from_weights({"offroad": 1.0}), "offroad")
    assert not criteria.is_pure(criteria.from_weights(weights), "offroad")


def test_explain_geeft_waarom_regels_met_ok_per_criterium():
    spec = criteria.parse([
        {"metriek": "stil", "label": "Rustig voor de kinderen", "drempel": 0.6},
        {"metriek": "kassei", "richting": "laag", "hard": True, "drempel": 0.05},
        {"metriek": "oversteken", "richting": "laag", "drempel": 0.3},
        {"metriek": "kort"},
    ])
    quality = {"stil_pct": 72.0, "kassei_m": 1800, "steenweg_kruisingen": 5}
    lines = criteria.explain(spec, quality, {"total_km": 10.0, "ascend_m": 120})
    assert [l["id"] for l in lines] == ["stil", "kassei", "oversteken"]  # kort heeft geen eindmeting
    assert lines[0] == {"id": "stil", "label": "Rustig voor de kinderen", "hard": False, "waarde": 0.72, "tekst": "72 % rustige wegen", "ok": True}
    assert lines[1]["ok"] is False and lines[1]["tekst"] == "1,8 km kassei" and lines[1]["hard"] is True
    assert lines[2]["ok"] is False and "5 drukke oversteken" in lines[2]["tekst"]
    assert criteria.explain(spec, {}, {})[0]["tekst"] == "niet gemeten"


def test_from_goal_en_chat_schema():
    assert criteria.from_goal("hoogtemeters")[0]["metriek"] == "hoogtemeters"
    assert criteria.from_goal("toeren") == []
    validate_arguments({"start": "Wetteren", "target_km": 10, "criteria": [{"metriek": "stil", "gewicht": 2}]}, PLAN_ROUTE_SCHEMA)
    try:
        validate_arguments({"start": "Wetteren", "criteria": [{"metriek": "onbekend"}]}, PLAN_ROUTE_SCHEMA)
    except ValueError:
        pass
    else:
        raise AssertionError("onbekende metriek moet het schema weigeren")


def test_answers_become_criteria_and_ok_removes_them():
    spec = criteria.merge(None, criteria.from_answers({"kasseien": "vermijd", "stil": "belangrijk"}))
    assert [(c["id"], c["metriek"], c["richting"], c["hard"]) for c in spec] == [
        ("kasseien", "kassei", "laag", True), ("stil", "stil", "hoog", False)]
    assert spec[1]["gewicht"] == 1.0  # enige zachte criterium
    later = criteria.merge(spec, criteria.from_answers({"heuvels": "zoek", "kasseien": "ok"}), dropped={"kasseien"})
    assert [c["id"] for c in later] == ["stil", "heuvels"] and later[0]["gewicht"] == 0.5
    assert criteria.merge(None, criteria.from_answers({"heuvels": "ok"}), dropped={"heuvels"}) is None
