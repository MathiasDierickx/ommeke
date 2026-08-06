# T12 — Readiness-tool + probe-routes: incrementeel voorkeuren opbouwen

## Waarom

De MCP moet de LLM begeleiden: welke voorkeuren ontbreken, welke vraag is nú
relevant, en wat zegt een snelle verkenningsroute over het terrein? Zo bouwt
de LLM samen met de gebruiker stap voor stap een topprofiel en -route.
Bouwt op T11 (profieldocument met null=onbekend, gewogen objectives).

## 1. Probe (`draft.probe(d, climb_db) -> dict`)

Snelle verkenning, GEEN optimize: één `draft.route`-run (bestaand pad) plus
een compacte analyse:

```json
{
  "km": ..., "hm": ...,
  "kwaliteit": { ...bestaande metrieken... },
  "terrein": {
    "kassei_aanwezig_m": 1800,
    "offroad_beschikbaar_pct": 12.0,
    "klimmen_binnen_5km": 7,
    "heat_dekking_pct": 61.0
  }
}
```

- `klimmen_binnen_5km`: klimpool geteld rond de route (bestaande
  suggest-prefilter hergebruiken, geen GH-calls).
- `heat_dekking_pct`: populair_pct van de proberoute.
- Resultaat cachen op de draft (`d["_probe"]`) met invalidatie zoals
  `computed` (add/remove-climb, avoid, profielwijziging → weg).

## 2. Readiness-engine (`lusmaker/readiness.py`)

`assess(d, profiel, climb_db) -> dict`, puur en deterministisch:

```json
{
  "profiel": "standaard",
  "onbekend": ["kasseien", "gewichten"],
  "vragen": [
    {
      "id": "kasseien",
      "prioriteit": 1,
      "reden": "de verkenningsroute bevat 1.8 km kasseien; kasseivoorkeur onbekend",
      "vraag": "Er liggen kasseistroken op het parcours. Vind je die leuk (Flandrien!), oké, of vermijd je ze liever?",
      "opties": {
        "graag":   {"patch": {"voorkeuren": {"kasseien": "graag"}}},
        "ok":      {"patch": {"voorkeuren": {"kasseien": "ok"}}},
        "vermijd": {"patch": {"voorkeuren": {"kasseien": "vermijd"}}}
      }
    }
  ],
  "klaar": false,
  "advies": "stel de kasseivraag eerst; gewichten daarna"
}
```

Vraaggeneratie (regels, in deze prioriteitsvolgorde; alléén vragen die
materieel zijn):

1. `kasseien` is null EN probe.kassei_aanwezig_m > 300.
2. `beton` is null EN activiteit == fietsen EN probe bevat > 1 km beton
   (voeg beton_m toe aan de kwaliteit/probe via de bestaande surface-details:
   CONCRETE-klassen).
3. `steenwegen` is null EN probe.kruisingen > 8 of steenweg_m > 1500.
4. `gewichten` allemaal default (alleen hoogtemeters=1) EN
   (probe.offroad_beschikbaar_pct > 20 → vraag offroad-mix;
   heat_dekking beschikbaar → vraag populair-mix). Optievorm: 2-3 concrete
   mixen als patch, bv. "vooral klimmen" {hoogtemeters:.7, offroad:.3}.
5. `vermijd_plaatsen` leeg EN de route passeert een plaatskern
   (place-node binnen 400 m van de route, uit de gazetteer) → vraag of die
   doorgang oké is (optie: avoid_place-patch op de DRAFT, niet het profiel;
   markeer dat in de optie met `"doel": "draft"`).
- `klaar` = true wanneer er geen vragen met prioriteit ≤ 2 meer zijn.
- Max 3 vragen per assess (hoogste prioriteit eerst) — de LLM mag niet
  overladen worden.

## 3. MCP + CLI

- Tool `route_readiness(draft_id, profiel_naam="standaard")`: draait probe
  indien nodig (dus WEL GH-calls) en dan assess. Docstring instrueert de
  LLM expliciet: "stel de vragen aan de gebruiker, pas antwoorden toe via
  update_profile (of avoid_place bij doel=draft), en vraag daarna opnieuw
  readiness op tot klaar=true; routeer dan met optimize."
- Lite-toolset += `route_readiness`, `get_profile`, `update_profile`
  (lite wordt 10; vol 24 — toolaantal-tests bijwerken).
- CLI: `lus draft readiness <id> [--profiel-naam ...]`.
- CLAUDE.md: herschrijf de flowsectie rond deze lus (draft → readiness →
  vragen → update_profile → readiness → optimize → preview/export), met
  jouw kasseivoorbeeld uitgewerkt.

## Tests (puur)

- assess-regels: elk van de 5 regels met synthetische probe/profiel-combos
  (materieel vs niet-materieel, prioriteitsvolgorde, max 3, klaar-logica).
- optie-patches valideren tegen profiles.apply_patch (round-trip).
- probe-caching + invalidatie.
- plaatskern-detectie op synthetische gazetteer.

## DoD

`python -m tests.run` groen incl. cassettes (probe gebruikt het bestaande
route-pad; scenariodrafts krijgen geen probe in de regressietests). Docs
bijgewerkt. Kleine commits; niet pushen; geen netwerk/docker.
