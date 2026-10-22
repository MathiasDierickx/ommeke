"""Select and phrase readiness questions, with a deterministic fallback."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError


def deterministic(candidates, context=None):
    context = context or {}
    wish = (context.get("wenstekst") or "").casefold()
    if not any(word in wish for word in ("kind", "kinderen", "gezin", "buggy")):
        candidates = [q for q in candidates if q["id"] not in {"speeltuin", "toilet"}]
    ordered = sorted(candidates, key=lambda q: (q["prioriteit"], q["id"]))
    if ordered and ordered[0]["id"] == "plek_afstand":
        return ordered[:1] + [q for q in ordered[1:] if q["id"] != "plek_afstand"][:2]
    return ordered[:3]


def _bedrock(candidates, context):
    from . import aws_chat, telemetry, tenant, quotas

    model = os.environ.get("LUSMAKER_BEDROCK_MODEL_ID", "eu.anthropic.claude-sonnet-4-6")
    payload = {"context": context, "kandidaten": candidates}
    system = (
        "Kies maximaal drie relevante vragen uit kandidaten op basis van context. "
        "Sla vragen over die de gebruiker al beantwoordde. Houd plek_afstand altijd eerst. "
        "Formuleer kort Nederlands, maximaal 200 tekens, met de gemeten reden. "
        'Antwoord uitsluitend JSON: {"vragen":[{"id":"<kandidaat-id>","vraag":"..."}]}.'
    )
    reserved = len(json.dumps([system, payload], ensure_ascii=False).encode()) + 400
    quotas.consume("tokens", amount=reserved)

    def invoke():
        return aws_chat._bedrock_client().converse(
            modelId=model,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": json.dumps(payload, ensure_ascii=False)}]}],
            inferenceConfig={"maxTokens": 400, "temperature": 0.1},
        )

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        response = executor.submit(invoke).result(timeout=4)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    usage = response.get("usage", {})
    telemetry.emit("chat", input_tokens=usage.get("inputTokens", 0),
                   output_tokens=usage.get("outputTokens", 0), iterations=1, success=True)
    content = response["output"]["message"]["content"]
    raw = next(part["text"] for part in content if "text" in part)
    result = json.loads(raw)
    rows = result["vragen"]
    by_id = {candidate["id"]: candidate for candidate in candidates}
    if not isinstance(rows, list) or len(rows) > 3:
        raise ValueError("ongeldige vragenlijst")
    seen, selected = set(), []
    for row in rows:
        ident, question = row.get("id"), row.get("vraag")
        if ident not in by_id or ident in seen or not isinstance(question, str) or not question.strip() or len(question) > 200:
            raise ValueError("ongeldige modelvraag")
        seen.add(ident)
        selected.append({**by_id[ident], "vraag": question.strip()})
    if candidates and candidates[0]["id"] == "plek_afstand" and (not selected or selected[0]["id"] != "plek_afstand"):
        place = next((q for q in selected if q["id"] == "plek_afstand"), candidates[0])
        selected = [place, *[q for q in selected if q["id"] != "plek_afstand"]][:3]
    return selected


def compose(candidates, context, *, provider=None):
    """Compose questions; any provider failure preserves the existing behavior."""
    fallback = lambda: deterministic(candidates, context)
    if provider is None:
        if os.environ.get("LUSMAKER_QUESTION_COMPOSER", "regels") != "bedrock":
            return fallback()
        provider = _bedrock
    try:
        return provider(candidates, context)
    except Exception:
        return fallback()
