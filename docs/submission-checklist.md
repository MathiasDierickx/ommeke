# Submission-checklist: Claude-connector + ChatGPT-app

*Stappen met [MENS] vereisen Mathias; de rest is code/config die er al is of
uit het AWS-spoor komt. Volgorde is geoptimaliseerd op doorlooptijd.*

## Nu al starten (doorlooptijd!)

- [ ] [MENS] OpenAI Platform Dashboard: identiteits- of bedrijfsverificatie
      starten (vereist vóór indiening; naamkeuze = publicatienaam).
- [ ] [MENS] Juridische review van `docs/legal/privacy-policy.md` en
      `terms.md`; bedrijfsgegevens/termijnen invullen.
- [ ] [MENS] Naamcheck "Lusmaker" (merk/handelsnaam, domein definitief).

## Uit het AWS-spoor (zie docs/INTEGRATIE-AWS.md)

- [ ] Publiek domein + TLS voor `lus-mcp --http` (bv. mcp.lusmaker.app)
- [ ] IdP met interactieve OAuth 2.1 + PKCE (géén client_credentials;
      DCR of CIMD aanbevolen voor Claude)
- [ ] Env's gezet: `LUSMAKER_OAUTH_ISSUER/JWKS_URL/AUDIENCE`,
      `LUSMAKER_PUBLIC_URL`
- [ ] `/privacy` en `/terms` publiek (na juridische review)
- [ ] 2 reviewer-testaccounts in de IdP
- [ ] Rate limiting aan de rand

## Claude-connectordirectory

- [x] Streamable HTTP-transport (T17)
- [x] Tool-annotaties: titles + readOnly/destructive-hints, alle tools (T17)
- [x] RFC 9728 protected-resource-metadata (T17)
- [x] 401 zonder token; bearer-JWT-validatie (T17)
- [ ] End-to-end OAuth-flow testen met echte IdP (na AWS-spoor)
- [ ] [MENS] Indienen via het submission-portal in Claude.ai-adminsettings:
      beschrijving (NL/EN), logo, privacy-URL, testaccount-credentials,
      voorbeeldprompts ("plan een lus van 45 km vanuit Wetteren…")
- [ ] Verwachte reviewfocus: annotaties + privacy policy (beide afgedekt)

## ChatGPT-appdirectory

- [x] MCP-server (zelfde als Claude) + lite-toolset
- [ ] T18: component-template (inline kaartpreview) — in uitvoering
- [ ] [MENS] Domeincontrole-verificatie van de MCP-host in het
      OpenAI-dashboard
- [ ] [MENS] Submission: MCP-URL, testinstructies, directory-metadata,
      landenbeschikbaarheid, screenshots
- [ ] Review duurt ~1-2 weken; screenshots/testcases kunnen terugkomen

## Definition of done per platform

- Claude: connector installeerbaar vanuit de directory; OAuth-consent →
  vraag "plan een lus van 45 km vanuit Wetteren" → readiness-vragen →
  route + preview-link.
- ChatGPT: idem, met de kaartpreview inline als component.
