"""MCP-server bovenop de Lusmaker-domeinfuncties."""

import argparse
import functools
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # mcp 2.x: FastMCP werd MCPServer
    from mcp.server import MCPServer as FastMCP
from mcp.types import Annotations, CallToolResult, TextContent
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from . import __version__
from . import (
    artifacts,
    aws_state,
    climbs,
    config,
    draft,
    geocode as geocode_mod,
    geo,
    gpx,
    intents,
    oauth,
    preview,
    profiles,
    readiness,
    regions,
    tenant,
)
from .mcp_contracts import (
    Activity,
    APPS_COMPONENT_MIME_TYPE,
    APPS_PREVIEW_TOOLS,
    APPS_PREVIEW_URI,
    APPS_RESOURCE_META,
    APPS_STRUCTURED_CONTENT_KEY,
    AvoidFactor,
    ClimbListResult,
    ClimbSuggestionResult,
    DraftListResult,
    ExpectedRevision,
    GeocodeResult,
    Goal,
    GpxDownloadResult,
    GraphProfile,
    InsertPosition,
    NonEmptyString,
    NonNegativeRatio,
    Objective,
    PositiveKm,
    ProfileListResult,
    ProfilePatch,
    RadiusKm,
    RequestId,
    ResultLimit,
    RouteName,
    RouteDetailsResult,
    RouteWorkflowResult,
    ToleranceKm,
    tool_contract,
)


SERVER_INSTRUCTIONS = (
    "Gebruik plan_route voor een nieuwe routewens en adjust_route voor een "
    "bestaande draft. Vraag ontbrekende gebruikerskeuzes uit wanneer een tool "
    "status needs_input teruggeeft. Hergebruik bij retries dezelfde request_id "
    "en stuur bij mutaties de laatst ontvangen revision mee. Poll region_status "
    "na ensure_region. Geef plan_route altijd een korte naam die de routewens "
    "samenvat. Gebruik download_gpx wanneer de gebruiker het GPX-bestand wil."
)

HOSTED_SERVER_INSTRUCTIONS = (
    "Gebruik plan_route voor een nieuwe routewens en adjust_route voor een "
    "bestaande draft. Deze hosted server bevat een vooraf gebouwde regio: "
    "vraag de gebruiker om een startplaats binnen die regio wanneer de route "
    "erbuiten valt. Vraag ontbrekende keuzes uit bij status needs_input. "
    "Hergebruik bij retries dezelfde request_id en stuur bij mutaties de laatst "
    "ontvangen revision mee. Geef plan_route altijd een korte naam die de "
    "routewens samenvat. Gebruik download_gpx voor een tijdelijke HTTPS-link."
)

REMOTE_SERVER_INSTRUCTIONS = (
    "Gebruik plan_route voor een nieuwe routewens en adjust_route voor een "
    "bestaande draft. Vraag ontbrekende gebruikerskeuzes uit bij status "
    "needs_input. Hergebruik bij retries dezelfde request_id en stuur bij "
    "mutaties de laatst ontvangen revision mee. Geef plan_route altijd een "
    "korte naam die de routewens samenvat. Gebruik download_gpx wanneer de "
    "gebruiker het GPX-bestand wil."
)


def _server(
    name: str,
    *,
    instructions: str = SERVER_INSTRUCTIONS,
    **kwargs,
):
    return FastMCP(
        name,
        title="Lusmaker",
        description="Bouw en verfijn fiets- en traillussen met GPX-export.",
        instructions=instructions,
        version=__version__,
        **kwargs,
    )


mcp = _server("lusmaker")


@mcp.tool(**tool_contract("status"))
def status() -> dict[str, Any]:
    """Controleer of de lokale data en GraphHopper beschikbaar zijn."""
    return config.status()


@mcp.tool(**tool_contract("get_profile"))
def get_profile(naam: NonEmptyString = "standaard") -> dict[str, Any]:
    """Toon een persistent voorkeurenprofiel; ontbrekend geeft defaults."""
    return profiles.load(naam)


@mcp.tool(**tool_contract("update_profile"))
def update_profile(naam: NonEmptyString, patch: ProfilePatch) -> dict[str, Any]:
    """Pas een getypeerde profielpatch toe; ongeldige velden geven een toolfout."""
    return profiles.apply_patch(naam, patch, bron="mcp")


