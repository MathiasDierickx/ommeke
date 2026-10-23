"""Deterministische intenthints vullen alleen lege velden aan."""
from lusmaker import intent_hints


def test_recognises_activity_flat_and_cobbles():
    assert intent_hints.hints("Een vlakke rit met de racefiets, liever geen kasseien") == {
        "activiteit": "koersfiets", "heuvels": "vlak", "kasseien": False,
    }
    assert intent_hints.hints("Mountainbiken in de heuvelachtige Ardennen")["activiteit"] == "mtb"
    assert intent_hints.hints("Een heuvelrit")["heuvels"] == "zoek"
    assert intent_hints.hints("traillus van 12 km")["activiteit"] == "trail"
    assert intent_hints.hints("Een mooie lus vanuit Gent") == {}


def test_stroller_walk_is_flat_paved_walking():
    assert intent_hints.hints("Wandeling met de kinderwagen") == {
        "activiteit": "wandelen", "ondergrond": "verhard", "heuvels": "vlak",
    }


def test_apply_only_fills_missing_keys():
    values = {"start": "Gent", "heuvels": "ok", "kasseien": None}
    result = intent_hints.apply(values, "Vlakke rit zonder kasseien")
    assert result["heuvels"] == "ok"          # expliciet antwoord blijft staan
    assert result["kasseien"] is False        # onbekend wordt aangevuld
    assert values["kasseien"] is None         # invoer wordt niet gemuteerd


def test_named_activity_overrides_the_model_guess():
    assert intent_hints.apply({"activiteit": "wandelen"}, "trail rondje vanuit brugse poort gent van 10 km")["activiteit"] == "trail"
    assert intent_hints.apply({"activiteit": "koersfiets"}, "Maak een rustige lus van 30 km")["activiteit"] == "koersfiets"


def test_naar_x_with_a_distance_turns_a_model_end_point_into_a_loop():
    # Live: gpt-oss maakte van "naar het Donkmeer" een lijnrit (route 22afea).
    text = "Wandeling van ongeveer 12 km vanuit Wetteren langs de Schelde naar het Donkmeer"
    result = intent_hints.apply({"start": "Wetteren", "eind": "Donkmeer", "rond_plaats": None}, text)
    assert result["rond_plaats"] == "Donkmeer" and result["eind"] is None


def test_explicit_line_ride_keeps_the_end_point():
    for text in ("Fietstocht van 60 km naar Brugge, met de trein terug",
                 "Wandeling van 12 km, eindig in Gent",
                 "Enkel naar Oudenaarde, 40 km"):
        assert intent_hints.apply({"eind": "X", "rond_plaats": None}, text)["eind"] == "X"
    assert intent_hints.apply({"eind": "Brugge"}, "Van Gent naar Brugge")["eind"] == "Brugge"
