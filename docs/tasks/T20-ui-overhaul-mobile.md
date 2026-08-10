# T20 — UI/UX-overhaul + mobile-first (app-achtig)

De webapp (`web/`, Next.js + React, één component `components/lusmaker-app.tsx`
van ~668 regels, styling in `app/globals.css`) moet er als een verzorgde,
mobiel-eerste route-app uitzien. Deps nu: next, react, lucide-react. De backend
levert sinds kort per route een `geometry`-veld (zie hieronder).

## Designrichting (referenties: komoot, AllTrails, ChatGPT/Copilot)

- **Routedetail = fullscreen kaart + zwevende bottom-sheet** (komoot/AllTrails):
  de kaart vult het paneel; een kaartje "zweeft" onderaan met routenaam,
  activiteit-pill, een **stat-grid** (Afstand · Hoogtemeters · Klimmen), een
  **hoogteprofiel-sparkline**, kwaliteitschips (0 m kassei · X% offroad ·
  Y% populair), en een prominente **Download GPX**-knop.
- **Chat** (Copilot/ChatGPT): grote begroeting, starters als **pill-chips**,
  een **ronde input-pill** met verzendknop; berichten in nette bubbels;
  readiness-vragen als tikbare optie-chips (niet enkel tekst).
- Behoud de bestaande huisstijl (donkergroen/cream, serif-koppen) — die is goed;
  maak ze consistenter en luchtiger.

## 1. Native kaart (vervangt de gesandboxte iframe — die rendert blanco)

- Voeg **Leaflet** toe (`leaflet` + types) en render de kaart in React op basis
  van het nieuwe `route.geometry` uit `/api/routes/{id}`:
  `{ points: [[lat,lon],...], climbs: [{lat,lon,id}], start: {lat,lon,label} }`.
  OSM-rastertiles (`https://tile.openstreetmap.org/{z}/{x}/{y}.png`,
  attributie verplicht) — CSP-vriendelijk, zelfde bron als de serverpreview.
- Polyline in de merkkleur, start-marker, klim-markers; `fitBounds` op de route.
- Verwijder het `preview_url`-iframe-pad uit de UI (laat het API-endpoint staan;
  het is niet meer nodig in de webapp). Laadstatus en lege staat behouden.
- Hoogteprofiel: kleine inline-SVG-sparkline uit de ele-waarden (de geometry
  bevat enkel lat/lon; als er geen hoogte is, toon dan de stat maar geen grafiek
  — of vraag optioneel een `elevation`-array toe te voegen aan geometry als dat
  eenvoudig kan; niet blokkerend).

## 2. Mobile-first / app-achtig

- Alles bouwen vanaf **390×844 (iPhone)** en opschalen naar desktop met CSS.
- Mobiel: de zijbalk wordt een **hamburger-drawer** (bestaat deels: het
  menu-icoon); de routedetail-sheet is een echte **bottom-sheet** die je omhoog
  kunt slepen (of minstens scrollbaar met een grote greep). Chat-input plakt
  onderaan boven een veilige-zone-padding (`env(safe-area-inset-bottom)`).
- Touch-targets ≥ 44px; geen hover-only-acties.
- Desktop: twee kolommen (gesprek + kaart/detail) zoals nu, maar de kaart
  krijgt meer ademruimte en het detail zweeft eroverheen i.p.v. links-onder.
- **PWA**: voeg `app/manifest.ts` (of `public/manifest.webmanifest`) +
  apple-touch-icon + theme-color toe zodat "toevoegen aan beginscherm" een
  app-icoon en standalone-modus geeft. Naam "Lusmaker" / "Ommeke".

## 3. Kwaliteit & consistentie

- Refactor `lusmaker-app.tsx` in kleinere componenten (Chat, RouteDetail, Map,
  Sidebar, StatGrid) — mag in `web/components/`. Houd de datalaag (`lib/api.ts`,
  `lib/auth.ts`, types) intact; breid het `Route`-type uit met `geometry`.
- Nette lege/lade/foutstaten. Nederlandstalig. Geen dode `preview_url`-code.
- `npm run typecheck` en `npm run build` moeten slagen.

## Niet doen

- Geen backend-wijzigingen (de API levert al `geometry`, `elevation_gain_m`,
  `download_url`). Geen auth-flow aanraken.
- Geen zware map-libraries (MapLibre/vector tiles) — Leaflet + rastertiles is
  bewust de keuze (CSP, eenvoud, betrouwbaarheid).

## Let op

- Er kan een andere agent in de repo werken: raak niet-gecommitte wijzigingen
  van anderen niet aan; commit alleen je eigen bestanden onder `web/`.
- Vroeg en klein committen; niet pushen (de reviewer deployt en test in Chrome,
  desktop én smartphone-emulatie).
