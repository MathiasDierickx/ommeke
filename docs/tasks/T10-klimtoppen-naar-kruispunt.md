# T10 — Klim-eindpunten doortrekken naar het dichtstbijzijnde kruispunt

## Waarom

Auto-gedetecteerde klimsegmenten beginnen/eindigen midden in een straatblok
(daar waar het DEM-profiel de steilte begrenst). Een route moet daar dan
"aantikken en omkeren", wat kleine uitsteeksels geeft. Als voet en top op
een kruispunt liggen, kan de route natuurlijk in- en uitvoegen.

## Gedrag

Bij klimdetectie (`detect_auto`) én bij de curated resolutie (`resolve_all`):
nadat het beste segment gekozen is, verleng beide uiteinden LANGS DE KETTING
tot het dichtstbijzijnde kruispuntknooppunt, met een cap van 120 m per kant.
Geen kruispunt binnen 120 m → laat het uiteinde staan (en voeg
`"warning": "eindigt midden in een blok"` toe aan het klim-record).

## Implementatie

- Kruispuntenset: tel in het extract per node-ref hoeveel wegen hem gebruiken
  (ALLE ways, één pass; refs staan al in het extract). Refs met gebruik ≥ 2
  over verschillende way-ids zijn kruispunten. Bouw dit één keer in
  `build_extract` en cache het mee (`extract["junction_refs"]`, als set) —
  verhoog daarvoor het cacheformaat en documenteer dat een `lus build
  --force` nodig is (de reviewer draait dat).
- De ketting (`_order_chain`-resultaat) heeft nu alleen coords; laat hem ook
  de refs per punt teruggeven zodat het verlengen op refs kan matchen
  (kleinste refactor: parallel aan `merged` een `merged_refs`-lijst).
- `_best_segment` werkt op geresamplede punten; map de gekozen i/j terug naar
  de dichtstbijzijnde oorspronkelijke ketenindex en verleng vandaar op de
  originele geometrie (zo blijven foot/top exact op way-knopen liggen — dat
  verbetert meteen de snapping).
- Stats (gain/avg/max) blijven berekend op het STEILE deel (i..j), maar
  `geom`/`foot`/`top` omvatten de verlengde uiteinden; voeg
  `"kern_m": <lengte steile deel>` toe voor transparantie.

## Tests (puur)

- kruispuntdetectie op een synthetisch extract (3 wegen, 1 gedeelde node).
- verlenging: eindpunt schuift naar de kruispuntknoop; cap 120 m
  gerespecteerd; warning zonder kruispunt.
- terug-mapping resample-index → ketenindex.

## DoD

Tests groen; `lus build --force` + `lus climbs detect` door de reviewer;
README-noot. Kleine commits; niet pushen.
