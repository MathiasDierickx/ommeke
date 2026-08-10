"""JSON API voor de Cognito-webapp bovenop routes en Bedrock-chat."""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
from typing import Any
from urllib.parse import quote

import logging

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from . import artifacts, aws_sharing, aws_state, climbs, draft, geo, intents, tenant
from .aws_chat import ChatError, ChatNotFound, ConversationStore, send_message


_DRAFT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _error(message: str, status: int = 400, code: str = "bad_request") -> JSONResponse:
    return JSONResponse({"error": message, "code": code}, status_code=status)


logger = logging.getLogger(__name__)


async def _json_body(request: Request, *, max_bytes: int = 16_384) -> dict[str, Any]:
    body = await request.body()
    if len(body) > max_bytes:
        raise ChatError("request is te groot")
    try:
        value = json.loads(body or b"{}")
    except json.JSONDecodeError as exc:
        raise ChatError("ongeldige JSON") from exc
    if not isinstance(value, dict):
        raise ChatError("request body moet een JSON-object zijn")
    return value


def _draft_id(request: Request) -> str:
    value = request.path_params.get("draft_id", "")
    if not _DRAFT_ID_RE.fullmatch(value):
        raise draft.DraftError("ongeldig route-id")
    return value


def _route_item(item: dict[str, Any]) -> dict[str, Any]:
    computed = item.get("computed") or {}
    return {
        "id": item["id"],
        "revision": int(item.get("revision", 0)),
        "name": item.get("name") or "Naamloze route",
        "created": item.get("created"),
        "start": (item.get("start") or {}).get("label"),
        "activity": "trail" if item.get("profile") == "trail" else "fietsen",
        "region": item.get("region"),
        "climbs": item.get("climbs") or [],
        "total_km": computed.get("total_km"),
        # de engine schrijft de hoogtemeters als 'ascend_m'
        "elevation_gain_m": computed.get("ascend_m"),
        "ready": bool(computed),
        "download_url": f"/api/routes/{item['id']}/gpx" if computed else None,
        "preview_url": f"/api/routes/{item['id']}/preview" if computed else None,
    }


async def me(_request: Request) -> JSONResponse:
    return JSONResponse({"id": tenant.current()})


async def routes_list(_request: Request) -> JSONResponse:
    try:
        items = await asyncio.to_thread(draft.list_all)
        full = await asyncio.gather(
            *(asyncio.to_thread(draft.load, item["id"]) for item in items)
        )
        full.sort(key=lambda item: item.get("created", ""), reverse=True)
        return JSONResponse({"routes": [_route_item(item) for item in full]})
    except Exception as exc:
        return _error(str(exc), 500, "routes_unavailable")


def _elevation_profile(legs: list, *, samples: int = 120) -> list[dict[str, float]]:
    """Cumulatieve-afstand/hoogte-reeks voor het hoogteprofiel in de bottom-sheet."""
    import math

    flat = [pt for leg in legs for pt in leg]
    if len(flat) < 2 or not any(len(pt) > 2 and pt[2] is not None for pt in flat):
        return []
    profile: list[dict[str, float]] = []
    dist = 0.0
    prev = None
    prev_ele = 0.0
    for pt in flat:
        if prev is not None:
            p1, p2 = math.radians(prev[0]), math.radians(pt[0])
            dl = math.radians(pt[1] - prev[1])
            a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
            dist += 2 * 6371000.0 * math.asin(math.sqrt(a))
        ele = pt[2] if len(pt) > 2 and pt[2] is not None else prev_ele
        profile.append({"km": round(dist / 1000, 3), "ele": round(ele, 1)})
        prev, prev_ele = pt, ele
    if len(profile) > samples:
        step = len(profile) / samples
        profile = [profile[int(i * step)] for i in range(samples)] + [profile[-1]]
    return profile


def _route_geometry(item: dict[str, Any], *, max_points: int = 1500) -> dict[str, Any]:
    """Compacte polyline + klimmarkers zodat de webapp de kaart native tekent."""
    legs = item.get("_geometry") or []
    points: list[list[float]] = []
    for leg in legs:
        for pt in leg:
            points.append([round(pt[0], 5), round(pt[1], 5)])
    if len(points) > max_points:
        step = len(points) / max_points
        points = [points[int(i * step)] for i in range(max_points)] + [points[-1]]
    markers = []
    for cid in item.get("climbs") or []:
        for meta, leg in zip(
            (item.get("computed") or {}).get("legs", []), legs
        ):
            if meta.get("climb") == cid and leg:
                top = leg[-1]
                markers.append(
                    {"lat": round(top[0], 5), "lon": round(top[1], 5), "id": cid}
                )
                break
    start = item.get("start") or {}
    return {
        "points": points,
        "climbs": markers,
        "elevation": _elevation_profile(legs),
        "start": (
            {"lat": start.get("lat"), "lon": start.get("lon"), "label": start.get("label")}
            if start.get("lat") is not None
            else None
        ),
    }


