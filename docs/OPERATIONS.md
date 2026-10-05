# Pilotbeheer

## Controle en uitrol

De deploymentworkflow roept de CI-workflow aan en controleert de main-SHA vóór
AWS-toegang. Geen bypass voor handmatige starts.

**Frontend (Vercel).** `web/vercel.json` zet `ignoreCommand` op
`node scripts/vercel-ignore.mjs`. Voor een productiebuild vraagt het script de
check-runs `test`, `terraform` en `web` van exact `VERCEL_GIT_COMMIT_SHA` op bij
GitHub (publiek, zonder token), wacht tot ~9 minuten op lopende CI en bouwt
alleen bij drie keer `success`. Mislukte of geannuleerde CI, rate limit,
netwerkfout of time-out slaan de build over (Vercel toont die als geannuleerd).
Preview-builds blijven ongemoeid. Is CI achteraf groen geworden: kies in Vercel
bij die deployment **Redeploy**; de controle draait dan opnieuw.

**Rollback backend (AWS).** Zoek de vorige digest (functie- en repositorynaam
volgen `<project>-<omgeving>`, bijvoorbeeld `lusmaker-prod`; controleer met
`terraform -chdir=infra/terraform output ecr_repository_url`):

```sh
# huidige digest van de draaiende Lambda
aws lambda get-function --function-name lusmaker-prod \
  --query 'Code.ImageUri' --output text
# recente images, nieuwste laatst
aws ecr describe-images --repository-name lusmaker-prod \
  --query 'sort_by(imageDetails,&imagePushedAt)[-10:].[imagePushedAt,imageDigest,imageTags[0]]' \
  --output table
```

Start daarna in GitHub **Actions -> Deploy AWS -> Run workflow** op `main` met
`image_digest=sha256:<digest>`. De workflow bouwt niets, controleert dat de
digest in ECR bestaat en draait dezelfde CI, stale-guard, Terraform-plan en
smoke-test. Let op:

- De stale-guard blijft gelden: de run moet starten op de huidige `main`-HEAD
  en de CI van die HEAD moet slagen. Terraform past de infra van HEAD toe met
  het oude image; kies dus een digest die compatibel is met die infra, packs en
  opslag.
- De smoke-test slaat de vergelijking van `route_sources.build_id` over, want
  het oude image bevat zijn eigen brondata.
- ECR bewaart beperkt veel images (lifecycle policy); een verlopen digest
  faalt in de controlestap.
- Is HEAD zelf kapot, laat dan eerst een revert-commit op `main` slagen. Alleen
  als productie plat ligt en dat niet kan, met beheerrechten:
  `aws lambda update-function-code --function-name lusmaker-prod --image-uri <repo>@sha256:<digest>`;
  laat de Terraform-state achteraf volgen via een gewone deployment.

**Rollback frontend (Vercel).** Open het project, tab **Deployments**, kies de
laatste goede Production-deployment en gebruik **... -> Promote to Production**
(of `vercel promote <deployment-url>`). Dit herbouwt niet en omzeilt dus ook de
CI-controle; gebruik alleen een deployment die eerder door de gate kwam. Draai
frontend en backend samen terug wanneer de API-contracten verschillen.

Geen data of runtime wissen om een rollback te forceren.

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

Met monitoring aan maakt Terraform ook SNS-topic `<project>-<omgeving>-alarms`
dat alle alarmen (alarm en herstel) ontvangt. Zet de Terraform-variabele
`alarm_email` (standaard `null` = geen abonnement) en bevestig daarna de
e-mail van AWS; zonder bevestiging komt er niets aan. Bestaande topics uit
`monitoring_alarm_actions` blijven werken. De deployrol heeft hiervoor de
SNS-rechten uit `infra/bootstrap` nodig.

### Alarmrunbook

1. **`*-http-errors`** (>= 5 HTTP-5xx in 5 min). Bekijk de fouten:
   `aws logs tail /aws/lambda/<functie> --since 30m --filter-pattern '{ $.event = "http" && $.status >= 500 }'`.
   Vuurde het alarm kort na een deployment: rollback (zie boven). Controleer
   anders Bedrock-, GraphHopper- en DynamoDB-fouten in dezelfde logs.
2. **`*-slow-requests`** (p95 > 4 min, 2 periodes). Vaak cold starts of een
   zware routeaanvraag; kijk op dashboard `<project>-<omgeving>-pilot` naar
   duur, throttling en fouten. Houdt het aan na een deployment: rollback. Stel
   de drempel bij na de baseline.
3. Na herstel meldt dezelfde SNS-topic `OK`. Noteer oorzaak en actie in
   `docs/STATUS.md`.

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