@mcp.tool(**tool_contract("list_profiles"))
def list_profiles() -> ProfileListResult:
    """Toon alle opgeslagen voorkeurenprofielen."""
    return {"profielen": profiles.list_all()}


@mcp.tool(**tool_contract("list_regions"))
def list_regions() -> dict[str, Any]:
    """Toon beschikbare regiopacks, de default-regio en hun status."""
    return regions.list_all()


@mcp.tool(**tool_contract("ensure_region"))
def ensure_region(place: NonEmptyString) -> dict[str, Any]:
    """Zoek een plaats of slug en start provisioning van de kleinste regio."""
    from . import provision

    return provision.ensure_region(place)


@mcp.tool(**tool_contract("region_status"))
def region_status(slug: NonEmptyString) -> dict[str, Any]:
    """Toon de pollbare voortgang van een regioprovisioning."""
    from . import provision

    return provision.region_status(slug)


@mcp.tool(**tool_contract("geocode"))
def geocode(query: NonEmptyString, limit: ResultLimit = 5) -> GeocodeResult:
    """Zoek een plaats, straat of adres in de lokale geocoder."""
    return {
        "query": query,
        "resultaten": geocode_mod.geocode(query, limit=limit),
    }


@mcp.tool(**tool_contract("list_climbs"))
def list_climbs(
    near: NonEmptyString | None = None,
    radius_km: RadiusKm = 15,
    region: NonEmptyString | None = None,
) -> ClimbListResult:
    """Toon bekende klimmen, eventueel rond een plaats of ``lat,lon``."""
    with config.use_region(region):
        if near is None:
            data = climbs.load()
            return {
                "klimmen": [
                    climbs.summary(climb)
                    for climb in sorted(
                        data["climbs"].values(), key=lambda climb: climb["id"]
                    )
                ],
                "niet_opgelost": data["failed"],
            }

        point, _ = geocode_mod.resolve(near)
        results = []
        for climb in climbs.all_climbs().values():
            distance_m = geo.haversine(
                point["lat"], point["lon"], climb["foot"][0], climb["foot"][1]
            )
            if distance_m <= radius_km * 1000:
                item = climbs.summary(climb)
                item["afstand_km"] = round(distance_m / 1000, 1)
                results.append(item)
        results.sort(key=lambda climb: climb["afstand_km"])
        return {"bij": point["label"], "klimmen": results}


@mcp.tool(**tool_contract("new_draft"))
def new_draft(
    start: NonEmptyString,
    name: NonEmptyString | None = None,
    loop: bool = True,
    end: NonEmptyString | None = None,
    profiel: GraphProfile = "quiet",
    strict: bool = False,
    vermijd_kasseien: bool = False,
    vermijd_beton: bool = False,
    autovrij: bool = False,
    region: NonEmptyString | None = None,
    profiel_naam: NonEmptyString | None = None,
) -> dict[str, Any]:
    """Maak een quiet-fiets- of traildraft vanaf een plaats of ``lat,lon``."""
    return draft.create(
        start=start,
        name=name,
        loop=loop,
        end=end,
        profile=profiel,
        strict=strict,
        avoid_cobbles=vermijd_kasseien,
        avoid_concrete=vermijd_beton,
        avoid_busy=autovrij,
        region=region,
        profile_doc=profiel_naam,
    )


@mcp.tool(**tool_contract("list_drafts"))
def list_drafts() -> DraftListResult:
    """Toon alle opgeslagen route-drafts."""
    return {"drafts": draft.list_all()}


@mcp.tool(**tool_contract("get_draft"))
def get_draft(draft_id: NonEmptyString) -> dict[str, Any]:
    """Toon de samenvatting en berekende route van één draft."""
    return draft.summary(draft.load(draft_id))


@mcp.tool(**tool_contract("add_climb"))
def add_climb(
    draft_id: NonEmptyString,
    climb_id: NonEmptyString,
    position: InsertPosition | None = None,
    expected_revision: ExpectedRevision | None = None,
) -> dict[str, Any]:
    """Voeg een bekende klim toe op een optionele positie in de draft."""
    return draft.add_climb(
        draft_id,
        climb_id,
        position=position,
        expected_revision=expected_revision,
    )


