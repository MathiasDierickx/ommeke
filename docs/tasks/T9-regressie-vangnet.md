# T9 — Regressie-vangnet: cassette-tests + live smoke

## Waarom

De engine is inmiddels gevoelig afgesteld (corridors, headings, lus-toets,
retrace-guard, round_trip-fill, offroad-boost). We willen canonieke routes
vastleggen zodat een wijziging die de kwaliteit sloopt meteen rood kleurt.

## Architectuur

Twee lagen:

1. **Cassette-replay (default, geen netwerk)** — GH-antwoorden opgenomen in
   fixtures; tests spelen ze af via een geïnjecteerde `post_fn` en asserteren
   kwaliteits-INVARIANTEN (ranges), niet exacte geometrie.
2. **Live smoke (opt-in, met draaiende GH)** — zelfde scenario's live,
   metriekentabel als output; voor na een graafherimport of GH-upgrade.

## Implementatie

### `lusmaker/recording.py`

- `hash_body(body) -> str`: sha256 van canonieke JSON (sorted keys).
- `RecordingPost`: wrapper om `gh._post` die {hash: response} verzamelt.
- `ReplayPost(fixture)`: dient responses uit de fixture; onbekende hash →
  duidelijke fout ("engine-gedrag gewijzigd t.o.v. cassette — herrecord met
  tests/record_fixtures.py of controleer je wijziging").
- Fixtureformaat: gzipped JSON in `tests/fixtures/<scenario>.json.gz`:
  `{"draft": {...}, "climbs": {id: {...}}, "responses": {hash: resp}}` —
  de draft en gebruikte klim-objecten zitten erin zodat tests GEEN
  regiocaches nodig hebben. Rond coördinaten in responses af op 5 decimalen
  om de bestanden klein te houden (geometrie-afronding is voor de
  invarianten irrelevant).

### `tests/record_fixtures.py` (handmatig draaien, met live GH)

Voert de scenario's uit met `RecordingPost`, schrijft fixtures. Print per
scenario de metrieken zodat de recorder ziet wat hij vastlegt.

### Scenario's (klein maar representatief)

| naam | opzet | invarianten (assert) |
|---|---|---|
| `berendries_quiet` | Wetteren-lus, klim `berendries`, quiet | 54 ≤ km ≤ 64; 600 ≤ hm ≤ 820; heen_en_weer < 300; kassei < 200 |
| `trail_offroad` | Wetteren, profiel trail, klimmen zoals de huidige trail-offroad-draft | 6 ≤ km ≤ 9; hm ≥ 80; heen_en_weer < 300; offroad_pct ≥ 25 |
| `zottegem_avoid` | Wetteren-lus + berendries + avoid Zottegem (2.5 km) | route raakt de Zottegem-cirkel niet (max 200 m overschrijding); km ≤ 70 |

Gebruik `draft.route` met `router=gh.route` maar `post_fn=Replay/Recording`
(threading door de bestaande injectiepunten; voeg waar nodig een
`post_fn`-doorgave toe aan draft.route/gh.route — минimale diff).

### `tests/test_regression.py`

Laadt elke fixture, bouwt de draft + klim-db eruit, draait `draft.route` met
ReplayPost en asserteert de invarianten hierboven. Draait mee in
`python -m tests.run`. Sla het scenario over met een duidelijke SKIP als de
fixture ontbreekt (vóór de eerste recording).

### `tests/live_smoke.py`

`python -m tests.live_smoke` — draait de scenario's tegen de echte GH
(default-regio), print een metriekentabel en exit 1 als een invariant faalt.
Niet opgenomen in tests.run. Documenteer in AGENTS.md wanneer dit hoort te
draaien (na herimport, GH-upgrade, profielwijziging).

## Herrecord-beleid (AGENTS.md-aanvulling)

Bewuste engine-wijziging die cassettes breekt → herrecord + vermeld de
metriekverschuiving in de commitmessage. Cassettebreuk zonder bewuste
wijziging = regressie.

## DoD

- `python -m tests.run` groen mét skip-gedrag zonder fixtures; jij levert de
  code + tests, de reviewer draait record_fixtures live en commit de
  fixtures.
- Kleine commits; niet pushen; geen netwerk/docker in jouw sandbox.
