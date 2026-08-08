"""MCP-server bovenop de Lusmaker-domeinfuncties."""

import argparse
import ipaddress
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # mcp 2.x: FastMCP werd MCPServer
    from mcp.server import MCPServer as FastMCP
from mcp.types import Annotations, ToolAnnotations

from . import __version__
from . import (
    climbs,
    artifacts,
    config,
    draft,
    geocode as geocode_mod,
    geo,
    gpx,
    intents,
    preview,
    profiles,
    readiness,
    regions,
)
from .mcp_contracts import (
    Activity,
    AvoidFactor,
    ClimbListResult,
    ClimbSuggestionResult,
    DraftListResult,
    ExpectedRevision,
    GeocodeResult,
    Goal,
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
    RouteDetailsResult,
    RouteWorkflowResult,
    ToleranceKm,
)


SERVER_INSTRUCTIONS = (
    "Gebruik plan_route voor een nieuwe routewens en adjust_route voor een "
    "bestaande draft. Vraag ontbrekende gebruikerskeuzes uit wanneer een tool "
    "status needs_input teruggeeft. Hergebruik bij retries dezelfde request_id "
    "en stuur bij mutaties de laatst ontvangen revision mee. Poll region_status "
    "na ensure_region. Geef GPX en preview via de teruggegeven artifact-URI's "
    "aan de gebruiker."
)

HOSTED_SERVER_INSTRUCTIONS = (
    "Gebruik plan_route voor een nieuwe routewens en adjust_route voor een "
    "bestaande draft. Deze hosted server bevat een vooraf gebouwde regio: "
    "vraag de gebruiker om een startplaats binnen die regio wanneer de route "
    "erbuiten valt. Vraag ontbrekende keuzes uit bij status needs_input. "
    "Hergebruik bij retries dezelfde request_id en stuur bij mutaties de laatst "
    "ontvangen revision mee. Geef GPX en preview via de artifact-URI's aan de "
    "gebruiker."
)

READ_ONLY_CLOSED = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
READ_ONLY_ROUTER = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)
ADDITIVE_CLOSED = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
MUTATING_CLOSED = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)
MUTATING_ROUTER = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=True,
)
ENSURE_EXTERNAL = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)


def _server(name: str, *, instructions: str = SERVER_INSTRUCTIONS):
    return FastMCP(
        name,
        title="Lusmaker",
        description="Bouw en verfijn fiets- en traillussen met GPX-export.",
        instructions=instructions,
        version=__version__,
    )


mcp = _server("lusmaker")


@mcp.tool(annotations=READ_ONLY_ROUTER)
def status() -> dict[str, Any]:
    """Controleer of de lokale data en GraphHopper beschikbaar zijn."""
    return config.status()


@mcp.tool(annotations=READ_ONLY_CLOSED)
def get_profile(naam: NonEmptyString = "standaard") -> dict[str, Any]:
    """Toon een persistent voorkeurenprofiel; ontbrekend geeft defaults."""
    return profiles.load(naam)


@mcp.tool(annotations=MUTATING_CLOSED)
def update_profile(naam: NonEmptyString, patch: ProfilePatch) -> dict[str, Any]:
    """Pas een getypeerde profielpatch toe; ongeldige velden geven een toolfout."""
    return profiles.apply_patch(naam, patch, bron="mcp")


@mcp.tool(annotations=READ_ONLY_CLOSED)
def list_profiles() -> ProfileListResult:
    """Toon alle opgeslagen voorkeurenprofielen."""
    return {"profielen": profiles.list_all()}


@mcp.tool(annotations=READ_ONLY_ROUTER)
def list_regions() -> dict[str, Any]:
    """Toon beschikbare regiopacks, de default-regio en hun status."""
    return regions.list_all()


@mcp.tool(annotations=ENSURE_EXTERNAL)
def ensure_region(place: NonEmptyString) -> dict[str, Any]:
    """Zoek een plaats of slug en start provisioning van de kleinste regio."""
    from . import provision

    return provision.ensure_region(place)


@mcp.tool(annotations=READ_ONLY_CLOSED)
def region_status(slug: NonEmptyString) -> dict[str, Any]:
    """Toon de pollbare voortgang van een regioprovisioning."""
    from . import provision

    return provision.region_status(slug)


@mcp.tool(annotations=READ_ONLY_CLOSED)
def geocode(query: NonEmptyString, limit: ResultLimit = 5) -> GeocodeResult:
    """Zoek een plaats, straat of adres in de lokale geocoder."""
    return {
        "query": query,
        "resultaten": geocode_mod.geocode(query, limit=limit),
    }


@mcp.tool(annotations=READ_ONLY_CLOSED)
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


@mcp.tool(annotations=ADDITIVE_CLOSED)
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


@mcp.tool(annotations=READ_ONLY_CLOSED)
def list_drafts() -> DraftListResult:
    """Toon alle opgeslagen route-drafts."""
    return {"drafts": draft.list_all()}


@mcp.tool(annotations=READ_ONLY_CLOSED)
def get_draft(draft_id: NonEmptyString) -> dict[str, Any]:
    """Toon de samenvatting en berekende route van één draft."""
    return draft.summary(draft.load(draft_id))


@mcp.tool(annotations=ADDITIVE_CLOSED)
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