@mcp.tool(**tool_contract("remove_climb"))
def remove_climb(
    draft_id: NonEmptyString,
    climb_id: NonEmptyString,
    expected_revision: ExpectedRevision | None = None,
) -> dict[str, Any]:
    """Verwijder een klim uit de draft."""
    return draft.remove_climb(
        draft_id, climb_id, expected_revision=expected_revision
    )


@mcp.tool(**tool_contract("avoid_place"))
def avoid_place(
    draft_id: NonEmptyString,
    place: NonEmptyString,
    radius_km: RadiusKm = 2.5,
    factor: AvoidFactor = 0.35,
    expected_revision: ExpectedRevision | None = None,
) -> dict[str, Any]:
    """Voeg een zachte vermijdzone rond een plaats toe."""
    return draft.avoid_place(
        draft_id,
        place,
        radius_km=radius_km,
        factor=factor,
        expected_revision=expected_revision,
    )


@mcp.tool(**tool_contract("unavoid_place"))
def unavoid_place(
    draft_id: NonEmptyString,
    place: NonEmptyString,
    expected_revision: ExpectedRevision | None = None,
) -> dict[str, Any]:
    """Verwijder vermijdzones die overeenkomen met een plaatsnaam."""
    return draft.unavoid_place(
        draft_id, place, expected_revision=expected_revision
    )


@mcp.tool(**tool_contract("route_draft"))
def route_draft(
    draft_id: NonEmptyString,
    expected_revision: ExpectedRevision | None = None,
) -> dict[str, Any]:
    """Routeer de draft via GraphHopper en bereken de kwaliteitsmetrieken."""
    d = draft.load(draft_id)
    draft.require_revision(d, expected_revision)
    with draft.region_scope(d):
        return draft.route(
            d, climbs.all_climbs(), expected_revision=expected_revision
        )


@mcp.tool(**tool_contract("route_readiness"))
def route_readiness(
    draft_id: NonEmptyString,
    profiel_naam: NonEmptyString = "standaard",
    expected_revision: ExpectedRevision | None = None,
) -> dict[str, Any]:
    """Verken en beoordeel de routevoorkeuren. Stel de vragen aan de gebruiker,
    pas antwoorden toe via update_profile (of avoid_place bij doel=draft), en
    vraag daarna opnieuw readiness op tot klaar=true; routeer dan met optimize.
    """
    d = draft.load(draft_id)
    draft.require_revision(d, expected_revision)
    with draft.region_scope(d):
        climb_db = climbs.all_climbs()
        draft.probe(d, climb_db)
        return readiness.assess(d, profiles.load(profiel_naam), climb_db)


@mcp.tool(**tool_contract("suggest_climbs"))
def suggest_climbs(
    draft_id: NonEmptyString,
    max_detour_km: PositiveKm = 8,
    limit: ResultLimit = 6,
) -> ClimbSuggestionResult:
    """Zoek klimmen die met weinig extra kilometers in de route passen."""
    d = draft.load(draft_id)
    with draft.region_scope(d):
        suggestions = draft.suggest(
            d,
            climbs.all_climbs(),
            max_detour_km=max_detour_km,
            limit=limit,
        )
    return {
        "draft": d["id"],
        "huidige_km": d["computed"]["total_km"],
        "suggesties": suggestions,
        "hint": (
            "stel deze aan de gebruiker voor; toevoegen kan met het "
            "'voorstel'-commando"
        ),
    }


