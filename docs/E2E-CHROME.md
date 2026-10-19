# End-to-end testen in Chrome (door Claude)

Protocol voor live acceptatie van https://ommeke.vercel.app via de
Claude-in-Chrome-extensie. Dit vult de drie bestaande lagen aan:

| Laag | Commando | Wat het bewijst |
|---|---|---|
| Offline browserregressie | `npm --prefix web run test:e2e` | UI-flows tegen een nep-API, geen netwerk |
| Backendketen zonder browser | `.venv/bin/python -m tests.e2e_prod --verbose` | Health, Cognito, chat, Bedrock, routebestanden, MCP |
| **Chrome op productie (dit document)** | handmatig door Claude | Wat een gebruiker écht ziet, inclusief downloads en SSE |

Een groene build of unit-test is geen bewijs van een werkende wandeling.

## Browser en account

- Gebruik de **persoonlijke Chrome** (deviceId `e72faee6-…`, zie
  `~/.claude/CLAUDE.md`). Die is ingelogd met het eigen account van Mathias.
- Claude typt **nooit** een wachtwoord op productie. De sessie staat in
  `localStorage` (`lusmaker.auth`) en wordt via het refresh-token (30 dagen
  geldig) automatisch vernieuwd. Is de sessie weg, dan logt Mathias zelf
  opnieuw in.
- Er bestaat een apart testaccount `reviewer@lusmaker.test` in de Cognito-pool
  `eu-west-1_hc7UuD8ZV`. Wil je testroutes buiten de eigen bibliotheek houden,
  maak dan een Chrome-profiel "Ommeke", installeer de extensie, log daar als
  reviewer in en noteer het nieuwe deviceId in `~/.claude/CLAUDE.md`.
- Testroutes krijgen een naam die begint met `e2e` zodat ze herkenbaar blijven
  en achteraf opgeruimd kunnen worden.

## Vaste proef (ca. 10 minuten, kost < $0,05)

1. **Startscherm.** Open `/`, screenshot. Sidebar laadt gesprekken en routes;
   geen `role=alert`. Lees de console met patroon `error|Error`.
2. **Snelplanner, wandeling.** Startplaats `Markt, Wetteren`, 4 km, Wandelen,
   Ontspannen. Klik *Maak mijn route*. Verwacht: voortgangsfasen met
   verstreken tijd (SSE), invoer vergrendeld, daarna eindscherm met kaart,
   afstand en hoogtemeters. Noteer de wachttijd en of de Lambda koud was
   (eerste request van de dag is koud).
3. **Situationele vragen.** Verschijnen er vragen (kasseien, heuvels,
   ondergrond, oversteken), beantwoord er één via de knoppen en controleer dat
   de route herlaadt met een nieuwe `revision`.
4. **Aanpassen.** Zet de gewenste afstand op 6 km. Verwacht: nieuwe afstand
   binnen ±10 %, revision +1, geen 409.
5. **Download GPX en FIT.** Klik beide knoppen. Controleer in de shell:

   ```sh
   ls -t ~/Downloads | head -3
   .venv/bin/python scripts/inspect_download.py ~/Downloads/<naam>.gpx ~/Downloads/<naam>.fit
   ```

   Verwacht: `lengte_m` binnen 10 % van de app, `sluiting_m` < 50, GPX en FIT
   met hetzelfde aantal trackpunten, `crc_ok: true`, sport `walking`.
6. **Chat.** Stel in de chat een vraag over de zojuist gemaakte route
   ("hoe lang is deze route?"). Verwacht een antwoord met de juiste afstand en
   geen nieuwe route. Daarna een wijziging: "maak er 5 km van". Verwacht een
   aangepaste route, geen tweede.
7. **Foutgeval.** Startplaats `91,3` (buiten gebied). Verwacht een begrijpelijke
   `buiten_gebied`-melding, spinner stopt, formulier weer bruikbaar.
8. **Mobiel.** Herhaal stap 2 op 390 px breed (`resize_window`) en controleer
   dat kaart, knoppen en voortgang zichtbaar blijven zonder horizontale scroll.
9. **Herladen tijdens plannen.** Start een route, herlaad halverwege. Verwacht:
   na herladen toont de app dat de vraag nog loopt of afgebroken is, met
   *Vraag opnieuw stellen*; geen dubbele route.

## Backend meekijken

Alles draait in Lambda `lusmaker-prod` (profiel `ommeke-prod`, zie README):

```sh
export AWS_PROFILE=ommeke-prod
aws logs tail /aws/lambda/lusmaker-prod --since 15m --format short \
  --filter-pattern '{ $.event = "http" }'
aws logs tail /aws/lambda/lusmaker-prod --since 15m --filter-pattern '{ $.status >= 500 }'
```

Het `X-Request-Id` uit het netwerkpaneel (`read_network_requests`, filter
`lambda-url`) komt overeen met `request_id` in de logs.

## Rapporteren

Zet per stap in de issue of in `docs/STATUS.md` (kolom *Live geverifieerd*):
route-id, gemeten afstand app versus bestand, wachttijd koud/warm, en wat
**niet** bewezen is. Een gelukte download bewijst geen Garmin-import; een
groene stap 2 bewijst niet dat de route veilig of mooi is.
