# T15 — Alle bruikbare Toerisme Vlaanderen-lagen binnenhalen

## Waarom

Naast de netwerken (T14) publiceert geodata.toerismevlaanderen.be per-segment
kwaliteitsdata en POI's onder dezelfde vrije licentie. Verkend op 2026-08-08:

| laag | attribuut | waardes (sample) | gebruik |
|---|---|---|---|
| routes:wegdek_fiets / _wandel | `ground` | verhard / onverhard / **kassei** / leeg | officiële kassei- en onverhard-data (OSM-surface ontbreekt vaak) |
| routes:verkeersintensiteit_fiets / _wandel | `traffic` | "niet-autovrij" (vlag-laag: aanwezig = niet autovrij) | autovrij-aandeel van een route |
| poi:picknickbank, zitbank, toilet, uitkijktoren, fietspomp_en_fietsherstel, fietsverhuur, speeltuin, ebike | puntlagen | | route-verrijking in preview + probe |
| routes:knoop_fiets / knoop_wandel | `knoopnr` (−9999 = virtueel) | | knooppunt-labels in preview; basis voor latere knooppunt-navigatie |

## Gedrag

### 1. Fetch (uitbreiding `lus heat fetch-vlaanderen`)

Zelfde WFS-patroon/bbox als T14 (zie `_wfs_url`/`_vlaanderen_wfs_url`).
Cache per regio uitbreiden (`vlaanderen_routes.pkl` versieveld toevoegen):

- `wegdek`: {"kassei": set(cellen), "onverhard": set(cellen)} — fiets- en
  wandellaag samengevoegd; klassen dynamisch lezen (lege/None-ground
  overslaan).
- `druk`: set(cellen) uit beide verkeersintensiteit-lagen (waarde ≠ leeg).
- `pois`: {type: [(lat, lon, naam?)]} — puntlagen, binnen bbox.
- `knopen`: [(lat, lon, knoopnr, "fiets"|"wandel")] — alleen knoopnr ≥ 0.

### 2. Metrieken (`analysis.route_stats`)

- `kassei_m`: als de GH-surface-details "missing" zijn voor een stuk route,
  val terug op de wegdek-kassei-cellen (cell-lidmaatschap van de
  routepunten × stuklengte). Zelfde patroon voor een nieuw veld
  `onverhard_m` (wegdek-onverhard als aanvulling op road_class-offroad).
- Nieuw: `autovrij_pct` = aandeel routepunten op netwerk-cellen dat NIET in
  de druk-set valt (alleen berekenen waar de route op netwerkcellen ligt;
  geen netwerkdekking → veld weglaten).

### 3. Preview + probe

- `preview.render`: POI-markers binnen 150 m van de route (klein icoon per
  type, max ~40 markers) en knooppunt-nummers binnen 100 m als tekstlabel.
- `draft.probe` terrein-sectie: `pois_langs_route` (telling per type) en
  `knooppunten_langs_route` (aantal). `intents`-compactoutput: één regel
  "onderweg: 2 picknickbanken, 1 uitkijktoren, toilet" wanneer niet leeg.
- readiness: GEEN nieuwe vraagregels in deze taak.

### 4. Géén routingwijzigingen

Geen nieuwe GH-areas in deze taak (grafbloat; de netwerken sturen al).
Alleen data, metrieken en verrijking.

## Tests (puur)

- fetch-parsing per laagtype (wegdek-klassen, druk-vlag, poi-punten,
  knoopnr-filter) met geïnjecteerde fetch.
- kassei-fallback: synthetische route half op kassei-cellen met "missing"
  surface-details → kassei_m telt het cellen-deel.
- autovrij_pct: wel/geen netwerkdekking.
- preview: POI/knooppunt-markers verschijnen; cap gerespecteerd.
- Cassettes blijven groen (metriek-fallbacks alleen actief bij aanwezige
  caches; de fixtures hebben er geen — controleer die aanname en documenteer
  ze in de test).

## Let op

Er kan een andere agent in de repo werken: raak bestaande niet-gecommitte
wijzigingen van anderen niet aan en commit uitsluitend je eigen bestanden.
Commit vroeg en klein; niet pushen; geen netwerk/docker.
