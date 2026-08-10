# T24 — Landmarks/POI's in de gazetteer + "lus rond/langs een plek"

## Probleem

De geocoder kent alleen **straten** en **administratieve plaatsen**. Benoemde
landmarks (recreatiedomeinen, parken, waterplassen) worden niet gevonden:

- `geocode("Blaarmeersen")` → geen hits
- `geocode("Blaarmeersen, Gent")` → valt terug op **Gent-centrum** (51.054, 3.725)

Gevolg: een prompt als "loop rond de Blaarmeersen" wordt genegeerd; de engine
maakt enkel een round-trip vanaf de startplaats en loopt langs een willekeurige
nabije plas (de Watersportbaan). De gebruiker wil dat de route de benoemde
landmark **respecteert**.

Doel, **heel Vlaanderen** (de bestaande `vlaanderen`-regio / `config.BBOX`):
1. Landmarks vindbaar maken in de geocoder.
2. Een route echt **rond/langs** een benoemde landmark laten lopen.

## Deel A — Landmarks extraheren (`lusmaker/osm.py`)

`build_extract()` haalt nu in pass 1 alleen `place`-**nodes** en in pass 2
benoemde `highway`-ways. Voeg een landmark-extractie toe:

- Extraheer benoemde **POI's/areas** met een `name` én één van deze tags
  (kies pragmatisch; dek minstens water/parken/recreatie):
  - `leisure` ∈ {park, nature_reserve, recreation_ground, sports_centre,
    garden, common, pitch (alleen met naam), stadium, marina, water_park}
  - `natural` ∈ {water, wood, beach, heath, scrub, wetland}
  - `landuse` ∈ {recreation_ground, forest, meadow, village_green, cemetery}
  - `tourism` ∈ {attraction, theme_park, zoo, viewpoint, museum, park}
  - `water` (elke waarde) en `boundary=protected_area` met naam
- Bronnen: zowel **nodes** (met tag + name) als **ways/areas** (bereken het
  **centroid** uit de node-coördinaten; hergebruik `.with_locations()` zoals
  pass 2). Relations mogen overgeslagen worden als dat de bouw te zwaar maakt,
  maar veel grote domeinen (Blaarmeersen) zijn multipolygon-relations — probeer
  ze mee te nemen via de osmium AreaManager als het redelijk kan; anders
  documenteer de beperking en zorg dat de way-variant de Blaarmeersen dekt.
- Alles binnen `config.BBOX` (`_in_bbox`).
- Sla op als `extract["landmarks"] = [(name, kind, lat, lon), ...]` waarbij
  `kind` de brontag is (bv. `"leisure:park"`, `"natural:water"`).
- **Verhoog `EXTRACT_FORMAT_VERSION` naar 3** (forceert rebuild).
- `build_gazetteer()`: neem de landmarks mee als `gaz["landmarks"]`
  (zelfde tuple-vorm als `places`). Dedupe op (genormaliseerde naam, ~100 m).
  Houd `places` en `streets` ongewijzigd van semantiek.

## Deel B — Geocoder (`lusmaker/geocode.py`)

- `_load()`/callers: tolereer een oude pickle zonder `landmarks` (default `[]`)
  met een nette melding "draai `lus build --force`".
- Pas `geocode()` aan zodat landmarks meespelen, met deze prioriteit voor een
  1-part query (`"Blaarmeersen"`): **exacte/genormaliseerde landmark-match**
  vóór straat-cluster, vóór plaats. Voor `"X, Plaats"`: als `X` een landmark is
  binnen ~8 km van die plaats, geef die terug (i.p.v. de plaats-fallback).
- Genormaliseerde matching zoals `_match_places` (case/accent-insensitive).
  Geef landmark-hits `type: "landmark"` en een `kind`.
- Raak `_nearest_place`/`places_near_route` **niet** aan met landmarks (die
  blijven op administratieve `places` werken, anders vervuilt readiness).

## Deel C — Route rond/langs een landmark

- `intents.plan_route` (en `adjust_route`) krijgen een nieuwe optionele param
  `rond_plaats: str | None` ("loop rond/langs deze plek"). Geocode ze; is het
  een landmark (of gewone plek), gebruik het punt als **round-trip-anker** i.p.v.
  de start. Concreet: geef het door tot in `draft._fill_with_round_trip` /
  `_round_trip_anchor` zodat de rondrit **rond dat punt** wordt gebouwd, terwijl
  start/eind de opgegeven `start` blijven. Als een pure "rond"-lus gevraagd is
  zonder aparte start, mag start = het landmark-punt.
- Kies een afstandsdoel dat de landmark echt omcirkelt: als de gebruiker geen
  afstand geeft, leid een redelijke lusomtrek af uit de landmark-grootte (of
  gebruik een default van ~1,5–2× de straal-tot-landmark). Houd het simpel maar
  zorg dat de lus binnen ~300 m langs de landmark komt.
- Tooling: voeg `rond_plaats` toe aan het `plan_route`-schema in
  `lusmaker/aws_chat.py` (`PLAN_ROUTE_SCHEMA` + executor-defaults) en breid
  `SYSTEM_PROMPT` uit: "Als de gebruiker vraagt om rond/langs een specifieke
  plek (park, plas, domein) te lopen/rijden, zet die plek in `rond_plaats`."

## Rebuild + acceptatie

- Draai `.venv/bin/lus build --force` (herparse Belgium-PBF → Vlaanderen; duurt
  minuten) zodat de nieuwe extract+gazetteer met landmarks lokaal bestaan.
- Voeg tests toe (in `tests/`, stijl van de bestaande):
  1. `geocode("Blaarmeersen, Gent")` geeft een **landmark**-hit binnen ~800 m
     van het recreatiedomein (rond 51.03–51.05 N, 3.69–3.71 E) — **niet**
     Gent-centrum.
  2. `geocode("Blaarmeersen")` (1 part) geeft dezelfde landmark.
  3. Een `plan_route(..., rond_plaats="Blaarmeersen, Gent", target_km=5,
     activiteit="trail")` levert een lus waarvan minstens één punt binnen
     ~300 m van de landmark ligt (gebruik een gemockte/kleine routecheck als
     een volledige GraphHopper-run in de test te zwaar is; anders markeer als
     integratietest).
- Volledige suite groen: `.venv/bin/python -m tests.run`.
- **Raak geen bestanden van de web-/auth-/deploy-laag aan** (alleen
  `lusmaker/osm.py`, `geocode.py`, `intents.py`, `draft.py`, `aws_chat.py` en
  `tests/`). De productie-regiopack-rebuild + deploy doet de hoofdagent nadien.

## Belangrijk

- Houd de bouwtijd/omvang beheersbaar: cap het aantal punten per landmark en
  het totaal (bv. skip naamloze of piepkleine features). Log tellingen zoals de
  bestaande `[build]`-prints.
- Geen nieuwe zware dependencies; gebruik het reeds aanwezige `osmium`.
