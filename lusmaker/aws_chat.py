"""Tenant-scoped chatgeschiedenis en een compacte Bedrock-routeagent."""

from __future__ import annotations

import os
import json
import time
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from .chat_contracts import PLAN_ROUTE_SCHEMA, ADJUST_ROUTE_SCHEMA

from . import draft, intents, tenant, quotas, requests, telemetry


MAX_PROMPT_CHARS = 4000
MAX_HISTORY_MESSAGES = 20
MAX_AGENT_ITERATIONS = 8


import re as _re

_THINKING_RE = _re.compile(r"<thinking>.*?</thinking>", _re.DOTALL | _re.IGNORECASE)


def _clean_answer(text: str) -> str:
    """Strip Nova's uitgelekte <thinking>-blokken en trim."""
    return _THINKING_RE.sub("", text or "").strip()


class ChatError(RuntimeError):
    pass


class ChatNotFound(ChatError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _conversation_key(conversation_id: str) -> str:
    try:
        return str(uuid.UUID(conversation_id))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ChatError("ongeldig gesprek-id") from exc


@lru_cache(maxsize=1)
def _dynamodb_client():
    try:
        import boto3
    except ImportError as exc:
        raise ChatError(
            "Chatopslag is geconfigureerd maar boto3 ontbreekt"
        ) from exc
    return boto3.client("dynamodb")


@lru_cache(maxsize=1)
def _bedrock_client():
    try:
        import boto3
    except ImportError as exc:
        raise ChatError("Bedrock is geconfigureerd maar boto3 ontbreekt") from exc
    return boto3.client(
        "bedrock-runtime",
        region_name=os.environ.get("LUSMAKER_BEDROCK_REGION") or None,
    )


class ConversationStore:
    """DynamoDB single-table adapter zonder scan of vaste capaciteit."""

    def __init__(self, client: Any | None = None, table_name: str | None = None):
        self.client = client or _dynamodb_client()
        self.table_name = table_name or os.environ.get("LUSMAKER_CHAT_TABLE", "")
        if not self.table_name:
            raise ChatError("LUSMAKER_CHAT_TABLE ontbreekt")

    @staticmethod
    def _user_pk() -> str:
        return f"USER#{tenant.current()}"

    @staticmethod
    def _conversation_pk(conversation_id: str) -> str:
        return f"CONVERSATION#{_conversation_key(conversation_id)}"

    @staticmethod
    def _decode(item: dict[str, dict[str, str]]) -> dict[str, Any]:
        decoded: dict[str, Any] = {}
        for key, value in item.items():
            if "S" in value:
                decoded[key] = value["S"]
            elif "N" in value:
                decoded[key] = int(value["N"])
            elif "SS" in value:
                decoded[key] = value["SS"]
        return decoded

    def create(self, title: str | None = None) -> dict[str, Any]:
        conversation_id = str(uuid.uuid4())
        created_at = _now()
        clean_title = (title or "Nieuwe route").strip()[:80] or "Nieuwe route"
        item = {
            "pk": {"S": self._user_pk()},
            "sk": {"S": f"CONVERSATION#{conversation_id}"},
            "entity": {"S": "conversation"},
            "id": {"S": conversation_id},
            "title": {"S": clean_title},
            "preview": {"S": ""},
            "created_at": {"S": created_at},
            "updated_at": {"S": created_at},
        }
        self.client.put_item(
            TableName=self.table_name,
            Item=item,
            ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)",
        )
        return self._decode(item)

    def get(self, conversation_id: str) -> dict[str, Any]:
        conversation_id = _conversation_key(conversation_id)
        response = self.client.get_item(
            TableName=self.table_name,
            Key={
                "pk": {"S": self._user_pk()},
                "sk": {"S": f"CONVERSATION#{conversation_id}"},
            },
            ConsistentRead=True,
        )
        item = response.get("Item")
        if not item:
            raise ChatNotFound("gesprek niet gevonden")
        return self._decode(item)

    def _query_all(self, **kwargs):
        items = []
        while True:
            response = self.client.query(TableName=self.table_name, **kwargs)
            items.extend(response.get("Items", []))
            cursor = response.get("LastEvaluatedKey")
            if not cursor:
                return items
            kwargs["ExclusiveStartKey"] = cursor

    def all_conversations(self):
        return [self._decode(item) for item in self._query_all(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": {"S": self._user_pk()}, ":prefix": {"S": "CONVERSATION#"}},
            ConsistentRead=True,
        )]

    def export(self):
        result = []
        for conversation in self.all_conversations():
            messages = self._query_all(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
                ExpressionAttributeValues={":pk": {"S": self._conversation_pk(conversation["id"])}, ":prefix": {"S": "MESSAGE#"}},
                ConsistentRead=True,
            )
            result.append({"conversation": conversation, "messages": [self._decode(item) for item in messages]})
        return result

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        conversations = self.all_conversations()
        conversations.sort(key=lambda item: item["updated_at"], reverse=True)
        return conversations[:limit]

    def messages(
        self, conversation_id: str, limit: int = MAX_HISTORY_MESSAGES
    ) -> list[dict[str, Any]]:
        conversation = self.get(conversation_id)
        response = self.client.query(
            TableName=self.table_name,
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={
                ":pk": {"S": self._conversation_pk(conversation["id"])},
                ":prefix": {"S": "MESSAGE#"},
            },
            ScanIndexForward=False,
            Limit=max(1, min(int(limit), 100)),
        )
        messages = [self._decode(item) for item in response.get("Items", [])]
        messages.reverse()
        return messages

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        route_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        conversation = self.get(conversation_id)
        if role not in {"user", "assistant"}:
            raise ChatError("ongeldige berichtrol")
        clean_content = content.strip()
        if not clean_content:
            raise ChatError("bericht mag niet leeg zijn")
        timestamp = _now()
        message_id = str(uuid.uuid4())
        item = {
            "pk": {"S": self._conversation_pk(conversation["id"])},
            "sk": {"S": f"MESSAGE#{timestamp}#{message_id}"},
            "entity": {"S": "message"},
            "id": {"S": message_id},
            "conversation_id": {"S": conversation["id"]},
            "role": {"S": role},
            "content": {"S": clean_content},
            "created_at": {"S": timestamp},
        }
        if route_ids:
            item["route_ids"] = {"SS": sorted(set(route_ids))}
        self.client.put_item(TableName=self.table_name, Item=item)

        update = "SET updated_at = :updated, preview = :preview"
        values = {
            ":updated": {"S": timestamp},
            ":preview": {"S": clean_content[:120]},
        }
        if role == "user" and conversation.get("title") == "Nieuwe route":
            update += ", title = :title"
            values[":title"] = {"S": clean_content[:80]}
        self.client.update_item(
            TableName=self.table_name,
            Key={
                "pk": {"S": self._user_pk()},
                "sk": {"S": f"CONVERSATION#{conversation['id']}"},
            },
            UpdateExpression=update,
            ExpressionAttributeValues=values,
            ConditionExpression="attribute_exists(pk) AND attribute_exists(sk)",
        )
        return self._decode(item)

    def delete(self, conversation_id: str) -> int:
        conversation = self.get(conversation_id)
        keys = self._query_all(
            KeyConditionExpression="pk = :pk",
            ExpressionAttributeValues={
                ":pk": {"S": self._conversation_pk(conversation["id"])},
            },
            ProjectionExpression="pk, sk",
        )
        metadata = {"pk": {"S": self._user_pk()}, "sk": {"S": f"CONVERSATION#{conversation['id']}"}}
        batches = [keys[offset:offset + 25] for offset in range(0, len(keys), 25)]
        # Verwijder het eigendomsbewijs pas wanneer alle berichten gewist zijn.
        batches.append([metadata])
        for batch in batches:
            pending = {self.table_name: [{"DeleteRequest": {"Key": key}} for key in batch]}
            for attempt in range(6):
                response = self.client.batch_write_item(RequestItems=pending)
                pending = {name: writes for name, writes in response.get("UnprocessedItems", {}).items() if writes}
                if not pending:
                    break
                time.sleep(min(0.05 * 2 ** attempt, 1))
            if pending:
                raise ChatError("Niet alle berichten konden worden verwijderd; probeer opnieuw.")
        return len(keys) + 1



