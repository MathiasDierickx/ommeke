# Lusmaker

Bouw fiets- en trail-GPX-**lussen** stap voor stap, aangestuurd door een LLM
(Claude/ChatGPT) via MCP of door scripts via de `lus`-CLI. Denk:

> "Zoek een route van Wetteren naar de Berendries, rustige wegen, klimmen die
> weinig omweg vragen erbij, en een lus — geen twee keer dezelfde baan."

De LLM vertaalt dat naar tool calls; de tool stelt suggesties voor ("Molenberg
erbij voor ~9 km extra?") die de LLM aan de gebruiker terugspeelt.

Voor de volledig serverless AWS-deployment, Cognito-authenticatie en GitHub
Actions-pipeline: zie [docs/AWS.md](docs/AWS.md).

## Architectuur

```
Claude / ChatGPT ──MCP stdio of Streamable HTTP──> Lusmaker-domeinlaag
scripts          ──CLI met JSON─────────────────>     ├── GraphHopper-routing
                                                       ├── klim- en geodata
                                                       ├── stateful drafts
                                                       └── GPX + HTML-resources
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
  segment geknipt (de straat is vaak langer dan de klim). Voet en top worden
  langs de straat tot maximaal 120 m naar een kruispunt verlengd; `kern_m` en
  de klimstatistieken blijven het steile kernsegment beschrijven. Resultaten
  liggen dicht bij de Climbfinder-cijfers, uit 100% open data.

Na een upgrade naar het extract-cacheformaat met kruispunten moet de lokale
cache bewust opnieuw worden gebouwd. Draai eenmalig `lus build --force` en
daarna `lus climbs detect`. Dit kan klimgeometrieën en daardoor gerouteerde
metriekwaarden wijzigen.

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
lus draft readiness <id>                  # probe + relevante voorkeurvragen
lus draft optimize <id> --max-km 45       # klimmen + mooie rondrit binnen budget
lus draft suggest <id> --max-detour-km 10 # "Molenberg erbij voor +9.2 km?"
lus draft preview <id> -o route.html      # kaart + hoogteprofiel bekijken
lus draft export <id> -o route.gpx
```

Voorkeuren kunnen regio-onafhankelijk in een benoemd profiel worden bewaard:

```bash
lus profile set gravel \
  --gewichten "hoogtemeters=0.4,offroad=0.5,populair=0.1" \
  --kasseien graag --beton ok --steenwegen vermijd --autovrij belangrijk
lus profile show gravel
lus draft new --start "Wetteren" --profiel-naam gravel
```

Profielen staan onder `<LUSMAKER_HOME>/profiles/`. Een voorkeur met waarde
`null` is nog onbekend; `ok` betekent dat de gebruiker er expliciet geen
voorkeur voor heeft. Elke wijziging via CLI of MCP wordt met tijdstip en bron
in de profielhistoriek bewaard. Expliciete draftknoppen zoals
`--vermijd-kasseien` blijven boven op het profiel werken.

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

Met een voorkeurenprofiel gebruikt `draft optimize` standaard diens
genormaliseerde mix van `hoogtemeters`, `offroad`, `populair` en `kort`. Een
eenmalige override kan zonder het profiel te wijzigen:

```bash
lus draft optimize <id> --max-km 45 \
  --gewichten "hoogtemeters=0.5,offroad=0.35,populair=0.15"
```

De componenten liggen tussen 0 en 1; budget, luskwaliteit en heen-en-weer-
detectie blijven harde voorwaarden. `kasseien=graag` voegt boven op de
genormaliseerde mix een kasseicomponent met gewicht 0,15 toe. Het beïnvloedt
alleen de selectie, niet het GraphHopper-routingmodel. Zonder profiel of
gewichten blijft de bestaande standaardoptimalisatie ongewijzigd.

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

De lokale data moeten eerst met `lus setup` en `lus build` opgebouwd zijn.
GraphHopper moet beschikbaar zijn wanneer een tool routeert; controleer dat
met `lus status`. Gebruik voor een normale chat de lite-server met tien
composiet-tools; de volledige server biedt daarnaast de fijnmazige drafttools.

### Claude via stdio

Vervang het pad hieronder door het absolute repositorypad:

```bash
claude mcp add lusmaker -- /absoluut/pad/naar/lusmaker/.venv/bin/lus-mcp --lite
```

Claude Desktop gebruikt dezelfde executable en `args: ["--lite"]` in zijn
`mcpServers`-configuratie. Zonder transportoptie gebruikt Lusmaker stdio.

### Conversatiecontract

Gebruik `plan_route` voor de eerste wens. `target_km=50` betekent “mik op 50
km”; `tolerance_km=2.5` bepaalt de toegestane afwijking. `max_km=50` is een
harde bovengrens. `doel` onderscheidt `hoogtemeters`, `toeren` en de kortste
route via expliciete klimmen. Laat onbekende voorkeuren zoals `kasseien` op
`null` staan; `false` is een echte keuze om ze te vermijden.

`plan_route` geeft ofwel `status="needs_input"` met maximaal drie gerichte
vragen, ofwel `status="ready"` met cijfers, een constraint-rapport en deze
MCP-resources:

- `lusmaker://drafts/<id>/route.gpx` (`application/gpx+xml`);
- `lusmaker://drafts/<id>/preview.html` (`text/html`).

Pas profielantwoorden toe met `update_profile`. Een plaats vermijden of juist
toestaan gaat via `adjust_route`; roep die daarna opnieuw aan tot `ready`.
Hergebruik bij retries dezelfde `request_id`, zodat geen tweede draft ontstaat.
Stuur bij mutaties de laatst ontvangen `revision` als `expected_revision` mee;
een verouderde call wordt dan afgewezen in plaats van nieuwere wijzigingen te
overschrijven.

Dezelfde afstandssemantiek bestaat in de CLI:

```bash
lus plan-route --start Wetteren --target-km 50 --doel hoogtemeters \
  --request-id rit-2026-08-08
lus adjust-route <draft-id> --target-km 45 --expected-revision 4
```

### ChatGPT en Streamable HTTP

Start een lokale HTTP-endpoint voor ontwikkeling als volgt:

```bash
.venv/bin/lus-mcp --lite --transport streamable-http \
  --host 127.0.0.1 --port 8000 --path /mcp --stateless-http --json-response
```

ChatGPT verbindt met een remote MCP-server, niet rechtstreeks met localhost.
Gebruik voor een lokale/private installatie OpenAI Secure MCP Tunnel, of zet
de endpoint achter een eigen HTTPS- en authenticatieproxy. Voeg hem daarna in
ChatGPT developer mode als custom app toe. Zie de actuele
[OpenAI-instructies voor developer mode en MCP-apps](https://help.openai.com/en/articles/12584461-developer-mode-and-full-mcp-connectors-in-chatgpt).

Een bind op een niet-lokaal adres wordt zonder `--allow-remote` geweigerd.
Die vlag voegt zelf **geen** authenticatie of TLS toe en is dus alleen bedoeld
achter een beveiligde proxy. OAuth/tenant-isolatie horen bij de hosted laag,
niet bij deze lokale server.

### Evals

`evals/route_intents.json` bevat netwerkloze prompt→tool-acceptatiecases voor
Claude en ChatGPT. Score opgenomen toolcalls met:

```bash
.venv/bin/python -m lusmaker.mcp_evals opgenomen-toolcalls.json
```

### Open routelagen en populariteit

`lus heat build` combineert eigen GPX-tracks, optioneel gecachete publieke
OSM-GPS-traces en drie gecureerde datasets van
[Toerisme Vlaanderen Open Data](https://data.toerismevlaanderen.be):

- `cycling_node_network_v2` — fietsknooppuntnetwerk;
- `hiking_node_network_v2` — wandelknooppuntnetwerken;
- `lf_routes` — LF- en icoonroutes.

Dezelfde Vlaanderen-fetch cachet daarnaast fiets- en wandelwegdek,
verkeersintensiteit, recreatieve POI's en fiets-/wandelknooppunten. Kasseicellen
en drukke cellen worden als `kassei_tvl` en `druk_tvl` ingebakken, zodat
`vermijd-kasseien` ook ontbrekende OSM-tags opvangt en `autovrij` verkeersarme
wegen kan prioriteren. De overige data vullen kwaliteitsmetrieken aan en
verrijken preview en terreinprobe met voorzieningen en knooppuntlabels.

De Toerisme Vlaanderen-data vallen onder de Modellicentie Gratis Hergebruik;
de bron en datasetnamen blijven hierboven vermeld voor naamsvermelding en
herleidbaarheid. De WFS-download vraagt GeoJSON met een server-side bbox-filter
voor de actieve regio en bewaart alleen het gerasterde resultaat lokaal.

```bash
lus heat fetch-vlaanderen [--region vlaanderen]
lus heat build [--region vlaanderen]
```

`popular` combineert eigen GPX, OSM-traces en de fietslagen. Zodra de wandellaag
beschikbaar is, combineert `popular_trail` die met de eigen GPX-tracks. Beide
custom areas staan in `popular.geojson`; `quiet` en `trail` gebruiken alleen
hun eigen area. Na `heat build` is een volledige GraphHopper-graafherimport
nodig voordat de nieuwe areas routering beïnvloeden. Lusmaker verwijdert of
herimporteert de bestaande graaf niet automatisch.

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
steenwegmeters, kruisingen met drukke wegen), en profielgebonden
populariteitslagen (`lus heat build`) uit eigen GPX en gecureerde open
routedata — zonder de juridisch gesloten Strava Global Heatmap.

Bekende beperkingen en volgende stappen:

- [x] M1: `draft optimize` — greedy klimselectie met afstandsbudget en
      budget-rollback
- [x] M2: stdio MCP-server met LLM-gerichte tools bovenop dezelfde kern
- [x] M3: lokale HTML-kaartpreview per draft met hoogteprofiel
- [x] M4: regiopacks met eigen data, GraphHopper-graaf en draftbinding
- [x] M5: sportprofielen met trail-lopen naast het bestaande fietsprofiel
- [x] M6: serverless AWS Lambda-container, Cognito, S3-state en CI/CD
- [ ] DHMV II 1 m LiDAR-DTM i.p.v. 30 m terrain tiles voor klimprofielen
- [ ] Bosberg heet in OSM niet "Bosberg" — juiste straatnaam opzoeken
- [ ] Corridor-penalty is zacht; bij smalle valleien kan een stukje heenweg
      toch hergebruikt worden
- [ ] Heat-polygonen schalen: bij duizenden ritten eerst vereenvoudigen
      (concave hulls) voor de GH-import
- [ ] Strava API-sync voor automatische eigen-ritten-import (OAuth)
- Grensoverschrijdende routes over meerdere regiopacks worden nog niet gemerged
- Een bbox wordt nog niet automatisch uit de Geofabrik-polygon afgeleid
