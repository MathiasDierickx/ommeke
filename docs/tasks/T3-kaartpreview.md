# T3 — Kaartpreview per draft

## Waarom

PRODUCT.md M3: niemand vertrouwt een blinde GPX. Eén HTML-bestand per draft
dat de route toont; de LLM geeft het pad terug en de gebruiker opent het.

## Commando + MCP-tool

- CLI: `lus draft preview <id> [-o pad.html]` — default `<naam>-preview.html`
  in de cwd. Output-JSON: `{"file": "<pad>", "total_km": ..., "ascend_m": ...}`.
- MCP: tool `preview_draft(draft_id, output_path=None)` met dezelfde logica.
  **Let op**: `tests/test_mcp.py` asserteert de exacte toolset — voeg
  `preview_draft` daar toe (15 tools).
- Vereist een gerouteerde draft (`_geometry`); anders DraftError
  "routeer eerst: `lus draft route <id>`".

## Inhoud van de HTML (één bestand, `lusmaker/preview.py`)

1. **Kaart**: Leaflet 1.9 via unpkg-CDN (integrity-attributen niet nodig),
   OSM-standaardtiles met correcte attributie. De pagina draait in de browser
   van de gebruiker; CDN/tiles online is daar prima.
2. Per leg een polyline (afwisselend twee kleuren, bv. #2563eb/#f97316);
   klim-legs (`climb`-veld) in #dc2626. Popup per leg: van → naar, km, hm.
3. Markers: start (huisje-emoji of cirkel), per klim de top met naam +
   lengte/percentages uit de klim-DB.
4. **Hoogteprofiel** onder de kaart: inline SVG, cumulatieve afstand (x) vs
   hoogte (y) uit de leg-coords (derde element; None overslaan), klimzones
   in dezelfde rode kleur gearceerd. Geen JS-libraries hiervoor.
5. Kop: draftnaam, totaal km, hoogtemeters, kwaliteitsmetrieken
   (kassei_m, steenweg_m, kruisingen, populair_pct indien aanwezig).
6. Titel/strings Nederlands. Fit-bounds op de route.

## Implementatie

- Nieuw `lusmaker/preview.py`: `render(d: dict, climb_db: dict) -> str` (pure
  functie die HTML teruggeeft) + `export(d, climb_db, path) -> dict`.
- CLI-wiring in cli.py, MCP-wiring in mcp_server.py (dun, delegeren).
- Coords zitten in `d["_geometry"]` (lijst legs van [lat, lon, ele]);
  leg-metadata in `d["computed"]["legs"]` (zelfde volgorde).
- Downsample polylines naar max ~1500 punten totaal voor bestandsgrootte.

## Tests (puur)

`tests/test_preview.py`: bouw een synthetische draft-dict (2 legs, 1 klim,
enkele coords met hoogtes) + mini-klim-DB; assert dat `render()`:
- de klimnaam en draftnaam bevat;
- het juiste aantal polylines (2) en één SVG-element;
- geen crash bij ontbrekende hoogtes (None) en ontbrekende populair_pct.

## Docs & DoD

- README (gebruik + M3 afvinken in PRODUCT.md), CLAUDE.md-flow: na
  `route`/`optimize` altijd een preview aanbieden.
- `.venv/bin/python -m tests.run` groen; bestaande tests niet breken.
- Kleine commits; niet pushen.