TOOL_CONFIG = {
    "tools": [
        {
            "toolSpec": {
                "name": "plan_route",
                "description": "Maak een nieuwe fiets- of traillus en exporteer GPX en preview.",
                "inputSchema": {"json": PLAN_ROUTE_SCHEMA},
            }
        },
        {
            "toolSpec": {
                "name": "adjust_route",
                "description": "Pas een bestaande Lusmaker-route aan en routeer opnieuw.",
                "inputSchema": {"json": ADJUST_ROUTE_SCHEMA},
            }
        },
        {
            "toolSpec": {
                "name": "list_routes",
                "description": "Toon de routes van de ingelogde gebruiker.",
                "inputSchema": {
                    "json": {"type": "object", "properties": {}, "additionalProperties": False}
                },
            }
        },
        {
            "toolSpec": {
                "name": "route_details",
                "description": "Toon details en kwaliteitscijfers van één route.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "required": ["draft_id"],
                        "properties": {"draft_id": {"type": "string"}},
                        "additionalProperties": False,
                    }
                },
            }
        },
    ]
}


SYSTEM_PROMPT = """Je bent Lus, een Nederlandstalige routebouwer voor fiets- en traillussen.
Gebruik plan_route zodra de gebruiker een nieuwe route vraagt. Gebruik adjust_route voor een
wijziging aan een route die al in het gesprek staat. Verzin nooit routecijfers of route-id's.
Als de gebruiker vraagt om rond/langs een specifieke plek (park, plas, domein) te lopen/rijden,
zet die plek in rond_plaats.
Als de gebruiker zo lang mogelijk langs een benoemde waterloop (rivier of kanaal, bv. de Schelde,
de Leie, een kanaal) wil rijden of lopen, zet die naam in `langs_water` (niet in `rond_plaats`).
Geef plan_route altijd een korte, natuurlijke naam die de routewens samenvat in maximaal 80
tekens. Gebruik plaats, karakter en eventueel afstand; kopieer niet de volledige prompt.
Als een tool status needs_input teruggeeft, stel alleen de meegegeven gerichte vragen.
Als een route klaar is, vat afstand, hoogtemeters en belangrijke voorkeuren compact samen en
zeg dat GPX en preview rechts in de routebibliotheek staan. Hou antwoorden praktisch en kort.
Een wandeling gebruikt het trail-voetgangersprofiel, maar is daarmee niet geverifieerd kindvriendelijk.
Je hebt geen algemene webzoektool. Verzin geen hoteladres, parkinguitgang, veilige oversteek of strandtoegang.
De functie langs_water geldt voor rivieren en kanalen, niet voor een garantie van maximale strandlengte.
Meld expliciet wanneer zulke wensen niet door tools zijn geverifieerd. Een concept of needs_input is geen voltooide route.
Een tool draait altijd voor de ingelogde gebruiker; vraag of gebruik nooit een user-id."""


