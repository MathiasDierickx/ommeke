# Inventaris en voortgang

## Actuele uitvoering — 2 oktober 2026, avond

De expliciete opdracht om te deployen vervangt voor deze sessie het eerdere
pushverbod. AWS SSO naar `ommeke-prod` werkt nu voor account `384268138628`
(`meander-prod`). GitHub Actions deployt naar dat account; de frontend staat op
https://ommeke.vercel.app. Het publieke brondatapack is actief. De lokale
GraphHopper-runtime en `~/.lusmaker` zijn tijdens deze uitbreiding niet gewijzigd.

Nieuwe onderdelen zijn ingecheckt en worden in echte Chrome-proeven gecontroleerd:
modelvrij routeformulier, lokale plaatsnaam bij GPS-coördinaten, terugweg met
budget/revisiecontrole, FIT-course-export, GPX-cues, POI-filter, kandidaatcache,
CLI-intent-evals, SSE-voortgang en een expliciet lokaal bewaarde offline route.
De offline kaart bevat een routelijn en hoogteprofiel, nog geen achtergrondtegels.

Offline bewijs: 295 Python-tests inclusief drie bestaande regressiecassettes,
9 frontendtests, TypeScript en productiebuild. De eerste browsertest vond een
ontbrekend standaardprofiel in de snelplanner; daarvoor bestaat nu ook een
integratietest door de echte intentielaag. De eerste SSE-proef vond een race
bij het lezen van de POST-body; de reparatie leest die body vóór streaming en
heeft een aparte regressietest. Een groene deployment alleen is geen E2E-bewijs.

| Issue | Nieuwe implementatie | Resterend bewijs / werk |
|---|---|---|
| #12 | SSE-stappen uit backend/engine, heartbeats, werkelijk eindresultaat; antwoord blijft zichtbaar | Snelplanner (39,320 km), chatroute (app 19,9 km), eindantwoord/kaart/download en ongeldige-invoerproef live geslaagd; chat duurde 61,716 s |
| #19 | Cache van kandidaatroutering per optimize-run; hit/miss-tellers | Losse warme GH-service, LM-import en p50/p95-doel nog niet gerealiseerd |
| #20 | Bredene op geïsoleerde kustdata getest; coördinatenvalidatie verbeterd | Volledig Vlaanderen-pack en gestructureerde dekkingsfout nog niet afgerond |
| #21 | FIT-encoder met CRC/parserproeven, GPX-cues, API/CLI/webdownload | Live nieuw gegenereerde cues en echt Garmin-toestel nog controleren; directe providerpush uitgesteld |
| #22 | Snelplanner met GPS, afstand, activiteit, doel, quota/receipts, vraagknoppen | Browserproef na standaardprofielfix geslaagd; nieuwe mobiele layout nog controleren |
| #23 | `lus eval-model`, eerste-toolscoring, verbruik/latentie/optionele kosten | Suite bevat ook synthetische cases en MCP-only gevallen; geen modelmigratiebesluit op ruwe score; Claude-betaling nog extern |
| #24 | Budgetrollbackteller toegevoegd | Hints/richting en kandidaatpariteit nog niet gewijzigd; cassettes onveranderd |
| #25 | `reroute_from` in CLI/MCP/chat/API/web; oorspronkelijke draft behouden bij budgetfout | Live omleidingsproef en toestemming voor GPS op toestel |
| #26 | Service worker met offline shell; 10 expliciet bewaarde routes, routelijn/GPS/hoogteprofiel; wissen bij logout | Achtergrondtegels ontbreken; vliegtuigmodus nog niet live geverifieerd |
| #27 | OSM-extractie, afstand tot/langs route, kaartfilter en export-POI's | Productiepack moet nieuwe OSM-POI's bevatten; café-via-wens nog niet geïmplementeerd |
| #28 | Contact in user-agent, bronvermelding in webkaart/gedeelde kaart/HTML | Geen lokale graafherimport of verwijdering van legacy-seeds uitgevoerd |

