# T25 — Google Maps geocoding-fallback voor specifieke POI's/zaken

## Doel

De lokale OSM-gazetteer kent geen specifieke zaken ("café Tonneke, Wetteren").
Voeg een **Google Maps-fallback** toe: als de lokale geocoder niets (of enkel
een zwakke plaats-fallback) vindt, vraag het aan Google en gebruik díé
coördinaten — voor zowel het **startpunt** als `rond_plaats`.

De key staat in de Lambda-env als `LUSMAKER_GOOGLE_MAPS_KEY` (leeg = fallback
uit; dan gedraagt alles zich als vandaag). Getest: zowel Places Text Search
(New) als Geocoding lossen "café Tonneke Wetteren" op naar Massemsesteenweg 48,
9230 Wetteren (50.9956, 3.8786).

## Nieuw: `lusmaker/google_geocode.py`

- `resolve(query: str, *, fetch=<default http>) -> dict | None`:
  - Als `LUSMAKER_GOOGLE_MAPS_KEY` leeg/afwezig is → return `None` (uit).
  - Probeer eerst **Places Text Search (New)**:
    `POST https://places.googleapis.com/v1/places:searchText`
    headers `X-Goog-Api-Key`, `X-Goog-FieldMask:
    places.displayName,places.formattedAddress,places.location`,
    body `{"textQuery": query, "regionCode": "BE",
    "languageCode": "nl"}`. Neem de eerste hit.
  - Val terug op **Geocoding API**:
    `GET https://maps.googleapis.com/maps/api/geocode/json?address=<q>&
    components=country:BE&language=nl&key=...`. Neem `results[0]`.
  - Return `{"label": <naam of formatted_address>, "lat": float,
    "lon": float, "type": "google", "source": <"places"|"geocoding">}`
    of `None` bij geen hit/fout.
  - Gebruik **stdlib `urllib`** (geen nieuwe dependency), een korte timeout
    (~5 s), en vang alle netwerk-/parsefouten af → `None` (nooit crashen).
  - `fetch` injecteerbaar maken zodat tests geen echte HTTP doen.
  - Cache met `functools.lru_cache` op de querystring (bespaart billing).
  - Log niets met de key erin.

## Wiring in `lusmaker/geocode.py`

- Bekijk de bestaande `resolve(query) -> tuple[dict, list[dict]]` en `geocode()`.
  Voeg een fallback toe: **eerst lokaal** (gratis, offline). Als lokaal geen
  bruikbare **primaire** hit geeft (leeg, of enkel een generieke plaats-fallback
  terwijl de query duidelijk een specifieke zaak/POI is), roep dan
  `google_geocode.resolve(query)` aan en gebruik die als primaire hit
  (met de bestaande tuple-vorm; alternatives mag leeg/onveranderd blijven).
- Zorg dat **zowel het startpunt als `rond_plaats`** hiervan profiteren. Als
  `intents`/`draft` het startpunt via een andere functie geocoden dan `resolve`,
  draad de fallback daar ook in (of centraliseer). Gedrag bij lege key = exact
  als vandaag.
- Injecteerbaarheid: laat de Google-aanroep injecteerbaar/uitschakelbaar zodat
  bestaande tests offline blijven.

## Tests (`tests/`)

- `google_geocode.resolve` met een gemockte `fetch`:
  1. Places-hit → correct dict (label "Café Tonneke", lat/lon).
  2. Places leeg → Geocoding-fallback gebruikt.
  3. Lege key → `None`.
  4. Netwerkfout → `None` (geen exception).
- Geocoder-integratie met gemockte Google-resolver: een query die lokaal niets
  geeft, valt terug op Google; een query die lokaal wél een landmark/straat
  vindt, gebruikt **geen** Google (geen billing als het niet hoeft).
- Volledige suite groen: `.venv/bin/python -m tests.run`.

## Grenzen

- **Alleen** `lusmaker/google_geocode.py` (nieuw), `lusmaker/geocode.py`,
  eventueel `lusmaker/intents.py`/`draft.py` voor de startpunt-wiring, en
  `tests/`. **Niet** aan de web-/auth-/deploy-/terraform-laag komen (de
  hoofdagent heeft de env-var + secret al geregeld). Commit niet; laat de
  wijzigingen staan.
- Geen nieuwe dependencies. Geen echte HTTP in tests.