@mcp.tool(**tool_contract("plan_route"))
def plan_route(
    start: NonEmptyString,
    region: NonEmptyString | None = None,
    max_km: PositiveKm | None = None,
    target_km: PositiveKm | None = None,
    tolerance_km: ToleranceKm = 2.5,
    doel: Goal = "hoogtemeters",
    via_klimmen: list[str] = [],
    vermijd_plaatsen: list[str] = [],
    kasseien: bool | None = None,
    beton_vermijden: bool | None = None,
    autovrij: bool | None = None,
    strict: bool | None = None,
    naam: RouteName | None = None,
    activiteit: Activity = "fietsen",
    geen_opvulling: bool = False,
    profiel_naam: NonEmptyString = "standaard",
    request_id: RequestId | None = None,
) -> RouteWorkflowResult:
    """Start een routeworkflow; kan eerst gerichte ``needs_input``-vragen geven."""
    return intents.plan_route(
        start=start,
        region=region,
        max_km=max_km,
        target_km=target_km,
        tolerance_km=tolerance_km,
        doel=doel,
        via_klimmen=via_klimmen,
        vermijd_plaatsen=vermijd_plaatsen,
        kasseien=kasseien,
        beton_vermijden=beton_vermijden,
        autovrij=autovrij,
        strict=strict,
        naam=naam,
        activiteit=activiteit,
        geen_opvulling=geen_opvulling,
        profiel_naam=profiel_naam,
        check_readiness=True,
        request_id=request_id,
    )


@mcp.tool(**tool_contract("adjust_route"))
def adjust_route(
    draft_id: NonEmptyString,
    voeg_klimmen_toe: list[str] = [],
    verwijder_klimmen: list[str] = [],
    vermijd_plaatsen: list[str] = [],
    niet_meer_vermijden: list[str] = [],
    sta_plaatsen_toe: list[str] = [],
    max_km: PositiveKm | None = None,
    target_km: PositiveKm | None = None,
    tolerance_km: ToleranceKm | None = None,
    doel: Goal | None = None,
    geen_opvulling: bool | None = None,
    profiel_naam: NonEmptyString | None = None,
    expected_revision: ExpectedRevision | None = None,
) -> RouteWorkflowResult:
    """Vervolg of wijzig een routeworkflow; kan opnieuw om input vragen."""
    return intents.adjust_route(
        draft_id=draft_id,
        voeg_klimmen_toe=voeg_klimmen_toe,
        verwijder_klimmen=verwijder_klimmen,
        vermijd_plaatsen=vermijd_plaatsen,
        niet_meer_vermijden=niet_meer_vermijden,
        sta_plaatsen_toe=sta_plaatsen_toe,
        max_km=max_km,
        target_km=target_km,
        tolerance_km=tolerance_km,
        doel=doel,
        geen_opvulling=geen_opvulling,
        profiel_naam=profiel_naam,
        check_readiness=True,
        expected_revision=expected_revision,
    )


@mcp.tool(**tool_contract("optimize_draft"))
def optimize_draft(
    draft_id: NonEmptyString,
    max_km: PositiveKm,
    objective: Objective | None = None,
    min_ratio: NonNegativeRatio = 8.0,
    geen_opvulling: bool = False,
    target_km: PositiveKm | None = None,
    expected_revision: ExpectedRevision | None = None,
) -> dict[str, Any]:
    """Vul de route greedy met klimmen binnen een hard afstandsbudget."""
    d = draft.load(draft_id)
    draft.require_revision(d, expected_revision)
    with draft.region_scope(d):
        return draft.optimize(
            d,
            climbs.all_climbs(),
            max_km=max_km,
            objective=objective,
            min_ratio=min_ratio,
            fill=not geen_opvulling,
            fill_target_km=target_km,
        )


@mcp.tool(**tool_contract("export_gpx"))
def export_gpx(
    draft_id: NonEmptyString, output_path: str | None = None
) -> dict[str, Any]:
    """Exporteer een gerouteerde draft als GPX-bestand."""
    d = draft.load(draft_id)
    path = artifacts.safe_output_path(draft_id, "route.gpx", output_path)
    with draft.region_scope(d):
        result = gpx.export(d, climbs.all_climbs(), str(path))
        canonical = artifacts.safe_output_path(draft_id, "route.gpx")
        if canonical != path:
            gpx.export(d, climbs.all_climbs(), str(canonical))
        artifacts.publish(draft_id, "route.gpx")
    result["artifact"] = artifacts.describe(draft_id, "route.gpx")
    result["file"] = artifacts.output_reference(
        result["file"], draft_id, "route.gpx"
    )
    return result


