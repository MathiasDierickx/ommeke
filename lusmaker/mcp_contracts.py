"""Getypeerde MCP-contracten voor schemas en structured content."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal

from mcp.types import ToolAnnotations
from pydantic import ConfigDict, Field
from typing_extensions import NotRequired, TypedDict


# Versiegevoelige OpenAI Apps SDK-wirevelden. Bron (geraadpleegd voor T18):
# https://developers.openai.com/apps-sdk/build/mcp-server/
# ``meta`` wordt op de MCP-wire als ``_meta`` geserialiseerd; toolresultaten
# gebruiken daar ``structuredContent`` en bereiken de component als
# ``window.openai.toolOutput``.
APPS_PREVIEW_URI = "ui://widget/lusmaker-preview.html"
APPS_OUTPUT_TEMPLATE_META_KEY = "openai/outputTemplate"
APPS_STRUCTURED_CONTENT_KEY = "preview"
APPS_COMPONENT_MIME_TYPE = "text/html+skybridge"
APPS_PREVIEW_TOOLS = frozenset({"plan_route", "preview_draft"})
APPS_RESOURCE_META = {
    "openai/widgetPrefersBorder": True,
    "openai/widgetCSP": {
        "connect_domains": [],
        "resource_domains": [
            "https://unpkg.com",
            "https://tile.openstreetmap.org",
        ],
    },
}


@dataclass(frozen=True)
class ToolContract:
    title: str
    annotations: ToolAnnotations


def _annotations(*, read_only: bool, open_world: bool) -> ToolAnnotations:
    return ToolAnnotations(
        readOnlyHint=read_only,
        destructiveHint=False,
        idempotentHint=read_only,
        openWorldHint=open_world,
    )


_READ_ONLY_CLOSED = _annotations(read_only=True, open_world=False)
_READ_ONLY_ROUTER = _annotations(read_only=True, open_world=True)
_MUTATING_CLOSED = _annotations(read_only=False, open_world=False)
_MUTATING_ROUTER = _annotations(read_only=False, open_world=True)

TOOL_CONTRACTS = {
    "status": ToolContract("Status controleren", _READ_ONLY_ROUTER),
    "get_profile": ToolContract("Profiel ophalen", _READ_ONLY_CLOSED),
    "update_profile": ToolContract("Profiel bijwerken", _MUTATING_CLOSED),
    "list_profiles": ToolContract("Profielen tonen", _READ_ONLY_CLOSED),
    "list_regions": ToolContract("Regio's tonen", _READ_ONLY_ROUTER),
    "ensure_region": ToolContract("Regio klaarmaken", _MUTATING_ROUTER),
    "region_status": ToolContract("Regiostatus ophalen", _READ_ONLY_CLOSED),
    "geocode": ToolContract("Plaats zoeken", _READ_ONLY_CLOSED),
    "list_climbs": ToolContract("Klimmen tonen", _READ_ONLY_CLOSED),
    "new_draft": ToolContract("Draft maken", _MUTATING_CLOSED),
    "list_drafts": ToolContract("Drafts tonen", _READ_ONLY_CLOSED),
    "get_draft": ToolContract("Draft ophalen", _READ_ONLY_CLOSED),
    "add_climb": ToolContract("Klim toevoegen", _MUTATING_CLOSED),
    "remove_climb": ToolContract("Klim verwijderen", _MUTATING_CLOSED),
    "avoid_place": ToolContract("Plaats vermijden", _MUTATING_CLOSED),
    "unavoid_place": ToolContract("Plaats toestaan", _MUTATING_CLOSED),
    "route_draft": ToolContract("Draft routeren", _MUTATING_ROUTER),
    "route_readiness": ToolContract("Routevoorkeuren beoordelen", _READ_ONLY_ROUTER),
    "suggest_climbs": ToolContract("Klimmen voorstellen", _READ_ONLY_ROUTER),
    "plan_route": ToolContract("Route plannen", _MUTATING_ROUTER),
    "adjust_route": ToolContract("Route aanpassen", _MUTATING_ROUTER),
    "optimize_draft": ToolContract("Draft optimaliseren", _MUTATING_ROUTER),
    "export_gpx": ToolContract("GPX exporteren", _MUTATING_CLOSED),
    "preview_draft": ToolContract("Preview maken", _MUTATING_CLOSED),
    "download_gpx": ToolContract("GPX downloaden", _READ_ONLY_CLOSED),
    "route_details": ToolContract("Routedetails ophalen", _READ_ONLY_CLOSED),
}


def tool_contract(name: str, *, apps_sdk: bool = False) -> dict[str, Any]:
    contract = TOOL_CONTRACTS[name]
    result = {"title": contract.title, "annotations": contract.annotations}
    if apps_sdk and name in APPS_PREVIEW_TOOLS:
        result["meta"] = {
            APPS_OUTPUT_TEMPLATE_META_KEY: APPS_PREVIEW_URI,
        }
    return result


Activity = Literal["fietsen", "trail"]
Goal = Literal["hoogtemeters", "kort", "toeren"]
GraphProfile = Literal["quiet", "trail"]
Objective = Literal["hm", "hm-per-km", "offroad", "toeren"]
Preference = Literal["vermijd", "ok", "graag"] | None
MainRoadPreference = Literal["vermijd", "ok"] | None
QuietPreference = Literal["belangrijk", "ok"] | None

NonEmptyString = Annotated[
    str,
    Field(min_length=1, description="Niet-lege tekstwaarde."),
]
RouteName = Annotated[
    str,
    Field(
        min_length=1,
        max_length=80,
        description=(
            "Korte, natuurlijke routenaam die de routewens samenvat, bijvoorbeeld "
            "'Heuvelrit rond Wetteren · 38 km'."
        ),
    ),
]
PositiveKm = Annotated[
    float,
    Field(gt=0, le=1000, description="Afstand in kilometer; groter dan nul."),
]
ToleranceKm = Annotated[
    float,
    Field(ge=0, le=100, description="Toegestane afwijking van de doelafstand."),
]
RadiusKm = Annotated[
    float,
    Field(gt=0, le=100, description="Straal in kilometer; groter dan nul."),
]
AvoidFactor = Annotated[
    float,
    Field(
        gt=0,
        le=1,
        description="Zachte routeringsfactor: lager vermijdt sterker; maximaal 1.",
    ),
]
ResultLimit = Annotated[
    int,
    Field(ge=1, le=50, description="Maximum aantal resultaten."),
]
InsertPosition = Annotated[
    int,
    Field(ge=0, description="Nulgebaseerde invoegpositie."),
]
NonNegativeRatio = Annotated[
    float,
    Field(ge=0, description="Minimale hoogtemeter-per-kilometerverhouding."),
]
ExpectedRevision = Annotated[
    int,
    Field(ge=0, description="Revisie uit get_draft of een vorige toolrespons."),
]
RequestId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
        description="Stabiele sleutel waarmee retries dezelfde workflow hervatten.",
    ),
]
NonNegativeWeight = Annotated[
    float,
    Field(ge=0, allow_inf_nan=False, description="Niet-negatief eindig gewicht."),
]


class WeightPatch(TypedDict, total=False):
    __pydantic_config__ = ConfigDict(extra="forbid")

    hoogtemeters: NonNegativeWeight
    offroad: NonNegativeWeight
    populair: NonNegativeWeight
    autovrij: NonNegativeWeight
    kort: NonNegativeWeight


class PreferencePatch(TypedDict, total=False):
    __pydantic_config__ = ConfigDict(extra="forbid")

    kasseien: Preference
    beton: Preference
    steenwegen: MainRoadPreference
    autovrij: QuietPreference
    vermijd_plaatsen: list[str]


class ProfilePatch(TypedDict, total=False):
    __pydantic_config__ = ConfigDict(extra="forbid")

    activiteit: Activity
    gewichten: WeightPatch
    voorkeuren: PreferencePatch


class ArtifactFiles(TypedDict):
    gpx: str
    preview: str


class ArtifactDescriptor(TypedDict):
    type: Literal["gpx", "preview"]
    title: str
    uri: str
    mime_type: str
    bytes: NotRequired[int]
    sha256: NotRequired[str]


class CompactRouteResult(TypedDict):
    status: Literal["ready"]
    draft: str
    revision: int
    request_id: str | None
    km: float
    hoogtemeters: float
    klimmen: list[str]
    kwaliteit: str
    bestanden: ArtifactFiles
    samenvatting: str
    vervolg: list[str]
    artifacts: NotRequired[list[ArtifactDescriptor]]
    constraints: dict[str, Any]


class RouteWorkflowResult(TypedDict, total=False):
    """Objectvorm die zowel ``ready`` als ``needs_input`` kan dragen."""

    status: Literal["ready", "needs_input"]
    draft: str
    revision: int
    request_id: str | None
    km: float
    hoogtemeters: float
    klimmen: list[str]
    kwaliteit: str
    bestanden: ArtifactFiles
    samenvatting: str
    vervolg: list[str]
    artifacts: list[ArtifactDescriptor]
    constraints: dict[str, Any]
    profiel: str
    onbekend: list[str]
    vragen: list[dict[str, Any]]
    advies: str
    next_action: dict[str, Any]


class RouteDetailsResult(TypedDict):
    draft: str
    km: float
    hoogtemeters: float
    legs: list[dict[str, Any]]
    kwaliteit: dict[str, Any]


class GpxDownloadResult(TypedDict):
    draft: str
    naam: str
    download_url: str
    expires_in: int | None
    mime_type: str
    bytes: int
    sha256: str


class ClimbSuggestionResult(TypedDict):
    draft: str
    huidige_km: float
    suggesties: list[dict[str, Any]]
    hint: str


class DraftListResult(TypedDict):
    drafts: list[dict[str, Any]]


class GeocodeResult(TypedDict):
    query: str
    resultaten: list[dict[str, Any]]


class ProfileListResult(TypedDict):
    profielen: list[dict[str, Any]]


class ClimbListResult(TypedDict, total=False):
    klimmen: list[dict[str, Any]]
    niet_opgelost: list[Any]
    bij: str
