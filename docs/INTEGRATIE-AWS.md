# Integratiecontract: platform-apps ⇄ AWS/UI-spoor

*Voor de agent/collega die de AWS-deployment en UI bouwt. Branch
`platform-apps` levert de remote-MCP-server; dit document is de interface.*

## Wat platform-apps levert (na T17)

- `lus-mcp --http --host 0.0.0.0 --port 8123`: streamable-HTTP MCP-server
  (lite-toolset default), plus:
  - `/.well-known/oauth-protected-resource` (RFC 9728, verwijst naar issuer)
  - `GET /files/...` voor GPX/preview-exports (auth verplicht, user-gescoped)
  - Bearer-JWT-validatie (RS256 via JWKS)
- Multi-user opslag onder `<LUSMAKER_HOME>/users/<sub>/` — drafts, profielen
  en exports per gebruiker; regio's/graven/heat gedeeld zoals nu.
- Tool-annotaties conform Claude/OpenAI-revieweisen.

## Wat het AWS-spoor moet leveren

| # | wat | details |
|---|---|---|
| 1 | Publiek domein + TLS voor de MCP-server | bv. `mcp.lusmaker.app`; OpenAI eist domeincontrole-verificatie |
| 2 | OAuth-IdP met **interactieve** flow | Claude ondersteunt géén client_credentials; authorization-code + PKCE vereist. Cognito (hosted UI) of Auth0 passen. Dynamic Client Registration (oauth_dcr) of CIMD wordt door Claude aanbevolen |
| 3 | Env-vars naar de container | `LUSMAKER_OAUTH_ISSUER`, `LUSMAKER_OAUTH_JWKS_URL`, `LUSMAKER_OAUTH_AUDIENCE`, `LUSMAKER_PUBLIC_URL` (basis-URL voor export-links), `LUSMAKER_HOME` |
| 4 | Persistente volumes | `LUSMAKER_HOME` (regio-data + users); GH-containers per regio zoals docker-compose.regions.yml |
| 5 | GraphHopper naast de MCP-container | zelfde compose/taskdef; `LUSMAKER_GH_URL`-patroon per regio zoals nu |
| 6 | Statische hosting van `/privacy` en `/terms` | concepten staan in `docs/legal/` (eerst juridische review!) |
| 7 | Twee reviewer-testaccounts in de IdP | vereist door zowel Claude- als OpenAI-review |
| 8 | Rate limiting aan de rand | aanbevolen: per-user op ALB/API GW-niveau; de app zelf throttlet niet |

## Niet in scope van platform-apps

- IdP-configuratie zelf, DNS, certificaten, CI/CD.
- De web-UI: staat los; de MCP-server is een aparte service.

## Productie-E2E als post-deploy-hook

`python -m tests.e2e_prod` controleert de gedeployde Function-URL als echte
Cognito-eindgebruiker, inclusief Bedrock-chat, route-artifacts en MCP. De
runner gebruikt geen AWS-credentials. Voor CI zijn een afzonderlijk
testaccount en de volgende repositorysecrets nodig:

- `LUSMAKER_E2E_POOL_ID`;
- `LUSMAKER_E2E_CLIENT_ID`;
- `LUSMAKER_E2E_USERNAME`;
- `LUSMAKER_E2E_PASSWORD`.

Na de bestaande deploy- en publieke smoke-stappen kan `deploy-aws.yml` later
deze hook krijgen. Dit is alleen de voorgestelde integratie; de workflow blijft
eigendom van het AWS-spoor:

```yaml
- name: Test volledige productieketen
  env:
    LUSMAKER_E2E_POOL_ID: ${{ secrets.LUSMAKER_E2E_POOL_ID }}
    LUSMAKER_E2E_CLIENT_ID: ${{ secrets.LUSMAKER_E2E_CLIENT_ID }}
    LUSMAKER_E2E_USERNAME: ${{ secrets.LUSMAKER_E2E_USERNAME }}
    LUSMAKER_E2E_PASSWORD: ${{ secrets.LUSMAKER_E2E_PASSWORD }}
    LUSMAKER_E2E_REGION: ${{ vars.AWS_REGION || 'eu-west-1' }}
  run: |
    python -m pip install --disable-pip-version-check -e '.[e2e]'
    LUSMAKER_E2E_API="$(terraform -chdir=infra/terraform output -raw api_endpoint)" \
      python -m tests.e2e_prod
```

Activeer deze blokkerende stap zodra het Bedrock-model voor productie is
vrijgegeven. Tot dan rapporteert stap 7 bewust `FOUT` met de modeltoegang-hint
en wordt alleen de daarvan afhankelijke artifactcontrole `SKIP`.

## Afstemming

- Beide sporen raken `pyproject.toml` mogelijk (deps). Bij merge naar main:
  kleine conflicten verwacht in pyproject/README — inhoudelijk onafhankelijk.
- Compose-pinning: main pint `israelhikingmap/graphhopper:11.0` in
  docker-compose.yml; de generator in `lusmaker/regions.py` schrijft nog
  `latest` — als pinning beleid is, ook daar aanpassen (één regel).
