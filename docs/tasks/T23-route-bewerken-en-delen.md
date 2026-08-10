# T23 — Route bewerken vanuit de UI + deelbare read-only link

Twee features op de werkende (Nova) app. Belangrijk ontwerpprincipe voor
feature 1: de bewerkacties roepen `intents.adjust_route` RECHTSTREEKS aan via
een eigen API-endpoint — géén Bedrock/model in de lus. Dat is instant,
deterministisch en omzeilt Nova's tool-use-wispelturigheid.

## Backend (`lusmaker/aws_api.py` + routes in `aws_app.py`)

### 1a. Route bijstellen — `POST /api/routes/{draft_id}/adjust`

- Auth zoals de andere `/api/routes`-routes (tenant = Cognito sub).
- Body (alle optioneel): `{ "target_km": number, "voeg_klimmen_toe": [id],
  "verwijder_klimmen": [id], "vermijd_plaatsen": [naam],
  "sta_plaatsen_toe": [naam], "doel": "hm|offroad|toeren|kort",
  "expected_revision": int }`.
- Roept `intents.adjust_route(draft_id, ..., check_readiness=False,
  expected_revision=...)` aan in een thread (`asyncio.to_thread`), met
  `tenant.current()` actief. `check_readiness=False` zodat er GEEN vraag
  terugkomt — de UI stuurt expliciete parameters, geen gesprek.
- Retour: hetzelfde compacte route-object als `route_detail` (herbruik
  `_route_item` + `_route_geometry` op de herladen draft), plus de nieuwe
  `revision`. Fouten → nette 400/404/409 (revision-conflict) JSON.
- Klim-ids voor de UI: voeg `GET /api/routes/{id}/climbs-near?radius_km=15`
  toe dat `climbs.all_climbs()` in de regio rond de route teruggeeft
  (id, naam, km, hm) zodat de UI een keuzelijst kan tonen. Klein en read-only.

### 1b. Deelbare link — publieke read-only route

- `POST /api/routes/{draft_id}/share` (auth): genereert een onraadbaar
  share-token (secrets.token_urlsafe), slaat het op de draft op
  (`share_token`) en retourneert `{ "token": ..., "url":
  "<PUBLIC>/s/<token>" }`. Idempotent: bestaat er al een token, geef dat.
- `DELETE /api/routes/{draft_id}/share` (auth): verwijdert het token
  (stopt delen).
- `GET /api/shared/{token}` — **GEEN auth** (CognitoAuthMiddleware moet dit
  pad doorlaten, net als /health en de well-known): zoekt de draft met dat
  token en geeft een read-only payload terug: naam, activiteit, total_km,
  ascend, `geometry`, kwaliteit — GEEN persoonsgegevens, GEEN start-adres-
  label fijner dan de plaatsnaam. De opzoek-op-token mag niet tenant-
  gescoped falen: sla een index op of scan binnen de gebruiker is niet
  mogelijk zonder tenant — kies de eenvoudigste betrouwbare opslag (bv. een
  apart item `SHARE#<token> -> {uid, draft_id}` in dezelfde tabel, buiten de
  tenant-partitie, met alleen de verwijzing; de GET laadt dan de draft in de
  juiste tenant-context). Documenteer de keuze.
- De CognitoAuthMiddleware in `aws_app.py`: voeg `/api/shared/` en `/s/` toe
  aan de publieke-paden-allowlist.

## Frontend (`web/`)

### Route bewerken (in de bottom-sheet / route-detail)

- Een compacte **"Aanpassen"-sectie** onder de acties met:
  - afstand: knoppen "−5 km / +5 km" (stuurt `target_km` = huidige ± 5) of een
    klein invoerveld;
  - doel-chips: Klimmen / Offroad / Toeren / Kort (stuurt `doel`);
  - "Klim toevoegen": opent de lijst uit `climbs-near`, tik = `voeg_klimmen_toe`;
  - "Plaats vermijden": vrij invoerveld → `vermijd_plaatsen`.
- Elke actie POST't naar `/adjust`, toont een laadstatus, en vervangt de route
  (kaart + stats + profiel) met het antwoord. Gebruik `expected_revision` en
  behandel 409 met een nette "de route is intussen gewijzigd"-melding +
  refetch.

### Delen

- Een **"Deel"-knop** in de route-detail: POST `/share`, toon de URL met een
  kopieer-knop (en, indien beschikbaar, `navigator.share`).
- Publieke pagina `web/app/s/[token]/page.tsx`: haalt `/api/shared/{token}`
  (zonder auth) en toont een **read-only** routedetail — dezelfde kaart +
  stat-grid + hoogteprofiel, maar zonder bewerk-/download-privé-acties. Wel
  een "Maak je eigen route"-CTA naar de hoofdapp. Mobielvriendelijk.

## Tests

- Pure tests voor de nieuwe intents-doorgifte waar zinvol; de meeste logica
  zit al in intents.adjust_route (bestaande tests). Voeg tests toe voor de
  share-token-opslag/opzoek-helper (pure functie met geïnjecteerde store) en
  voor de publieke-payload-samenstelling (geen PII-lekken).
- `web`: `npm run typecheck` + `npm run build` slagen.
- Cassettes en bestaande suite blijven groen.

## Let op

- Andere agent kan actief zijn: raak vreemde niet-gecommitte wijzigingen niet
  aan. Backend en web mogen in dezelfde taak, maar commit logisch gescheiden.
- Vroeg en klein committen; niet pushen (reviewer deployt + test in Chrome,
  desktop + `npm run shots` mobiel).
