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
