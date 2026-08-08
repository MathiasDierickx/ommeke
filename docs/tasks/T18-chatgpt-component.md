# T18 — ChatGPT Apps-component: kaartpreview inline in de chat

## Waarom

De Apps SDK laat een MCP-tool een UI-component meegeven die ChatGPT inline
rendert. Onze kaartpreview is het "wow"-moment; inline > link.

## Wat er moet komen

1. **Componentbestand** `lusmaker/appsdk/preview-component.html`:
   herbruik van de bestaande preview-opbouw (Leaflet, legs, klimmen,
   hoogteprofiel) maar dan:
   - data NIET ingebakken maar uit `window.openai.toolOutput` (het
     structuredContent van de tool-call);
   - hoogte beperkt (~480 px) met fullscreen-knop via
     `window.openai.requestDisplayMode`;
   - geen externe calls behalve OSM-tiles en unpkg-Leaflet (toegestaan in
     component-iframes; documenteer de CSP-noot).
2. **Tool-meta in http-modus** (mcp_contracts.py / mcp_server.py):
   - `preview_draft` en `plan_route` krijgen in hun tool-descriptor
     `_meta["openai/outputTemplate"] = "ui://widget/lusmaker-preview.html"`;
   - de server registreert die resource (MCP resource met het component-
     HTML) — alleen wanneer de server in http-modus draait met
     `LUSMAKER_APPS_SDK=1` (geen effect op Claude/stdio).
   - `structuredContent` van die tools bevat een compacte payload voor de
     component: legs-geometrie (gedownsampled ~600 punten), klimmen
     (naam/stats/top-coord), kwaliteit, samenvatting. LET OP: dit wijkt af
     van het token-zuinige contract — de component-payload gaat in
     `structuredContent`, het LLM-zichtbare deel blijft de compacte tekst
     (Apps SDK stuurt structuredContent naar de component, de tekst naar het
     model; check de exacte veldnamen in de SDK-docs en documenteer ze).
3. **Fallback**: zonder Apps-SDK-modus blijft alles zoals nu (URL/pad).

## Tests (puur)

- component-HTML bevat de window.openai-bindings en geen ingebakken data;
- meta/resource alleen aanwezig met LUSMAKER_APPS_SDK=1 (toolsets anders
  ongewijzigd — bestaande toolaantal-tests blijven groen);
- payload-bouwer: downsampling + veldenset.

## Let op

Branch platform-apps; vroeg en klein committen; niet pushen; geen netwerk.
De exacte SDK-veldnamen (outputTemplate-URI-vorm, structuredContent-key)
zijn versiegevoelig — schrijf ze als constanten met bronverwijzing in een
comment, zodat de reviewer ze bij de live test kan bijstellen.

## Bijvangst uit de live smoke (meenemen)

Readiness-regel 5 stelt plaatskern-vragen serieel (Overbeke → daarna
Kwatrecht → ...): elke beurt één plaats. Batch ze: één vraag die ALLE
gepasseerde kernen noemt, met opties `ok` (patch: sta alle genoemde plaatsen
toe) en `kies_zelf` (geen patch; de LLM handelt selectief af met
adjust_route sta_plaatsen_toe/vermijd_plaatsen). Tests aanpassen.
