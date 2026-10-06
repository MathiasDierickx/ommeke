# Contractmatrix per interface

Eén routemotor (`lusmaker/intents.py`, `lusmaker/reroute.py`) wordt via vier
interfaces aangeboden: de **CLI** (`lusmaker/cli.py`), de **MCP-tools**
(`lusmaker/mcp_server.py` + `mcp_contracts.py`), de **chattools** van de
Bedrock-agent (`lusmaker/aws_chat.py` + `chat_contracts.py`) en de **web-API**
(`lusmaker/aws_api.py`, `quick_plan.py`). Dit document legt per operatie vast
welke parameters elke interface aanbiedt, wat de defaults zijn en welke fouten en
idempotentieregels gelden.

`tests/test_contract_matrix.py` leest de tabellen hieronder en faalt wanneer een
hier genoemde parameternaam (tussen backticks) niet meer in de code-schema's of
signaturen voorkomt. Een `—` betekent: bewust niet aangeboden op die interface.
Werk de tabel dus bij wanneer je een parameter toevoegt, hernoemt of schrapt.

Kolommen: CLI = vlagnaam in `cli.py`, MCP = parameter van de toolfunctie, Chat =
eigenschap van het JSON-schema dat het model te zien krijgt, Web = sleutel in de
JSON-body.

## plan_route

CLI: `lus plan-route`. MCP/chat: `plan_route`. Web: `POST /api/routes` en
`POST /api/routes/stream` (modelvrij formulier, `quick_plan.py`).

| Parameter | CLI | MCP | Chat | Web | Default en opmerking |
|---|---|---|---|---|---|
| start | `--start` | `start` | `start` | `start` | Verplicht. Web accepteert ook `{lat, lon}`. |
| region | `--region` | `region` | — | — | Standaard de actieve/default-regio. |
| max_km | `--max-km` | `max_km` | `max_km` | — | Harde bovengrens. |
| target_km | `--target-km` | `target_km` | `target_km` | `target_km` | Web: verplicht, 1 tot 300 km. |
| tolerance_km | `--tolerance-km` | `tolerance_km` | `tolerance_km` | — | 2,5. Web: vast `min(2,5; 10% van target_km)`. |
| doel | `--doel` | `doel` | `doel` | `doel` | `toeren`; keuze uit hoogtemeters, offroad, kort, toeren. |
| via_klimmen | `--via-klim` | `via_klimmen` | `via_klimmen` | — | Max. 12 in chat. |
| vermijd_plaatsen | `--vermijd-plaats` | `vermijd_plaatsen` | `vermijd_plaatsen` | — | Max. 12 in chat. |
| kasseien | `--kasseien` | `kasseien` | `kasseien` | — | `null` = onbekend (niet `false`). CLI heeft ook `--vermijd-kasseien`. Web: vast `null`. |
| beton_vermijden | `--vermijd-beton` | `beton_vermijden` | `beton_vermijden` | — | `null` = onbekend. CLI heeft ook `--beton-toestaan`. |
| autovrij | `--autovrij` | `autovrij` | `autovrij` | — | `null` = onbekend. |
| strict | `--strict` | `strict` | `strict` | — | `null` = onbekend. |
| naam | `--naam` | `naam` | `naam` | — | 1 tot 80 tekens; zonder naam volgt een afgeleide titel. |
| activiteit | `--activiteit` | `activiteit` | `activiteit` | `activiteit` | `toerfiets`; `fietsen` is de oude naam van toerfiets. |
| geen_opvulling | `--geen-opvulling` | `geen_opvulling` | `geen_opvulling` | — | `false`. |
| profiel_naam | `--profiel-naam` | `profiel_naam` | — | — | MCP `standaard`; CLI standaard leeg; chat en web gebruiken vast `standaard`. |
| request_id | `--request-id` | `request_id` | — | `request_id` | Zie idempotentie. Chat: impliciet per toolaanroep. Web: verplicht. |
| rond_plaats | `--rond-plaats` | `rond_plaats` | `rond_plaats` | — | Lus rond een plaats (landmark). |
| langs_water | `--langs-water` | `langs_water` | `langs_water` | — | Waterloop of water langs de route. |
| heuvels | `--heuvels` | `heuvels` | `heuvels` | — | `null` = onbekend (vlag weglaten); zoek, ok of vlak. |
| ondergrond | `--ondergrond` | `ondergrond` | `ondergrond` | — | `null` = onbekend (vlag weglaten); verhard, ok of onverhard. |
| stop_onderweg | `--stop-onderweg` | `stop_onderweg` | `stop_onderweg` | — | Optioneel object met soort (cafe, water, bakker, toilet, fietsenmaker) en rond_km ≥ 0. CLI: JSON. Dichtst bij gevraagde routeafstand, binnen 150 m; herroutering bewaakt doel/tolerantie en hard maximum, anders waarschuwing en oorspronkelijke route. |
| check_readiness | `--check-readiness` | — | — | — | CLI: standaard uit. MCP, chat en web sturen altijd `true`. |