class RouteToolExecutor:
    """Whitelist rond de bestaande domeinfuncties voor Bedrock tool use."""

    def execute(
        self, name: str, arguments: dict[str, Any], *, request_id: str
    ) -> dict[str, Any]:
        if name == "plan_route":
            allowed = set(PLAN_ROUTE_SCHEMA["properties"])
            values = {key: value for key, value in arguments.items() if key in allowed}
            values.setdefault("tolerance_km", 2.5)
            values.setdefault("doel", "hoogtemeters")
            values.setdefault("via_klimmen", [])
            values.setdefault("vermijd_plaatsen", [])
            values.setdefault("kasseien", None)
            values.setdefault("beton_vermijden", None)
            values.setdefault("autovrij", None)
            values.setdefault("strict", None)
            values.setdefault("activiteit", "fietsen")
            values.setdefault("geen_opvulling", False)
            values.setdefault("rond_plaats", None)
            values.setdefault("langs_water", None)
            return intents.plan_route(
                **values,
                profiel_naam="standaard",
                check_readiness=True,
                request_id=request_id,
            )
        if name == "adjust_route":
            allowed = set(ADJUST_ROUTE_SCHEMA["properties"])
            values = {key: value for key, value in arguments.items() if key in allowed}
            values.setdefault("voeg_klimmen_toe", [])
            values.setdefault("verwijder_klimmen", [])
            values.setdefault("vermijd_plaatsen", [])
            values.setdefault("niet_meer_vermijden", [])
            values.setdefault("sta_plaatsen_toe", [])
            values.setdefault("rond_plaats", None)
            values.setdefault("langs_water", None)
            return intents.adjust_route(**values, check_readiness=True)
        if name == "list_routes":
            return {"drafts": draft.list_all()[:50]}
        if name == "route_details":
            return intents.route_details(str(arguments.get("draft_id", "")))
        raise ChatError(f"onbekende route-tool '{name}'")


