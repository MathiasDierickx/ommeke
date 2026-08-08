# Lusmaker — productstrategie

*Status: richtinggevend document. Eigenaar: Mathias. Denklaag: Claude; uitvoering: Codex.*

## Wat dit is (generiek geformuleerd)

**Conversational route engineering**: een stateful tool-laag tussen LLM's en
routing-engines. De LLM voert het gesprek ("max 45 km, zoveel mogelijk
hoogtemeters, geen kasseien, vermijd Zottegem"); de tool-laag bezit de
domeinkennis: drafts, klim-database, optimalisatie, kwaliteitsmetrieken,
GPX-export. Die middenlaag blijft de kern; de hosted versie biedt nu ook een
eigen chat- en routebibliotheek als eerste distributiekanaal.

De generieke kern is regio- en sport-agnostisch: OSM + open DEM + GraphHopper
werken overal; de klimdetectie is een DEM-sweep zonder namenlijst; voorkeuren
zijn custom-model-regels. Vlaanderen is launch-regio, geen beperking.

## Waarom dit kan winnen

1. **Constraint-onderhandeling bestaat nergens.** Strava/Komoot/RideWithGPS
   plannen punt-naar-punt met één profiel. "Lus, budget 45 km, maximaal
   klimmen, dit liever niet" is een gesprek — precies waar LLM + stateful
   tools sterk zijn.
2. **Open data volstaat.** De klim-DB (716 hellingen, cijfers ≈ Climbfinder)
   kost 4,5 s rekentijd. Persoonlijke heatmap uit eigen ritten is legaal én
   persoonlijker dan de (juridisch gesloten) Strava-heatmap.
3. **MCP én eigen app als distributie.** Claude/ChatGPT blijven zero-install
   interfaces; de Next.js-app geeft niet-MCP-gebruikers registratie,
   chatgeschiedenis en een blijvende GPX-bibliotheek.

## Wat we geleerd hebben (PoC-sessies, augustus 2026)

- De suggest→add→reroute-lus werkt, maar de LLM moest hem handmatig aansturen
  en schattingen driften (~1-2 km per toevoeging). **De greedy-lus moet ín de
  tool** (`draft optimize`): LLM voor intentie, solver voor het rekenwerk.
- Zachte penalties stapelen multiplicatief → te agressieve factoren geven
  absurde omwegen. Alle voorkeuren mild houden en het effect rapporteren.
- Kwaliteitsmetrieken (kassei_m, steenweg_m, kruisingen, populair_pct) maken
  het gesprek concreet: de LLM kan varianten vergelijken en uitleggen.
- Auto-klimdetectie versloeg de handgemaakte lijst meteen (Diepestraat-les).

## Roadmap (volgorde = prioriteit)

| # | Milestone | Waarom |
|---|-----------|--------|
| M1 | `draft optimize` — greedy-lus in-tool, budget + doel | Grootste UX-win; minder LLM-calls; deterministisch |
| M2 ✅ | **MCP-server** via stdio met LLM-gerichte tools bovenop de CLI-kern | Go-to-market-artefact |
| M3 ✅ | Kaartpreview per draft (zelfstandige HTML) | Niemand vertrouwt een blinde GPX |
| M4 ✅ | Regiopacks: `lus region add <slug>` → extract, DEM-tegels uit bbox, eigen GH-graaf | Regio-agnostisch |
| M5 ✅ | Sportprofielen: trail-lopen naast het rustige fietsprofiel | Sport-agnostisch |
| M6 | Strava/Garmin OAuth-sync voor eigen-ritten-heat | Frictie weg bij de saus |
| M7 ✅ | Hosted multi-tenant + webapp | Cognito, Bedrock-chat, S3-routes en DynamoDB-historiek |
| M8 | Betaalplan, quota en abuse-controls | Na pilotvalidatie |

**Noot bij M4:** ad-hoc provisioning is toegevoegd: een plaatsnaam wordt via
Nominatim en de Geofabrik-index naar de kleinste regio vertaald. Provisioning
draait pollbaar op de achtergrond en kan vooraf gebouwde packs uit lokale,
HTTP(S)- of S3-caches hergebruiken.

**Noot bij M5:** trail-lopen gebruikt een afzonderlijk GraphHopper-profiel dat
paden en onverhard opzoekt. Run, gravel en MTB volgen later als extra custom
models.

## Go-to-market (klein en toetsbaar)

- **Pilot**: 5-10 wielervrienden, self-host of op Mathias' VPS. Meetlat:
  komen ze wekelijks terug; hoeveel routes geëxporteerd; % suggesties
  geaccepteerd.
- **Kanalen**: MCP-directories, r/cycling & BE-wielerfora, Climbfinder/RouteYou
  als potentiële partners i.p.v. concurrenten (zij hebben curatie, wij het
  gesprek).
- **Model**: open-core. Repo publiek (zelf hosten gratis), hosted versie met
  OAuth-sync en preview betaald (~€10-15/jaar). Geen venture-verhaal;
  Climbfinder-pad (hobby → klein bedrijf) is het realistische scenario.

## Risico's

- Incumbent plakt AI-chat op zijn planner → verdediging: niche-diepte
  (klimmen, lussen, trainingsdoelen) en open-source-goodwill.
- GH-kosten per regio bij hosted (flex-routing is CPU-zwaar) → regio's on
  demand, caching, kleine regio's.
- OSM-traces-API is een gunst, geen SLA → cachen, éénmalig per regio, nooit
  runtime-afhankelijk.
- LLM-kosten per route → M1 drukt het aantal tool-calls fors.

## Token-economie

In de hosted versie betalen we voor drie dingen: elke tool-round-trip stuurt
de gesprekscontext opnieuw mee, uitgebreide route-antwoorden kosten
resultaattokens, en ieder aangeboden toolschema neemt ruimte in de
systeemprompt. Daarom handelen `plan_route` en `adjust_route` het normale pad
in één call af en geven ze een compact resultaat zonder legs, coördinaten of
geneste berekeningen. Detailinformatie blijft opt-in via `route_details`.

`lus-mcp --lite` beperkt bovendien de schema-overhead tot tien tools:
`plan_route`, `adjust_route`, `suggest_climbs`, `route_details`,
`route_readiness`, `get_profile`, `update_profile`, `ensure_region`,
`region_status` en `list_drafts`. Self-hosted en ontwikkelomgevingen houden
zonder die vlag de volledige toolset.
