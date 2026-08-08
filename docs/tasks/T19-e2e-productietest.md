# T19 — End-to-end-productietest zonder UI

## Waarom

Het "vastlopen" van 2026-08-08 kostte handmatige curl-archeologie: token,
conversatie, bericht, Bedrock-fout. Dit hoort één commando te zijn dat de
volledige gedeployde keten test en per stap groen/rood rapporteert.

## Commando

```
python -m tests.e2e_prod [--api URL] [--verbose]
```

Config via env (defaults uit args): `LUSMAKER_E2E_API` (Function-URL),
`LUSMAKER_E2E_POOL_ID`, `LUSMAKER_E2E_CLIENT_ID`, `LUSMAKER_E2E_USERNAME`,
`LUSMAKER_E2E_PASSWORD`, `LUSMAKER_E2E_REGION` (default eu-west-1).
GEEN AWS-credentials nodig: login als echte eindgebruiker.

## Stappen (elke stap → OK/FOUT + duur; doorgaan na fout waar zinvol)

1. `GET /health` → status ok (ruime timeout: cold start tot 120 s).
2. `POST /mcp` zonder token → verwacht 401.
3. `GET /.well-known/oauth-protected-resource` → geldige RFC 9728-metadata.
4. Cognito-login via SRP met `pycognito` (nieuwe optionele dependency:
   `[project.optional-dependencies] e2e = ["pycognito"]`; de runner geeft een
   duidelijke installatiehint als het pakket ontbreekt). Levert access token.
5. `GET /api/conversations` met token → 200.
6. `POST /api/conversations` → 201, conversation-id.
7. `POST /api/conversations/<id>/messages` met
   `{"content": "maak een lus van 30 km vanuit Wetteren"}`; timeout 600 s.
   - 200 → assert `message` + `route_ids` aanwezig.
   - 502/`model_unavailable` → stap FOUT met duidelijke uitleg
     ("Bedrock-modeltoegang: check use-case-formulier/betaalmethode"),
     maar vervolgstappen die ervan afhangen worden SKIP i.p.v. FOUT.
8. Bij route_ids: `GET /api/routes/<laatste>` → route met gpx/preview-refs;
   haal die bestanden op met token → 200 en niet-leeg; GPX begint met
   `<?xml`.
9. MCP mét token: initialize + tools/list (streamable HTTP, sessieheader) →
   lite-toolset aanwezig (bevat plan_route).
10. Eindrapport: tabel stap/status/duur; exit 0 alleen als alles OK
    (SKIP telt niet als fout wanneer de veroorzakende stap al FOUT gaf —
    exit 1 blijft dan door die stap).

## Implementatie

- `tests/e2e_prod.py`, zelfstandig (urllib + pycognito), geen imports uit
  lusmaker-runtime nodig behalve niets — houd hem los zodat hij ook tegen
  een oudere deploy kan draaien.
- Nederlandse output, zelfde toon als tests/live_smoke.
- Documenteer in README (sectie "Productie testen") en in
  docs/INTEGRATIE-AWS.md (CI-hook-suggestie: post-deploy-stap in
  deploy-aws.yml met secrets; alleen documenteren, niet aanpassen — de
  workflow is van het AWS-spoor).

## Pure tests (wel in tests.run)

`tests/test_e2e_prod.py`: staporkestratie met geïnjecteerde HTTP/auth-stubs —
volgorde, SKIP-cascade na model-FOUT, exitcode-logica, 401-verwachting,
GPX-validatie. Geen netwerk.

## DoD

Suite groen; de reviewer draait de runner live tegen prod (verwacht: alles
groen behalve stap 7 zolang de betaalmethode ontbreekt). Kleine commits;
push mag niet vanuit jouw sandbox (reviewer pusht).