class BedrockRouteAgent:
    def __init__(
        self,
        client: Any | None = None,
        tool_executor: RouteToolExecutor | None = None,
        model_id: str | None = None,
    ):
        self.client = client or _bedrock_client()
        self.tools = tool_executor or RouteToolExecutor()
        self.model_id = model_id or os.environ.get(
            "LUSMAKER_BEDROCK_MODEL_ID", "eu.anthropic.claude-sonnet-4-6"
        )

    def _converse(self, messages: list[dict[str, Any]], request_id: str) -> dict[str, Any]:
        """Roep Bedrock aan met retry op transiente model-/throttlingfouten.

        Nova produceert af en toe een ongeldige tool-use-sequentie
        (ModelErrorException) of loopt tegen een minuutlimiet (ThrottlingException);
        een korte herkansing lost dat meestal op zonder de gebruiker te storen.
        """
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                # UTF-8 bytes form a conservative input-token upper bound.
                reserved = len(json.dumps([messages, SYSTEM_PROMPT, TOOL_CONFIG], ensure_ascii=False).encode()) + 1400
                quotas.consume("tokens", amount=reserved)
                return self.client.converse(
                    modelId=self.model_id,
                    system=[{"text": SYSTEM_PROMPT}],
                    messages=messages,
                    toolConfig=TOOL_CONFIG,
                    inferenceConfig={"maxTokens": 1400, "temperature": 0.2},
                    requestMetadata={"tenant": tenant.current(), "request_id": request_id},
                )
            except Exception as exc:  # botocore ClientError-subklassen
                name = type(exc).__name__
                if name not in {"ModelErrorException", "ThrottlingException", "InternalServerException"}:
                    raise
                last_exc = exc
                if attempt < 2:
                    time.sleep(1.2 * (attempt + 1))
        raise ChatError(
            "De AI-dienst gaf een tijdelijke fout. Probeer je bericht opnieuw."
        ) from last_exc

    def reply(
        self,
        history: list[dict[str, Any]],
        *,
        request_id: str,
    ) -> dict[str, Any]:
        # Bedrock vereist strikt afwisselende user/assistant-rollen die met
        # 'user' beginnen. Mislukte turns laten soms twee user-berichten na
        # elkaar staan (assistant-antwoord werd niet opgeslagen); zonder
        # coalescing geeft dat een ModelErrorException en verliest het model de
        # context. We voegen opeenvolgende gelijke rollen samen.
        messages: list[dict[str, Any]] = []
        for item in history[-MAX_HISTORY_MESSAGES:]:
            role = item.get("role")
            text = item.get("content")
            if role not in {"user", "assistant"} or not text:
                continue
            if messages and messages[-1]["role"] == role:
                messages[-1]["content"][0]["text"] += f"\n\n{text}"
            else:
                messages.append({"role": role, "content": [{"text": text}]})
        while messages and messages[0]["role"] != "user":
            messages.pop(0)
        route_ids: set[str] = set()
        ready_route_ids: set[str] = set()
        tool_events: list[dict[str, Any]] = []
        usage = {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}

        for iteration in range(1, MAX_AGENT_ITERATIONS + 1):
            response = self._converse(messages, request_id)
            for key in usage:
                usage[key] += int((response.get("usage") or {}).get(key, 0))
            message = (response.get("output") or {}).get("message") or {}
            content = message.get("content") or []
            text_parts = [block["text"] for block in content if block.get("text")]
            tool_uses = [block["toolUse"] for block in content if block.get("toolUse")]
            messages.append({"role": "assistant", "content": content})

            if not tool_uses:
                answer = _clean_answer("\n".join(text_parts))
                if not answer:
                    raise ChatError("Het model gaf geen antwoord terug")
                return {
                    "content": answer,
                    "route_ids": sorted(route_ids),
                    "ready_route_ids": sorted(ready_route_ids),
                    "tools": tool_events,
                    "usage": usage,
                    "iterations": iteration,
                }

            results = []
            for tool_use in tool_uses:
                started = time.monotonic()
                name = tool_use.get("name", "")
                error_detail: str | None = None
                try:
                    output = self.tools.execute(
                        name,
                        tool_use.get("input") or {},
                        request_id=request_id,
                    )
                    draft_id = output.get("draft") if isinstance(output, dict) else None
                    if isinstance(draft_id, str):
                        route_ids.add(draft_id)
                        if output.get("status") == "ready":
                            ready_route_ids.add(draft_id)
                        elif output.get("status") == "needs_input":
                            ready_route_ids.discard(draft_id)
                    status = "success"
                except Exception as exc:
                    error_detail = f"{type(exc).__name__}: {exc}"
                    output = {"error": str(exc)}
                    status = "error"
                    print(
                        f"[chat] tool {name} faalde (req={request_id}): {error_detail}",
                        flush=True,
                    )
                event = {
                    "name": name,
                    "status": status,
                    "duration_ms": round((time.monotonic() - started) * 1000),
                }
                if error_detail:
                    event["error"] = error_detail[:300]
                tool_events.append(event)
                results.append(
                    {
                        "toolResult": {
                            "toolUseId": tool_use["toolUseId"],
                            "content": [{"json": output}],
                            "status": status,
                        }
                    }
                )
            messages.append({"role": "user", "content": results})

        # Iteratielimiet bereikt (Nova blijft soms tool-calls stapelen zonder af
        # te ronden). Als er al een route klaarstaat, lever die met een nette
        # boodschap i.p.v. een harde fout.
        if route_ids:
            return {
                "content": (
                    "Je route staat klaar — open de kaart hieronder. Stel gerust een vervolgvraag om hem bij te sturen."
                    if ready_route_ids else
                    "Er is een routeconcept opgeslagen, maar de wandeling of rit is nog niet klaar. "
                    "Controleer de ontbrekende routewensen in het gesprek; dit concept is nog geen bruikbare route."
                ),
                "route_ids": sorted(route_ids),
                "ready_route_ids": sorted(ready_route_ids),
                "tools": tool_events,
                "usage": usage,
                "iterations": MAX_AGENT_ITERATIONS,
            }
        raise ChatError(
            "Het duurde te lang om je route samen te stellen. Probeer het opnieuw "
            "of formuleer je vraag iets concreter."
        )


