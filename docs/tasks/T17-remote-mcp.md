# T17 — Remote MCP-fundament (Claude-app + ChatGPT-app)

Zie docs/platforms-plan.md voor de context. Dit is het gedeelde fundament;
IdP/domein/hosting komen uit het AWS-spoor (interface via env-vars).

## 1. Streamable HTTP-transport

- `lus-mcp --http [--host 0.0.0.0] [--port 8123]`: FastMCP streamable-http.
  stdio blijft default (Claude Desktop/Code lokaal, geen auth).
- Lite-set default in http-modus; `--full` voor alles (en stdio blijft vol,
  huidig gedrag).

## 2. Multi-user scoping

- Nieuw contextmechanisme in config: `user_scope(uid)` — drafts, profiles en
  exports resolven naar `<HOME>/users/<uid>/{drafts,profiles,exports}`;
  uid "local" = de huidige paden (backwards compat, stdio-modus).
  Regio's/caches/heat/GH blijven gedeeld (ongewijzigde paden).
- uid-bron in http-modus: het gevalideerde token-subject (zie 3);
  ongeauthenticeerd http-verzoek → 401.
- Draft-id's blijven per-user uniek; geen cross-user toegang mogelijk
  (pad-scoping volstaat, maar valideer draft-id-format tegen path traversal).

## 3. Bearer-validatie (pluggable, geen eigen AS)

- Env: `LUSMAKER_OAUTH_ISSUER`, `LUSMAKER_OAUTH_JWKS_URL`,
  `LUSMAKER_OAUTH_AUDIENCE`. JWT-validatie (RS256 via JWKS, exp/aud/iss) —
  implementeer met een kleine eigen module bovenop `python-jose` of puur
  (voorkeur: dependency `PyJWT[crypto]`; noteer de toevoeging in pyproject).
- Discovery: OAuth 2.0 Protected Resource Metadata (RFC 9728) endpoint
  `/.well-known/oauth-protected-resource` dat naar de issuer verwijst —
  vereist door de MCP-spec/Claude.
- `LUSMAKER_AUTH_DISABLED=1` voor lokaal http-testen (uid "local").

## 4. Tool-annotaties (reviewkritiek bij beide platformen)

In mcp_contracts.py per tool: `title` (NL, kort) + annotaties:
- readOnlyHint=true: status, geocode, list_climbs, get_draft, list_drafts,
  get_profile, list_profiles, route_readiness*, region_status, route_details,
  list_regions, suggest_climbs
- destructiveHint=false, readOnlyHint=false (muterend maar niet destructief):
  new_draft, add/remove_climb, avoid/unavoid_place, route_draft,
  optimize_draft, plan_route, adjust_route, update_profile, export_gpx,
  preview_draft, ensure_region
- route_readiness doet GH-calls maar muteert alleen probe-cache → readOnly.

## 5. Export-URL's

- In http-modus krijgen export_gpx/preview_draft/plan_route een URL terug
  i.p.v. lokaal pad: bestanden landen in de user-scope exports-map en worden
  geserveerd op `GET /files/<uid-token-gebonden pad>` binnen dezelfde app
  (auth verplicht; uid uit token moet matchen). Basis-URL uit env
  `LUSMAKER_PUBLIC_URL` (het AWS-spoor zet die).
- stdio-modus: paden zoals nu.

## Tests (puur)

- user_scope-padresolutie + traversal-afwijzing + local-fallback.
- JWT-validatie met zelfgemaakte sleutel/JWKS-fixture (geldig, verlopen,
  verkeerde audience) — geen netwerk.
- annotaties: elke tool heeft title + hint; readonly-lijst klopt.
- export-URL-opbouw in http-modus vs pad in stdio-modus (injecteerbare mode).
- Cassettes blijven groen.

## Let op

- Werk op branch `platform-apps` in DEZE worktree; niet naar main mergen.
- Ander agent-werk op main: niet relevant hier, maar géén bestanden
  verwijderen die je niet kent.
- Vroeg en klein committen; niet pushen; geen netwerk/docker.
