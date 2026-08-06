"""Pure tests voor route-kwaliteitsmetrieken."""

from lusmaker import analysis


def test_concrete_surface_classes_are_measured_separately_from_cobbles():
    coords = [
        [50.0, 4.0, 0],
        [50.001, 4.0, 0],
        [50.002, 4.0, 0],
        [50.003, 4.0, 0],
    ]
    details = [
        [0, 1, "concrete"],
        [1, 2, "concrete:plates"],
        [2, 3, "cobblestone"],
    ]

    concrete_m = analysis.detail_meters(
        coords, details, analysis.CONCRETE_SURFACES
    )
    cobble_m = analysis.detail_meters(coords, details, analysis.COBBLE_SURFACES)

    assert 220 < concrete_m < 223
    assert 110 < cobble_m < 112
