# T22 — Hoogteprofiel in de bottom-sheet + UI-polish

De backend levert nu per route `geometry.elevation`: een lijst
`[{km, ele}, ...]` (cumulatieve afstand in km, hoogte in m). Toon dit als
grafiek en fix twee kleine UI-punten die live opvielen.

## 1. Hoogteprofiel-sparkline (route-detail bottom-sheet)

- In `web/components/route-detail.tsx` (of waar de bottom-sheet-stats staan):
  render onder het stat-grid een compacte **inline-SVG area/line-chart** uit
  `geometry.elevation` — zoals AllTrails/komoot.
  - x = km (0..max), y = hoogte (min..max), gevulde area onder de lijn in de
    merkkleur met lage opacity + een lijn erbovenop.
  - toon min/max-hoogte als kleine labels; hoogte-as niet op 0 forceren
    (gebruik het werkelijke min..max-bereik zodat glooiing zichtbaar is).
  - `viewBox` + `preserveAspectRatio="none"`, responsive breedte (100%),
    hoogte ~64px. Werkt in beide thema's.
  - Leeg/ontbrekend `elevation` (vlakke route zonder DEM) → toon niets
    (geen lege grafiek), de stat "Hoogtemeters" blijft staan.
- Breid het `RouteGeometry`-type in `web/lib/types.ts` uit met
  `elevation?: { km: number; ele: number }[]`.

## 2. Kaarttiles betrouwbaarder laden

- De Leaflet-kaart toont soms kort grijze tiles. Voeg een korte
  `map.whenReady`/`invalidateSize()`-aanroep toe na mount en na het tonen van
  de bottom-sheet (layout-shift), zodat tiles direct de juiste grootte
  krijgen. Optioneel een tweede OSM-tileserver-subdomein voor snelheid
  (blijf bij openstreetmap.org-tiles; attributie behouden).

## 3. Zijbalk opschonen

- De gesprekkenlijst kan lang worden. Toon in de zijbalk max ~15 recente
  gesprekken met een subtiele scroll; niets verwijderen. (Kosmetisch —
  alleen CSS/slice in de sidebar-render.)

## Niet doen

- Geen backend-wijzigingen (elevation zit al in de API). Geen auth/kaart-
  architectuur omgooien (Leaflet + rastertiles blijft).

## DoD

- `npm run typecheck` + `npm run build` slagen.
- Andere agent kan actief zijn: commit alleen `web/`. Klein committen; niet
  pushen (reviewer deployt + test in Chrome, incl. `npm run shots` voor mobiel).