Bewuste verschillen:

- `check_readiness`: MCP, chat en web sturen altijd `true` (vragen via
  `needs_input`); de CLI laat het standaard uit en gebruikt `readiness` als
  aparte stap, of zet het aan met `--check-readiness`.
- Het webformulier toont enkel een beperkte set; alle andere wensen lopen via
  de chat.
- Een `null`-voorkeur is onbekend, `ok` is expliciet onverschillig. Geef geen
  `false` door voor een onbekende keuze.

## adjust_route

CLI: `lus adjust-route <id>`. MCP/chat: `adjust_route`. Web:
`POST /api/routes/{draft_id}/adjust`.

| Parameter | CLI | MCP | Chat | Web | Default en opmerking |
|---|---|---|---|---|---|
| draft_id | `id` | `draft_id` | `draft_id` | `draft_id` | Verplicht. Web: padparameter. |
| voeg_klimmen_toe | `--voeg-klim-toe` | `voeg_klimmen_toe` | `voeg_klimmen_toe` | `voeg_klimmen_toe` | Lijst. |
| verwijder_klimmen | `--verwijder-klim` | `verwijder_klimmen` | `verwijder_klimmen` | `verwijder_klimmen` | Lijst. |
| vermijd_plaatsen | `--vermijd-plaats` | `vermijd_plaatsen` | `vermijd_plaatsen` | `vermijd_plaatsen` | Lijst. |
| niet_meer_vermijden | `--niet-meer-vermijden` | `niet_meer_vermijden` | `niet_meer_vermijden` | — | Lijst. |
| sta_plaatsen_toe | `--sta-plaats-toe` | `sta_plaatsen_toe` | `sta_plaatsen_toe` | `sta_plaatsen_toe` | Passage die expliciet oké is. Lijst, max. 12 in chat. |
| max_km | `--max-km` | `max_km` | `max_km` | — | Web: afgeleid, `target_km + 3`. |
| target_km | `--target-km` | `target_km` | `target_km` | `target_km` | Web: getal. |
| tolerance_km | `--tolerance-km` | `tolerance_km` | `tolerance_km` | — | Leeg = bestaande waarde. |
| doel | `--doel` | `doel` | `doel` | `doel` | Leeg = bestaande waarde. Web gebruikt `hm` voor hoogtemeters. |
| geen_opvulling | `--geen-opvulling` | `geen_opvulling` | `geen_opvulling` | — | Leeg = bestaande waarde. |
| profiel_naam | `--profiel-naam` | `profiel_naam` | `profiel_naam` | — | Leeg = profiel van de draft. |
| expected_revision | `--expected-revision` | `expected_revision` | `expected_revision` | `expected_revision` | Zie revisies. Web: geheel getal. |
| rond_plaats | `--rond-plaats` | `rond_plaats` | `rond_plaats` | `rond_plaats` | |
| langs_water | `--langs-water` | `langs_water` | `langs_water` | `langs_water` | |
| request_id | — | `request_id` | — | `request_id` | Optioneel; zie idempotentie. Chat: impliciet per toolaanroep (hash van beurt en argumenten). Web: scope `adjust:{draft_id}`. De CLI geeft geen request-id door. |

Bewuste verschillen:

- `adjust_route` is idempotent via de revisie (`expected_revision`) en, wanneer
  een `request_id` meekomt, ook via een receipt (zie idempotentie).
- Web gebruikt `check_readiness=false` (een UI-bewerking stelt geen vragen);
  MCP en chat gebruiken `true`.
- Web stelt `max_km` altijd ruim in zodat een nieuwe `target_km` niet botst met
  een strakke bovengrens uit de oorspronkelijke vraag.

## apply_answers

Antwoorden op situationele vragen (`needs_input`) toepassen zonder taalmodel en
opnieuw routeren. Enkel beschikbaar via de web-API
(`POST /api/routes/{draft_id}/answers` en `.../answers/stream`) en de motor
(`intents.apply_answers`). Chat doet hetzelfde via `update_profile` plus
`adjust_route`; de CLI en MCP bieden het niet aan.

| Parameter | CLI | MCP | Chat | Web | Default en opmerking |
|---|---|---|---|---|---|
| draft_id | — | — | — | `draft_id` | Padparameter. |
| antwoorden | — | — | — | `antwoorden` | Verplicht, niet leeg. Sleutels `kasseien` (graag, ok, vermijd), `heuvels` (zoek, ok, vlak), `ondergrond` (verhard, ok, onverhard). Antwoorden gelden voor deze rit, niet voor het profiel. |
| request_id | — | — | — | `request_id` | Verplicht in de web-API (receipt, scope `answers`). |

