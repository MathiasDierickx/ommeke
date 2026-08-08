"""Getypeerde MCP-contracten voor schemas en structured content."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field
from typing_extensions import NotRequired, TypedDict


Activity = Literal["fietsen", "trail"]
Goal = Literal["hoogtemeters", "kort", "toeren"]
GraphProfile = Literal["quiet", "trail"]
Objective = Literal["hm", "hm-per-km", "offroad", "toeren"]
Preference = Literal["vermijd", "ok", "graag"] | None
MainRoadPreference = Literal["vermijd", "ok"] | None

NonEmptyString = Annotated[
    str,
    Field(min_length=1, description="Niet-lege tekstwaarde."),
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
    kort: NonNegativeWeight


class PreferencePatch(TypedDict, total=False):
    __pydantic_config__ = ConfigDict(extra="forbid")

    kasseien: Preference
    beton: Preference
    steenwegen: MainRoadPreference
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
