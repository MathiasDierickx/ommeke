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
lus draft suggest <id> --max-detour-km 10 # "Molenberg erbij voor +9.2 km?"
lus draft export <id> -o route.gpx
```

Alle output is JSON; zie `CLAUDE.md` voor de LLM-instructies.

## Status / roadmap

PoC. Bekende beperkingen en volgende stappen:

- [ ] MCP-server (elke CLI-subcommand mapt 1-op-1 op een MCP-tool) voor gebruik
      buiten Claude Code, incl. elicitation voor de suggestie-vragen
- [ ] Populariteitslaag uit eigen Strava-historiek (map-matching op OSM-ways,
      injectie in het custom model)
- [ ] DHMV II 1 m LiDAR-DTM i.p.v. 30 m terrain tiles voor klimprofielen
- [ ] Klimdetectie zonder namenlijst (DEM-sweep over alle wegen)
- [ ] Bosberg heet in OSM niet "Bosberg" — juiste straatnaam opzoeken
- [ ] Corridor-penalty is zacht (×0.15); bij smalle valleien kan een stukje
      heenweg toch hergebruikt worden
- Regio is nu de bbox Wetteren–Vlaamse Ardennen (`config.BBOX`)
