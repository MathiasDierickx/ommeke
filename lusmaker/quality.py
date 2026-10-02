"""Pure acceptatiemetrieken voor routegeometrie, zonder routing of brondata."""
import math
from . import geo


def evaluate(route: dict, constraints: dict) -> dict:
    legs = route.get('_geometry') or []
    points = [p[:2] for leg in legs for p in leg]
    if not points or any(len(p) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in p) or abs(p[0]) > 90 or abs(p[1]) > 180 for p in points):
        return {'ok': False, 'failures': ['geldige routegeometrie ontbreekt'], 'metrics': {}}
    # Resampling voorkomt dat een lange leg een anker/vermijdcirkel ongemerkt passeert.
    samples = [p for leg in legs for p in geo.resample([p[:2] for p in leg], 50)]
    if not samples:
        samples = points
    distance = sum(geo.haversine(*a, *b) for leg in legs for a, b in zip([p[:2] for p in leg], [p[:2] for p in leg][1:])) / 1000
    gap = max((geo.haversine(*a[-1][:2], *b[0][:2]) for a, b in zip(legs, legs[1:]) if a and b), default=0)
    metrics = {'km': round(distance, 3), 'closure_m': round(geo.haversine(*points[0], *points[-1]), 1), 'leg_gap_m': round(gap, 1)}
    failures = []
    def require(condition, message):
        if not condition:
            failures.append(message)
    require(distance > 0, 'route heeft geen lengte')
    require(gap <= constraints.get('max_leg_gap_m', 25), 'route bevat een onderbreking')
    if constraints.get('loop', True):
        require(metrics['closure_m'] <= constraints.get('closure_m', 25), 'route is niet gesloten')
    if constraints.get('max_km') is not None:
        require(distance <= constraints['max_km'] + 0.01, 'hard afstandsbudget overschreden')
    if constraints.get('target_km') is not None:
        deviation = abs(distance - constraints['target_km'])
        metrics['target_deviation_km'] = round(deviation, 3)
        require(deviation <= constraints.get('tolerance_km', 2.5), 'doelafstand buiten tolerantie')
    for index, anchor in enumerate(constraints.get('anchors', [])):
        nearest = min(geo.haversine(*p, anchor['lat'], anchor['lon']) for p in samples)
        metrics[f'anchor_{index}_m'] = round(nearest, 1)
        require(nearest <= anchor.get('radius_m', 300), f'anker {index} niet bereikt')
    for index, area in enumerate(constraints.get('avoid', [])):
        nearest = min(geo.haversine(*p, area['lat'], area['lon']) for p in samples)
        margin = nearest - area['radius_m']
        metrics[f'avoid_{index}_margin_m'] = round(margin, 1)
        require(margin >= -area.get('tolerance_m', 0), f'vermijdzone {index} geraakt')
    water = constraints.get('water_points') or []
    if water:
        water_samples = geo.resample(water, 50)
        nearby = sum(min(geo.haversine(*p, *w[:2]) for w in water_samples) <= constraints.get('water_radius_m', 100) for p in samples)
        metrics['water_pct'] = round(100 * nearby / len(samples), 1)
        require(metrics['water_pct'] >= constraints.get('water_min_pct', 0), 'te weinig route langs water')
    return {'ok': not failures, 'failures': failures, 'metrics': metrics}
