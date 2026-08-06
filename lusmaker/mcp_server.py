"""MCP-server bovenop de Lusmaker-domeinfuncties."""

import argparse

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # mcp 2.x: FastMCP werd MCPServer
    from mcp.server import MCPServer as FastMCP

from . import (
    climbs,
    config,
    draft,
    geocode as geocode_mod,
    geo,
    gpx,
    intents,
    preview,
    regions,
)


mcp = FastMCP("lusmaker")


@mcp.tool()
def status() -> dict:
    """Controleer of de lokale data en GraphHopper beschikbaar zijn."""
    return config.status()


@mcp.tool()
def list_regions() -> dict:
    """Toon beschikbare regiopacks, de default-regio en hun status."""
    return regions.list_all()


@mcp.tool()
def ensure_region(place: str) -> dict:
    """Zoek een plaats of slug en start provisioning van de kleinste regio."""
    from . import provision

    return provision.ensure_region(place)


@mcp.tool()
def region_status(slug: str) -> dict:
    """Toon de pollbare voortgang van een regioprovisioning."""
    from . import provision

    return provision.region_status(slug)


@mcp.tool()
def geocode(query: str, limit: int = 5) -> dict:
    """Zoek een plaats, straat of adres in de lokale geocoder."""
    return {
        "query": query,
        "resultaten": geocode_mod.geocode(query, limit=limit),
    }


@mcp.tool()
def list_climbs(
    near: str | None = None,
    radius_km: float = 15,
    region: str | None = None,
) -> dict:
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


@mcp.tool()
def new_draft(
    start: str,
    name: str | None = None,
    loop: bool = True,
    end: str | None = None,
    profiel: str = "quiet",
    strict: bool = False,
    vermijd_kasseien: bool = False,
    vermijd_beton: bool = False,
    region: str | None = None,
) -> dict:
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
        region=region,
    )


@mcp.tool()
def list_drafts() -> dict:
    """Toon alle opgeslagen route-drafts."""
    return {"drafts": draft.list_all()}


@mcp.tool()
def get_draft(draft_id: str) -> dict:
    """Toon de samenvatting en berekende route van één draft."""
    return draft.summary(draft.load(draft_id))


@mcp.tool()
def add_climb(
    draft_id: str, climb_id: str, position: int | None = None
) -> dict:
    """Voeg een bekende klim toe op een optionele positie in de draft."""
    return draft.add_climb(draft_id, climb_id, position=position)


@mcp.tool()
def remove_climb(draft_id: str, climb_id: str) -> dict:
    """Verwijder een klim uit de draft."""
    return draft.remove_climb(draft_id, climb_id)


@mcp.tool()
def avoid_place(
    draft_id: str,
    place: str,
    radius_km: float = 2.5,
    factor: float = 0.35,
) -> dict:
    """Voeg een zachte vermijdzone rond een plaats toe."""
    return draft.avoid_place(
        draft_id, place, radius_km=radius_km, factor=factor
    )


@mcp.tool()
def unavoid_place(draft_id: str, place: str) -> dict:
    """Verwijder vermijdzones die overeenkomen met een plaatsnaam."""
    return draft.unavoid_place(draft_id, place)


@mcp.tool()
def route_draft(draft_id: str) -> dict:
    """Routeer de draft via GraphHopper en bereken de kwaliteitsmetrieken."""
    d = draft.load(draft_id)
    with draft.region_scope(d):
        return draft.route(d, climbs.all_climbs())


@mcp.tool()
def suggest_climbs(
    draft_id: str, max_detour_km: float = 8, limit: int = 6
) -> dict:
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


@mcp.tool()
def plan_route(
    start: str,
    region: str | None = None,
    max_km: float | None = None,
    doel: str = "hoogtemeters",
    via_klimmen: list[str] = [],
    vermijd_plaatsen: list[str] = [],
    kasseien: bool = False,
    beton_vermijden: bool = True,
    strict: bool = False,
    naam: str | None = None,
    activiteit: str = "fietsen",
    geen_opvulling: bool = False,
) -> dict:
    """Maak en exporteer een fiets- of traillus vanuit één routewens."""
    return intents.plan_route(
        start=start,
        region=region,
        max_km=max_km,
        doel=doel,
        via_klimmen=via_klimmen,
        vermijd_plaatsen=vermijd_plaatsen,
        kasseien=kasseien,
        beton_vermijden=beton_vermijden,
        strict=strict,
        naam=naam,
        activiteit=activiteit,
        geen_opvulling=geen_opvulling,
    )


@mcp.tool()
def adjust_route(
    draft_id: str,
    voeg_klimmen_toe: list[str] = [],
    verwijder_klimmen: list[str] = [],
    vermijd_plaatsen: list[str] = [],
    niet_meer_vermijden: list[str] = [],
    max_km: float | None = None,
) -> dict:
    """Pas meerdere routewensen toe en lever één compact nieuw resultaat."""
    return intents.adjust_route(
        draft_id=draft_id,
        voeg_klimmen_toe=voeg_klimmen_toe,
        verwijder_klimmen=verwijder_klimmen,
        vermijd_plaatsen=vermijd_plaatsen,
        niet_meer_vermijden=niet_meer_vermijden,
        max_km=max_km,
    )


@mcp.tool()
def optimize_draft(
    draft_id: str,
    max_km: float,
    objective: str = "hm",
    min_ratio: float = 8.0,
    geen_opvulling: bool = False,
) -> dict:
    """Vul de route greedy met klimmen binnen een hard afstandsbudget."""
    d = draft.load(draft_id)
    with draft.region_scope(d):
        return draft.optimize(
            d,
            climbs.all_climbs(),
            max_km=max_km,
            objective=objective,
            min_ratio=min_ratio,
            fill=not geen_opvulling,
        )


@mcp.tool()
def export_gpx(draft_id: str, output_path: str | None = None) -> dict:
    """Exporteer een gerouteerde draft als GPX-bestand."""
    d = draft.load(draft_id)
    path = output_path or f"{d['name']}.gpx"
    with draft.region_scope(d):
        return gpx.export(d, climbs.all_climbs(), path)


@mcp.tool()
def preview_draft(draft_id: str, output_path: str | None = None) -> dict:
    """Schrijf een HTML-kaartpreview van een gerouteerde draft."""
    d = draft.load(draft_id)
    path = output_path or f"{d['name']}-preview.html"
    with draft.region_scope(d):
        return preview.export(d, climbs.all_climbs(), path)


def route_details(draft_id: str) -> dict:
    """Toon legs en volledige kwaliteit wanneer compacte route-info niet volstaat."""
    return intents.route_details(draft_id)


lite_mcp = FastMCP("lusmaker-lite")
for _lite_tool in (
    plan_route,
    adjust_route,
    suggest_climbs,
    route_details,
    ensure_region,
    region_status,
    list_drafts,
):
    lite_mcp.tool()(_lite_tool)


def main(argv: list[str] | None = None) -> None:
    """Start de Lusmaker MCP-server via stdio."""
    parser = argparse.ArgumentParser(prog="lus-mcp")
    parser.add_argument(
        "--lite",
        action="store_true",
        help="exposeer alleen de zeven token-zuinige tools",
    )
    args = parser.parse_args(argv)
    (lite_mcp if args.lite else mcp).run(transport="stdio")


if __name__ == "__main__":
    main()