def _route_detail_payload(item: dict[str, Any]) -> dict[str, Any]:
    result = _route_item(item)
    result["avoid_places"] = item.get("avoid_places") or []
    result["route_request"] = item.get("route_request") or {}
    result["computed"] = item.get("computed")
    result["geometry"] = _route_geometry(item) if item.get("computed") else None
    return result


def public_route_payload(item: dict[str, Any]) -> dict[str, Any]:
    """Stel expliciet een publieke allowlist samen, zonder labels of PII."""
    computed = item.get("computed") or {}
    geometry = _route_geometry(item) if computed else None
    if geometry and geometry.get("start"):
        geometry["start"].pop("label", None)
    return {
        "name": item.get("name") or "Naamloze route",
        "activity": "trail" if item.get("profile") == "trail" else "fietsen",
        "region": item.get("region"),
        "climbs": item.get("climbs") or [],
        "total_km": computed.get("total_km"),
        "elevation_gain_m": computed.get("ascend_m"),
        "geometry": geometry,
        "kwaliteit": computed.get("kwaliteit") or {},
    }


async def route_detail(request: Request) -> JSONResponse:
    try:
        item = await asyncio.to_thread(draft.load, _draft_id(request))
        return JSONResponse({"route": _route_detail_payload(item)})
    except draft.DraftError as exc:
        return _error(str(exc), 404, "route_not_found")


def _string_list(body: dict[str, Any], name: str) -> list[str]:
    value = body.get(name, [])
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ChatError(f"{name} moet een lijst met tekstwaarden zijn")
    return [item.strip() for item in value]


async def route_adjust(request: Request) -> JSONResponse:
    try:
        draft_id = _draft_id(request)
        await asyncio.to_thread(draft.load, draft_id)
        body = await _json_body(request)
        target_km = body.get("target_km")
        if target_km is not None and (
            isinstance(target_km, bool) or not isinstance(target_km, (int, float))
        ):
            raise ChatError("target_km moet een getal zijn")
        expected_revision = body.get("expected_revision")
        if expected_revision is not None and (
            isinstance(expected_revision, bool) or not isinstance(expected_revision, int)
        ):
            raise ChatError("expected_revision moet een geheel getal zijn")
        goal = body.get("doel")
        goal_map = {"hm": "hoogtemeters", "offroad": "offroad", "toeren": "toeren", "kort": "kort"}
        if goal is not None and goal not in goal_map:
            raise ChatError("doel moet 'hm', 'offroad', 'toeren' of 'kort' zijn")
        await asyncio.to_thread(
            intents.adjust_route,
            draft_id,
            target_km=float(target_km) if target_km is not None else None,
            voeg_klimmen_toe=_string_list(body, "voeg_klimmen_toe"),
            verwijder_klimmen=_string_list(body, "verwijder_klimmen"),
            vermijd_plaatsen=_string_list(body, "vermijd_plaatsen"),
            sta_plaatsen_toe=_string_list(body, "sta_plaatsen_toe"),
            doel=goal_map.get(goal),
            check_readiness=False,
            expected_revision=expected_revision,
        )
        item = await asyncio.to_thread(draft.load, draft_id)
        return JSONResponse({"route": _route_detail_payload(item)})
    except ChatError as exc:
        return _error(str(exc))
    except intents.IntentError as exc:
        return _error(str(exc))
    except draft.DraftError as exc:
        return _error(str(exc), 409, "route_conflict")


def _nearby_climbs(item: dict[str, Any], radius_km: float) -> list[dict[str, Any]]:
    route_points = [point[:2] for leg in item.get("_geometry") or [] for point in leg]
    if not route_points:
        start = item.get("start") or {}
        if start.get("lat") is not None and start.get("lon") is not None:
            route_points = [[start["lat"], start["lon"]]]
    if len(route_points) > 250:
        step = len(route_points) / 250
        route_points = [route_points[int(index * step)] for index in range(250)]
    result = []
    with draft.region_scope(item):
        climb_db = climbs.all_climbs()
    for climb in climb_db.values():
        point = climb.get("mid") or climb.get("foot") or climb.get("top")
        if not point or not route_points:
            continue
        distance_km = min(
            geo.haversine(point[0], point[1], route[0], route[1])
            for route in route_points
        ) / 1000
        if distance_km <= radius_km:
            result.append(
                {
                    "id": climb["id"],
                    "naam": climb.get("name") or climb["id"],
                    "km": round(float(climb.get("length_m", 0)) / 1000, 1),
                    "hm": round(float(climb.get("gain_m", 0))),
                }
            )
    return sorted(result, key=lambda value: (value["naam"].casefold(), value["id"]))