De motor kent ook `expected_revision`; de web-endpoint geeft die niet door.

## reroute_from

Terugweg vanaf de huidige positie binnen een resterend budget. CLI:
`lus reroute-from`. MCP/chat: `reroute_from`. Web:
`POST /api/routes/{draft_id}/reroute`.

| Parameter | CLI | MCP | Chat | Web | Default en opmerking |
|---|---|---|---|---|---|
| draft_id | `draft_id` | `draft_id` | `draft_id` | `draft_id` | Verplicht. Web: padparameter. |
| lat | `lat` | `lat` | `lat` | `lat` | Verplicht, -90 tot 90. |
| lon | `lon` | `lon` | `lon` | `lon` | Verplicht, -180 tot 180. |
| rest_km | `--rest-km` | `rest_km` | `rest_km` | `rest_km` | `kortste`; anders een getal tussen 0 en 300 (hard budget). |
| expected_revision | `--expected-revision` | `expected_revision` | `expected_revision` | `expected_revision` | Zie revisies. |
| closure | — | `closure` | `closure` | `closure` | `{lat, lon}` van een afgesloten punt. |
| request_id | — | `request_id` | — | `request_id` | Chat: impliciet. Web: verplicht. De CLI geeft geen request-id door. |

De locatie moet binnen 2 km van de route liggen, anders volgt een `bad_request`.
Web: een revisieconflict geeft 409 `route_conflict`, een locatie buiten de
dekking 422 `buiten_gebied`.

## update_profile

Persistent voorkeurenprofiel bijwerken (`profiles.apply_patch`). CLI:
`lus profile set`. MCP/chat: `update_profile`. De web-API heeft geen
profielendpoint; de webapp past voorkeuren per rit toe via `apply_answers`.

| Parameter | CLI | MCP | Chat | Web | Default en opmerking |
|---|---|---|---|---|---|
| naam | `naam` | `naam` | `naam` | — | Verplicht; MCP `standaard` bij `get_profile`. |
| patch | — | `patch` | `patch` | — | Getypeerde patch met `activiteit`, `gewichten`, `voorkeuren`. MCP valideert strikt (`extra=forbid`), chat enkel als object. |
| --activiteit | `--activiteit` | — | — | — | CLI-vlag voor `patch.activiteit`. |
| --gewichten | `--gewichten` | — | — | — | CLI-vlag voor `patch.gewichten` (bv. `hoogtemeters=0.5,offroad=0.5`). |
| --kasseien | `--kasseien` | — | — | — | CLI-vlag voor `patch.voorkeuren.kasseien`. |
| --beton | `--beton` | — | — | — | CLI-vlag voor `patch.voorkeuren.beton`. |
| --steenwegen | `--steenwegen` | — | — | — | CLI-vlag voor `patch.voorkeuren.steenwegen`. |
| --autovrij | `--autovrij` | — | — | — | CLI-vlag voor `patch.voorkeuren.autovrij`. |
| --vermijd-plaats | `--vermijd-plaats` | — | — | — | CLI-vlag voor `patch.voorkeuren.vermijd_plaatsen`. |

Er is geen `request_id` of `expected_revision`: een profielpatch is een
last-write-wins samenvoeging met historiek (`bron` = cli, mcp of chat). Een
gekoppelde verkenningsprobe wordt automatisch ongeldig.

## Exportselectie

`GET /api/routes/{draft_id}/gpx` en `/fit` accepteren de queryparameter
`poi=cafe,water` (kommagescheiden bekende types) of `poi=geen`.
Zonder parameter blijft de bestaande export met alle voorzieningen behouden.
Bekende soorten komen uit `route_pois.EXPORT_KINDS`: de vijf stopsoorten en
logiescategorieën uit de lokale Toerisme Vlaanderen-bron.
Onbekende of lege selecties geven HTTP 400 met `code: invalid_poi`.
Klimwaypoints en navigatie-instructies blijven behouden. De kaart geeft haar
actuele selectie mee; “Alle” laat de parameter weg en “Verbergen” stuurt `geen`.
Beide antwoorden behouden `Cache-Control: private, no-store`.

GPX filtert de voorzieningswaypoints in het opgeslagen S3-artefact bij het
serveren. Dit vermijdt een nieuwe lokale data-/klimdatabase-afhankelijkheid en
behoudt dezelfde geëxporteerde route. FIT wordt zoals voorheen gegenereerd,
met de selectie toegepast vóór de course-pointlimiet.

## Foutcodes

