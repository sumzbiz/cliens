"""Material catalogue schemas and per-component material selection.

Material codes are untrusted client input. They are always resolved against the
catalogue before scoring, so an unknown or misspelled code produces a typed error
rather than silently scoring against a default.
"""

from __future__ import annotations

from typing import Annotated, Literal, get_args

from pydantic import Field

from app.core import constants
from app.schemas.common import SchemaBase, UnitInterval

BuildingComponent = Literal["foundation", "walls", "roofing"]

MaterialCode = Annotated[
    str,
    Field(
        min_length=1,
        max_length=80,
        # Codes are lowercase snake_case identifiers. Constraining the shape here
        # keeps obviously malformed input away from the database lookup.
        pattern=r"^[a-z][a-z0-9_]*$",
        description="Stable catalogue identifier, e.g. 'fired_clay_brick_masonry'.",
    ),
]


class HazardResistance(SchemaBase):
    """How much of each hazard's load a material resists, as a share in [0, 1]."""

    wind: UnitInterval = Field(description="Share of wind loading resisted.")
    flood: UnitInterval = Field(description="Share of flood loading resisted.")
    heat: UnitInterval = Field(description="Share of heat loading resisted.")


class MaterialResponse(SchemaBase):
    """One catalogue entry.

    ``source_reference`` is required and always returned: an undocumented
    resistance rating is not admissible in a permit context, so the basis travels
    with the number.
    """

    code: MaterialCode
    name: str
    component: BuildingComponent
    resistance: HazardResistance
    relative_cost_index: float = Field(
        gt=0,
        description=(
            "Installed cost relative to the conventional option for this component, "
            "which is 1.0. Ranks recommendations by affordability; not a price estimate."
        ),
    )
    source_reference: str = Field(
        description="Published basis the resistance values were derived from."
    )
    notes: str | None = Field(default=None, description="Practical caveats for this material.")


class MaterialCatalogueResponse(SchemaBase):
    """The full catalogue, grouped for the component pickers in the UI."""

    foundation: tuple[MaterialResponse, ...]
    walls: tuple[MaterialResponse, ...]
    roofing: tuple[MaterialResponse, ...]


class MaterialSelection(SchemaBase):
    """One material chosen per building component.

    Every component must be specified. Defaulting an unspecified component would
    quietly score a building that nobody described.
    """

    foundation: MaterialCode
    walls: MaterialCode
    roofing: MaterialCode

    def as_mapping(self) -> dict[str, str]:
        """Return the selection keyed by component name.

        Used wherever the components must be iterated in the canonical order from
        ``constants.BUILDING_COMPONENTS``.
        """
        return {
            "foundation": self.foundation,
            "walls": self.walls,
            "roofing": self.roofing,
        }


class ResolvedMaterial(SchemaBase):
    """A catalogue entry resolved for a specific component of a specific building."""

    component: BuildingComponent
    code: MaterialCode
    name: str
    resistance: HazardResistance
    relative_cost_index: float


# Guards against the schema and the constants drifting apart: the Literal above is
# hand-written, and this checks it still matches the canonical component list at
# import time rather than failing much later with a confusing validation error.
if set(get_args(BuildingComponent)) != set(constants.BUILDING_COMPONENTS):
    raise RuntimeError(
        "BuildingComponent literal must match constants.BUILDING_COMPONENTS; "
        f"got {get_args(BuildingComponent)} vs {constants.BUILDING_COMPONENTS}"
    )
