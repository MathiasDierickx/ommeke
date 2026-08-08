# Lusmaker op AWS

Deze stack deployt Lusmaker als een authenticated remote MCP-app. De productie-
compute bestaat uit één Lambda-container met twee processen: GraphHopper op
localhost en de Lusmaker ASGI/MCP-server via de AWS Lambda Web Adapter.
GraphHopper en de routegegevens zijn vooraf in het image gebouwd; een request
downloadt of importeert nooit kaartdata.

## Architectuur

```text
ChatGPT / Claude / MCP-client
              │ HTTPS + OAuth access token
              ▼
      Lambda Function URL              Cognito hosted OAuth
              │                              │
              ▼                              │ GetUser
 AWS Lambda Web Adapter                      │
              │                              │
              ▼                              ▼
      Lusmaker ASGI/MCP ─────────────── tenant = Cognito sub
              │
       ┌──────┴───────────┐
       ▼                  ▼
 GraphHopper         S3 tenant-state
 in hetzelfde        drafts, profielen,
 Lambda-image        GPX en previews
```

Terraform maakt aan:

- één ECR-repository met immutable images en lifecycle-retentie;
- één Lambda zonder provisioned concurrency, maximaal vijftien minuten per
  request en standaard maximaal één gelijktijdige execution;
- een Function URL met response streaming;
- een Cognito user pool, hosted OAuth-domain en vooraf geregistreerde client;
- een private, versleutelde en geversioneerde S3-bucket voor tenant-state;
- een CloudWatch-loggroep met korte retentie;
- optioneel een maandelijks AWS Budget met e-mailmeldingen;
- in de bootstrap-stack: een private Terraform-statebucket en een branch-
  gebonden GitHub OIDC-deployrol.

Er zijn bewust geen VPC, NAT Gateway, API Gateway, EFS, EC2, ECS/Fargate of
provisioned Lambda instances.

## Wat “scale to zero” hier betekent

Als niemand Lusmaker gebruikt, draait er geen compute. `max_concurrency` is een
kosten- en capaciteitsplafond; het warmt of reserveert geen Lambda-instances.
Een cold start kopieert de read-only GraphHopper-cache naar Lambda `/tmp`, start
GraphHopper en opent daarna pas de MCP-server. `AWS_LWA_ASYNC_INIT` laat die
opstart binnen de Lambda-timeout doorlopen.

AWS wordt niet letterlijk kosteloos wanneer de app idle is. ECR bewaart het
containerimage, S3 bewaart Terraform-state, het regiopack en gebruikersdata, en
CloudWatch bewaart logs. Dat zijn doorgaans kleine opslagkosten, maar geen
vaste compute-kosten. Een invocation met 10 GB geheugen die lang loopt kan wel
materieel kosten; de concurrency-cap en het optionele budget begrenzen en
signaleren dat risico. Een AWS Budget is een alarm, geen harde spend-stop.

Relevante harde AWS-grenzen zijn een containerimage van maximaal 10 GB
uncompressed, maximaal 10 GB `/tmp` en een Lambda-timeout van 15 minuten. Maak
een kleinere regiopack wanneer graph plus runtime daar niet binnen passen. Zie
de [AWS Lambda quota's](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html)
en de [Lambda Web Adapter](https://github.com/awslabs/aws-lambda-web-adapter).

## Vereisten

- een AWS-account en lokaal werkende AWS CLI-credentials voor de eenmalige
  bootstrap;
- Terraform 1.10 of nieuwer;
- een GitHub-repository waarvan `main` de deploymentbranch is;
- GitHub Actions op een runner met voldoende disk en geheugen om één keer de
  regiograph te bouwen;
- een concrete OAuth callback. Voor Claude is dit
  `https://claude.ai/api/mcp/auth_callback`. ChatGPT toont per pluginverbinding
  een URL van de vorm `https://chatgpt.com/connector/oauth/{callback_id}`.

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
| `BILLING_EMAIL` | nee | `aws-kosten@example.com` |

Met de GitHub CLI:

```bash
gh variable set AWS_DEPLOY_ROLE_ARN --body '<role-arn>'
gh variable set TF_STATE_BUCKET --body '<bucketnaam>'
gh variable set AWS_REGION --body 'eu-west-1'
gh variable set LUSMAKER_REGION_SLUG --body 'vlaanderen'
gh variable set OAUTH_CALLBACK_URLS_JSON \
  --body '["https://claude.ai/api/mcp/auth_callback"]'
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
  -f bbox=50.68,3.35,51.10,4.20
```

Volg de run met `gh run watch`. De resulterende locatie is
`s3://<TF_STATE_BUCKET>/region-packs/vlaanderen.tar.gz`.

Dit is de enige zware build. Gewone codewijzigingen hergebruiken het pack. Een
bewuste data-, GraphHopper- of profielupgrade vereist een nieuwe pack-run. De
pack en de runtime zijn beide op GraphHopper 11.0 gepind; een pack van een
andere engineversie wordt tijdens deployment geweigerd.

Een GitHub-hosted runner kan voor een grotere regio onvoldoende geheugen of
disk hebben. Gebruik dan dezelfde workflow op een grotere self-hosted runner;
de uiteindelijke AWS-runtime blijft volledig serverless.

## 4. Deploy

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
7. apply, gevolgd door een echte `/health` cold-start en een verwachte 401 op
   een MCP-call zonder token.

Een afgebroken deployment is retry-safe. ECR-tags zijn immutable; een bestaande
code-plus-pack tag wordt hergebruikt en Terraform deployt altijd de digest.

## 5. Maak een gebruiker

Initialiseer de applicatiestack lokaal tegen dezelfde backend wanneer je de
outputs of Cognito pool-ID buiten Actions nodig hebt:

```bash
terraform -chdir=infra/terraform init -reconfigure \
  -backend-config="bucket=<TF_STATE_BUCKET>" \
  -backend-config="key=lusmaker/prod/terraform.tfstate" \
  -backend-config="region=eu-west-1" \
  -backend-config="use_lockfile=true"

POOL_ID=$(terraform -chdir=infra/terraform output -raw cognito_user_pool_id)
aws cognito-idp admin-create-user \
  --user-pool-id "$POOL_ID" \
  --username fietser@example.com \
  --user-attributes Name=email,Value=fietser@example.com Name=email_verified,Value=true \
  --desired-delivery-mediums EMAIL
```

Zelfregistratie staat uit. Iedere geauthenticeerde gebruiker krijgt een eigen
S3-prefix op basis van Cognito `sub`; drafts, profielen en artifacts worden dus
niet tussen accounts gedeeld. Writes gebruiken S3 preconditions om verloren
updates door gelijktijdige tool calls te voorkomen.

## 6. Koppel Claude, ChatGPT of een API-client

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
  spreken. Alle paden behalve health, OAuth-metadata en CORS preflight worden
  in de app met Cognito bearer tokens afgeschermd.
- S3 blokkeert public access, vereist TLS en versleutelt server-side. De Lambda-
  rol mag alleen onder `tenants/*` lezen en schrijven.
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
  -var=force_destroy_data=true \
  -var=force_destroy_ecr=true
```

Dit verwijdert gebruikersdata en images permanent. Verwijder de bootstrap pas
nadat de applicatiestack weg is en je de Terraform-state niet meer nodig hebt.
