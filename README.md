# Lusmaker

Bouw fiets-GPX-**lussen** in de Vlaamse Ardennen, stap voor stap, aangestuurd door
een LLM (Claude/OpenAI) via de `lus`-CLI. Denk:

> "Zoek een route van Wetteren naar de Berendries, rustige wegen, klimmen die
> weinig omweg vragen erbij, en een lus — geen twee keer dezelfde baan."

De LLM vertaalt dat naar tool calls; de tool stelt suggesties voor ("Molenberg
erbij voor ~9 km extra?") die de LLM aan de gebruiker terugspeelt.

## Architectuur

```
LLM (Claude Code, ...) ──bash──> lus CLI (JSON in/uit)
                                   ├── GraphHopper (Docker, lokaal) — routing
                                   │     profiel "quiet" + per-request custom model
                                   ├── klim-database — OSM-namen + DEM-klimsegmentdetectie
                                   ├── gazetteer — lokale geocoder (OSM plaatsen/straten)
                                   └── drafts — stateful route-opbouw + GPX-export
```

- **Routing**: self-hosted [GraphHopper](https://github.com/graphhopper/graphhopper)
  op het Geofabrik België-extract, met elevation (AWS Terrain Tiles). Het
  `quiet`-profiel straft drukke wegen en beloont fietsnetwerk-wegen
  (`bike_network`), à la "populair bij fietsers" zonder Strava-data nodig te
  hebben.
- **Lus zonder herhaalde wegen**: elke leg buffert zijn geometrie tot
  corridor-polygonen die als `areas` in het custom model van de volgende legs
  worden meegegeven (priority ×0.15). De start-omgeving wordt vrijgehouden.
- **Klimmen omhoog**: een klim wordt als voet→midden→top via-punten gerouteerd,
  dus altijd in de klimrichting.
- **Klim-database**: `lusmaker/climbs.yaml` (namen + gemeente) wordt gematcht op
  OSM-straatnamen; uit het DEM-hoogteprofiel wordt het steilste aaneengesloten
  segment geknipt (de straat is vaak langer dan de klim). Resultaten liggen
  dicht bij de Climbfinder-cijfers, uit 100% open data.

## Setup (eenmalig)

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e .
.venv/bin/lus setup      # ~700 MB downloads + GraphHopper-config
docker compose up -d     # GraphHopper importeert België (eenmalig, ~5-15 min)
.venv/bin/lus build      # klim-database + geocoder (~3 min)
.venv/bin/lus status
```

## Gebruik

```bash
lus draft new --start "Wetteren" --name berendries-lus
lus climbs near Wetteren --radius-km 25
lus draft add-climb <id> berendries
lus draft route <id>                      # lus, vermijdt eigen heenweg
lus draft optimize <id> --max-km 45       # vul automatisch aan binnen budget
lus draft suggest <id> --max-detour-km 10 # "Molenberg erbij voor +9.2 km?"
lus draft preview <id> -o route.html      # kaart + hoogteprofiel bekijken
lus draft export <id> -o route.gpx
```

`draft optimize` kiest per ronde de klim met de meeste extra hoogtemeters
(`--objective hm`, standaard) of de beste verhouding hoogtemeters per extra
kilometer (`--objective hm-per-km`). Het commando gebruikt een veiligheidsmarge
voor schattingsdrift en draait een toevoeging terug zodra de herrouteerde lus
het harde `--max-km`-budget overschrijdt.

`draft preview` schrijft één HTML-bestand met een interactieve routekaart,
klimmarkers, kwaliteitsmetrieken en een hoogteprofiel. Zonder `-o` wordt
`<draftnaam>-preview.html` in de huidige map geschreven. De kaart gebruikt bij
het openen Leaflet en OpenStreetMap via internet; het routebestand zelf blijft
lokaal.

Alle output is JSON; zie `CLAUDE.md` voor de LLM-instructies.

## MCP

Dezelfde routeflow is beschikbaar als lokale MCP-server via stdio. Vervang
`/absoluut/pad/naar/lusmaker` hieronder door het absolute pad naar deze
repository.

Voor Claude Code:

```bash
claude mcp add lusmaker -- /absoluut/pad/naar/lusmaker/.venv/bin/lus-mcp
```

Voor Claude Desktop, voeg dit toe aan de MCP-configuratie:

```json
{
  "mcpServers": {
    "lusmaker": {
      "command": "/absoluut/pad/naar/lusmaker/.venv/bin/lus-mcp"
    }
  }
}
```

De lokale data moeten eerst met `lus setup` en `lus build` opgebouwd zijn.
GraphHopper moet draaien wanneer MCP-tools routeren, suggesties berekenen of
optimaliseren; controleer dit met `lus status`.

## Regiopacks

Zonder `~/.lusmaker/regions.json` gebruikt Lusmaker exact de bestaande
Vlaanderen-paden (`~/.lusmaker/data`, `cache`, `gh` en `heat`) en GraphHopper
op poort 8989. Migreer een bestaande installatie eenmalig voordat je meerdere
regio's toevoegt:

```bash
lus region migrate-legacy
```

Dit registreert `vlaanderen`, verplaatst de vier datamappen naar
`~/.lusmaker/regions/vlaanderen/` en schrijft
`docker-compose.regions.yml`. Drafts blijven in de globale map en bestaande
drafts zonder regioveld worden als Vlaanderen behandeld.

Een regiopack voor Zeeland toevoegen:

```bash
lus region add zeeland \
  --geofabrik europe/netherlands/zeeland \
  --bbox 51.2,3.4,51.8,4.3
lus region list
lus region default zeeland
```

`region add` downloadt het Geofabrik-extract en de DEM-tegels die de bbox
raakt, bouwt gazetteer en auto-klimdatabase, schrijft een eigen
GraphHopper-config en voegt een service toe aan
`docker-compose.regions.yml`. Poorten worden vanaf 8989 toegewezen. Alleen
`vlaanderen` gebruikt de meegeleverde, handmatig samengestelde
`climbs.yaml`; andere regio's gebruiken uitsluitend auto-detectie.

De default-regio geldt voor `setup`, `build` en nieuwe drafts. Een eenmalige
override kan met `--region` op een commando of met `LUSMAKER_REGION`, waarbij
de CLI-optie voorrang heeft:

```bash
lus climbs near Middelburg --region zeeland
lus draft new --start Middelburg --region zeeland --name zeeuwse-lus
LUSMAKER_REGION=zeeland lus status
```

Een draft bewaart zijn regio. `route`, `suggest`, `optimize`, preview en export
gebruiken daarom altijd de regiopaden en GraphHopper-poort uit de draft, ook
als de default later verandert. MCP biedt dezelfde keuze via de optionele
`region`-parameter van `new_draft` en `list_climbs`; `list_regions` toont het
register.

Regiopacks ondersteunen nog geen route over twee packs heen. Maak daarvoor
voorlopig één regio met één passend Geofabrik-extract. Lusmaker leidt een bbox
ook niet automatisch af uit de Geofabrik-polygon; `--bbox` blijft verplicht.

## Status / roadmap

PoC. Al gebouwd naast de basisflow: auto-klimdetectie (DEM-sweep, ~700 klimmen
naast de namenlijst), zachte voorkeuren (kasseien/beton/strict), vermijdzones
rond plaatsen (`draft avoid`), kwaliteitsmetrieken per route (kassei- en
steenwegmeters, kruisingen met drukke wegen), en een persoonlijke heatmap
(`lus heat build`): eigen GPX-ritten worden een GraphHopper custom area die
bereden wegen een relatieve boost geeft — de legale variant van
Strava-heatmap-routing.

Bekende beperkingen en volgende stappen:

- [x] M1: `draft optimize` — greedy klimselectie met afstandsbudget en
      budget-rollback
- [x] M2: stdio MCP-server met LLM-gerichte tools bovenop dezelfde kern
- [x] M3: lokale HTML-kaartpreview per draft met hoogteprofiel
- [x] M4: regiopacks met eigen data, GraphHopper-graaf en draftbinding
- [ ] DHMV II 1 m LiDAR-DTM i.p.v. 30 m terrain tiles voor klimprofielen
- [ ] Bosberg heet in OSM niet "Bosberg" — juiste straatnaam opzoeken
- [ ] Corridor-penalty is zacht; bij smalle valleien kan een stukje heenweg
      toch hergebruikt worden
- [ ] Heat-polygonen schalen: bij duizenden ritten eerst vereenvoudigen
      (concave hulls) voor de GH-import
- [ ] Strava API-sync voor automatische eigen-ritten-import (OAuth)
- Grensoverschrijdende routes over meerdere regiopacks worden nog niet gemerged
- Een bbox wordt nog niet automatisch uit de Geofabrik-polygon afgeleid