@mcp.tool(**tool_contract("preview_draft"))
def preview_draft(
    draft_id: NonEmptyString, output_path: str | None = None
) -> dict[str, Any]:
    """Schrijf een HTML-kaartpreview van een gerouteerde draft."""
    d = draft.load(draft_id)
    path = artifacts.safe_output_path(draft_id, "preview.html", output_path)
    with draft.region_scope(d):
        result = preview.export(d, climbs.all_climbs(), str(path))
        canonical = artifacts.safe_output_path(draft_id, "preview.html")
        if canonical != path:
            preview.export(d, climbs.all_climbs(), str(canonical))
        artifacts.publish(draft_id, "preview.html")
    result["artifact"] = artifacts.describe(draft_id, "preview.html")
    result["file"] = artifacts.output_reference(
        result["file"], draft_id, "preview.html"
    )
    return result


def route_details(draft_id: NonEmptyString) -> RouteDetailsResult:
    """Toon legs en volledige kwaliteit wanneer compacte route-info niet volstaat."""
    return intents.route_details(draft_id)


@mcp.tool(**tool_contract("download_gpx"))
def download_gpx(draft_id: NonEmptyString) -> GpxDownloadResult:
    """Maak een downloadbare GPX-link; hosted links vervallen na 15 minuten."""
    d = draft.load(draft_id)
    descriptor = artifacts.describe(draft_id, "route.gpx")
    if "bytes" not in descriptor or "sha256" not in descriptor:
        raise artifacts.ArtifactError(
            f"GPX voor draft '{draft_id}' bestaat niet; routeer eerst"
        )
    hosted = aws_state.enabled()
    return {
        "draft": draft_id,
        "naam": d.get("name") or "Lusmaker-route",
        "download_url": artifacts.temporary_download_url(
            draft_id,
            "route.gpx",
            download_name=f"{d.get('name') or 'lusmaker-route'}.gpx",
        ),
        "expires_in": 900 if hosted else None,
        "mime_type": descriptor["mime_type"],
        "bytes": descriptor["bytes"],
        "sha256": descriptor["sha256"],
    }


LITE_TOOLS = (
    plan_route,
    adjust_route,
    suggest_climbs,
    route_details,
    download_gpx,
    route_readiness,
    get_profile,
    update_profile,
    ensure_region,
    region_status,
    list_drafts,
)

FULL_TOOLS = (
    status,
    get_profile,
    update_profile,
    list_profiles,
    list_regions,
    ensure_region,
    region_status,
    geocode,
    list_climbs,
    new_draft,
    list_drafts,
    get_draft,
    add_climb,
    remove_climb,
    avoid_place,
    unavoid_place,
    route_draft,
    route_readiness,
    suggest_climbs,
    plan_route,
    adjust_route,
    optimize_draft,
    export_gpx,
    download_gpx,
    preview_draft,
)


def _apps_sdk_enabled() -> bool:
    return os.environ.get("LUSMAKER_APPS_SDK") == "1"


def _apps_tool_result(result: dict, draft_id: str | None) -> CallToolResult:
    """Splits compacte modeltekst en de uitgebreidere componentdata."""
    structured = dict(result)
    if draft_id and result.get("status") != "needs_input":
        d = draft.load(draft_id)
        with draft.region_scope(d):
            structured[APPS_STRUCTURED_CONTENT_KEY] = preview.component_payload(
                d, climbs.all_climbs()
            )
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=json.dumps(
                    result,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        ],
        structured_content=structured,
    )


def _apps_tool(tool):
    @functools.wraps(tool)
    def wrapped(*args, **kwargs):
        result = tool(*args, **kwargs)
        draft_id = result.get("draft")
        if tool.__name__ == "preview_draft":
            draft_id = kwargs.get("draft_id") or (args[0] if args else None)
        return _apps_tool_result(result, draft_id)

    return wrapped


def _register_tools(server, tools, *, apps_sdk: bool = False) -> None:
    for tool in tools:
        handler = (
            _apps_tool(tool)
            if apps_sdk and tool.__name__ in APPS_PREVIEW_TOOLS
            else tool
        )
        server.tool(**tool_contract(tool.__name__, apps_sdk=apps_sdk))(handler)


lite_mcp = _server("lusmaker-lite")
for _lite_tool in LITE_TOOLS:
    lite_mcp.tool(**tool_contract(_lite_tool.__name__))(_lite_tool)