async def route_climbs_near(request: Request) -> JSONResponse:
    try:
        radius_km = float(request.query_params.get("radius_km", "15"))
        if not 0 < radius_km <= 100:
            raise ValueError
        item = await asyncio.to_thread(draft.load, _draft_id(request))
        return JSONResponse({"climbs": await asyncio.to_thread(_nearby_climbs, item, radius_km)})
    except ValueError:
        return _error("radius_km moet tussen 0 en 100 liggen")
    except draft.DraftError as exc:
        return _error(str(exc), 404, "route_not_found")


def _share_url(request: Request, token: str) -> str:
    base = (
        os.environ.get("LUSMAKER_WEB_URL")
        or request.headers.get("origin")
        or str(request.base_url)
    ).rstrip("/")
    return f"{base}/s/{token}"


async def route_share(request: Request) -> JSONResponse:
    try:
        draft_id = _draft_id(request)
        item = await asyncio.to_thread(draft.load, draft_id)
        token = item.get("share_token")
        if not token:
            for _attempt in range(3):
                token = secrets.token_urlsafe(32)
                try:
                    await asyncio.to_thread(
                        aws_sharing.store_reference, token, tenant.current(), draft_id
                    )
                    break
                except aws_state.StateConflict:
                    token = None
            if not token:
                return _error("deel-link kon niet worden gemaakt", 500, "share_failed")
            item["share_token"] = token
            try:
                await asyncio.to_thread(draft.save, item)
            except Exception:
                await asyncio.to_thread(aws_sharing.delete_reference, token)
                raise
        return JSONResponse({"token": token, "url": _share_url(request, token)})
    except draft.DraftError as exc:
        return _error(str(exc), 404, "route_not_found")
    except (aws_state.StateError, ValueError) as exc:
        return _error(str(exc), 500, "share_failed")


async def route_unshare(request: Request) -> Response:
    try:
        item = await asyncio.to_thread(draft.load, _draft_id(request))
        token = item.pop("share_token", None)
        if token:
            await asyncio.to_thread(draft.save, item)
            await asyncio.to_thread(aws_sharing.delete_reference, token)
        return Response(status_code=204)
    except draft.DraftError as exc:
        return _error(str(exc), 404, "route_not_found")
    except (aws_state.StateError, ValueError) as exc:
        return _error(str(exc), 500, "share_failed")


async def shared_route(request: Request) -> JSONResponse:
    try:
        token = request.path_params.get("token", "")
        reference = await asyncio.to_thread(aws_sharing.load_reference, token)
        if not reference:
            return _error("deze deel-link bestaat niet of is ingetrokken", 404, "shared_route_not_found")
        with tenant.use(reference["uid"]):
            item = await asyncio.to_thread(draft.load, reference["draft_id"])
        if item.get("share_token") != token:
            return _error("deze deel-link bestaat niet of is ingetrokken", 404, "shared_route_not_found")
        return JSONResponse({"route": public_route_payload(item)})
    except (ValueError, draft.DraftError):
        return _error("deze deel-link bestaat niet of is ingetrokken", 404, "shared_route_not_found")
    except aws_state.StateError as exc:
        return _error(str(exc), 500, "share_unavailable")


async def route_update(request: Request) -> JSONResponse:
    try:
        draft_id = _draft_id(request)
        body = await _json_body(request)
        name = body.get("name")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
            return _error("naam moet 1 tot 80 tekens bevatten")
        item = await asyncio.to_thread(draft.load, draft_id)
        expected_revision = body.get("expected_revision")
        if not isinstance(expected_revision, int):
            return _error("expected_revision is verplicht")
        draft.require_revision(item, expected_revision)
        item["name"] = name.strip()
        await asyncio.to_thread(
            draft.save, item, expected_revision=expected_revision
        )
        return JSONResponse({"route": _route_item(item)})
    except draft.DraftError as exc:
        return _error(str(exc), 409, "route_conflict")
    except ChatError as exc:
        return _error(str(exc))


