"""Genome schema v0.2.0 — the authoritative, vendor-neutral building specification.

All models forbid undeclared fields. Namespaced extensions live only under `extensions`
and must be declared in `project.extensions_declared`.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "0.2.0"

Basis = Literal["measured", "observed", "extracted", "inferred", "assumed", "unknown"]
Verification = Literal["unverified", "verified", "disputed"]
Point2 = tuple[float, float]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Uncertainty(Strict):
    kind: Literal["pm"] = "pm"  # symmetric ± bound (≈95%), in the value's canonical unit
    value: float = Field(ge=0)


class Selection(Strict):
    by: str
    process: Literal["review", "capture-auto", "cli", "import", "migration", "design"]
    reason: str = ""
    at: Optional[str] = None


class Candidate(Strict):
    value: Optional[float] = None
    observations: list[str] = []
    note: str = ""


class Value(Strict):
    """A provenance-carrying scalar. Canonical units: metres for lengths, rise/run for pitch."""

    value: Optional[float] = None
    basis: Basis
    verification: Verification = "unverified"
    uncertainty: Optional[Uncertainty] = None
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    observations: list[str] = []
    selection: Optional[Selection] = None
    conflicts: list[Candidate] = []
    input: Optional[str] = None

    @field_validator("confidence")
    @classmethod
    def _conf_only_for_inference(cls, v, info):
        if v is not None and info.data.get("basis") not in ("inferred", "observed"):
            raise ValueError("confidence applies only to basis inferred/observed")
        return v


class StoreyRef(Strict):
    ref: Literal["storey"]


class SourceRef(Strict):
    id: str
    sha256: str
    filename: str
    media_type: str
    description: str = ""


class Observation(Strict):
    """A single piece of evidence-derived information. Observations are never deleted."""

    id: str
    kind: Literal["measurement", "observation", "extraction", "statement"]
    source: Optional[str] = None  # SourceRef id
    locator: str = ""  # e.g. "line 14", "frame 00:01:12", "page 2 dim D7"
    text: str = ""  # verbatim excerpt
    subject: Optional[str] = None  # element id (if associated)
    property: Optional[str] = None  # e.g. "thickness"
    value: Optional[float] = None
    uncertainty: Optional[Uncertainty] = None
    recorded_by: str = ""
    recorded_at: Optional[str] = None
    status: Literal["active", "rejected", "superseded"] = "active"
    data: dict = {}  # structured capture row (category, location, colour, condition, photos ...), 0.2


class Tolerances(Strict):
    join: float = 0.002  # endpoint coincidence for wall junctions (m)
    geometry: float = 1e-6
    overlap: float = 0.002  # interpenetration depth (m) below which overlaps are reported, not errors


class SurveyReference(Strict):
    epsg: Optional[int] = None
    easting: Optional[float] = None
    northing: Optional[float] = None
    elevation: Optional[float] = None
    note: str = ""


class CoordinateSystem(Strict):
    handedness: Literal["right"] = "right"
    up: Literal["+z"] = "+z"
    project_north: Literal["+y"] = "+y"
    true_north_deg: Optional[Value] = None  # clockwise angle from project north to true north
    origin_description: str = ""


class Project(Strict):
    id: str
    name: str
    units: Literal["m"] = "m"
    tolerances: Tolerances = Tolerances()
    coordinate_system: CoordinateSystem = CoordinateSystem()
    survey_reference: Optional[SurveyReference] = None
    extensions_declared: list[str] = []
    fictional: bool = False


class Property(Strict):
    id: str
    address: Optional[str] = None
    parcel: Optional[str] = None


class Storey(Strict):
    id: str
    name: str
    elevation: Value
    height: Value  # floor-to-floor


class Building(Strict):
    id: str
    name: str
    storeys: list[Storey]


class Material(Strict):
    id: str
    name: str
    category: Literal["masonry", "concrete", "wood", "gypsum", "glass", "metal", "insulation", "roofing", "other"] = "other"
    color: Optional[str] = None  # hex for viewing only
    layers: list[dict] = []  # reserved: assembly layers (LOD 200+), not interpreted in v0.1


class RoofAttach(Strict):
    attach: str  # roof element id


# ---------------------------------------------------------------- information (LOI), 0.2

class Condition(Strict):
    rating: Literal["good", "fair", "poor", "failed", "unknown"] = "unknown"
    notes: str = ""


class Observed(Strict):
    """When / by whom / from what this element's information was observed (the time axis)."""

    date: Optional[str] = None  # ISO date of the evidence (photo date, site visit)
    by: str = ""
    photos: list[str] = []  # SourceRef ids
    observation: Optional[str] = None  # Observation id holding the structured capture row
    confidence: Optional[float] = Field(default=None, ge=0, le=1)


