# Lusmaker op AWS en Vercel

Deze stack deployt Lusmaker als webapp én authenticated remote MCP-app. De
statische React/Next.js-interface draait op Vercel. De AWS-compute bestaat uit
één Lambda-container met de Lusmaker ASGI/API/MCP-server via de AWS Lambda
Web Adapter. Standaard draait GraphHopper op localhost; met de opt-in
`gh_service_enabled` draait hij altijd warm op EC2 achter CloudFront. GraphHopper en routegegevens zijn vooraf
in het image gebouwd; een request downloadt of importeert nooit kaartdata.

## Architectuur

```text
Browser ──> Vercel static Next.js ──┐
                                    │ HTTPS + Cognito access token
ChatGPT / Claude / MCP-client ──────┤
                                    ▼
                           Lambda Function URL <── Cognito managed login
                                    │
                           Lusmaker ASGI/API/MCP
                                    │ tenant = Cognito sub
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
               GraphHopper      S3 routes       DynamoDB chat
               in Lambda        GPX/preview     PAY_PER_REQUEST
                                    │
                                    ▼
                            Claude via Bedrock
```

Terraform maakt aan:

- één ECR-repository met immutable images en lifecycle-retentie;
- één Lambda zonder provisioned concurrency en maximaal vijftien minuten per
  request;
- een Function URL met response streaming;
- een Cognito user pool met self-service registratie, optionele TOTP-MFA,
  managed login, een confidential MCP-client en publieke webclient met PKCE;
- een private, versleutelde en geversioneerde S3-bucket voor tenant-state;
- een versleutelde DynamoDB on-demand tabel voor gesprekken en berichten;
- IAM-rechten voor uitsluitend het gekozen Europese Claude-model in Bedrock;
- een CloudWatch-loggroep met korte retentie;
- optioneel een maandelijks AWS Budget met e-mailmeldingen;
- in de bootstrap-stack: een private Terraform-statebucket en een branch-
  gebonden GitHub OIDC-deployrol.

Zonder `gh_service_enabled` maakt de stack geen CloudFront of EC2 aan.
De opt-in router gebruikt de bestaande default VPC, zonder Lambda-VPC of NAT.
Er zijn geen API Gateway, EFS, ECS/Fargate of provisioned Lambda instances.
Vercel levert de CDN/HTTPS-laag voor de frontend; CloudFront bedient uitsluitend
de optionele router. De
Function URL vermijdt de API Gateway-timeout voor lange route- en modelcalls.

## Wat “scale to zero” hier betekent

Met `gh_service_enabled=false` draait er geen compute als niemand Lusmaker
gebruikt. Met `true` blijft uitsluitend de EC2-router draaien. `max_concurrency` kan
als kosten- en capaciteitsplafond worden ingesteld; het warmt of reserveert
geen Lambda-instances. AWS-accounts met de minimale concurrencyquota van 10
kunnen geen reserved concurrency instellen, omdat AWS minstens 10 executions
accountbreed ongereserveerd houdt. In dat geval blijft de accountquota de cap.
Een cold start kopieert de read-only GraphHopper-cache naar Lambda `/tmp`, start
GraphHopper op de achtergrond. De API opent meteen; routeraanvragen wachten
op de health-check. Met een externe URL worden de kopie en JVM overgeslagen. `AWS_LWA_ASYNC_INIT` laat die
opstart binnen de Lambda-timeout doorlopen.

AWS wordt niet letterlijk kosteloos wanneer de app idle is. ECR bewaart het
containerimage, S3 bewaart Terraform-state, regiopack en gebruikersdata,
DynamoDB bewaart chatitems en CloudWatch bewaart logs. ECR rekent bijvoorbeeld
per opgeslagen GB-maand. In de standaardstand zijn er geen vaste servers of gereserveerde compute,
maar persistente opslag maakt “uitsluitend per invocation” technisch
onmogelijk. DynamoDB rekent in `PAY_PER_REQUEST` geen idle throughput aan.

