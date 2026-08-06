# T6 — Token-zuinige tool-API (hosted-kostenmodel)

## Waarom

In een gehoste webapp betalen wij de LLM-tokens. Drie kostenposten:
round-trips (elke call herbetaalt de context), resultaatgrootte, en
schema-overhead. De tools moeten "voorkauwen": het happy path = 1-2 calls,
elke output compact met een kant-en-klare samenvattingszin.

## 1. Composiet-tools (in `lusmaker/intents.py`, dun gewired in MCP + CLI)

### `plan_route(...)` — één call van wens naar route

```
plan_route(start, region=None, max_km=None,
           doel="hoogtemeters"|"kort"|"toeren",
           via_klimmen=[], vermijd_plaatsen=[],
           kasseien=False,  # True = mogen, False = zacht vermijden
           beton_vermijden=True, strict=False, naam=None)
```

Serverkant: geocode start → new_draft (prefs) → avoid_place per
vermijd_plaats → via_klimmen toevoegen (fuzzy op naam matchen tegen de
klimpool; onbekende naam = fout met 3 suggesties) → `doel=="hoogtemeters"` en
max_km: `optimize`; anders route (bij `kort` zonder extra klimmen) →
preview + GPX exporteren naar `<HOME>/exports/<draft>/`.

### `adjust_route(draft_id, ...)` — alle edits in één call

```
adjust_route(draft_id, voeg_klimmen_toe=[], verwijder_klimmen=[],
             vermijd_plaatsen=[], niet_meer_vermijden=[], max_km=None)
```

Past alles toe, éénmalige reroute (of optimize als max_km meegegeven),
zelfde compacte output. Vervangt reeksen add/remove/avoid/route-calls.

## 2. Compact outputcontract (beide composiet-tools én suggest)

Doel: < ~300 tokens per resultaat. Vorm:

```json
{
  "draft": "abc123",
  "km": 44.0, "hoogtemeters": 559,
  "klimmen": ["Diepestraat (1.1 km @ 3.5%)", "Kampenheuvel (0.6 km @ 4.3%)"],
  "kwaliteit": "0 m kassei · 0.9 km steenweg · 7 kruisingen · 73% populaire wegen",
  "bestanden": {"gpx": "...", "preview": "..."},
  "samenvatting": "Lus vanuit Wetteren: 44,0 km / +559 hm langs 4 klimmen; kasseien vermeden.",
  "vervolg": ["suggest_climbs voor extra klimmen (tot +8 km)", "adjust_route om te wijzigen"]
}
```

- `samenvatting`: één NL-zin, direct citeerbaar door het model.
- `kwaliteit` als string, niet als object.
- GEEN legs, GEEN coördinaten, GEEN nested computed. (De bestaande
  granulaire tools behouden hun huidige output — niets breken.)
- `suggest_climbs`-output compacter: per suggestie
  `{"id", "label": "Molenberg (1.1 km @ 4%)", "extra_km", "extra_hm", "pos"}`
  — geen genest climb-object meer nodig in de composietwereld; laat de
  bestaande velden staan maar voeg `label` toe.

## 3. Lite-modus voor hosted

- `lus-mcp --lite`: exposeert ALLEEN
  `plan_route, adjust_route, suggest_climbs, route_details(draft_id),
  ensure_region, region_status, list_drafts` (7 tools).
- `route_details(draft_id)`: legs-tabel + volle kwaliteit, voor wanneer de
  gebruiker doorvraagt (opt-in verbositeit i.p.v. standaard).
- Tool-descriptions in lite-modus: max één zin (schema-overhead).
- Volle modus blijft default en behoudt alle bestaande tools + de twee
  composieten (test_mcp: vol = 20 tools; nieuwe test voor lite = 7).

## 4. Docs

- CLAUDE.md: "gebruik plan_route/adjust_route eerst; granulair alleen als
  het echt moet"; kostenrationale kort.
- PRODUCT.md: sectie "Token-economie" (drie kostenposten + lite-modus).
- README: lite-modus onder MCP.

## Tests (puur)

- intents: fuzzy klimnaam-matching (exact > prefix > substring; ambigu →
  fout met kandidaten), outputcontract-velden aanwezig, samenvatting-opbouw.
- lite vs vol toolsets (exacte namen).
- route_details zonder computed → nette fout.
- Router/route-functies injecteerbaar zoals in T1/T5-stijl.

## DoD

Tests groen; bestaande outputs ongewijzigd; kleine commits; niet pushen.
