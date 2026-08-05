# T2 — MCP-server (stdio) bovenop de bestaande kern

## Waarom

PRODUCT.md M2: de MCP-server is het go-to-market-artefact. Elke MCP-client
(Claude Desktop/Code, ChatGPT, …) wordt dan de chat-UI; wij leveren de tools.
De CLI blijft bestaan; de MCP-server hergebruikt dezelfde interne functies
(géén subprocess naar `lus`).

## Dependency-uitzondering

Voeg toe aan pyproject: `mcp>=1.2` (het officiële Python-SDK,
modelcontextprotocol). Gebruik de FastMCP-server-API met **stdio**-transport.
Geen HTTP-transport in deze taak.

## Entry point

- Console-script `lus-mcp = "lusmaker.mcp_server:main"`.
- `lusmaker/mcp_server.py` met een FastMCP-server genaamd `lusmaker`.

## Tools (ergonomie voor de LLM, niet 1-op-1 de CLI)

Elke tool geeft dezelfde dicts terug als de CLI-commando's (JSON-schoon).
Docstrings in het Nederlands; die worden de tool-descriptions.

| tool | signatuur | delegeert naar |
|---|---|---|
| `status()` | – | cmd_status-logica |
| `geocode(query, limit=5)` | – | geocode.geocode |
| `list_climbs(near=None, radius_km=15)` | near = plaatsnaam of "lat,lon"; zonder near: alle bekende (niet-auto) | climbs.all_climbs + filter |
| `new_draft(start, name=None, loop=True, end=None, strict=False, vermijd_kasseien=False, vermijd_beton=False)` | | draft.new |
| `list_drafts()` | – | draft.list_all |
| `get_draft(draft_id)` | – | draft.summary |
| `add_climb(draft_id, climb_id, position=None)` | | cli-logica add-climb |
| `remove_climb(draft_id, climb_id)` | | idem |
| `avoid_place(draft_id, place, radius_km=2.5, factor=0.35)` | | cmd_draft_avoid-logica |
| `unavoid_place(draft_id, place)` | | idem |
| `route_draft(draft_id)` | | draft.route |
| `suggest_climbs(draft_id, max_detour_km=8, limit=6)` | | draft.suggest |
| `optimize_draft(draft_id, max_km, objective="hm", min_ratio=8.0)` | | draft.optimize |
| `export_gpx(draft_id, output_path=None)` | default: `<naam>.gpx` in cwd | gpx.export |

Niet exposen in v1: setup/build/heat/climbs-detect (admin, blijft CLI).
Geen MCP-elicitation: suggesties zijn gewone tool-output; de client-LLM stelt
de vraag aan de gebruiker (bewuste keuze, zie CLAUDE.md).

## Refactor-aanwijzing

De CLI-commando's bevatten nu al dunne logica; waar de MCP-tool en het
CLI-commando dezelfde stappen delen (bv. add-climb-validatie, avoid-place),
til die op naar een gedeelde functie in het betreffende domeinmodule
(`draft.py`) zodat cli.py en mcp_server.py beide dun blijven. Fouten:
DraftError/RuntimeError gewoon laten opborrelen — het SDK zet exceptions om
in tool-errors; geen eigen error-envelope bouwen.

## Docs

- README: sectie "MCP" met config-snippet voor Claude Code
  (`claude mcp add lusmaker -- <absolute pad>/.venv/bin/lus-mcp`) en Claude
  Desktop (mcpServers-JSON), plus de noot dat GraphHopper moet draaien.
- CLAUDE.md: één regel dat dezelfde flow ook via MCP beschikbaar is.
- PRODUCT.md: M2 afvinken.

## Tests (puur, geen netwerk, geen ~/.lusmaker)

- `tests/test_mcp.py`: zet `LUSMAKER_HOME` naar een tempdir VÓÓR imports van
  lusmaker-modules (subprocess of importlib-reload is toegestaan; kies de
  eenvoudigste betrouwbare aanpak). Test:
  1. de server importeert en heeft exact de tool-namen uit de tabel;
  2. `new_draft` + `get_draft` + `add_climb`-validatiefout (onbekende klim)
     werken tegen de tempdir met een minimale klimdatabase-fixture
     (schrijf een kleine climbs.json in de tempdir-cache).
- Bestaande tests blijven groen.

## Definition of done

- `uv pip install -e .` (reviewer draait dit) levert werkend `lus-mcp`-script
  dat opstart en op stdio wacht.
- `.venv/bin/python -m tests.run` groen.
- Commits klein en helder; niet pushen.
