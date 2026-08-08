# Lusmaker als Claude-app en ChatGPT-app — plan

*Onderzocht 2026-08-08. Beide platformen zijn geconvergeerd op remote MCP;
~80% van het werk is gedeeld fundament.*

## Wat beide platformen eisen (gedeeld fundament → T17)

| eis | status | werk |
|---|---|---|
| Streamable HTTP-transport over HTTPS | ❌ lus-mcp is stdio | FastMCP streamable-http-modus + uvicorn |
| OAuth 2.1 + PKCE, interactieve user-consent | ❌ | resource-server-kant bij ons (bearer-validatie + discovery-RFC's); IdP/domein bij het AWS-deploymentspoor |
| Multi-user: per-gebruiker drafts/profielen/exports | ❌ alles globaal | user-scoping `<HOME>/users/<uid>/` (regio's/graven/heat blijven gedeeld) |
| Tool-annotaties: title + readOnlyHint/destructiveHint per tool | ❌ | in mcp_contracts.py; **doorslaggevend bij Claude-review** |
| Exports als HTTPS-URL i.p.v. lokaal pad | ❌ | export-endpoint; URL's in tool-output |
| Publieke privacy policy | ❌ | **instant-reject bij Claude zonder**; GDPR-basics (profielen = persoonsdata) |
| Reviewer-testaccount | ❌ | bij OAuth-oplevering regelen |

## Claude-specifiek

- Indienen via het submission-portal in Claude.ai-adminsettings
  ([docs](https://claude.com/docs/connectors/building/submission)).
- OAuth: interactieve flow verplicht; client_credentials wordt NIET
  ondersteund; start met oauth_cimd of oauth_dcr
  ([sunpeak-analyse](https://sunpeak.ai/blogs/claude-connector-oauth-authentication/)).
- Reviewfocus: annotaties + privacy policy
  ([sunpeak](https://sunpeak.ai/blogs/claude-connector-directory-submission/)).
- Lokale stdio-modus blijft bestaan (Claude Desktop/Code zonder OAuth).

## ChatGPT/OpenAI-specifiek

- Apps SDK = MCP + optionele component-UI in ChatGPT
  ([Apps SDK](https://help.openai.com/en/articles/12515353-build-with-the-apps-sdk),
  [submission open](https://openai.com/index/developers-can-now-submit-apps-to-chatgpt/)).
- Identiteitsverificatie (individu of bedrijf) in het OpenAI-dashboard VOOR
  indiening; domeincontrole van de MCP-server-host verplicht
  ([guidelines](https://developers.openai.com/apps-sdk/app-submission-guidelines),
  [praktijknotities](https://3minapi.com/blog/building-chatgpt-app-with-apps-sdk)).
- Review ~1-2 weken.
- **Kans**: component-template met de kaartpreview inline in de chat — onze
  preview.render is al zelfstandige HTML; ombouwen naar Apps-SDK-component
  (window.openai-bridge) = T18, af te stemmen met het UI-spoor.

## Volgorde

1. **T17** (dit spoor, worktree `platform-apps`): remote transport,
   user-scoping, bearer-validatie-interface, annotaties, export-URL's.
2. AWS-spoor levert: domein + TLS, IdP (bv. Cognito: issuer/JWKS/audience via
   env), hosting van exports.
3. Privacy policy + ToS schrijven; reviewer-testaccounts.
4. Claude-submission (annotaties af) → parallel OpenAI-verificatie starten
   (doorlooptijd) → T18-component → ChatGPT-submission.

## Beslissingen (voorstel)

- Persoonlijk vs gedeeld: drafts/profielen/exports per gebruiker; regio's,
  klim-DB, heat-lagen en GH-graven gedeeld (dat is de kostenstructuur die
  hosted haalbaar maakt — zie PRODUCT.md M7).
- Token-validatie pluggable (env: `LUSMAKER_OAUTH_ISSUER`,
  `LUSMAKER_OAUTH_JWKS_URL`, `LUSMAKER_OAUTH_AUDIENCE`); geen eigen
  authorization-server bouwen.
- Lite-toolset is de default voor beide directories (tokenkosten + review-
  eenvoud); volle set achter een env-vlag.