class Info(Strict):
    category: str = ""
    subtype: str = ""
    material: str = ""
    finish: Optional[str] = None  # -> Genome.finishes
    manufacturer: str = ""
    model: str = ""
    serial: str = ""
    install_year: Optional[Value] = None
    condition: Optional[Condition] = None
    observed: Optional[Observed] = None
    notes: str = ""


class HistoryEvent(Strict):
    date: Optional[str] = None
    event: Literal["installed", "replaced", "repaired", "painted", "observed_damage", "removed", "other"]
    note: str = ""
    source: Optional[str] = None


class Finish(Strict):
    id: str
    name: str
    hex: Optional[str] = None  # approximate display colour unless from a paint chip / product
    product: str = ""
    sheen: str = ""
    basis: Basis = "observed"
    notes: str = ""


class _ElementBase(Strict):
    id: str
    rev: int = 1
    name: str = ""
    aliases: list[str] = []
    material: Optional[str] = None
    notes: str = ""
    info: Optional[Info] = None
    family: Optional[str] = None  # -> Genome.families (shared defaults, like IFC types)
    phase: Literal["existing", "demolish", "new", "temporary"] = "existing"
    history: list[HistoryEvent] = []
    properties: dict[str, Value] = {}  # extra numeric attributes with provenance (e.g. exposure)


class Wall(_ElementBase):
    type: Literal["wall"]
    storey: str
    start: Point2
    end: Point2
    thickness: Value
    height: Union[Value, StoreyRef]
    base_offset: Optional[Value] = None
    alignment: Literal["center", "left", "right"] = "center"
    exterior: bool = False
    top: Optional[RoofAttach] = None
    shape: Literal["straight", "arc"] = "straight"  # arc is declared but not yet supported


class Filling(Strict):
    type: Literal["door", "window", "none"]
    operation: str = ""
    material: Optional[str] = None


class OpeningUnit(Strict):
    """What fills the opening, as information (geometry stays a proxy panel)."""

    type: str = ""  # double-hung, casement, fixed, picture, panel door, French door, screen door, overhead ...
    lites: str = ""  # e.g. "2/2", "9-lite over 3-panel"
    frame_material: str = ""
    sash_finish: Optional[str] = None  # -> finishes
    storm: Optional[bool] = None
    screen: Optional[bool] = None
    hardware: str = ""


class Opening(_ElementBase):
    type: Literal["opening"]
    host: str
    kind: Literal["door", "window", "void"]
    offset: Value
    width: Value
    height: Value
    sill: Value
    filling: Optional[Filling] = None
    shape: Literal["rectangle", "arch"] = "rectangle"
    unit: Optional[OpeningUnit] = None


class Slab(_ElementBase):
    type: Literal["slab"]
    storey: str
    kind: Literal["floor", "base", "ceiling"]
    boundary: list[Point2]
    thickness: Value
    top_offset: Optional[Value] = None  # top surface relative to storey elevation; default 0


class Roof(_ElementBase):
    type: Literal["roof"]
    storey: str
    form: Literal["gable", "hip", "shed", "planes"]
    footprint: list[Point2]  # wall-plate outline (outer faces), counter-clockwise
    edge_roles: list[Literal["eave", "flush-eave", "rake", "abut"]]  # per footprint edge i: footprint[i]->footprint[i+1]
    trim_by: list[str] = []  # roofs this roof dies into: the part below their top surface is removed (valleys)
    pitch: Value  # rise/run
    plate_height: Value  # relative to storey elevation
    overhang: Value  # eave overhang, horizontal
    rake_overhang: Value
    thickness: Value  # perpendicular to roof plane


class Space(_ElementBase):
    type: Literal["space"]
    storey: str
    boundary: list[Point2]
    bounded_by: list[str] = []
    height: Value
    usage: str = ""
    surfaces: dict[Literal["walls", "ceiling", "floor", "base", "crown", "wainscot", "trim"], Info] = {}


# ---------------------------------------------------------------- components (G3/G4), 0.2

Side = Literal["exterior", "interior", "left", "right"]


class OnWall(Strict):
    """Box on a wall face. u = along the wall from its start to the component centre; z = bottom above wall base."""

    on: Literal["wall"]
    wall: str
    side: Side = "exterior"
    u: Value
    z: Value


