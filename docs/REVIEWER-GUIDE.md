# Ommeke / Lusmaker — MCP-reviewergids

Stand: 6 oktober 2026. Deze gids beschrijft de hosted MCP-connector voor reviewers van Claude- en ChatGPT-directories.

## Dienst

Ommeke bouwt met Lusmaker wandel-, loop- en fietslussen in Vlaanderen. Gebruikers geven afstand, activiteit, doel en voorkeuren op en beantwoorden zo nodig situationele vragen, bijvoorbeeld over heuvels, ondergrond, kasseien of autovrij. De dienst routeert via vooraf gebouwde GraphHopper-regiopacks en kan GPX leveren.

## Aanmelden en testaccount

De hosted MCP gebruikt Cognito en een interactieve authorization-codeflow. De connector ontdekt de beveiligde resource via `/.well-known/oauth-protected-resource`, laat de gebruiker aanmelden en stuurt daarna een bearer-token naar `/mcp`. De server valideert handtekening, issuer, audience, vervaldatum, subject en de vereiste scope. De Cognito-client staat vooraf geregistreerd; DCR/CIMD wordt niet aangeboden.

Gevraagde OAuth-scopes:

- `openid`
- `email`
- `profile`
- `aws.cognito.signin.user.admin` (vereiste scope voor MCP-toegang)

Vraag een reviewaccount aan via het submission-portaal of het contactadres in het privacybeleid. De beheerder verstrekt tijdelijke account- en verbindingsinstructies rechtstreeks aan de reviewer. Deel credentials niet in issues, documentatie of openbare berichten. Gebruik een afzonderlijk revieweraccount.

## MCP-tools

De hosted MCP biedt de 12 functies uit `LITE_TOOLS` in `lusmaker/mcp_server.py`. Resultaten zijn JSON-objecten; voorbeelden tonen relevante velden. Routeafstand en beschikbaarheid hangen af van startlocatie en regiopack.

| Tool | Voorbeeldaanroep | Verwacht resultaat |
|---|---|---|
| `plan_route` | `{"start":"Gent","target_km":25,"activiteit":"wandelen","naam":"Wandellus Gent"}` | `needs_input` met vragen, of `ready` met `draft`, `revision`, `km`, `hoogtemeters`, `kwaliteit` en bestanden. |
| `adjust_route` | `{"draft_id":"<draft>","target_km":30,"expected_revision":0}` | Workflowresultaat met nieuwe route/revision of `needs_input` met vragen. Gebruik de laatst ontvangen revision. |
| `reroute_from` | `{"draft_id":"<draft>","lat":51.05,"lon":3.72,"rest_km":8,"expected_revision":0}` | Route vanaf de positie met status, draft/revision en routegegevens. |
| `suggest_climbs` | `{"draft_id":"<draft>","max_detour_km":5,"limit":3}` | `draft`, `huidige_km`, lijst `suggesties` en een `hint`. |
| `route_details` | `{"draft_id":"<draft>"}` | `draft`, `revision`, `status`, afstand, hoogtemeters, `legs` en `kwaliteit`. |
| `download_gpx` | `{"draft_id":"<draft>"}` | Tijdelijke `download_url`, vervalt na 900 seconden; ook MIME-type, bytes en SHA-256. Vereist een gerouteerde draft. |
| `route_readiness` | `{"draft_id":"<draft>"}` | Beoordeling met gereedheid, eventuele vragen en advies. |
| `get_profile` | `{"naam":"standaard"}` | Opgeslagen voorkeurenprofiel; ontbrekend profiel geeft defaults. |
| `update_profile` | `{"naam":"standaard","patch":{"hoogtemeters":0.7}}` | Bijgewerkt profiel. Alleen getypeerde profielvelden worden aanvaard. |
| `ensure_region` | `{"place":"Gent"}` | In lokale omgevingen kan provisioning starten; deze tool wordt niet aangeboden door de hosted MCP omdat de productie-image onveranderlijk is. |
| `region_status` | `{"slug":"vlaanderen"}` | Status van een bestaande regioprovisioning, indien aanwezig; hosted MCP kan zelf geen provisioning starten. |
| `list_drafts` | `{}` | `{"drafts":[…]}` met drafts van de aangemelde tenant. |

`plan_route` en `adjust_route` kunnen eerst `needs_input` geven. Stel de vragen aan de gebruiker en verwerk antwoorden met `adjust_route`; presenteer ontbrekende informatie niet als bevestigd.

## Privacy, export en verwijderen

De MCP verwerkt toolaanroepen en routegegevens, geen volledige assistentgesprekshistoriek. Tenantgegevens zijn per gebruiker afgeschermd. Zie het [privacybeleid](legal/privacy-policy.md) voor categorieën, verwerkers en termijnen. Dit is nog een concept dat juridische review en publicatie vereist.

Een gebruiker kan accountgegevens exporteren en accountwissing aanvragen. Wissing blokkeert nieuw werk; na 16 minuten is opnieuw bevestigen nodig. Daarna worden actieve routes, chats, deelverwijzingen en het Cognito-account verwijderd. Historische S3-versies kunnen tot 30 dagen blijven bestaan; logs maximaal 7 dagen. Zie [OPERATIONS.md](OPERATIONS.md). Voor assistentgesprekken geldt ook het beleid van het gebruikte platform.

## Bekende beperkingen

- De hosted dekking hangt af van geïnstalleerde regiopacks. Vlaanderen is de huidige launch-regio; dekking verschilt per gebied.
- Lange routes met veel klimmen kunnen minuten rekenen. De Lambda-limiet is 15 minuten; koude starts kunnen extra vertraging geven.
- De eigen chat gebruikt momenteel `openai.gpt-oss-120b-1:0` op AWS Bedrock. Directoryreviewers kiezen hun eigen model; resultaten kunnen verschillen.
- Hosted regioprovisioning is niet beschikbaar via MCP.
- Directoryacceptatie, OAuth-proef met echte revieweraccounts en pilotmetingen zijn nog niet afgerond.
