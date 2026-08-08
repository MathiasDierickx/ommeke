# T16 — Wegdek- en verkeerslagen effectief in de routing

## Waarom

T15 haalde officiële kassei- en verkeersdata binnen maar gebruikt ze alleen
als metriek. End-to-end: (1) `vermijd-kasseien` moet ook werken waar OSM
geen surface-tag heeft (de kassei-cellen), (2) er komt een echte
autovrij-voorkeur met readiness-vraag en routing-effect.

## 1. Areas bakken (`heat.build`)

Naast `popular`/`popular_trail` twee extra features in popular.geojson:

- `kassei_tvl`: wegdek-kassei-cellen (fiets ∪ wandel)
- `druk_tvl`: verkeersintensiteit-cellen (fiets ∪ wandel)

Zelfde rect-merging; alleen schrijven als de cache de data heeft. Sla in
heat.pkl op welke area-ids gebakken zijn (`areas`: [..]). Herimport nodig —
reviewer doet die.

## 2. Request-side routingregels (`gh.py`)

- Capability-detectie: `gh.available_area_evs()` — leest één keer per proces
  `/info` `encoded_values` en cachet welke `in_<area>`-values bestaan;
  fallback lege set bij fout. Regels alleen toevoegen als de EV bestaat
  (anders GH-error op onbekende variabele).
- `avoid_cobbles` voegt (naast surface==COBBLESTONE) toe:
  `{"if": "in_kassei_tvl", "multiply_by": "0.25"}`.
- Nieuw param `avoid_busy: bool` → `{"if": "in_druk_tvl", "multiply_by": "0.45"}`
  (mild: bijna het hele netwerk is "niet-autovrij"; te agressief = absurde
  omwegen, zie AGENTS-les over stapeling).

## 3. Voorkeur `autovrij` (profiel + doorwerking)

- profiles: `voorkeuren.autovrij` ∈ {null, "belangrijk", "ok"};
  routing_prefs: "belangrijk" → avoid_busy=True.
- draft-veld/override + CLI-vlag `--autovrij` op draft new; intents
  plan_route-param; MCP-schema's mee (toolaantallen ongewijzigd).
- Scoring (gewogen objectives): nieuwe component `autovrij` = aandeel van de
  toevoeging NIET op druk-cellen (alleen als druk-data bestaat; anders 0).
  Gewichten-dict accepteert de sleutel; default 0.

## 4. Readiness-regel 6

`autovrij` is null EN druk-data aanwezig EN probe.autovrij_pct < 40 →
vraag ("Wil je autovrije/verkeersarme wegen prioriteren? De verkenning zit
op X% autovrij.") met opties belangrijk/ok als profielpatches. Prioriteit 3.
Max-3-vragen-regel blijft.

## 5. Cassettes

`berendries_quiet` heeft avoid_cobbles → request-bodies wijzigen zodra de
kassei_tvl-EV bestaat. In de REPLAY-tests bestaat er geen GH (/info faalt →
lege capability-set → regels niet toegevoegd → bodies ongewijzigd) — zorg
dat dat pad deterministisch is en documenteer het in de test. Live
herrecord door de reviewer NA de herimport; verwachte verschuiving vermelden.

## Tests (puur)

- capability-gate: met/zonder ge-injecteerde EV-set → regels wel/niet in body.
- autovrij-scoringcomponent en profielmapping.
- readiness-regel 6 materialiteit.
- heat.build: area-ids in pkl + geojson.

## Let op

Andere agent mogelijk actief in de repo: alleen eigen bestanden committen,
vreemde niet-gecommitte wijzigingen laten staan. Vroeg en klein committen;
niet pushen; geen netwerk/docker.