De Next.js-app gebruikt geen Vercel Functions. Vercel Hobby is $0/maand binnen
de limieten, maar is uitsluitend bedoeld voor persoonlijk, niet-commercieel
gebruik. Voor een commerciële hosted Lusmaker is Vercel Pro een vaste
abonnementskost; host de statische `web/out` dan desgewenst op een usage-based
object/CDN-platform. Zie [Vercel Hobby](https://vercel.com/docs/plans/hobby),
[DynamoDB on-demand](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/on-demand-capacity-mode.html)
en [ECR-prijzen](https://aws.amazon.com/ecr/pricing/).

Relevante harde AWS-grenzen zijn een containerimage van maximaal 10 GB
uncompressed, maximaal 10 GB `/tmp` en een Lambda-timeout van 15 minuten. Maak
een kleinere regiopack wanneer graph plus runtime daar niet binnen passen. Zie
de [AWS Lambda quota's](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html)
en de [Lambda Web Adapter](https://github.com/awslabs/aws-lambda-web-adapter).
De stack start bewust met 3.008 MB geheugen en een 2 GB Java-heap, zodat ook
accounts met de lage initiële memoryquota kunnen deployen. Verhoog
`lambda_memory_mb` en `java_opts` samen als AWS een hogere quota heeft
goedgekeurd.

## Vereisten

- een AWS-account en lokaal werkende AWS CLI-credentials voor de eenmalige
  bootstrap;
- Terraform 1.10 of nieuwer;
- een GitHub-repository waarvan `main` de deploymentbranch is;
- een lokale machine of GitHub Actions-runner met voldoende disk en geheugen
  om een regiograph te bouwen;
- een concrete OAuth callback. Voor Claude is dit
  `https://claude.ai/api/mcp/auth_callback`. ChatGPT toont per pluginverbinding
  een URL van de vorm `https://chatgpt.com/connector/oauth/{callback_id}`.
- een Vercel-project en zijn vaste productie-URL, bijvoorbeeld
  `https://ommeke.vercel.app/`;
- toegang van de Vercel GitHub App tot de repository voor automatische
  frontenddeploys.

## 1. Bootstrap state en GitHub OIDC

De bootstrap gebruikt initieel lokale Terraform-state omdat de remote bucket
nog niet bestaat. Bewaar `infra/bootstrap/terraform.tfstate` veilig nadat je
deze stap uitvoert; het bestand wordt door `.gitignore` uitgesloten.

```bash
cd infra/bootstrap
cp terraform.tfvars.example terraform.tfvars
# Vul minstens github_repository = "owner/repository" in.
terraform init
terraform plan
terraform apply
terraform output
```

GitHub-repositories die vanaf 15 juli 2026 zijn gemaakt, of die immutable OIDC
subjects hebben aangezet, gebruiken owner- en repository-ID's in de `sub`-
claim. Vul in dat geval `github_oidc_subjects` expliciet in zoals in het
voorbeeldbestand. Als de AWS-account al een GitHub OIDC-provider heeft, geef je
diens ARN door als `github_oidc_provider_arn`; IAM staat maar één provider voor
dezelfde URL toe. De trust policy accepteert alleen de opgegeven subjects en
`sts.amazonaws.com` als audience. Zie de [GitHub OIDC-handleiding voor
AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws).

## 2. GitHub Actions-variabelen

Zet de outputs van de bootstrap als repository variables, niet als langlevende
AWS access keys:

| Variable | Vereist | Voorbeeld |
|---|---:|---|
| `AWS_DEPLOY_ROLE_ARN` | ja | bootstrap-output `github_deploy_role_arn` |
| `TF_STATE_BUCKET` | ja | bootstrap-output `terraform_state_bucket` |
| `AWS_REGION` | nee | `eu-west-1` |
| `PROJECT_NAME` | nee | `lusmaker` |
| `DEPLOY_ENVIRONMENT` | nee | `prod` |
| `LUSMAKER_REGION_SLUG` | nee | `vlaanderen` |
| `OAUTH_CALLBACK_URLS_JSON` | ja | `["https://claude.ai/api/mcp/auth_callback"]` |
| `WEB_CALLBACK_URLS_JSON` | ja | `["https://ommeke.vercel.app/","http://localhost:3000/"]` |
| `BILLING_EMAIL` | nee | `aws-kosten@example.com` |

Met de GitHub CLI:

```bash
gh variable set AWS_DEPLOY_ROLE_ARN --body '<role-arn>'
gh variable set TF_STATE_BUCKET --body '<bucketnaam>'
gh variable set AWS_REGION --body 'eu-west-1'
gh variable set LUSMAKER_REGION_SLUG --body 'vlaanderen'
gh variable set OAUTH_CALLBACK_URLS_JSON \
  --body '["https://claude.ai/api/mcp/auth_callback"]'
gh variable set WEB_CALLBACK_URLS_JSON \
  --body '["https://ommeke.vercel.app/","http://localhost:3000/"]'
```

De workflows gebruiken uitsluitend kortlevende OIDC-credentials. Er horen geen
`AWS_ACCESS_KEY_ID` of `AWS_SECRET_ACCESS_KEY` in GitHub Secrets te staan.

## 3. Bouw één regiopack

Start eerst de handmatige workflow. Ze downloadt de brondata, bouwt de caches,
importeert GraphHopper 11.0, maakt een pack zonder de grote PBF en uploadt die
naar de statebucket:

```bash
gh workflow run build-region-pack.yml --ref main \
  -f slug=vlaanderen \
  -f geofabrik=europe/belgium \
  -f bbox=boundary
```

`bbox=boundary` (de standaard) leidt de bbox af uit de ingecheckte, vereenvoudigde
Vlaanderen-grens (`lusmaker/data/flanders_boundary.geojson`, OpenStreetMap
relatie 53134, ODbL) plus 2 km buffer. De grens haal je eenmalig op met
`.venv/bin/python scripts/flanders_boundary.py` en check je daarna in; bestaat
het bestand niet, dan faalt de build met een duidelijke melding. Je kan nog
steeds een expliciete `minlat,minlon,maxlat,maxlon` meegeven. De dekkingscontrole
in productie gebruikt ongewijzigd de gemeten GraphHopper-`/info`-bbox.

Volg de run met `gh run watch`. De resulterende locatie is
`s3://<TF_STATE_BUCKET>/region-packs/vlaanderen.tar.gz`.

Dit is de enige zware build. Gewone codewijzigingen hergebruiken het pack. Een
bewuste data-, GraphHopper- of profielupgrade vereist een nieuwe pack-run. De
pack en de runtime zijn beide op GraphHopper 11.0 gepind; een pack van een
andere engineversie wordt tijdens deployment geweigerd.

Een GitHub-hosted runner kan voor een grotere regio onvoldoende geheugen of
disk hebben. Gebruik dan dezelfde workflow op een grotere self-hosted runner;
de uiteindelijke AWS-runtime blijft volledig serverless.

Wanneer de regio lokaal al volledig en compatibel gebouwd is, kan de zware
stap zonder GitHub Action-minuten gebeuren. Maak en valideer de pack lokaal en
upload hem daarna naar de canonieke, geversioneerde S3-locatie:

```bash
.venv/bin/lus region pack vlaanderen -o /tmp/vlaanderen.tar.gz
.venv/bin/python deploy/aws/prepare_region.py \
  /tmp/vlaanderen.tar.gz vlaanderen /tmp/lusmaker-pack-check
aws s3 cp /tmp/vlaanderen.tar.gz \
  s3://<TF_STATE_BUCKET>/region-packs/vlaanderen.tar.gz \
  --sse AES256
```

S3 is hier bewust het deploymentartifact: GitHub Actions-artifacts verlopen en
zouden voor elke imagebuild opnieuw via GitHub moeten worden opgehaald.

## 4. Deploy AWS

Een push naar `main` met relevante code start deployment automatisch. Voor de
eerste of een handmatige deployment:

```bash
gh workflow run deploy-aws.yml --ref main
gh run watch
```

De workflow voert in volgorde uit:

1. download en veilige validatie van de regiopack;
2. initialisatie van S3 Terraform-state met native lockfile;
3. creatie van ECR wanneer die nog niet bestaat;
4. een linux/amd64 Lambda-image zonder multi-platform manifest;
5. push onder een immutable code-plus-pack tag;
6. resolve van de ECR digest en Terraform-plan op `repository@sha256:...`;
7. apply, gevolgd door een echte `/health` cold-start en verwachte 401's op
   MCP en web-API zonder token.

Een afgebroken deployment is retry-safe. ECR-tags zijn immutable; een bestaande
code-plus-pack tag wordt hergebruikt en Terraform deployt altijd de digest.

### Vlaamse brondata in dezelfde Lambda-image

Voor `vlaanderen` neemt de deployworkflow automatisch het open-datapack mee.
Ze hergebruikt gecontroleerde WFS-snapshots in de statebucket, bouwt de
segmentdatabase en activeert die in de image via `deploy/aws/prepare_sources.py`.
Er zijn geen WFS-downloads tijdens gebruikersrequests. De bronbuild-ID zit in
de immutable image-tag en wordt na deployment via `/health` gecontroleerd.

Bronnen bewust vernieuwen:

```bash
gh workflow run deploy-aws.yml --ref main -f refresh_route_sources=true
```

Zonder deze vlag blijven snapshots behouden. De eerste run haalt ontbrekende
bronnen op. Dit voegt bronlijnscores, wegdek en voorzieningen aan de engine toe;
nieuwe GraphHopper-voorkeurgebieden vereisen nog een afzonderlijke graafherimport.
Zie [Vlaamse routedata](VLAANDEREN-ROUTEDATA.md) voor dekking en beperkingen.

## 5. Deploy de Next.js-app naar Vercel

Gebruik Vercels native GitHub-integratie voor frontend-CD. Zo hoeft een lokaal
Vercel-token niet als GitHub secret te worden gekopieerd en verbruikt een
frontenddeploy geen GitHub Action-minuten. Configureer het project als volgt:

| Instelling | Waarde |
|---|---|
| Git repository | de Lusmaker-repository |
| Production branch | `main` |
| Root Directory | `web` |
| Framework Preset | `Next.js` |
| Output Directory | leeg (Vercel-default) |

Zet de drie waarden uit Terraform-output `vercel_environment` als Vercel
Production Environment Variables. Het zijn publieke buildwaarden, geen
secrets:

```bash
terraform -chdir=infra/terraform output -json vercel_environment
vercel env add NEXT_PUBLIC_API_URL production
vercel env add NEXT_PUBLIC_COGNITO_DOMAIN production
vercel env add NEXT_PUBLIC_COGNITO_CLIENT_ID production
vercel git connect https://github.com/owner/repository.git --yes
```

Vercel bouwt voortaan pushes naar `main`, maar `web/vercel.json` laat via
`ignoreCommand` een productiebuild alleen door als de GitHub-CI van die commit
slaagde (zie `docs/OPERATIONS.md`). Geen extra secrets nodig; de repository
moet publiek blijven. Controleer dat **Root Directory** `web` is (anders wordt
`vercel.json` niet gelezen) en dat onder **Settings -> Git** geen "Ignored
Build Step" in het dashboard is ingesteld, want die overschrijft het bestand.

`next.config.ts` zet
`output: "export"`; laat de Vercel Output Directory toch leeg, zodat de
Next.js-builder zijn vereiste `.next`-metadata kan verwerken en de statische
export publiceert. De production alias moet exact in `WEB_CALLBACK_URLS_JSON`
staan; deploy AWS opnieuw wanneer die URL wijzigt.

Lokaal:

```bash
cd web
cp .env.example .env.local
npm ci
npm run dev
```

De webclient bewaart tokens alleen in `sessionStorage`, gebruikt OAuth
authorization code + PKCE en ververst access tokens met de Cognito token-
endpoint. Publieke `NEXT_PUBLIC_*`-waarden zijn configuratie, geen secrets.

## 6. Registreer en meld aan

Initialiseer de applicatiestack lokaal tegen dezelfde backend wanneer je de
outputs of Cognito pool-ID buiten Actions nodig hebt:

```bash
terraform -chdir=infra/terraform init -reconfigure \
  -backend-config="bucket=<TF_STATE_BUCKET>" \
  -backend-config="key=lusmaker/prod/terraform.tfstate" \
  -backend-config="region=eu-west-1" \
  -backend-config="use_lockfile=true"

terraform -chdir=infra/terraform output -json vercel_environment
```

Open de Vercel-app en kies **Account maken**. Cognito verzorgt registratie,
e-mailverificatie, login, wachtwoordreset en optionele authenticator-MFA.
Iedere gebruiker krijgt op basis van Cognito `sub` een eigen S3-prefix én
afgeschermde DynamoDB-conversaties. S3-writes gebruiken preconditions om
verloren updates door gelijktijdige calls te voorkomen.

## 7. Bedrock-modeltoegang

De productiedefault (`bedrock_model_id` in Terraform) is
`openai.gpt-oss-120b-1:0`. Claude (`eu.anthropic.claude-sonnet-4-6`) is
geblokkeerd door een AWS Marketplace-betaalfout (`INVALID_PAYMENT_INSTRUMENT`)
en kan terug zodra die billing-case is opgelost; controleer dan in de Bedrock-
console van `eu-west-1` of Anthropic model access en de use-casegegevens
voltooid zijn. De Lambda-rol kan alleen het gekozen model of inference profile
aanroepen. Het Converse-contract en tool use
volgen de [officiële Bedrock Converse API](https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html).

## 8. Koppel Claude, ChatGPT of een API-client

Haal de publieke configuratie op:

```bash
terraform -chdir=infra/terraform output -raw mcp_endpoint
terraform -chdir=infra/terraform output -raw oauth_authorization_endpoint
terraform -chdir=infra/terraform output -raw oauth_token_endpoint
terraform -chdir=infra/terraform output -raw oauth_client_id
terraform -chdir=infra/terraform output -raw oauth_client_secret
```

Gebruik het `mcp_endpoint` inclusief `/mcp`. De server publiceert ook
`/.well-known/oauth-protected-resource` en geeft bij 401 een
`WWW-Authenticate` challenge met metadata-URL en scope terug. Cognito publiceert
de OpenID Connect discoverymetadata. Lusmaker valideert het access token via
Cognito en controleert daarna ook de OAuth client-ID en vereiste scope.

De stack gebruikt bewust een vooraf geregistreerde OAuth-client. Cognito biedt
geen MCP Dynamic Client Registration of Client ID Metadata Documents. Kies in
de connector daarom een vooraf geregistreerde/custom OAuth-client en vul de
Terraform-outputs voor client-ID en secret in:

- Claude ondersteunt Streamable HTTP en laat bij een server zonder DCR een
  custom client-ID en secret invullen. Voeg onder Settings → Connectors het
  MCP-endpoint toe en gebruik de vaste Claude callback. Zie [Anthropic remote
  MCP](https://support.anthropic.com/en/articles/11503834-building-custom-integrations-via-remote-mcp-servers).
- ChatGPT ondersteunt predefined OAuth clients naast CIMD en DCR. Zet eerst de
  callback uit de plugin management page in `OAUTH_CALLBACK_URLS_JSON`, deploy
  opnieuw en configureer daarna client-ID en secret. Voeg in developer mode het
  `/mcp`-endpoint toe. Zie [OpenAI plugin authentication](https://developers.openai.com/plugins/build/auth)
  en [connect and test](https://developers.openai.com/plugins/deploy/connect-chatgpt).
- Bij direct gebruik van de OpenAI Responses API of Anthropic API handelt je
  applicatie de OAuth-flow af en geeft ze de verkregen access token als MCP
  authorization token door.

Voor een toekomstige publieke plugin waarbij CIMD of DCR verplicht is, vervang
Cognito door een authorization server die één van die registratievormen én
OAuth resource indicators ondersteunt, of plaats zo'n broker voor Cognito. De
MCP-resource- en tenantlaag hoeft daarvoor niet te veranderen.

## Security en beheer

- De Function URL is op AWS-niveau `NONE`, omdat ChatGPT en Claude geen SigV4
  spreken en de browser een Cognito JWT gebruikt. Alle paden behalve health,
  OAuth-metadata en CORS preflight worden in de app met Cognito bearer tokens
  afgeschermd. CORS accepteert alleen origins uit de webcallbacks en expliciete
  extra origins.
- S3 blokkeert public access, vereist TLS en versleutelt server-side. De Lambda-
  rol mag alleen onder `tenants/*` lezen en schrijven.
- DynamoDB gebruikt on-demand billing en server-side encryption. API-queries
  controleren gesprekseigenaarschap vóór ze de message-partitie lezen.
- Bedrock krijgt maximaal twintig historische berichten, 4.000 tekens per
  prompt, 1.400 outputtokens en vijf toolrondes per request.
- De GitHub-rol is aan de exacte repository/branch-subjects gebonden. De rol
  heeft deploymentrechten, maar geen statische sleutels.
- De hosted MCP exposeert geen `ensure_region`: een Lambda-image is immutable.
  Regiowijzigingen lopen uitsluitend via de gecontroleerde buildworkflow.
- ECR bewaart vijf releases; ongetagde lagen verlopen na één dag. S3 verwijdert
  oude objectversies na dertig dagen. Logs verlopen standaard na zeven dagen.
- GPX en preview blijven private MCP-resources en worden nooit als publieke S3-
  URL geretourneerd.

## Bekende operationele grenzen

- De eerste call na scale-to-zero kan lang duren door graph-copy en JVM-start.
  Een keep-warm schedule zou dit verminderen, maar introduceert bewust idle
  compute en staat daarom niet standaard aan.
- Eén image bevat één regio. Routes over regiogrenzen heen vereisen een grotere
  vooraf gebouwde pack of later een aparte functie per regio.
- De 15-minutenlimiet is hard. Splits langdurige routejobs later op via SQS en
  Step Functions wanneer echte prompts die grens bereiken; voeg die pas toe als
  de synchrone meetdata dat nodig maakt.
- Budgetmeldingen vereisen een geldig `BILLING_EMAIL` en stoppen resources niet
  automatisch.

## Teardown

Data en images worden standaard beschermd tegen een toevallige destroy. Voor
een bewuste, volledige verwijdering zet je beide force-variabelen alleen voor
die destroy op `true`:

```bash
terraform -chdir=infra/terraform destroy \
  -var='oauth_callback_urls=["https://claude.ai/api/mcp/auth_callback"]' \
  -var='web_callback_urls=["https://ommeke.vercel.app/"]' \
  -var=force_destroy_data=true \
  -var=force_destroy_ecr=true \
  -var=protect_user_data=false
```

Dit verwijdert gebruikersdata en images permanent. Verwijder de bootstrap pas
nadat de applicatiestack weg is en je de Terraform-state niet meer nodig hebt.

## Altijd-warme GraphHopper (issue #19)

Besluit: [0002 — warme GraphHopper](decisions/0002-warme-graphhopper.md).
`gh_service_enabled=false` is de Terraform-standaard: alle nieuwe resources
én lookups hebben count 0 en de Lambda-omgeving blijft gelijk. De deployment
gebruikt repositoryvariabele `GH_SERVICE_ENABLED`, standaard `false`.

Met `true`: één Amazon Linux 2023 x86_64 EC2 (standaard `t3.large`) in een
subnet van de default VPC met publiek IPv4/DNS, een versleuteld gp3-graphvolume
(standaard 40 GB) en een gp3-rootvolume van 16 GB. Het instanceprofile mag
uitsluitend `s3:GetObject` op
`s3://<TF_STATE_BUCKET>/region-packs/<slug>.tar.gz`. De instance downloadt
hetzelfde pack als de workflow, controleert SHA256, slug en GH-image, en
weigert persoonlijke heat. Elke pack-SHA krijgt een eigen map op het volume.
Een herstart behoudt graph-cache en LM-preparatie; een nieuwe pack-SHA vervangt
de instantie en activeert een nieuwe cache. Oude caches blijven op het volume;
controleer vrije ruimte bij packwissels. De rootdisk bevat geen graph-cache.

Docker draait `israelhikingmap/graphhopper:11.0`, uitsluitend op loopback:8989.
De serviceconfig is afgeleid van de packconfig, met `profiles_lm` voor `quiet`
en `trail` en MMAP; de packconfig en lokale engineconfig worden niet gewijzigd.
CH blijft uit wegens request-time custom models. Alle activiteit- en
voorkeursregels straffen alleen (priority-factor > 0 en ≤ 1), afgedwongen door
offline tests; ongeldige vermijdfactoren worden geweigerd. **LM-preparatieduur
en piekgeheugen: te meten** op EC2. De JVM start met `-Xms1g -Xmx5g` op een
8 GB-instance. Een eerste start kan langer duren dan de smoke-timeout van
900 s; wacht dan op voltooide voorbereiding en herhaal de smoke-test.

CloudFront gebruikt het standaard `*.cloudfront.net`-certificaat, HTTPS voor
clients, HTTP naar originpoort 80, alle methodes en geen caching. Het geeft
`X-Ommeke-Origin` van de client door; het voegt het geheim niet zelf toe.
nginx weigert elk verzoek zonder het juiste geheim. De security group laat
poort 80 uitsluitend toe vanaf AWS-managed prefix list
`com.amazonaws.global.cloudfront.origin-facing`; SSH en de GH-poort zijn dicht.
De default SG-quota moet het prefix-listgewicht (55 regels) kunnen dragen.
De Lambda krijgt de CloudFront-URL en het `random_password`-geheim als
`LUSMAKER_GH_URL` en `LUSMAKER_GH_ORIGIN_SECRET`. Route, info en health sturen
de header mee. `/health?router=1` controleert in beide standen de gekozen GH.
Alleen `gh_service_url` is een output; het geheim heeft geen output of logregel.
Terraform-state/plan, EC2-user-data en de nginx-config bevatten wel het geheim;
beperk beheertoegang. CloudFront/nginx-accesslogging staat uit.

Kostenraming door de eigenaar goedgekeurd: t3.large on-demand eu-west-1
**≈ $0,0912/u, ≈ $67/maand**, plus gp3 (40 GB graph + 16 GB root), CloudFront,
publiek IPv4 en eventuele T3 CPU-creditkosten. Dit is de afgesproken raming,
geen tijdens deze wijziging opgezochte offerte. Controleer vóór uitrol de
accountquota en het budget (huidige Terraform-standaard $50/maand).

### Uitrol door de eigenaar

0. Controleer vóór deployment op een machine met providerdownload-toegang:
   ```sh
   terraform -chdir=infra/terraform init -backend=false
   terraform -chdir=infra/terraform validate
   terraform -chdir=infra/terraform providers lock -platform=linux_amd64 -platform=darwin_arm64
   ```
   `random` is exact gepind op 3.8.1 met lockfile-checksums. Beide stacks zijn
   tijdens deze implementatie offline gevalideerd met reeds gecachte providers;
   CI initialiseert met `-lockfile=readonly`.
1. Pas de gewijzigde bootstrap één keer toe met een **adminidentiteit** (de
   deployrol kan zijn eigen rechten niet uitbreiden):
   ```sh
   terraform -chdir=infra/bootstrap init -backend=false
   terraform -chdir=infra/bootstrap plan -out=bootstrap.tfplan
   terraform -chdir=infra/bootstrap apply bootstrap.tfplan
   ```
   Gebruik de bestaande bootstrap-state en bestaande `terraform.tfvars` voor
   het juiste account; geen nieuwe lege state voor bestaande resources.
   De policy voegt gerichte EC2- en CloudFront-acties en instanceprofilebeheer
   toe; `iam:PassRole` voor de GH-rol is beperkt tot `ec2.amazonaws.com`.
2. Controleer dat het regiopack onder `TF_STATE_BUCKET/region-packs/<slug>.tar.gz`
   staat (zo nodig *Build region pack* uitvoeren). Zet GitHub-repositoryvariabelen
   `GH_SERVICE_ENABLED=true`, optioneel `GH_INSTANCE_TYPE=t3.large` en
   `GH_VOLUME_SIZE_GB=40`. `TF_STATE_BUCKET` blijft dezelfde bestaande bucket.
   Bij handmatige Terraform: `TF_VAR_gh_service_enabled=true`,
   `TF_VAR_gh_pack_bucket=<bucket>`, `TF_VAR_gh_pack_sha256=<pack-sha256>` en
   desgewenst `TF_VAR_gh_instance_type` / `TF_VAR_gh_volume_size_gb`.
3. Start **Deploy AWS** op de gereviewde main-versie, zonder rollback-digest.
   De workflow valideert het pack en neemt de SHA op in user-data. Bekijk het
   plan: EC2, volume, SG, instanceprofile, CloudFront en twee extra Lambda-envvars.
   Laat de workflow deployen en de bestaande smoke-test uitvoeren.
4. Controleer bij een eerste start via de EC2-console/cloud-init- en
   GraphHopper-servicelogs of LM-preparatie klaar is; toon nooit user-data of
   nginx-config in logs. Herhaal zo nodig:
   ```sh
   curl --fail --show-error --max-time 900 '<health_endpoint>?router=1'
   ```
   Controleer afzonderlijk dat `<gh_service_url>/info` zonder header 403 geeft.
5. Meet dezelfde representatieve routes (incl. 60 km klimroute), p50/p95,
   routertijd, koude API-start, CPU/credits en geheugengebruik. Leg ook
   LM-preparatieduur en piekgeheugen vast; beide zijn **te meten**.
6. Verlaag pas daarna `lambda_memory_mb` stapsgewijs en meet opnieuw. De workflow
   accepteert hiervoor `LAMBDA_MEMORY_MB` (standaard 3008, huidige ondergrens
   1769 MB). Er wordt in deze wijziging nog geen geheugenverlaging uitgevoerd.

Rollback: zet `GH_SERVICE_ENABLED=false` en voer **Deploy AWS** opnieuw uit
met het huidige compatibele image. Zet `LAMBDA_MEMORY_MB` eerst terug op 3008
als dit na metingen verlaagd was. Lambda start dan weer de ingebouwde GH;
de opt-in resources, inclusief het graphvolume, worden verwijderd. CloudFront
uitschakelen/verwijderen kan tijd kosten. De bronpack in S3 blijft bestaan.
Een image-digestrollback verandert de routerkeuze niet: de schakelaar bepaalt
het pad, en de EC2-router gebruikt het huidige gevalideerde S3-pack.