async def route_delete(request: Request) -> Response:
    try:
        draft_id = _draft_id(request)
        await asyncio.to_thread(draft.load, draft_id)
        await asyncio.to_thread(aws_state.delete, f"drafts/{draft_id}.json")
        await asyncio.to_thread(aws_state.delete_prefix, f"artifacts/{draft_id}")
        return Response(status_code=204)
    except draft.DraftError as exc:
        return _error(str(exc), 404, "route_not_found")
    except Exception as exc:
        return _error(str(exc), 500, "route_delete_failed")


async def route_gpx(request: Request) -> Response:
    try:
        draft_id = _draft_id(request)
        item = await asyncio.to_thread(draft.load, draft_id)
        payload = await asyncio.to_thread(artifacts.read, draft_id, "route.gpx")
        filename = quote(f"{item.get('name') or 'lusmaker-route'}.gpx")
        return Response(
            payload,
            media_type="application/gpx+xml",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
                "Cache-Control": "private, no-store",
            },
        )
    except (draft.DraftError, artifacts.ArtifactError) as exc:
        return _error(str(exc), 404, "artifact_not_found")


async def route_preview(request: Request) -> Response:
    try:
        draft_id = _draft_id(request)
        await asyncio.to_thread(draft.load, draft_id)
        payload = await asyncio.to_thread(artifacts.read, draft_id, "preview.html")
        return HTMLResponse(
            payload.decode("utf-8"),
            headers={"Cache-Control": "private, no-store"},
        )
    except (draft.DraftError, artifacts.ArtifactError, UnicodeDecodeError) as exc:
        return _error(str(exc), 404, "artifact_not_found")


async def conversations_list(_request: Request) -> JSONResponse:
    try:
        items = await asyncio.to_thread(ConversationStore().list)
        return JSONResponse({"conversations": items})
    except ChatError as exc:
        return _error(str(exc), 500, "chat_unavailable")


async def conversation_create(request: Request) -> JSONResponse:
    try:
        body = await _json_body(request)
        title = body.get("title")
        if title is not None and not isinstance(title, str):
            return _error("title moet tekst zijn")
        item = await asyncio.to_thread(ConversationStore().create, title)
        return JSONResponse({"conversation": item}, status_code=201)
    except ChatError as exc:
        return _error(str(exc), 500, "chat_unavailable")


async def conversation_messages(request: Request) -> JSONResponse:
    try:
        conversation_id = request.path_params["conversation_id"]
        store = ConversationStore()
        conversation, messages = await asyncio.gather(
            asyncio.to_thread(store.get, conversation_id),
            asyncio.to_thread(store.messages, conversation_id, 100),
        )
        return JSONResponse(
            {"conversation": conversation, "messages": messages}
        )
    except ChatNotFound as exc:
        return _error(str(exc), 404, "conversation_not_found")
    except ChatError as exc:
        return _error(str(exc))


async def conversation_send(request: Request) -> JSONResponse:
    try:
        conversation_id = request.path_params["conversation_id"]
        body = await _json_body(request)
        content = body.get("content")
        if not isinstance(content, str):
            return _error("content moet tekst zijn")
        result = await asyncio.to_thread(send_message, conversation_id, content)
        return JSONResponse(result, status_code=201)
    except ChatNotFound as exc:
        return _error(str(exc), 404, "conversation_not_found")
    except ChatError as exc:
        return _error(str(exc), 422, "chat_failed")
    except Exception as exc:
        logger.exception("chatbericht mislukt (conversation=%s)", conversation_id)
        detail = str(exc)
        if "Marketplace" in detail or "PAYMENT_INSTRUMENT" in detail:
            message = (
                "De AI-dienst is nog niet geactiveerd op dit AWS-account "
                "(Bedrock-modeltoegang/betaalmethode). Beheerder: rond de "
                "Marketplace-activatie af."
            )
        elif "Too many tokens" in detail or "ThrottlingException" in detail:
            message = (
                "De AI-dienst zit aan zijn (opstart)limiet. Beheerder: "
                "Bedrock-servicequota voor het model staat mogelijk nog op 0."
            )
        else:
            message = "Claude kon dit bericht niet verwerken. Probeer het opnieuw."
        return _error(message, 502, "model_unavailable")


async def conversation_delete(request: Request) -> Response:
    try:
        await asyncio.to_thread(
            ConversationStore().delete, request.path_params["conversation_id"]
        )
        return Response(status_code=204)
    except ChatNotFound as exc:
        return _error(str(exc), 404, "conversation_not_found")
    except ChatError as exc:
        return _error(str(exc))