@mcp.tool(annotations=MUTATING_CLOSED)
def remove_climb(
    draft_id: NonEmptyString,
    climb_id: NonEmptyString,
    expected_revision: ExpectedRevision | None = None,
) -> dict[str, Any]:
    """Verwijder een klim uit de draft."""
    return draft.remove_climb(
        draft_id, climb_id, expected_revision=expected_revision
    )


@mcp.tool(annotations=ADDITIVE_CLOSED)
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


@mcp.tool(annotations=MUTATING_CLOSED)
def unavoid_place(
    draft_id: NonEmptyString,
    place: NonEmptyString,
    expected_revision: ExpectedRevision | None = None,
) -> dict[str, Any]:
    """Verwijder vermijdzones die overeenkomen met een plaatsnaam."""
    return draft.unavoid_place(
        draft_id, place, expected_revision=expected_revision
    )


@mcp.tool(annotations=MUTATING_ROUTER)
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


@mcp.tool(annotations=MUTATING_ROUTER)
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


@mcp.tool(annotations=READ_ONLY_ROUTER)
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


@mcp.tool(annotations=MUTATING_ROUTER)
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
    naam: NonEmptyString | None = None,
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


@mcp.tool(annotations=MUTATING_ROUTER)
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


@mcp.tool(annotations=MUTATING_ROUTER)
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


@mcp.tool(annotations=MUTATING_CLOSED)
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
    return result


@mcp.tool(annotations=MUTATING_CLOSED)
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
    return result


def route_details(draft_id: NonEmptyString) -> RouteDetailsResult:
    """Toon legs en volledige kwaliteit wanneer compacte route-info niet volstaat."""
    return intents.route_details(draft_id)


lite_mcp = _server("lusmaker-lite")
for _lite_tool, _lite_annotations in (
    (plan_route, MUTATING_ROUTER),
    (adjust_route, MUTATING_ROUTER),
    (suggest_climbs, READ_ONLY_ROUTER),
    (route_details, READ_ONLY_CLOSED),
    (route_readiness, MUTATING_ROUTER),
    (get_profile, READ_ONLY_CLOSED),
    (update_profile, MUTATING_CLOSED),
    (ensure_region, ENSURE_EXTERNAL),
    (region_status, READ_ONLY_CLOSED),
    (list_drafts, READ_ONLY_CLOSED),
):
    lite_mcp.tool(annotations=_lite_annotations)(_lite_tool)


hosted_mcp = _server(
    "lusmaker-hosted", instructions=HOSTED_SERVER_INSTRUCTIONS
)
for _hosted_tool, _hosted_annotations in (
    (plan_route, MUTATING_ROUTER),
    (adjust_route, MUTATING_ROUTER),
    (suggest_climbs, READ_ONLY_ROUTER),
    (route_details, READ_ONLY_CLOSED),
    (route_readiness, MUTATING_ROUTER),
    (get_profile, READ_ONLY_CLOSED),
    (update_profile, MUTATING_CLOSED),
    (list_drafts, READ_ONLY_CLOSED),
):
    hosted_mcp.tool(annotations=_hosted_annotations)(_hosted_tool)


RESOURCE_ANNOTATIONS = Annotations(audience=["user"], priority=1.0)


def route_gpx_resource(draft_id: NonEmptyString) -> bytes:
    """Lees het GPX-bestand van een gerouteerde draft."""
    return artifacts.read(draft_id, "route.gpx")


def route_preview_resource(draft_id: NonEmptyString) -> bytes:
    """Lees de zelfstandige HTML-preview van een gerouteerde draft."""
    return artifacts.read(draft_id, "preview.html")


for _resource_server in (mcp, lite_mcp, hosted_mcp):
    _resource_server.resource(
        "lusmaker://drafts/{draft_id}/route.gpx",
        name="route-gpx",
        title="GPX-route",
        description="Downloadbare GPX van een gerouteerde Lusmaker-draft.",
        mime_type="application/gpx+xml",
        annotations=RESOURCE_ANNOTATIONS,
    )(route_gpx_resource)
    _resource_server.resource(
        "lusmaker://drafts/{draft_id}/preview.html",
        name="route-preview",
        title="Routepreview",
        description="Zelfstandige HTML-kaart en hoogtepreview van een draft.",
        mime_type="text/html",
        annotations=RESOURCE_ANNOTATIONS,
    )(route_preview_resource)


def main(argv: list[str] | None = None) -> None:
    """Start lokaal via stdio of als Streamable HTTP endpoint."""
    parser = argparse.ArgumentParser(prog="lus-mcp")
    parser.add_argument(
        "--lite",
        action="store_true",
        help="exposeer alleen de tien token-zuinige tools",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="MCP-transport (standaard: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
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
        help="sta een niet-lokale bind toe; zet authenticatie/TLS ervoor",
    )
    args = parser.parse_args(argv)
    server = lite_mcp if args.lite else mcp
    if args.transport == "stdio":
        server.run(transport="stdio")
        return

    if not 1 <= args.port <= 65535:
        parser.error("--port moet tussen 1 en 65535 liggen")
    if not args.path.startswith("/"):
        parser.error("--path moet met '/' beginnen")
    try:
        is_loopback = ipaddress.ip_address(args.host).is_loopback
    except ValueError:
        is_loopback = args.host.casefold() == "localhost"
    if not is_loopback and not args.allow_remote:
        parser.error(
            "een niet-lokale --host vereist --allow-remote; gebruik bovendien "
            "een authenticatie- en TLS-proxy"
        )
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
