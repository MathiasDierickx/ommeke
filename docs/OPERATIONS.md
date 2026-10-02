# Pilotbeheer

## Controle en uitrol

De deploymentworkflow roept de CI-workflow aan en controleert de main-SHA vóór
AWS-toegang. Geen bypass voor handmatige starts. Deze wijziging is lokaal
gevalideerd, nog niet in productie uitgevoerd. Voor rollback: bepaal de vorige
bekende image-digest en frontendcommit uit de laatste geslaagde deployment;
reviewer controleert compatibiliteit van packs en opslag en rolt die versie
bewust opnieuw uit. Geen data of runtime wissen om een rollback te forceren.

## Limieten en metingen

Terraform `daily_quotas`: per gebruiker per UTC-dag standaard 40 chatopdrachten,
80 routebewerkingen, 200.000 conservatief gereserveerde modeltokens, 20
feedbackmeldingen en 0 nieuwe regioprovisioneringen. Bestaande gezonde regio's
blijven bruikbaar. Limieten zijn atomair opgeslagen; een herhaald requestnummer
wordt niet dubbel verbruikt. Mislukte pogingen tellen mee. Tokenreserveringen zijn
bewust ruim; daadwerkelijke modelkosten kunnen daarvan afwijken.

Deze limieten zijn geen globale AWS-uitgavenstop ; ook de losse MCP-route-, readiness-, suggestie- en optimalisatietools tellen
mee. Leesacties vallen buiten het routequotum. Houd AWS-budgetten en Lambda-concurrency afzonderlijk bij.

JSON-logevents bevatten timing, status, request-ID en modeltokenaantallen, geen
prompts of routegeometrie. Een optionele `METRICS_SALT` GitHub-secret levert
pseudonieme gebruikersmetingen via Terraform. Zonder salt geen retentiemeting.
Dezelfde salt over meetdagen behouden; behandel hem als geheim.

CloudWatch-dashboard: Lambda p50/p95, HTTP-fouten, throttling en fouten.
Alarmen: vijf HTTP-5xx in vijf minuten en aanhoudende p95 boven vier minuten.
`monitoring_alarm_actions` moet door de beheerder worden gekoppeld aan een
bestemming; zonder bestemming bestaan alarmen zonder notificatie.

```sh
.venv/bin/lus check metrics --input events.json \
  --input-per-million 0 --output-per-million 0
```

Vervang nul door de afgesproken actuele modeltarieven. Resultaat is een
schatting op basis van gelogde tokens, exclusief AWS-infrastructuur, geocoding
en ontbrekende providerresponses. Meet geen echte pilotresultaten met fixtures.

## Herstel en accountgegevens

Chat gebruikt persistente requestreceipts. Een timeout mag dezelfde request-ID
herhalen; een voltooid antwoord wordt teruggegeven zonder tweede uitvoering.
Onderbroken opdrachten worden niet automatisch opnieuw uitgevoerd: er kunnen
al routes bestaan. De UI vraagt die te controleren vóór een bewuste nieuwe
opdracht. Een achtergebleven running receipt wordt na 960 s onderbroken gemeld.

Account-export maakt een ZIP van tenantgegevens (maximum 64 MB). Wissing vraagt
VERWIJDER, blokkeert nieuw werk, wacht 960 s op lopende Lambda-opdrachten en
vereist vervolgens opnieuw bevestigen. Eerst verdwijnen publieke deelverwijzingen,
dan chats/routes/overige actieve gegevens en de Cognito-gebruiker. Een tombstone
blijft staan om oude tokens te blokkeren. S3-versies, backups en technische logs
vallen niet onder deze actieve-objectwissing: leg retentie en afhandeling vast
vóór publieke lancering. Er is geen account verwijderd tijdens ontwikkeling.

## Packs en persoonlijke ritten

Nieuwe packs beschrijven formaat, extractversie, engine, modelhashes,
databroncache en aanwezige water-/landmarkdata. Incompatibele versies worden
geweigerd. Legacy packs blijven leesbaar maar hebben onbekende provenance;
herbouw door de reviewer is nodig om die garanties te verkrijgen.
Persoonlijke heat vereist expliciete private packaging; de gedeelde AWS-pack
weigert zulke packs. Hosted gebruikers kunnen niet de gedeelde heat opbouwen.

## Nog te valideren

Productie-CI, echte quota/concurrentie, Cognito-export/wissing, CloudWatch-
alarmering en modelkosten vereisen revieweracceptatie. Geometrie-invarianten
zijn geen bewijs van verkeersveiligheid. Gebruik `docs/ACCEPTANCE.md` en
`docs/PILOT.md` voor de volgende controles.
# Monitoringrechten en app-deployment

De GitHub-workflow gebruikt `ENABLE_APPLICATION_MONITORING=false` zolang die
repositoryvariabele niet is ingesteld. Dit laat de app en bestaande logging
uitrollen zonder de extra CloudWatch-alarmen en het pilotdashboard, waarvoor
de huidige productie-deployrol nog geen rechten heeft. Pas eerst de gerichte
IAM-policy uit `infra/bootstrap` toe met een beheeridentiteit voor het juiste
account en zet daarna de repositoryvariabele op `true`. Terraform zelf houdt
de standaard `enable_application_monitoring=true` voor andere installaties.
Schakel dit niet uit op een installatie met bestaande alarmen: Terraform zal
die dan verwijderen. In deze productieomgeving waren de nieuwe alarmen en
het dashboard nog niet aangemaakt door de eerdere AccessDenied-fout.
