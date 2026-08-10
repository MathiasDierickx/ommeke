# T21 — Mobiele screenshots via Playwright (CI-artefact)

## Waarom

De browser-emulatie in de reviewsessie kan het venster niet naar
smartphone-formaat krimpen, dus mobiele screenshots ontbreken. Een klein
Playwright-script rendert de webapp op 390×844 en levert PNG's op — lokaal én
als CI-artefact — zodat de mobiele look zichtbaar wordt zonder toestel.

## Opzet

- Map `web/e2e/` (of `web/screenshots/`) met een Playwright-script
  `mobile-shots.mjs` dat:
  - de gedeployde app opent (`SHOTS_BASE_URL`, default
    `https://ommeke.vercel.app`);
  - een reviewer-sessie in `sessionStorage['lusmaker.auth']` injecteert vóór
    load — de tokens komen uit env `SHOTS_ACCESS_TOKEN` / `SHOTS_ID_TOKEN`
    (NIET hardcoden; de reviewer levert ze). Zonder tokens: draai enkel het
    login/welkomstscherm-shot en sla de ingelogde shots over met een nette
    melding.
  - device-emulatie iPhone 13 (390×844, dpr 3, touch) via
    `playwright.devices['iPhone 13']`.
  - screenshots maakt van: (1) welkomst/chat, (2) een routedetail met kaart
    (navigeer naar een bekende route-id uit env `SHOTS_ROUTE_ID`, of maak er
    geen aanname over en shot de "Mijn routes"-lijst), (3) de open
    hamburger-drawer (klik `.mobile-menu`).
  - PNG's schrijft naar `web/e2e/shots/*.png`.
- `web/package.json`: script `"shots": "node e2e/mobile-shots.mjs"` en
  `@playwright/test` (of `playwright`) als devDependency.
- Korte README in `web/e2e/README.md`: hoe lokaal draaien
  (`SHOTS_ACCESS_TOKEN=… npm run shots`) en dat `npx playwright install
  chromium` eenmalig nodig is.

## CI (optioneel, licht)

- Voeg een workflow-stap-suggestie toe in `web/e2e/README.md` (NIET de
  bestaande workflows aanpassen — die zijn van het infra-spoor): een job die
  na de Vercel-deploy `npm run shots` draait met secrets en de PNG's als
  artefact uploadt. Alleen documenteren.

## Robuustheid

- Netwerk-/tijdslimieten ruim (kaarttiles laden traag): `waitForSelector`
  op `.leaflet-tile-loaded` met timeout, en een extra `waitForTimeout` voor
  de polyline-render.
- Script mag niet crashen zonder tokens of zonder route — nette skips +
  exitcode 0 tenzij een echte fout.

## DoD

- `npm run shots` draait lokaal (met tokens) en produceert de PNG's.
- Geen wijziging aan bestaande workflows of backend. Alleen `web/`.
- Kleine commits; niet pushen (de reviewer draait het en levert de shots).
