# 0003 - Model voor de pilot

- Status: aangenomen
- Datum: 6 oktober 2026
- Issue: #23

## Besluit

De pilot draait op `openai.gpt-oss-120b-1:0` via Amazon Bedrock in
`eu-west-1`.

## Redenen

- Claude-modellen geven `INVALID_PAYMENT_INSTRUMENT` bij de AWS Marketplace-
  betaling; zie `docs/aws-support-case.md`.
- GPT-6.x Sol is niet beschikbaar voor dit account.
- GPT-OSS scoort 23/31 op de hosted eval (waarvan 6/10 gesprekcases); zie
  `evals/README.md`.
- Een zwakte is dat het model soms maar één van meerdere antwoorden verwerkt.
  Deterministische paden vangen dit op: het answers-endpoint en intent-hints.

## Herziening

Wanneer de Marketplace-betaling is opgelost, voer dezelfde hosted eval uit op
Claude Sonnet. Wissel het model via `lusmaker/model_gate.py` en
`evals/approved-model.json`, volgens de bestaande evalpoort. De gemeten score
alleen keurt een wissel niet goed.
