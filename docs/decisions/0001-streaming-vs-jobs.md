# 0001 - Routegeneratie: SSE met receipts of een pollbare job

- Status: aangenomen (voorlopig, herzien bij de triggers hieronder)
- Datum: 6 oktober 2026
- Issue: #12 (wachtflow), raakt #19 (latentie)

## Context

Een routevraag duurt van enkele seconden tot meer dan een minuut. De backend
doet meerdere GraphHopper-rondes (optimize, readiness-probe, finale routering)
en in de chat ook meerdere modelrondes. De Lambda heeft een time-out van 15
minuten (900 s) en draait achter een Function URL met response streaming, dus
zonder API Gateway-limiet (`docs/AWS.md`).

Er waren twee opties voor de wachtflow:

1. **Streaming**: de client houdt één verbinding open (SSE) en ontvangt
   voortgang en resultaat. Herstel na een onderbreking loopt via persistente
   request-receipts.
2. **Pollbare job**: `POST` start een achtergrondjob (queue of asynchrone Lambda
   plus jobstatus in S3/DynamoDB), de client pollt `GET /jobs/{id}`.

## Gemeten gegevens

Alles hieronder komt uit de repo en de issuecommentaren (2 en 5 oktober 2026);
het zijn losse metingen, geen systematische percentielen.