def send_message(
    conversation_id: str,
    content: str,
    *,
    store: ConversationStore | None = None,
    agent: BedrockRouteAgent | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    clean_content = content.strip()
    if not clean_content:
        raise ChatError("bericht mag niet leeg zijn")
    if len(clean_content) > MAX_PROMPT_CHARS:
        raise ChatError(f"bericht mag maximaal {MAX_PROMPT_CHARS} tekens bevatten")
    store = store or ConversationStore()
    store.get(conversation_id)
    def execute():
        quotas.consume("chat", request_id=request_id)
        user_message = store.add_message(conversation_id, "user", clean_content)
        history = store.messages(conversation_id)
        route_agent = agent or BedrockRouteAgent()
        result = route_agent.reply(
            history,
            request_id=f"{conversation_id}:{user_message['id']}",
        )
        assistant_message = store.add_message(
            conversation_id,
            "assistant",
            result["content"],
            route_ids=result["route_ids"],
        )
        telemetry.emit("chat", input_tokens=result.get("usage", {}).get("inputTokens", 0),
                       output_tokens=result.get("usage", {}).get("outputTokens", 0),
                       iterations=result.get("iterations", 0), success=True)
        return {"message": assistant_message, **result}
    return requests.once(f"chat:{conversation_id}", request_id, {"content": clean_content}, execute)
