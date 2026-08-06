# T8 — Budget opvullen met round_trip (mooie lussen in vlak gebied)

## Waarom

In vlak gebied botst "maximale hoogtemeters" met "mooie lus": na de schone
klimmen blijft afstandsbudget over dat nu onbenut blijft (trail Wetteren:
4,5 van 10 km) of met doodlopers gevuld zou worden. GraphHopper heeft een
`round_trip`-algoritme dat vanuit één punt een lus van een gewenste afstand
maakt — ideaal om het restbudget mee op te vullen.

## Gedrag

`draft optimize`: nieuwe stap ná de greedy-klimrondes. Als
`resterend budget >= 1.5 km` en de draft een lus is:

1. Kies het opvulpunt: het waypoint op de route dat het verst van start ligt
   (bij 0 klimmen: start zelf).
2. Vraag GH een round_trip vanaf dat punt:
   `POST /route` met `"algorithm": "round_trip"`,
   `"round_trip.distance": restbudget_m`, `"round_trip.seed": 0..4`,
   één punt, zelfde profiel/voorkeuren. Probeer de 5 seeds.
3. Toets elke kandidaat-lus: geen overlap met de bestaande route
   (`geo.retrace_m` beide richtingen; drempel 120 m) en binnen het totale
   budget na integratie. Kies de kandidaat met de meeste ascend.
4. Integreer: vervang op het gekozen waypoint de doorgang door de
   round_trip-lus (splits de bestaande leg daar; de lus wordt een extra leg
   met `"opvulling": true` in de leg-metadata).
5. Rapporteer in de optimize-output als ronde met status
   `"opgevuld (round_trip)"` incl. extra km/hm; geen kandidaat die de toetsen
   haalt → sla over met `"gestopt_omdat"`-vermelding.

## Implementatie

- `gh.round_trip(point, distance_m, seed, profile=..., **prefs)` in gh.py.
- Integratielogica in draft.py (`_fill_with_round_trip(d, climb_db, budget_m,
  router=..., round_trip_fn=...)`) — injecteerbaar voor tests.
- `heen_en_weer_m` en de bestaande kwaliteit blijven gelden (route() draait
  opnieuw over de definitieve waypoint-set: representeer de round_trip-lus
  als extra via-punten (resample op ~400 m) in de leg-structuur zodat
  hercomputatie deterministisch blijft).
- CLI/MCP: geen nieuwe tools; optimize krijgt `--geen-opvulling` om het uit
  te zetten (default aan). plan_route geeft het door.

## Tests (puur)

- opvulpunt-keuze (verste waypoint) op synthetische draft.
- kandidaat-toets: overlap-afwijzing en ascend-keuze met geïnjecteerde
  round_trip-resultaten.
- integratie: via-punten correct in de leg-structuur; `--geen-opvulling`
  respecteert het budget zonder round_trip.

## DoD

Tests groen; bestaand gedrag met `--geen-opvulling` identiek aan nu;
docs (README/CLAUDE.md) bijgewerkt. Kleine commits; niet pushen; geen
docker/netwerk in jouw sandbox.
