# T14 — Toerisme Vlaanderen open-data-routelagen (fiets + wandel)

## Waarom

Legale, gecureerde "goede routes"-data: de knooppuntnetwerken en icoonroutes
van Toerisme Vlaanderen staan onder de Modellicentie Gratis Hergebruik op
https://data.toerismevlaanderen.be. Het wandelnetwerk is bovendien de eerste
kwaliteitslaag voor het trail-profiel (de heat/OSM-fietsdata zegt niets over
looppaden).

## Databronnen (WFS/GeoJSON)

- Fietsnetwerk: dataset `cycling_node_network_v2` (geoservices_v2)
- Wandelnetwerken: dataset `hiking_node_network_v2`
- LF-/icoonroutes: dataset `lf_routes`

Zoek bij implementatie de exacte WFS-endpoint-URL's op de datasetpagina's op
(GeoJSON-output; server-side bbox-filter op de regio-bbox gebruiken zodat de
download klein blijft). Schrijf de gevonden URL's als constanten met een
bronvermelding + licentienoot in de code.

## Gedrag

- `lus heat fetch-vlaanderen [--region ...]`: haalt de drie lagen op voor de
  regio-bbox, rastert lijngeometrieën op het bestaande celgrid
  (geo.cells/resample zoals GPX-tracks) en cachet per regio:
  `cache/vlaanderen_routes.pkl` = {"fiets": set(cellen), "wandel": set(...)}.
  (LF-routes tellen bij "fiets".) Nederlandstalige voortgang/foutmeldingen;
  404/HTML-antwoord → duidelijke fout, geen crash.
- `lus heat build`: bouwt voortaan TWEE custom areas:
  - `popular` = eigen GPX ∪ OSM-traces ∪ vlaanderen-fiets (zoals nu + laag)
  - `popular_trail` = vlaanderen-wandel ∪ eigen GPX-tracks
  Schrijf beide features in hetzelfde popular.geojson (ids "popular" en
  "popular_trail"); sla de celsets apart op in heat.pkl.
- `gh_config`: quiet.json houdt `!in_popular ×0.75`; trail.json krijgt
  `!in_popular_trail ×0.75` — alleen wanneer de respectieve area bestaat
  (zelfde bestaansafhankelijke logica als nu). Documenteer dat een
  graafherimport nodig is (reviewer doet die).
- `analysis.route_stats`: populair_pct meet voortaan tegen de bij het
  draft-profiel horende celset (trail → wandelset indien beschikbaar,
  anders zoals nu).
- Readiness-regel 4 (gewichtenvraag) mag "populair" nu ook voorstellen bij
  trail-activiteit als de wandelset bestaat.

## Tests (puur)

- WFS-GeoJSON-parsing → celset op een mini-fixture (2 lijntjes, geen
  netwerk; fetch injecteerbaar).
- heat.build: twee-area-geojson met correcte ids; zonder wandeldata alleen
  "popular" (bestaand gedrag, cassettes blijven groen).
- analysis: profielafhankelijke populair_pct-keuze.

## DoD

Suite + cassettes groen; docs (README databronnen + licentie, CLAUDE.md één
regel); kleine commits; niet pushen; geen netwerk/docker in jouw sandbox —
de reviewer draait fetch-vlaanderen, heat build en de herimport live.
