# Reproduceerbare Vlaamse routedata

De pipeline haalt openbare route- en voorzieningenlagen van Toerisme Vlaanderen
op, bewaart de bronfeatures en bouwt een lokaal datapack. Ze importeert geen
Strava-, Komoot-, Wikiloc- of RouteYou-collecties en neemt geen persoonlijke
of onherleidbare seeds over. Zie de aparte [RouteYou-verkenning](ROUTEYOU-INTEGRATIE.md).

## Downloaden en opnieuw bouwen

Vanaf de repository, met de bestaande venv en zonder nieuwe dependencies:

```sh
.venv/bin/python scripts/sync_vlaanderen.py
.venv/bin/python scripts/sync_vlaanderen.py --offline
.venv/bin/python scripts/sync_vlaanderen.py --refresh
```

De eerste opdracht downloadt ontbrekende lagen; herhalen hergebruikt gecontroleerde
snapshots. `--offline` doet geen netwerkcalls. `--refresh` downloadt alle lagen
opnieuw. De equivalente CLI is:

```sh
.venv/bin/lus heat sync-vlaanderen --output .route-data/vlaanderen
```

De uitvoer is JSON en geeft `build`, `database`, `home` en `runtime_geactiveerd`.
De uitvoermap moet buiten de actieve `LUSMAKER_HOME` liggen. Downloadfouten
geven JSON met `error` en exitcode 1. Voortgang staat op stderr.

De map bevat:

- `raw/<laag>.json`: bron, licentie, verzoek-URL's, downloadtijd, aantallen en SHA-256.
- `raw/<sha256>.geojson`: oorspronkelijke features, geometrieën en attributen.
- `builds/<id>/manifest.json`: bronnen, aantallen, waardeverdelingen en beperkingen.
- `builds/<id>/checksums.json`: checksums van alle gegenereerde bestanden.
- `builds/<id>/home/regions/vlaanderen/cache/route_sources.sqlite`: features,
  bronmetadata en een SQLite R-tree-index.
- Dezelfde cachemap: compatibele `vlaanderen_routes.pkl` en `heat.pkl`.
- `home/regions/vlaanderen/gh/`: gegenereerde area- en modelbestanden voor latere
  activering door de beheerder.
- `current.json`: atomische verwijzing naar de laatst volledig gecontroleerde build.

WFS-paginering is gesorteerd op `objectid`; ook een serverlimiet kleiner dan
de aangevraagde pagina wordt verwerkt. Dubbele ID's, veranderende aantallen,
afgebroken downloads, HTML/XML-fouten en ongeldige coördinaten blokkeren de
build. De vorige `current.json` blijft bij een fout intact. Een afgebroken
download kan voltooide lagen hergebruiken. De bron levert geen transactionele
snapshot over alle lagen; raadpleeg daarom ook de download- en updatedatums.

Elke build is onveranderlijk. De identiteit hangt af van bronchecksums,
licenties, regiozone en buildformaat. Bij wijzigingen in de conversie moet
`FORMAT_VERSION` omhoog. De offline tests bouwen dezelfde snapshots in een
tweede lege map en vergelijken **alle outputchecksums**, inclusief de database.
Gedownloade bestanden staan in `.route-data/`, buiten Git.

Een achtergebleven `.sync.lock` mag alleen worden verwijderd nadat vastgesteld
is dat de bijbehorende import niet meer loopt.

## Bronnen en dekking

De allowlist telt achttien lagen: fiets- en wandeltrajecten, icoontrajecten,
fiets- en wandelwegdek, twee verkeersvlaglagen, acht voorzieningenlagen,
twee knooppuntlagen en een afzonderlijke virtuele wandellaag.

De WFS wordt zonder de oude regionale bbox bevraagd, zodat de volledige
officiële collectie en aansluitende grensroutes behouden blijven. De stagingregio
gebruikt de ruime Vlaamse bbox `(50.67, 2.53, 51.51, 5.94)` in lat/lon-volgorde.
De puntencache wordt daarop gefilterd; de database behoudt de bronfeatures.
Dit wijzigt de actieve regioconfiguratie, geocoder, DEM en routinggraaf niet.

