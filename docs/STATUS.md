# Inventaris en voortgang

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
