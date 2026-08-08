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
