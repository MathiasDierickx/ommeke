# Lusmaker

Bouw fiets- en trail-GPX-**lussen** stap voor stap, aangestuurd door een LLM
(Claude/OpenAI) via de `lus`-CLI. Denk:

> "Zoek een route van Wetteren naar de Berendries, rustige wegen, klimmen die
> weinig omweg vragen erbij, en een lus — geen twee keer dezelfde baan."

De LLM vertaalt dat naar tool calls; de tool stelt suggesties voor ("Molenberg
erbij voor ~9 km extra?") die de LLM aan de gebruiker terugspeelt.

## Architectuur

```
LLM (Claude Code, ...) ──bash──> lus CLI (JSON in/uit)
                                   ├── GraphHopper (Docker, lokaal) — routing
                                   │     profielen "quiet" en "trail"
                                   │     + per-request custom model
                                   ├── klim-database — OSM-namen + DEM-klimsegmentdetectie
                                   ├── gazetteer — lokale geocoder (OSM plaatsen/straten)
                                   └── drafts — stateful route-opbouw + GPX-export
```

- **Routing**: self-hosted [GraphHopper](https://github.com/graphhopper/graphhopper)
  op het Geofabrik België-extract, met elevation (AWS Terrain Tiles). Het
  `quiet`-profiel straft drukke wegen en beloont fietsnetwerk-wegen
  (`bike_network`), à la "populair bij fietsers" zonder Strava-data nodig te
  hebben. Het `trail`-profiel gebruikt voettoegang en geeft paden, tracks en
  onverhard relatief voorrang op verharde en grotere wegen.
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
lus draft optimize <id> --max-km 45       # klimmen + mooie rondrit binnen budget
lus draft suggest <id> --max-detour-km 10 # "Molenberg erbij voor +9.2 km?"
lus draft preview <id> -o route.html      # kaart + hoogteprofiel bekijken
lus draft export <id> -o route.gpx
```

Voor een traillus kies je het profiel bij het aanmaken, of gebruik je de
composietopdracht met een activiteit:

```bash
lus draft new --start "Wetteren" --name trail-lus --profiel trail
lus plan-route --start "Wetteren" --max-km 10 --activiteit trail
```

Zonder optie blijft het profiel `quiet`, zodat bestaande fietsflows
ongewijzigd werken. Een draft bewaart zijn profiel en gebruikt het bij
routeren, suggesties en optimalisatie.

`draft optimize` kiest per ronde de klim met de meeste extra hoogtemeters
(`--objective hm`, standaard) of de beste verhouding hoogtemeters per extra
kilometer (`--objective hm-per-km`). Het commando gebruikt een veiligheidsmarge
voor schattingsdrift en draait een toevoeging terug zodra de herrouteerde lus
het harde `--max-km`-budget overschrijdt. Blijft daarna minstens 1,5 km over,
dan probeert de optimizer vijf deterministische GraphHopper-rondritten vanaf
het verste waypoint. Hij kiest binnen het budget de variant met de meeste
hoogtemeters die de bestaande route niet overlapt. De rondrit blijft als
`opvulling: true`-leg met via-punten in de draft bewaard, zodat herrouteren
deterministisch blijft. Gebruik `--geen-opvulling` om exact de vroegere,
uitsluitend op klimmen gebaseerde optimalisatie te behouden; dezelfde optie is
beschikbaar op `plan-route` en als `geen_opvulling=true` via MCP.

`draft preview` schrijft één HTML-bestand met een interactieve routekaart,
klimmarkers, kwaliteitsmetrieken en een hoogteprofiel. Zonder `-o` wordt
`<draftnaam>-preview.html` in de huidige map geschreven. De kaart gebruikt bij
het openen Leaflet en OpenStreetMap via internet; het routebestand zelf blijft
lokaal.

Alle output is JSON; zie `CLAUDE.md` voor de LLM-instructies.

## Regressievangnet

De gewone offline testsuite speelt drie canonieke GraphHopper-scenario's af
uit gzipped cassettes en controleert kwaliteitsranges in plaats van exacte
geometrie:

```bash
.venv/bin/python -m tests.run
```

Zolang een cassette nog niet is opgenomen, wordt alleen dat scenario met een
duidelijke `SKIP` overgeslagen. Cassettes opnemen is bewust een handmatige
actie met de lokale GraphHopper en default-regio:

```bash
.venv/bin/python -m tests.record_fixtures
```

Voor het trailscenario gebruikt de recorder de bestaande, gerouteerde
Wetteren-draft met profiel `trail`, een afstand van 6–9 km en minstens één
klim. Zijn er nul of meerdere kandidaten, wijs hem dan expliciet aan:

```bash
LUSMAKER_TRAIL_DRAFT_ID=<draft-id> .venv/bin/python -m tests.record_fixtures
```

Na een GraphHopper-upgrade, graafherimport of profielwijziging draait de
live-smoke dezelfde fixture-scenario's tegen de echte router en print hij een
metriekentabel:

```bash
.venv/bin/python -m tests.live_smoke
```

Een bewuste engine-wijziging die een cassette breekt vereist een heropname;
vermeld dan de metriekverschuiving in de commitmessage. Een onverwachte
cassettebreuk is een regressie. De recorder en live-smoke zijn netwerk/GH-tests
en draaien nooit mee in `tests.run`.

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

`new_draft` accepteert `profiel="quiet"|"trail"`; `plan_route` accepteert
`activiteit="fietsen"|"trail"`. Beide gebruiken standaard het bestaande
fietsprofiel.

Voor het normale gesprek volstaan meestal twee composiet-tools:
`plan_route(...)` maakt en routeert een lus en schrijft meteen
`<LUSMAKER_HOME>/exports/<draft>/route.gpx` plus `preview.html`;
`adjust_route(...)` bundelt latere toevoegingen, verwijderingen,
vermijdplaatsen en een nieuw afstandsbudget in één call. Beide antwoorden zijn
compact en bevatten een direct bruikbare Nederlandse samenvattingszin.

Start voor hosted gebruik de lite-modus om alleen de zeven token-zuinige tools
aan te bieden:

```bash
.venv/bin/lus-mcp --lite
```

In een MCP-config voeg je `"--lite"` als argument toe:

```json
{
  "mcpServers": {
    "lusmaker": {
      "command": "/absoluut/pad/naar/lusmaker/.venv/bin/lus-mcp",
      "args": ["--lite"]
    }
  }
}
```

Lite bevat `plan_route`, `adjust_route`, `suggest_climbs`, `route_details`,
`ensure_region`, `region_status` en `list_drafts`. `route_details` is de
expliciete uitweg voor legs en volledige kwaliteitsmetrieken; zonder
`--lite` blijft de volledige set van 20 tools beschikbaar.

Dezelfde composiet-flow bestaat in de CLI:

```bash
lus plan-route --start Wetteren --max-km 45 --via-klim Berendries
lus adjust-route <draft-id> --voeg-klim-toe Molenberg --max-km 45
```

### GraphHopper herimporteren voor trail

De trailondersteuning voegt de encoded values `foot_access`, `foot_priority`
en `foot_average_speed` toe. Een bestaande GraphHopper-graaf bevat die waarden
niet: schrijf eerst de nieuwe configuratie met `lus setup` en voer daarna een
volledige graafherimport uit (bestaande graph-cache verwijderen en
GraphHopper opnieuw starten). Dit gebeurt niet automatisch; maak eerst een
back-up als de cache behouden moet blijven.

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
voorlopig één regio met één passend Geofabrik-extract.

### Ad-hoc regio's en packs

Een onbekende plaats kan zonder handmatig opzoeken van een slug of bbox worden
klaargezet:

```bash
lus region ensure "Renesse"
lus region status zeeland
```

`region ensure` zoekt de plaats wereldwijd via Nominatim, kiest de kleinste
passende regio uit de Geofabrik-index en start een apart achtergrondproces.
De voortgang doorloopt `downloaden`, `bouwen`, `gh-import` en `klaar` en staat
in `~/.lusmaker/regions/<slug>/provision.json`. Nominatim-resultaten en de
Geofabrik-index worden onder `~/.lusmaker/cache/` bewaard. Een exacte
Geofabrik-slug kan ook rechtstreeks aan `region ensure` worden gegeven.

Om onverwacht grote imports te voorkomen worden PBF's boven 700 MB geweigerd.
Pas die grens alleen bewust aan, bijvoorbeeld
`LUSMAKER_MAX_PBF_MB=1200 lus region ensure ...`. Publieke OSM-GPS-traces
worden nooit automatisch opgehaald; de persoonlijke heatmap blijft een
handmatige stap.

Een eenmaal gebouwde regio kan zonder bron-PBF worden verpakt:

```bash
lus region pack zeeland
lus region pack zeeland -o /srv/lusmaker-packs/zeeland.tar.gz
```

Het pack bevat de Lusmaker-caches, DEM-tegels, GraphHopper-graaf en
configuratie plus `pack.json`. Zet voor provisioning een kommagescheiden
zoeklijst van lokale mappen of basis-URL's:

```bash
export LUSMAKER_PACK_CACHE="/srv/lusmaker-packs,https://packs.example/lusmaker"
export LUSMAKER_PACK_UPLOAD="/srv/lusmaker-packs"
```

Lusmaker zoekt daar naar `<slug>.tar.gz` (slashes worden `__`). Een cache-hit
wordt uitgepakt en geregistreerd, waarna alleen de GraphHopper-service nog
wordt gestart. Met `LUSMAKER_PACK_UPLOAD=s3://bucket/prefix` gebruikt Lusmaker
`aws s3 cp`; een mislukte upload wordt als waarschuwing gemeld en maakt de
lokale provisioning niet ongedaan.

De MCP-server biedt dezelfde asynchrone flow met `ensure_region(place)` en
`region_status(slug)`, naast de bestaande `list_regions`.

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
- [x] M5: sportprofielen met trail-lopen naast het bestaande fietsprofiel
- [ ] DHMV II 1 m LiDAR-DTM i.p.v. 30 m terrain tiles voor klimprofielen
- [ ] Bosberg heet in OSM niet "Bosberg" — juiste straatnaam opzoeken
- [ ] Corridor-penalty is zacht; bij smalle valleien kan een stukje heenweg
      toch hergebruikt worden
- [ ] Heat-polygonen schalen: bij duizenden ritten eerst vereenvoudigen
      (concave hulls) voor de GH-import
- [ ] Strava API-sync voor automatische eigen-ritten-import (OAuth)
- Grensoverschrijdende routes over meerdere regiopacks worden nog niet gemerged
- Een bbox wordt nog niet automatisch uit de Geofabrik-polygon afgeleid
