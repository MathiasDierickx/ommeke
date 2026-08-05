# Lusmaker — productstrategie

*Status: richtinggevend document. Eigenaar: Mathias. Denklaag: Claude; uitvoering: Codex.*

## Wat dit is (generiek geformuleerd)

**Conversational route engineering**: een stateful tool-laag tussen LLM's en
routing-engines. De LLM voert het gesprek ("max 45 km, zoveel mogelijk
hoogtemeters, geen kasseien, vermijd Zottegem"); de tool-laag bezit de
domeinkennis: drafts, klim-database, optimalisatie, kwaliteitsmetrieken,
GPX-export. Geen chat-app, geen kaart-app — de ontbrekende middenlaag.

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
3. **MCP als distributie.** Geen eigen chat-UI bouwen: Claude/ChatGPT is de
   interface. Eén `docker compose up` + MCP-config = installatie. De
   MCP-directories zijn jong; "prompt-to-GPX" is daar nu nog een leeg vak.

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
| M2 | **MCP-server** (stdio + streamable HTTP) 1-op-1 op de CLI-kern; elicitation voor suggestievragen | Go-to-market-artefact |
| M3 | Kaartpreview per draft (statische HTML, lokaal geserveerd) | Niemand vertrouwt een blinde GPX |
| M4 | Regiopacks: `lus region add <geofabrik-slug>` → extract, DEM-tegels uit bbox, eigen GH-graaf | Regio-agnostisch |
| M5 | Profielen: gravel / mtb / hardlopen (varianten van quiet.json) | Sport-agnostisch |
| M6 | Strava/Garmin OAuth-sync voor eigen-ritten-heat | Frictie weg bij de saus |
| M7 | Hosted multi-tenant + betaald plan | Pas na pilotvalidatie |

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