hosted_mcp = _server(
    "lusmaker-hosted", instructions=HOSTED_SERVER_INSTRUCTIONS
)
for _hosted_tool in (
    plan_route,
    adjust_route,
    suggest_climbs,
    route_details,
    download_gpx,
    route_readiness,
    get_profile,
    update_profile,
    list_drafts,
):
    hosted_mcp.tool(**tool_contract(_hosted_tool.__name__))(_hosted_tool)


RESOURCE_ANNOTATIONS = Annotations(audience=["user"], priority=1.0)


def route_gpx_resource(draft_id: NonEmptyString) -> bytes:
    """Lees het GPX-bestand van een gerouteerde draft."""
    return artifacts.read(draft_id, "route.gpx")


def route_preview_resource(draft_id: NonEmptyString) -> bytes:
    """Lees de zelfstandige HTML-preview van een gerouteerde draft."""
    return artifacts.read(draft_id, "preview.html")


def preview_component_resource() -> str:
    """Lees het statische ChatGPT-componentdocument uit het Pythonpakket."""
    return (
        Path(__file__).with_name("appsdk") / "preview-component.html"
    ).read_text(encoding="utf-8")


def _register_resources(server) -> None:
    server.resource(
        "lusmaker://drafts/{draft_id}/route.gpx",
        name="route-gpx",
        title="GPX-route",
        description="Downloadbare GPX van een gerouteerde Lusmaker-draft.",
        mime_type="application/gpx+xml",
        annotations=RESOURCE_ANNOTATIONS,
    )(route_gpx_resource)
    server.resource(
        "lusmaker://drafts/{draft_id}/preview.html",
        name="route-preview",
        title="Routepreview",
        description="Zelfstandige HTML-kaart en hoogtepreview van een draft.",
        mime_type="text/html",
        annotations=RESOURCE_ANNOTATIONS,
    )(route_preview_resource)


def _register_apps_resource(server) -> None:
    server.resource(
        APPS_PREVIEW_URI,
        name="lusmaker-preview-component",
        title="Lusmaker-routepreview",
        description="Interactieve kaart, klimmen en hoogteprofiel in ChatGPT.",
        mime_type=APPS_COMPONENT_MIME_TYPE,
        annotations=RESOURCE_ANNOTATIONS,
        meta=APPS_RESOURCE_META,
    )(preview_component_resource)


for _resource_server in (mcp, lite_mcp, hosted_mcp):
    _register_resources(_resource_server)


class _RemoteUserScopeMiddleware:
    """Koppel elk MCP-bericht aan het gevalideerde token-subject."""

    def __init__(self, *, auth_disabled: bool, public_url: str):
        self.auth_disabled = auth_disabled
        self.public_url = public_url

    async def __call__(self, context, call_next):
        access_token = get_access_token()
        uid = "local" if self.auth_disabled else getattr(
            access_token, "subject", None
        )
        if not uid:
            raise oauth.OAuthError("bearer-token mist een subject-claim")
        with (
            config.user_scope(uid),
            tenant.use(uid),
            artifacts.delivery_mode(True, public_url=self.public_url),
        ):
            return await call_next(context)


def _auth_error(public_url: str) -> JSONResponse:
    metadata = f"{public_url}/.well-known/oauth-protected-resource"
    return JSONResponse(
        {"error": "invalid_token", "error_description": "Authentication required"},
        status_code=401,
        headers={
            "WWW-Authenticate": (
                'Bearer error="invalid_token", '
                'error_description="Authentication required", '
                f'resource_metadata="{metadata}"'
            )
        },
    )


