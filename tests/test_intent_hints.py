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