| Meting | Waarde | Bron |
|---|---|---|
| Koude API, routedetail | 3,5 s, was 19 s | commit `5f36761`, `docs/STATUS.md` |
| GraphHopper-aanroep | mediaan ca. 1,7 s | #12-update |
| Korte wandeling (ca. 5 km) | koud ca. 75 s, warm 20 tot 45 s | #12-update |
| Chatroute 20 km (Wetteren) | 61,7 s (`/messages/stream`) | `docs/ACCEPTANCE.md` |
| Snelplanner 40 km | slaagde met 39,3 km; geen aparte tijd vastgelegd | `docs/ACCEPTANCE.md` |
| Lambda-limiet | 900 s; receipt `running` geldt na 960 s als onderbroken | `lusmaker/requests.py`, `docs/OPERATIONS.md` |
| Lambda-OOM | opgelost met MMAP in GraphHopper | `docs/STATUS.md` (#19) |

Wat nog ontbreekt: een systematische p50/p95 per operatie over echt verkeer.
Het alarm `*-slow-requests` staat op p95 boven 4 minuten en is nog nooit
afgegaan (er is nog geen pilotverkeer om dat te bewijzen).

## Wat al gebouwd is

- SSE rond bestaande JSON-handlers (`lusmaker/streaming.py`) met
  `progress`-, `result`- en `error`-events en een heartbeat elke 10 s.
  Live sinds begin oktober; een eerste race tussen POST-body en
  disconnect-listener is opgelost (`171fdd8`).
- Echte fasen, ook een eigen stap `router_start` bij een koude GraphHopper
  (`d1b9bc9`).
- Persistente receipts (`lusmaker/requests.py`): dezelfde `request_id` met
  dezelfde invoer geeft het opgeslagen resultaat terug; een onderbroken of
  lopend verzoek wordt nooit automatisch opnieuw uitgevoerd.
  `GET /api/conversations/{id}/requests/{request_id}` laat de client de status
  opvragen.
- Een verbroken browserverbinding annuleert de operatie niet; die rondt haar
  receipt af (`streaming.py`). Er ontstaat dus geen tweede uitvoering.
- Herstel in de UI: na herladen toont een onbeantwoorde vraag of ze nog loopt
  (polling) of afgebroken is, met "Vraag opnieuw stellen" onder een nieuw
  verzoeknummer (`a9052ad`).

## Beslissing

**Behoud SSE met receipts.** Bouw voorlopig geen pollbare job.

Redenen:

- De gemeten duur (typisch 20 tot 75 s, chat ca. 60 s) ligt ver onder de
  Lambda-limiet van 900 s en ruim binnen wat een open verbinding verdraagt.
- De herstelkant is al gedekt: receipts vermijden dubbele routes en berichten
  bij refresh, retry en dubbele submit, en de gebruiker krijgt een duidelijke
  herstelactie.
- Een job-architectuur vraagt een tweede uitvoeringspad (queue of
  zelf-aanroepende Lambda, jobstatus, annulering, opruimen), extra IAM en een
  nieuwe foutklasse (job verloren). Dat is onevenredig voor een pilot met
  enkele gebruikers, en het sluit niet aan bij de "scale to zero"-keuze.
- De latentiewinst zit in het GraphHopper-pad (#19), niet in het transport. Een
  job maakt de berekening niet sneller.
- De receiptlaag is transport-onafhankelijk: een jobendpoint kan later dezelfde
  `requests.once` hergebruiken. Deze keuze sluit de job dus niet uit.

Gevolgen en bekende beperkingen:

- Een mobiele browser die naar de achtergrond gaat kan de stream laten vallen
  terwijl de Lambda doorloopt. Het resultaat is dan via het receipt op te
  halen, maar de gebruiker moet de pagina heropenen.
- Een echte Lambda-time-out of afgebroken Lambda is nog niet live bewezen
  (open punt in #12).
- De drempel van de alarmen is nog niet op een baseline afgesteld.

## Triggers om te herzien

Herzie dit besluit (en overweeg een pollbare job) zodra een van deze voorwaarden
in de pilot optreedt. De getallen zijn startwaarden; stel ze bij na de eerste
twee weken baseline.

1. **Latentie**: p95 van de snelplanner (`POST /api/routes/stream`) boven
   120 s, of p95 van een chatbeurt boven 180 s, over minstens 50 verzoeken. Bij
   p95 boven 4 minuten vuurt `*-slow-requests` al.
2. **Lambda-time-outs**: meer dan 1 procent van de route- en chatverzoeken
   eindigt door de 900 s-limiet, of een enkel verzoek komt boven 600 s.
3. **Onderbrekingen**: meer dan 2 procent van de receipts eindigt als
   `interrupted`, of gebruikers melden herhaaldelijk een verloren resultaat na
   het sluiten of verbergen van de tab.
4. **Mobiele achtergrondtabs**: de pilot toont dat een merkbaar deel van de
   gebruikers de app tijdens het wachten verlaat (bijvoorbeeld meer dan 10
   procent van de streams zonder `result`-event terwijl het receipt `complete`
   wordt).
5. **Nieuwe workloads**: optimalisaties of regio-provisioning die structureel
   langer dan 5 minuten duren, of een warme GraphHopper-service (#19) die de
   vraag naar verbindingen verhoogt.

## Meting die de herziening voedt

Beschikbaar in `lusmaker/metrics.py` (`summarize`, via
`lus check metrics --input events.json`):

- `latency` per operatie met `count`, `p50_s` en `p95_s` (uit `http`-events);
- `cold_requests` en `http_errors`;
- `router`: aantal GraphHopper-calls, totale tijd en wachttijd
  (`router_calls`, `router_ms`, `router_wait_ms`);
- `funnel`: aanvraag, bruikbare route, aanpassing, export per kanaal
  (`quick`, `chat`, `mcp`) en activiteit, inclusief `ready_ratio` en
  `needs_input`.

Nog toe te voegen om de triggers te kunnen toetsen (vervolgwerk, geen deel van
dit besluit):

- latentie uitgesplitst per transport (stream versus gewone POST) en per
  `cold_start`, zodat p50 en p95 koud en warm los te lezen zijn;
- het aandeel receipts per eindstatus (`complete`, `interrupted`) en het aantal
  streams dat eindigt zonder `result`/`error`-event (clientdisconnect);
- verzoeken die dicht bij de Lambda-limiet komen (duur boven 600 s) als aparte
  teller;
- de duur per fase (`router_start`, routing, model) uit de progress-events.

Zonder deze velden is een besluit voor een job altijd een gok. Pas na de eerste
pilotweek met bovenstaande percentielen is er een gemeten basis om #12 volledig
af te sluiten.
