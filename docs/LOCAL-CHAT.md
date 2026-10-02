# Vrije routeprompts lokaal uitvoeren

`lus chat` gebruikt standaard de geïnstalleerde Codex CLI en diens bestaande
login. Codex roept via een lokale stdio-MCP dezelfde `RouteToolExecutor` aan
als de hosted chat. Er is geen automatische terugval naar Bedrock.

```sh
.venv/bin/lus chat 'Een wandeling van ongeveer 3 km in Bredene' \
  --provider codex --gh-url http://127.0.0.1:8989
.venv/bin/lus chat 'Maak de wandeling korter' --session <session-id>
```

Gebruik `--workspace` om gesprekken, routebestanden en logs apart te bewaren.
De standaard is `.route-data/local-chat`. De CLI kopieert de regiocaches bij
het eerste gebruik; hij start of wijzigt GraphHopper niet. Gebruik een nieuwe
werkmap na een datasetwijziging. `--region` kiest een bestaande bronregio.
`--model` kiest expliciet een model; zonder deze optie kiest Codex zijn default.
`--timeout` begrenst een Codex-run (standaard 600 seconden).

Stdout bevat één JSON-resultaat. `session` is het lokale gesprek-id; `log`
verwijst naar de volledige promptgeschiedenis en toolresultaten. `provider_log`
bevat Codex-events en eventuele foutmeldingen. Behandel deze bestanden als
persoonlijke gegevens. `ready_route_ids` komt uit de werkelijke MCP-resultaten,
niet uit het antwoord van het model. Een concept is geen voltooide route.

Codex krijgt uitsluitend de Lusmaker-chat-MCP geconfigureerd, een read-only
shellsandbox en webzoeken voor bronverificatie. De MCP mag routebestanden in
de gekozen werkmap schrijven. Er worden geen persoonlijke Codex-configuratie
of loginbestanden herschreven. De provider gebruikt Codex-verbruik van de
bestaande login; dit is geen garantie van gratis modelgebruik.

Bedrock blijft expliciet beschikbaar:

```sh
.venv/bin/lus chat 'Een fietsroute van 40 km vanuit Wetteren' \
  --provider bedrock --aws-profile <profiel> --aws-region eu-west-1 \
  --model <bedrock-model-id>
```

Dit verandert de provider van de online AWS-app niet. Persoonlijke
Codex-loginbestanden horen niet in de Lambda-image of GitHub-secrets.

`lookup_place` zoekt afzonderlijke locaties. `nearby_places` zoekt maximaal
2 km rond een bekend punt naar OSM-parkings, hotels, stranden of oversteekplaatsen.
Die tool vermeldt bronnen en toegangstags, en maakt onderscheid tussen een
kaartpunt en het centrum van een gebied. Dat centrum is geen bevestigde ingang.
Nieuwe gazetteers bewaren ook hotels, stranden en parkings zonder naam. Wanneer
die lokale snapshot geschikte kandidaten bevat, is er geen externe plaatszoekaanroep
nodig. Bestaande caches blijven leesbaar; opnieuw bouwen is nodig om die extra
plaatsgegevens te krijgen. Een lokale snapshot is geen actuele terreincontrole.
De publieke Overpass-dienst is configureerbaar met `LUSMAKER_OVERPASS_URL`;
gelijke queries worden per proces maximaal een uur hergebruikt.

Officiële referenties: [Codex non-interactive](https://developers.openai.com/codex/noninteractive/)
en [Codex MCP](https://developers.openai.com/codex/mcp/).