Pilotgebruikers (#7), platformreview (#17), echte fietscomputer (#21) en juridische
acceptatie (#6) blijven externe acceptatie. Die worden niet als voltooid gemarkeerd.

## Vervolg: afronding en modelevaluatie

Commit `774ba76` is via CI 37059502388 en AWS-deploy 37059502680 geslaagd;
Vercel rapporteerde eveneens success. In persoonlijke Chrome is route `c008b6`
via de snelplanner gemaakt: 39,3 km / 416 m, echte tussenstappen, een blijvende
eindstatus en een werkende knop naar de kaart. De GPX-download bevat 1007
trackpunten, 199 routeaanwijzingen en identieke start- en eindcoördinaten.
Een afzonderlijke chatvraag over deze route eindigde met het juiste antwoord,
de routeknop en “Antwoord klaar — Afgerond in 2 sec”.

De feedbackronde verwijdert de hernieuwde startsuggesties onder een voltooide
snelplanroute en ververst ook de bibliotheek na het resultaat. Offline controles:
303 Python-tests, 9 frontendtests, TypeScript en productiebuild.

Issue #23 heeft nu een hosted suite met 10 afgeleide echte gesprekcases erbij,
gesprekscontext en een offline CI-poort voor Terraform-modelwissels. De laatste
modelproef haalt 23/31 eerste-toolcases (6/10 echte gesprekcases), dus dit issue
blijft open. Claude-toegang en kosten per volledig gesprek zijn niet aangetoond.
De bedragen, beperkingen en ruwe meetrapporten staan in `evals/README.md`.

## Historische inventaris vóór de uitrol

Stand 2 oktober 2026, lokale main. [Bord](https://github.com/users/MathiasDierickx/projects/2).
De bestaande engine, CLI, MCP, AWS API, Bedrock-chat, OAuth/Cognito, webapp,
GPX/delen, regionale packs en drie regressiecassettes vormen de basis.

| Issue | Uitgevoerd | Openstaande acceptatie / werk |
|---|---|---|
| #3 | Herbruikbare CI als deployvereiste, SHA-check | GitHub-workflow en rollback live controleren |
| #4 | Tien scenario's, vier regressiefixes, geometrie-evaluator | Verse water-/landmarkroutes en reviewerproef |
| #5 | Atomaire quota, modelreservering, MCP-routebewerkingen | Werkelijke kosten en concurrentie in AWS |
| #6 | Account-export/wissing, deelwaarschuwing/intrekken, privacyinventaris | Juridische gegevens, backups/versiesretentie, Cognito live |
| #7 | Feedbackendpoint/UI, meetprotocol | Echte 5–10 gebruikers, geen resultaten verzonnen |
| #8 | JSON-metrieken, lokale samenvatter, Terraform-dashboard/alarmen | Alarmbestemming, salt, kostbaseline en live timing |
| #9 | Lokale fixture, mobiele controle, unit-tests | Volledige login/GPX/backend-acceptatie en browserautomatisering |
| #10 | Productstatus, merkrelatie, acceptatie-/beheer-/pilotdocs | Juridische publicatie en actuele deploymentgegevens |
| #11 | Gedeelde chatschema's, offroad/water/landmark-pariteit | Client-specifieke live contractacceptatie |
| #12 | Dubbelklikslot, persistente receipts, timeout/onderbrekingsherstel | Trage/afgebroken echte Lambda controleren |
| #13 | Hosted heat-writes geblokkeerd, private packs geweigerd bij gedeelde uitrol | Persoonlijke import bewust niet geactiveerd |
| #14 | Packprovenance, hashes, versievalidatie | Reviewer herbouwt legacy packs; geen data herimporteerd |
| #15 | Begrensde keysetpagina's, routebibliotheek laadt bij | S3-pagina leest nog draftgeometrie; nieuwste-eerst index ontbreekt |
| #16 | Chatschema's en nieuwe verantwoordelijkheden in aparte modules | Verdere extractie uit draft.py/aws_chat.py stapsgewijs |
| #17 | Bestaande protocoltests en submissionchecklist behouden | Echte Claude/ChatGPT-review en directorysubmission |
| #18 | Besliscriteria en privacyvoorwaarden voor eigen ritten | Pilotbewijs vóór keuze GPX/providerintegratie |

Issues blijven open zolang acceptatie ontbreekt. Er is niet gepusht of gedeployd,
conform AGENTS.md. De documentatie beschrijft code en beperkingen, geen claim
dat alle backlogitems of de volledige productlancering voltooid zijn.

## Tweede iteratie en uitrol

De eerste iteratie t/m eaa1e48 is inmiddels gepusht. Vercel is bijgewerkt en
AWS heeft de Lambda en Function URL gewijzigd. Run 37038453941 faalde vervolgens
op ontbrekende CloudWatch-rechten: alarmen en dashboard ontbreken nog en de
smoke-stap is niet uitgevoerd. De gerichte bootstrapfix staat in cfb6b2e.
De persoonlijke SSO-sessie geeft momenteel alleen account 120569634535 vrij,
niet het deploymentaccount 384268138628; er is geen wijziging in het andere
account uitgevoerd.

Vervolg op #15: nieuwe drafts bevatten compacte S3-metadata, atomair met de
revisiewrite. De opt-in routepagina `order=updated` leest HEAD-samenvattingen,
geeft recent gewijzigde routes eerst en blijft compatibel met legacy drafts.
Zonder metadata wordt alleen voor de geselecteerde pagina de volledige draft
gelezen. De sleutellijst wordt nog wel per pagina gescand; dit is geen volledige
zoekindex. Een paginacursor hoort bij één tenant en een levende lijst.

De frontend biedt zoeken binnen geladen routes, een activiteitsfilter,
laadstatus en bescherming tegen dubbele/verouderde pagina-antwoorden. Het
routedetail toont nu harde maxima, streefafstand en expliciet gemiste wensen.
Offline gecontroleerd: 248 Python-tests, 5 frontendtests, TypeScript en build.
I/O-proef met 100 routes en twee pagina's van 10: 20 HEAD-reads, nul volledige
routebestanden gelezen. Legacy, CAS-conflicten, gelijke timestamps, verwijdering
tijdens paginering en tenantvreemde cursors zijn afzonderlijk getest.
