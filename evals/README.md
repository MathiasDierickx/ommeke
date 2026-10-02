# MCP-evaluaties

`route_intents.json` is de vaste, netwerkloze acceptatieset voor de vertaling
van Nederlandse prompts naar Lusmaker-toolcalls. Laat Claude of ChatGPT per
case één object opnemen met deze vorm:

```json
{"id": "heuvelrit-wetteren-50", "tool": "plan_route", "arguments": {}}
```

Bewaar alle objecten als JSON-lijst en score ze lokaal:

```bash
.venv/bin/python -m lusmaker.mcp_evals /pad/naar/opgenomen-toolcalls.json
```

De scorer doet bewust geen netwerk- of modelcalls. Daardoor kan dezelfde
corpus handmatig of in een latere provider-specifieke evalrunner worden
gebruikt zonder de offline testsuite niet-deterministisch te maken.

## Hosted modelproef en releasepoort

`hosted_intents.json` gebruikt uitsluitend de tools die de webchat aanbiedt.
De MCP-suite blijft afzonderlijk bestaan. De hosted scorer controleert zowel
het werkelijke JSON-schema als de gevraagde intentie. Een foutieve extra sleutel
zoals `activity` telt dus als fout, ook als `activiteit` daarnaast correct is.
Bij bewerkingen zonder bekende revisie verwachten we eerst `route_details`;
dit bewijst nog niet dat de vervolgbewerking goed wordt uitgevoerd.

De opt-in proef gebruikt netwerk en modeltokens, maar voert geen routering uit:

```bash
.venv/bin/lus eval-model --aws-profile ommeke-prod \
  --model openai.gpt-oss-120b-1:0 --output /tmp/hosted-eval.json
```

Tokenprijzen zijn optioneel via `--input-per-million` en `--output-per-million`.
De bedragen betreffen uitsluitend de gemeten modelbeurt, niet een heel gesprek.
Providerfouten blijven afzonderlijk zichtbaar; een toegangsfout is geen bewijs
van slechte modelkwaliteit. De huidige runner gebruikt Bedrock Converse;
modellen die uitsluitend Responses ondersteunen vereisen een andere adapter.

CI vergelijkt het Terraform-standaardmodel met de base-commit. Een wijziging
vereist `evals/approved-model.json`: een volledig rapport van de huidige suite,
systeemprompt en toolschemas, maximaal 30 dagen oud, zonder providerfouten en
met alle cases geslaagd. De poort berekent de score opnieuw uit de toolcalls.
Een handmatig ingevulde totaalscore is onvoldoende. Er is nog geen goedgekeurd
rapport: de gemeten baseline haalt de poort niet. Modelkwaliteit, vervolgstappen
en echte routekwaliteit blijven afzonderlijke acceptatiepunten.

### Gemeten baseline (2 oktober 2026)

De uitgebreide suite bevat 21 bestaande cases en 10 uit eigen appgesprekken.
Straatadressen zijn vervangen door de plaatsnaam; account-id's en gesprek-id's
zijn weggelaten. De twee Blaarmeersen-cases komen uit verschillende gesprekken,
maar toetsen grotendeels dezelfde intentie. De vervolgcase bevat de werkelijke
voorafgaande vraag en het antwoord, niet alleen een los zinnetje.

Het huidige GPT-OSS-model scoort 23/31 op de uitgebreide suite, waarvan 6/10 op
de gesprekcases. P50 is 1,793 s en p95 3,488 s per eerste modelbeurt. De totale
tokenschatting is $0,014286 voor deze 31 beurten bij $0,18/M input en $0,70/M
output (AWS Price List, eu-west-1, On-demand Inference, 2026-09-30).
Dit zijn geen kosten per volledig gesprek en geen routeringstijden.
Het rapport staat in `results/gpt-oss-hosted-real-2026-10-02.json`.
Het eerdere rapport met 17/21 hoort bij de kleinere suite en heeft daarom een
andere fingerprint. Geen van beide rapporten keurt een modelwissel goed.

Claude Sonnet 4.6 gaf bij de afzonderlijke toegangsproef AccessDeniedException;
er is geen vergelijkbare kwaliteitsscore of gesprekprijs gemeten. Het huidige
model blijft voorlopig staan, maar de intentkwaliteit is nog onvoldoende voor
een afgerond pilotbesluit. De eerste-toolscore beoordeelt geen vervolggesprek:
een verduidelijkingsvraag of profielopvraag kan soms terecht zijn en vergt
inhoudelijke beoordeling. Nieuwe runs bewaren daarom ook de zichtbare modeltekst
naast de toolcall. Onbekende argumentnamen blijven onvoorwaardelijk fouten.
