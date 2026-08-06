# T5 — Ad-hoc regio-provisioning + regiopack-cache

## Waarom

Een vraag over een onbekende plek ("lus in Renesse") moet vanzelf leiden tot
een klaargezette regio, zonder dat de gebruiker slugs en bboxen kent.
Voorbereide packs zijn cachebaar (lokaal pad of URL/S3) zodat herinstallaties
en meerdere machines de dure stappen (GH-import, klimdetectie) overslaan.

## Onderdelen

### 1. Globale plaatsresolutie (`lusmaker/discover.py`)

- `find_place(query) -> {lat, lon, label, country}` via de publieke
  Nominatim-API (`https://nominatim.openstreetmap.org/search`, format=jsonv2,
  limit=3, User-Agent "lusmaker/0.1"). Max 1 request/seconde; resultaat
  cachen in `<HOME>/cache/nominatim.json` (query → resultaat, geen TTL nodig).
- `region_slug_for(lat, lon) -> {"slug", "pbf_url", "bbox"}` via de
  Geofabrik-index `https://download.geofabrik.de/index-v1.json` (eenmalig
  downloaden naar `<HOME>/cache/geofabrik-index.json`). Kies de KLEINSTE
  regio (diepste in de hiërarchie) waarvan de polygon het punt bevat;
  point-in-polygon zelf schrijven (ray casting, `geo.py`). Bbox = bounds van
  de polygon.
- Weiger regio's waarvan de PBF groter is dan `LUSMAKER_MAX_PBF_MB`
  (default 700): duidelijke fout met advies om een subregio te nemen.

### 2. Provisioner (`lusmaker/provision.py`)

- `provision(slug, pbf_url, bbox, background=True)`:
  fases `downloaden → bouwen (extract/gazetteer/climbs detect) → gh-import →
  klaar`, met fase + voortgang weggeschreven naar
  `<HOME>/regions/<slug>/provision.json` zodat status pollbaar is.
- GH-import: regio registreren (poort), compose-file bijwerken en
  `docker compose -f docker-compose.regions.yml up -d graphhopper-<slug>`
  draaien via subprocess; daarna wachten op `/health` (timeout 20 min).
  (Runtime-docker mag vanuit de app; jij draait het alleen niet in tests.)
- Achtergrond: `subprocess.Popen([sys.executable, "-m", "lusmaker.provision",
  slug, ...])` met een `__main__`-blok in provision.py; niet threads.
- **Geen** automatische OSM-traces-fetch (rate-limited upstream); heat blijft
  handmatig per regio.

### 3. Regiopacks

- `lus region pack <slug> [-o pad.tar.gz]` — tarball van
  `cache/ + data/*.hgt + gh/graph-cache + gh/config.yml + gh/custom_models`
  (NIET de PBF zelf: te groot en herbouwbaar) + `pack.json` (slug, bbox,
  geofabrik, lusmaker-versie, gh-image).
- Provisioning checkt eerst `LUSMAKER_PACK_CACHE` (kommagescheiden lijst van
  basis-URL's of paden; pack verwacht op `<basis>/<slug>.tar.gz`, slashes in
  de slug vervangen door `__`). Hit → download + uitpakken + registreren,
  klaar in seconden. Miss → lokaal bouwen; als
  `LUSMAKER_PACK_UPLOAD=<pad of s3://...>` gezet is, na afloop pack maken en
  uploaden (s3 via `aws s3 cp` subprocess als beschikbaar; anders kopiëren
  naar pad; falen van upload is een warning, geen error).

### 4. CLI + MCP

- CLI: `lus region ensure "<plaats of slug>"` (start provisioning of meldt
  bestaande regio), `lus region status <slug>`, `lus region pack`.
- MCP: tools `ensure_region(place)` en `region_status(slug)`
  (**test_mcp: 18 tools**). `new_draft` blijft ongewijzigd; de flow bij een
  geocode-miss staat in CLAUDE.md: ensure_region → melden aan de gebruiker →
  region_status pollen → new_draft met region.
- CLAUDE.md: beschrijf die flow expliciet (de LLM moet de wachttijd melden,
  niet blokkeren).

## Tests (puur, geen netwerk, geen docker)

- point-in-polygon + kleinste-regio-keuze op een mini-index-fixture
  (2 geneste polygonen).
- pack-URL-opbouw + slug-escaping.
- provision.json-fasemodel (schrijven/lezen/status).
- Nominatim-cachelaag met een geïnjecteerde fetch-functie.

## DoD

- Tests groen (`python -m tests.run`); bestaand gedrag ongewijzigd.
- README: sectie "Ad-hoc regio's en packs" + PRODUCT.md-noot onder M4.
- Kleine commits; niet pushen; geen downloads/docker in jouw sandbox.