Bron: [Toerisme Vlaanderen open data](https://toerismevlaanderen.be/nl/cijfers/open-data).
Routelagen gebruiken de Modellicentie Gratis Hergebruik met bronvermelding;
de via Pin je punt/OSM ontsloten voorzieningen houden hun OSM/ODbL-herkomst.
Beide vermeldingen staan per laag in het manifest. Het feit dat ze samen
geleverd worden maakt hun licenties niet identiek. De lokale pickle-bestanden
zijn eigen buildoutput; installeer nooit een willekeurig extern pickle-pack.

## Wat wordt gebruikt door de engine?

Met een actief pack leest `heat.vlaanderen_data` de nieuwe attributen en POI's.
`analysis.route_stats` voegt `routedata`, `gecureerd_pct`,
`niet_autovrij_pct` en `verkeer_onbekend_pct` toe. Ontbrekende GH-ondergrond kan
via passende bronlijnen worden aangevuld; expliciete GH-ondergrond blijft leidend.

Matching gebruikt samples van maximaal twintig meter, afstand tot de originele
bronlijn van maximaal twaalf meter en een richtingsverschil van maximaal dertig
graden. Afzonderlijke legs worden niet aan elkaar verbonden. Metrieken worden
gewogen op lengte. Dit voorkomt veel fouten van het oude raster, maar is nog
geen match op GraphHopper-edge-ID: zeer nabije parallelle wegen en hoogteverschillen
bij bruggen blijven aandachtspunten.

De bestaande gewogen optimizer gebruikt voor `populair` de geometrisch gematchte
curatiecomponent: 0,6 voor een passend netwerk en 0,8 voor een icoontraject.
Dit zijn eerste heuristische gewichten, geen geleerde kwaliteitsratings.
Overlappende bronnen tellen niet op. Fiets- en wandelbronnen blijven gescheiden;
virtuele wandeltrajecten krijgen geen bewegwijzeringsbonus, ook wanneer ze in
de algemene wandellaag voorkomen. Zonder pack blijft het bestaande gedrag gelden.

De verkeersbron bevat momenteel `niet-autovrij`, geen telling van verkeersdrukte.
Niet gemarkeerd blijft onbekend. `autovrij_pct` is daarom `null` als er onbekende
delen zijn. De optimizer geeft onbekende delen geen autovrijbonus. Een nieuw
GraphHopper-model gebruikt een milde factor 0,85 voor `niet_autovrij_tvl`, zonder
de historische `druk_tvl`-alias daarbovenop te stapelen. Oude caches blijven
leesbaar; herimport van de nieuwe areas gebeurt afzonderlijk.

De gegenereerde GH-areas gebruiken **nog steeds het bestaande circa 130 m-grid**.
Nauwkeurige segmentmatching verbetert nu de rapportage en selectie van kandidaten;
de lage routinglaag wordt daarmee nog geen exacte edge-score-engine. Ook de
standaardoptimizer die uitsluitend hoogtemeters optimaliseert, krijgt niet
stilzwijgend een andere doelstelling.

Wandelen heeft nog geen eigen publiek routeprofiel naast `trail`. Dit pack
voegt geen buggyprofiel toe; `buggygeschiktheid` blijft expliciet onbekend.

## Controle en offline route-evaluatie

Gebruik de `build`-waarde uit het importresultaat:

```sh
ROUTE_PACK="/absoluut/pad/naar/.route-data/vlaanderen/builds/<id>"
.venv/bin/lus heat verify-sources "$ROUTE_PACK"
.venv/bin/lus heat audit-seeds
.venv/bin/lus heat evaluate-sources "$ROUTE_PACK" \
  --drafts "$HOME/.lusmaker/drafts" --limit 20
```

De seed-audit leest de oorspronkelijke lokale cache en rapporteert aantallen,
geografische spreiding en onbekende herkomst. Ze verandert niets.
`evaluate-sources` heranalyseert opgeslagen geometrieën zonder routercalls.
Het resultaat bewijst dat de datapipeline werkt en meet dekking; het bewijst
niet dat nieuw gegenereerde routes beter zijn. Daarvoor blijft een vergelijking
van routevragen en terreinreview nodig.

Voor één proces kun je zonder permanente installatie kiezen voor:

```sh
LUSMAKER_ROUTE_PACK="$ROUTE_PACK" .venv/bin/lus heat status
```

Deze opt-in kiest het pakket voor data en kwaliteitsmeting. Hij start of
herimporteert GraphHopper niet. `LUSMAKER_ROUTE_DB` kan uitsluitend de
segmentdatabase overriden; gebruik het hele pack voor consistente attributen/POI's.

## Installatie door de beheerder

```sh
.venv/bin/lus heat install-sources "$ROUTE_PACK"
.venv/bin/lus heat install-sources "$ROUTE_PACK" --apply
```

De eerste opdracht toont alleen een concreet plan. `--apply` controleert het
pack, kopieert het naar de regiocache en schakelt de actieve versie atomisch om.
De oorspronkelijke caches, persoonlijke seeds en GraphHopper-bestanden blijven
bewaard. Een vorige packversie kan met dezelfde opdracht weer worden geactiveerd.
Voor terugkeer naar de oorspronkelijke caches verwijdert de beheerder alleen
`cache/route_sources/current.json`; verwijder geen oorspronkelijke databestanden.

Een geïnstalleerd open-datapack blijft onveranderlijk. Traditionele GPX-seeds
worden nog in de oorspronkelijke lokale heatcache geschreven; ze veranderen
de beheerde open-dataweergave niet. Vernieuw die met `sync-vlaanderen --refresh`
en installeer de nieuwe versie. Kopieer onherleidbare oude activiteitentellers
niet alsnog in een gedeeld pack.

Na installatie werken de bronlijnrapportage, POI's en gewogen kandidaatselectie
in processen die deze nieuwe code gebruiken. Voor de directe GraphHopper-voorkeur
moet de beheerder de **gegenereerde** `gh/custom_areas` en `gh/custom_models`
activeren en een graafherimport uitvoeren. De bestaande runtimeconfig bevat
mogelijk een kleinere geocoder/regiobbox; uitbreiding daarvan is een afzonderlijke
regiobuild. Een hosted deployment vergt bovendien uitrol van code én datapack.

Volgens `AGENTS.md` worden tijdens deze taak geen bestanden in `~/.lusmaker`
herschreven, geen containers aangeraakt en geen live smoke-tests uitgevoerd.
De installatie is getest in tijdelijke geïsoleerde homes. Het lokale pack en
een installatieplan zijn voorbereid; permanente runtime-activering vereist
een expliciete uitzondering op die projectregel of uitvoering door de beheerder.

## Vastgestelde resultaten — 2 oktober 2026

Gecontroleerde build: `1416c14a993c016b26b7fd8f1252b9228da2b93271be2b6298ebb819190038e2`.

| Onderdeel | Uitkomst |
|---|---:|
| Gedownloade lagen | 18 |
| Bronfeatures, inclusief overlap tussen lagen | 178.899 |
| Fietsnetwerksegmenten | 7.726 |
| Wandelnetwerksegmenten in de algemene bron | 21.301 |
| Daarvan expliciet bewegwijzerd | 16.932 |
| Icoonroutefeatures | 1.604 |
| Fietscellen in de compatibele cache | 124.224 |
| Wandelcellen na uitsluiten virtuele trajecten | 108.649 |
| Voorzieningen in de cache | 57.415 |
| Genummerde knooppunten in de cache | 19.324 |

De volledige download is opnieuw gebouwd in een tweede lege buildmap met
dezelfde ruwe snapshots en zonder netwerk: alle outputchecksums waren identiek.
De opgeslagen controle staat lokaal in `.route-data/reproducibility.json`.

Twintig bestaande routegeometrieën zijn offline herbeoordeeld: vijftien
fietsprofielen en vijf trailprofielen. Veertien raakten een passend gecureerd
netwerk. Mediane segmentanalyse: 0,074 s; traagste: 0,207 s op deze machine.
Dit is geen representatieve Vlaamse benchmark en geen nieuwe live routerun.
Resultaten: `.route-data/route-evidence-evaluation.json`.

De oude activiteitseeds zijn alleen gelezen en geaudit in
`.route-data/legacy-seeds-audit.json`; hun onbekende herkomst is niet als een
open licentie geïnterpreteerd. Het concrete, nog niet toegepaste installatieplan
staat in `.route-data/activation-plan.json`.