CLI en MCP geven JSON zonder HTTP-status; de web-API geeft `{"error", "code"}`
met de status hieronder. Chat geeft de foutpayload als `toolResult` met
`status: error` terug aan het model, waarna het model de gebruiker uitlegt wat
er misging.

| Code | HTTP | Wanneer | Waar |
|---|---|---|---|
| `buiten_gebied` | 422 | Start, anker of via-punt ligt buiten de gemeten dekking van de pack. Payload bevat `error`, `code`, `dekking` en optioneel `punt`. | Alle interfaces: CLI/chat/web als payload, MCP als JSON-tekst in de toolfout. |
| `quota_exceeded` | 429 | Daglimiet voor chat, routes, tokens, feedback of regio's bereikt. Header `Retry-After` in seconden. | Web (route_plan, route_adjust, answers, reroute, chat); in MCP/CLI enkel wanneer quota's aan staan. |
| `request_conflict` | 409 | Dezelfde `request_id` is al gebruikt voor een andere opdracht, of het eerdere verzoek is nog bezig of onderbroken. | Web: plan, adjust, answers, reroute, chat. |
| `route_conflict` | 409 | `expected_revision` komt niet overeen met de huidige draft (of de draft is gewijzigd). | Web: adjust, reroute en `PATCH /api/routes/{draft_id}`. |
| `route_not_found` | 404 | Onbekende `draft_id`. | Web. |
| `chat_failed` | 422 | De chatagent kon het bericht niet afronden. | Web. |
| `model_unavailable` | 502 | Bedrock niet beschikbaar of niet geactiveerd. | Web. |
| `invalid_poi` | 400 | Onbekend of leeg POI-type bij GPX/FIT-download. | Web. |
| `bad_request` | 400 | Ongeldige of onbekende invoer, onbekende waarden, schemafout. | Web (standaardcode). |

In de motor zijn dit `coverage.OutOfCoverage`, `quotas.QuotaExceeded`,
`requests.RequestConflict`, `draft.DraftError` (revisieconflict) en
`intents.IntentError` (ongeldige invoer, of een `request_id` hergebruikt voor
een andere routewens).

## Revisies en idempotentie

Er zijn twee onafhankelijke mechanismen.

**Revisie (`expected_revision`)** beschermt tegen verouderde schrijfacties op
een bestaande draft. Elke opgeslagen draft heeft een monotone `revision`; ieder
toolresultaat meldt de laatste. Geef bij een vervolgwijziging de laatst
ontvangen revisie mee. Komt die niet overeen, dan wijst `draft.require_revision`
de mutatie af zonder iets te wijzigen. Beschikbaar op `adjust_route`,
`apply_answers` (enkel de motor) en `reroute_from`. Zonder waarde wordt niet
gecontroleerd.

**Verzoeknummer (`request_id`)** laat een retry dezelfde workflow hervatten:

- `plan_route` (motor): een `request_id` zoekt een bestaande draft; dezelfde
  routewens hervat die draft, een andere routewens geeft een `IntentError`.
  Formaat motor: begint met letter of cijfer, daarna letters, cijfers, `.`, `_`,
  `:` of `-`, max. 128 tekens. De MCP-tools (`plan_route`, `adjust_route`,
  `reroute_from`) hanteren het strengere receiptformaat hieronder, zodat een
  ongeldig id meteen met een duidelijke schemafout faalt.
- Receipts (`requests.once`): web-plan (scope `quick-plan`), `answers`,
  `reroute`, `adjust` (scope `adjust:{draft_id}`, ook in de motor voor MCP en chat) en chatberichten (scope `chat:{conversation_id}`) schrijven een
  persistent receipt in S3. Formaat: 8 tot 128 tekens `[A-Za-z0-9_-]`. Zelfde id
  met dezelfde invoer geeft het opgeslagen resultaat terug; zelfde id met
  andere invoer geeft `request_conflict`.
- Een receipt dat `running` of `interrupted` blijft wordt **nooit automatisch
  opnieuw uitgevoerd** (de side effects kunnen al bestaan). Na 960 s geldt een
  `running` receipt als onderbroken (Lambda: maximaal 900 s plus drainmarge).
  Status: `GET /api/conversations/{id}/requests/{request_id}`. De client vraagt
  dan met een nieuw verzoeknummer opnieuw.
- Lokaal (zonder S3-state) vallen receipts weg en blijft enkel de
  draft-idempotentie van `plan_route` over.
- `update_profile` heeft geen verzoeknummer; `adjust_route` en `reroute_from`
  hebben er een op MCP, chat (impliciet) en web, niet op de CLI. Bij web-adjust
  is `request_id` optioneel en telt `max_km` (afgeleid van de huidige lengte)
  niet mee in de vergelijking.