class OnOpening(Strict):
    """Relative to an opening: casing (surround/head/sill), shutters (start/end/both = toward wall start/end)."""

    on: Literal["opening"]
    opening: str
    position: Literal["surround", "head", "sill", "start", "end", "both"]
    side: Side = "exterior"
    gap: Optional[Value] = None  # clear distance from the opening edge (shutters sit outside the casing)


class OnCorner(Strict):
    """L-shaped corner board where the exterior faces of two walls meet."""

    on: Literal["corner"]
    walls: tuple[str, str]
    sides: tuple[Side, Side] = ("exterior", "exterior")  # which face of each wall carries the board


class OnRoofEdge(Strict):
    """Along roof footprint edges (indices into footprint): fascia, rake boards, soffits, gutters."""

    on: Literal["roof_edge"]
    roof: str
    edges: list[int]
    gap: Optional[Value] = None  # offset outward from the overhang edge (gutter outside fascia)
    within: Optional[list[Point2]] = None  # plan polygon: keep only the run inside it (e.g. a gutter on part of an eave)


class AtPoint(Strict):
    """Free placement: plan point (box centre), z = bottom relative to storey elevation."""

    on: Literal["point"]
    at: Point2
    z: Value
    rotation: float = 0.0  # degrees, about +z; box w along rotated x


class InSpace(Strict):
    """Information-only placement in a room (no geometry until located)."""

    on: Literal["space"]
    space: str
    wall: Optional[str] = None
    location: str = ""


Placement = Annotated[Union[OnWall, OnOpening, OnCorner, OnRoofEdge, AtPoint, InSpace], Field(discriminator="on")]


class Size(Strict):
    w: Optional[Value] = None  # along the host (wall/edge) or x
    h: Optional[Value] = None  # vertical
    d: Optional[Value] = None  # projection from the host face / y


ComponentKind = Literal[
    "cladding", "trim", "shutter", "fascia", "soffit", "gutter", "downspout", "chimney", "vent",
    "fixture", "equipment", "post", "screen", "railing", "stair", "furnishing", "other"]


class Component(_ElementBase):
    type: Literal["component"]
    kind: ComponentKind
    storey: str
    placement: Placement
    size: Size = Size()
    hosts: list[str] = []  # cladding: covered walls
    geometry: Literal["box", "none", "prism"] = "box"  # "none" = information-only; "prism" = outline × size.h
    outline: Optional[list[Point2]] = None  # prism geometry: plan polygon (absolute coordinates), base at placement.z


class Family(Strict):
    id: str
    name: str
    kind: ComponentKind
    info: Info = Info()
    size: Size = Size()


class Capture(Strict):
    """Capture epochs: when closed, gathered evidence is accepted for modelling; new evidence opens a new epoch."""

    epoch: int = 1
    closed: bool = False
    closed_at: Optional[str] = None
    closed_by: str = ""
    note: str = ""


Element = Annotated[Union[Wall, Opening, Slab, Roof, Space, Component], Field(discriminator="type")]


class ChangeSummary(Strict):
    id: str
    number: int
    author: str
    at: str
    reason: str
    source: str
    ops: int


class Revision(Strict):
    number: int = 0
    history: list[ChangeSummary] = []


class Constraint(Strict):
    id: str
    kind: Literal["equal", "parallel", "perpendicular", "collinear", "fixed"]
    refs: list[str]  # JSON pointers into this document
    note: str = ""


class Genome(Strict):
    schema_version: str = SCHEMA_VERSION
    project: Project
    property: Property
    buildings: list[Building]
    materials: dict[str, Material] = {}
    elements: dict[str, Element] = {}
    observations: dict[str, Observation] = {}
    sources: dict[str, SourceRef] = {}
    constraints: list[Constraint] = []
    finishes: dict[str, Finish] = {}
    families: dict[str, Family] = {}
    capture: Capture = Capture()
    revision: Revision = Revision()
    extensions: dict[str, dict] = {}

    def storey(self, sid: str) -> Storey:
        for b in self.buildings:
            for s in b.storeys:
                if s.id == sid:
                    return s
        raise KeyError(sid)

    def storeys(self) -> list[Storey]:
        return [s for b in self.buildings for s in b.storeys]


def json_schema() -> dict:
    s = Genome.model_json_schema()
    s["$id"] = f"https://rebuilt.homes/schemas/genome/{SCHEMA_VERSION}"
    s["title"] = "Rebuilt Genome"
    return s
