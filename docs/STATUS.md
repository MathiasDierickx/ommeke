# Status

Stand 6 oktober 2026. Bord: [GitHub-project](https://github.com/users/MathiasDierickx/projects/2).
Dit is de enige statusmatrix; PRODUCT.md beschrijft richting, niet voortgang.

Betekenis van de kolommen:

- **Gebouwd**: code staat op `main` en is gedeployd (AWS Lambda `ommeke-prod`,
  account `384268138628`; frontend https://ommeke.vercel.app).
- **Lokaal geverifieerd**: offline tests, cassettes, build of lokale GraphHopper.
- **Live geverifieerd**: aantoonbaar gecontroleerd op de productieomgeving, met
  de aangegeven meting. Leeg = nog niet gedaan.
- **Gepland**: nog te doen of externe acceptatie.

Offline bewijs: Python-suite (`.venv/bin/python -m tests.run`), frontendtests,
TypeScript, productiebuild en Terraform-validatie. Een groene deployment alleen
is geen E2E-bewijs.

## Matrix per capability

| Capability (issue) | Gebouwd | Lokaal geverifieerd | Live geverifieerd | Gepland |
|---|---|---|---|---|
| Engine, CLI, MCP, AWS-API, Cognito/OAuth, webapp, GPX/delen, regiopacks (basis) | Alles aanwezig; hosted multi-tenant met S3-state en DynamoDB-historiek | Python-suite, 3 echte GraphHopper-cassettes, scenario's | Frontend en API live; zie rijen hieronder | Verdere extractie uit `draft.py`/`aws_chat.py` (#16) |
| CI vóór deploy (#3) | Herbruikbare CI als deployvereiste, SHA-check, Vercel-ignore | Workflowvalidatie | Deploy van `774ba76`: CI 37059502388 en AWS-deploy 37059502680 geslaagd | Rollbackprocedure live oefenen |
| Routekwaliteit-acceptatie (#4) | Tien scenario's, geometrie-evaluator | Scenario's groen | | Verse water-/landmarkroutes en reviewerproef |
| Quota en kostenlimieten (#5) | Atomaire quota, tokenreservering, MCP-routebewerkingen | Unit-tests | | Echte kosten en concurrentie in AWS |
| Privacy en accountlevenscyclus (#6) | Export, wissing met 16-min wachttijd, Cognito-verwijdering, deelwaarschuwing; beleid ingevuld | Tests met injecteerbare opslag | | Cognito-wissing live; postadres, juridische review en publicatie door de eigenaar |
| Pilot en feedback (#7) | Feedbackendpoint/UI, meetprotocol en pilotplan voor 8 Vlaamse deelnemers (13 okt–9 nov 2026) | Unit-tests | | Pilot uitvoeren; geen resultaten verzonnen |
| Metrics en alarmen (#8) | JSON-metrieken, lokale samenvatter, Terraform-dashboard/alarmen | Terraform-validatie | | Alarmbestemming, salt, kostbaseline |
| Mobiele flows (#9) | Lokale fixture, mobiele controle | Unit-tests | Eerste browserproeven in Chrome (zie snelformulier) | Volledige login/GPX-acceptatie met browserautomatisering |
| Docs en productstatus (#10) | Deze matrix, PRODUCT.md, acceptatie-/beheer-/pilotdocs | n.v.t. | n.v.t. | Juridische publicatie |
| Contractpariteit CLI/MCP/chat/web (#11) | Gedeelde chatschema's, offroad/water/landmark-pariteit | Contracttests | | Client-specifieke live acceptatie |
| Wachtflow en herstel (#12) | SSE-voortgang, heartbeats, persistente receipts, dubbelklikslot | Regressietest op POST-body-race | Snelplanner 39,320 km, chatroute 19,9 km, eindantwoord/kaart/download; chat 61,716 s | Trage/afgebroken Lambda |
| Nieuwe route via snelformulier | Modelvrij formulier met GPS, afstand, activiteit, doel | Integratietest door echte intentielaag | Wandeling Gent 4,8 km; Bredene 5 km | Nieuwe mobiele layout controleren |
| Situationele vragen | Vragen na probe, antwoorden verwerkt zonder taalmodel; deterministisch `answers`-endpoint (answers-endpoint (`route_answers` in `lusmaker/aws_api.py`)) | Tests voor `intents.apply_answers` | Oudenaarde: probe vond 6,0 km onverhard en 142 hm op 11,6 km; vragen beantwoord | |
| Activiteiten (#29) | 8 activiteiten: wandelen, trail, wegloop, stadsfiets, toerfiets, koersfiets, gravel, mtb | Catalogus- en intenttests | Wandeling Gent via het formulier | Live proef per overige activiteit |
| Heat en persoonlijke ritten (#13, #18) | Hosted heat-writes geblokkeerd; private packs geweigerd | Tests | | Besluit GPX/providerintegratie na pilot |
| Packprovenance (#14) | Manifest, hashes, versievalidatie | Pack-tests | `/health` toont `region_pack` | Reviewer herbouwt legacy packs |
| Pagineren routebibliotheek (#15) | Keysetpagina's, `order=updated` met S3-metadata, zoeken/filter in UI | 248+ tests, I/O-proef 100 routes: 20 HEAD-reads | | Zoekindex over alle routes |
| MCP-distributie (#17) | Lite- en full-toolset, submissionchecklist, ChatGPT-component | Protocoltests | | Echte Claude/ChatGPT-review en directorysubmission |
| Latentie (#19) | Kandidaatcache per optimize-run, hit/miss-tellers; MMAP-fix tegen Lambda-OOM | Unit-tests | Koude start API 3,5 s (was 19 s); Lambda-OOM opgelost via MMAP | Warme GraphHopper-service, p50/p95-doel |
| Dekking en packs (#20) | Bredene op geïsoleerde kustdata; coördinatenvalidatie | Bredene-test | Bredene 5 km live | Volledig Vlaanderen-pack, gestructureerde dekkingsfout |
| Fietscomputer-export (#21) | FIT-course-encoder, GPX-cues, API/CLI/webdownload | CRC- en parserproeven | FIT-download in Chrome: CRC ok, sport `walking`; GPX 1007 trackpunten, 199 aanwijzingen | Echt Garmin-toestel; providerpush uitgesteld |
| Snelplanner (#22) | GPS, afstand, activiteit, doel, quota/receipts, vraagknoppen | Browserproef na standaardprofielfix | Zie "Nieuwe route via snelformulier" | Mobiele layout |
| Modelkeuze en evals (#23) | `lus eval-model`, eerste-toolscoring, hosted suite met 10 echte gesprekcases, CI-poort voor modelwissels | 23/31 eerste-toolcases (6/10 echte gesprekken) | Productiemodel `openai.gpt-oss-120b-1:0` draait | Bij opgeloste Marketplace-betaling dezelfde hosted eval op Claude Sonnet; wissel via model_gate en approved-model |
| Klimhints en kandidaten (#24) | `point_hints` en `headings` in finale routering; rollbackteller | Cassettes ongewijzigd (hash negeert hints) | | `_candidates` met dezelfde via-punten/corridors; cassettes herrecorden; JSON-`null` in `headings` live |
| Omleiden onderweg (#25) | `reroute_from` in CLI/MCP/chat/API/web | Tests incl. budgetrollback | | Live omleidingsproef, GPS-toestemming |
| Offline route (#26) | Service worker, 10 bewaarde routes, routelijn/GPS/hoogteprofiel | Frontendtests | | Achtergrondtegels; vliegtuigmodus live |
| POI's onderweg (#27) | OSM-extractie, kaartfilter, export-POI's | Tests | | Productiepack met OSM-POI's; café-via-wens |
| Routedata en attributie (#28) | Contact in user-agent (alle uitgaande calls), bronvermelding in kaart | Offline UA-test | | Graafherimport en verwijdering legacy-seeds |

## Tools en model

- `lus-mcp --lite` (en de hosted `/mcp`) biedt 12 tools (`LITE_TOOLS` in
  `lusmaker/mcp_server.py`): `plan_route`, `adjust_route`, `reroute_from`,
  `suggest_climbs`, `route_details`, `download_gpx`, `route_readiness`,
  `get_profile`, `update_profile`, `ensure_region`, `region_status`,
  `list_drafts`. De hosted MCP exposeert `ensure_region` niet (immutable image).
- Pilotmodel van de eigen chat: `openai.gpt-oss-120b-1:0` op Bedrock
  (`bedrock_model_id` in `infra/terraform/variables.tf`). Claude
  (`eu.anthropic.claude-sonnet-4-6`) is geblokkeerd door de AWS
  Marketplace-betaalinstrument-fout; terug te zetten zodra die case is opgelost.

## Externe acceptatie (niet voltooid)

Pilotgebruikers (#7), platformreview (#17), echte fietscomputer (#21) en
juridische acceptatie (#6) blijven open tot ze aantoonbaar zijn gedaan.

## Taakbriefs

De historische briefs in `docs/tasks/` verwijzen naar issues waar de koppeling
evident is: T14, T15, T16 -> #28 (Toerisme Vlaanderen-data); T17, T18 -> #17
(MCP-distributie); T21 -> #9 (mobiele flows). De overige briefs (T1-T13, T19,
T20, T22-T25) zijn afgerond voorwerk zonder eigen issue.

## Detail per recente wijziging

**#24.** De finale routering (`draft._route`) geeft per leg `point_hints`
(straatnaam van de klim) en `headings` door aan `gh.route`, met evenveel items
als punten. `recording.hash_body` negeert beide, zodat de drie cassettes
geldig blijven; de replay bewijst dus niet dat de hints de keuze verbeteren.
Voor `tests/record_fixtures.py`-herrecording moet die negering weer weg.

**#15.** Nieuwe drafts bevatten compacte S3-metadata, atomair met de
revisiewrite; legacy drafts blijven werken. De sleutellijst wordt nog per
pagina gescand. Een paginacursor hoort bij één tenant en een levende lijst.

**#23.** Bedragen, beperkingen en ruwe meetrapporten staan in `evals/README.md`.