def _register_file_route(
    server,
    *,
    auth_disabled: bool,
    public_url: str,
) -> None:
    @server.custom_route(
        "/files/{uid}/{draft_id}/{filename}", methods=["GET"]
    )
    async def download_file(request: Request) -> Response:
        access_token = get_access_token()
        token_uid = "local" if auth_disabled else getattr(
            access_token, "subject", None
        )
        if not token_uid:
            return _auth_error(public_url)
        requested_uid = request.path_params["uid"]
        if requested_uid != token_uid:
            return JSONResponse(
                {"error": "geen toegang tot export van een andere gebruiker"},
                status_code=403,
            )
        draft_id = request.path_params["draft_id"]
        filename = request.path_params["filename"]
        try:
            config.validate_user_id(requested_uid)
            draft.validate_draft_id(draft_id)
            mime_type = artifacts.content_type(filename)
            with config.user_scope(token_uid), tenant.use(token_uid):
                payload = artifacts.read(draft_id, filename)
        except (ValueError, draft.DraftError, artifacts.ArtifactError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        disposition = "attachment" if filename.endswith(".gpx") else "inline"
        return Response(
            payload,
            media_type=mime_type,
            headers={
                "Content-Disposition": f'{disposition}; filename="{filename}"',
                "Cache-Control": "private, no-store",
            },
        )


def build_http_server(
    *,
    full: bool = False,
    auth_disabled: bool | None = None,
    oauth_config: oauth.OAuthConfig | None = None,
    token_verifier=None,
    public_url: str | None = None,
    apps_sdk: bool | None = None,
):
    """Bouw de remote FastMCP-app met auth, scoping en bestandsdownloads."""
    base_url = artifacts.public_base_url(public_url)
    if urlsplit(base_url).path not in {"", "/"}:
        raise oauth.OAuthError("LUSMAKER_PUBLIC_URL mag geen pad bevatten")
    auth_disabled = (
        oauth.auth_disabled() if auth_disabled is None else auth_disabled
    )
    apps_sdk = _apps_sdk_enabled() if apps_sdk is None else apps_sdk
    kwargs = {
        "middleware": [
            _RemoteUserScopeMiddleware(
                auth_disabled=auth_disabled, public_url=base_url
            )
        ]
    }
    if not auth_disabled:
        oauth_config = oauth_config or oauth.OAuthConfig.from_env()
        kwargs["auth"] = AuthSettings(
            issuer_url=oauth_config.issuer,
            resource_server_url=base_url,
        )
        kwargs["token_verifier"] = token_verifier or oauth.JWTTokenVerifier(
            oauth_config
        )
    server = _server(
        "lusmaker-http",
        instructions=REMOTE_SERVER_INSTRUCTIONS,
        **kwargs,
    )
    _register_tools(
        server,
        FULL_TOOLS if full else LITE_TOOLS,
        apps_sdk=apps_sdk,
    )
    _register_resources(server)
    if apps_sdk:
        _register_apps_resource(server)
    _register_file_route(
        server, auth_disabled=auth_disabled, public_url=base_url
    )
    return server


def main(argv: list[str] | None = None) -> None:
    """Start lokaal via stdio of als Streamable HTTP endpoint."""
    parser = argparse.ArgumentParser(prog="lus-mcp")
    toolset = parser.add_mutually_exclusive_group()
    toolset.add_argument(
        "--lite",
        action="store_true",
        help="exposeer alleen de tien token-zuinige tools",
    )
    toolset.add_argument(
        "--full",
        action="store_true",
        help="exposeer in HTTP-modus de volledige toolset",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="start met Streamable HTTP; standaard lite en OAuth-verplicht",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=None,
        help="legacy-alias voor de transportkeuze",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8123)
    parser.add_argument("--path", default="/mcp", help="HTTP-pad voor MCP")
    parser.add_argument(
        "--stateless-http",
        action="store_true",
        help="bewaar geen MCP-sessie tussen HTTP-requests",
    )
    parser.add_argument(
        "--json-response",
        action="store_true",
        help="antwoord via JSON in plaats van een SSE-stream",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)
    transport = args.transport or (
        "streamable-http" if args.http else "stdio"
    )
    if args.http and transport != "streamable-http":
        parser.error("--http kan niet met --transport stdio")
    if transport == "stdio":
        server = lite_mcp if args.lite else mcp
        server.run(transport="stdio")
        return

    if not 1 <= args.port <= 65535:
        parser.error("--port moet tussen 1 en 65535 liggen")
    if not args.path.startswith("/"):
        parser.error("--path moet met '/' beginnen")
    try:
        server = build_http_server(full=args.full)
    except (artifacts.ArtifactError, oauth.OAuthError, ValueError) as exc:
        parser.error(str(exc))
    server.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        streamable_http_path=args.path,
        stateless_http=args.stateless_http,
        json_response=args.json_response,
    )


if __name__ == "__main__":
    main()
