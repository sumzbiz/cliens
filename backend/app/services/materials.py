"""Material catalogue queries and resolution of per-component selections.

Resolution is the security-relevant part. Material codes arrive from the client and
are always checked against the catalogue before they reach the score engine, so an
unknown code fails loudly instead of scoring against a default that nobody chose.
"""

from __future__ import annotations

from app.core import constants
from app.core.exceptions import UnknownMaterialError
from app.core.logging import get_logger
from app.repositories.materials import MaterialRecord, MaterialRepository
from app.schemas.materials import (
    BuildingComponent,
    HazardResistance,
    MaterialCatalogueResponse,
    MaterialResponse,
    MaterialSelection,
    ResolvedMaterial,
)

logger = get_logger(__name__)


class MaterialService:
    """Business logic for the material catalogue."""

    def __init__(self, repository: MaterialRepository) -> None:
        """Bind the service to its repository."""
        self._repository = repository

    async def get_catalogue(self) -> MaterialCatalogueResponse:
        """Return the catalogue grouped by building component."""
        records = await self._repository.list_all()
        grouped: dict[str, list[MaterialResponse]] = {
            component: [] for component in constants.BUILDING_COMPONENTS
        }
        for record in records:
            grouped[record.component].append(self._to_response(record))

        return MaterialCatalogueResponse(
            foundation=tuple(grouped["foundation"]),
            walls=tuple(grouped["walls"]),
            roofing=tuple(grouped["roofing"]),
        )

    async def catalogue_size(self) -> int:
        """How many materials the catalogue holds.

        Consumed by the readiness probe: a migrated-but-unseeded database cannot
        score anything, so reporting it as ready would be misleading.
        """
        return await self._repository.count()

    async def resolve_selection(self, selection: MaterialSelection) -> tuple[ResolvedMaterial, ...]:
        """Resolve a client's per-component choices against the catalogue.

        Args:
            selection: One material code per component, as submitted.

        Returns:
            The resolved materials, in ``constants.BUILDING_COMPONENTS`` order so
            downstream scoring is deterministic regardless of request key order.

        Raises:
            UnknownMaterialError: If any code is absent from the catalogue, or is
                assigned to a different component than the one it was chosen for
                (for example a roofing material picked as a wall).
        """
        chosen = selection.as_mapping()
        found = await self._repository.get_by_codes(set(chosen.values()))

        missing = sorted({code for code in chosen.values() if code not in found})
        if missing:
            logger.info("material_codes_unknown", codes=missing)
            raise UnknownMaterialError(
                "One or more selected materials are not in the catalogue.",
                details={"unknown_codes": missing},
            )

        mismatched = [
            {"component": component, "code": code, "belongs_to": found[code].component}
            for component, code in chosen.items()
            if found[code].component != component
        ]
        if mismatched:
            # Structurally valid but semantically wrong: scoring a roof material as
            # a wall would silently produce a meaningless number.
            logger.info("material_component_mismatch", mismatches=mismatched)
            raise UnknownMaterialError(
                "A selected material is not valid for the component it was chosen for.",
                details={"mismatches": mismatched},
            )

        return tuple(
            self._to_resolved(component, found[chosen[component]])
            for component in constants.BUILDING_COMPONENTS
        )

    async def resistance_table(self, selection: MaterialSelection) -> dict[str, dict[str, float]]:
        """Build the resistance table the score engine consumes.

        Shaped as ``{component: {hazard: resistance}}``, which is exactly what
        ``calculations.resistance_weighted_stress`` expects — so the engine never
        needs to know the catalogue exists.

        Raises:
            UnknownMaterialError: If the selection cannot be resolved.
        """
        resolved = await self.resolve_selection(selection)
        return {
            material.component: {
                "wind": material.resistance.wind,
                "flood": material.resistance.flood,
                "heat": material.resistance.heat,
            }
            for material in resolved
        }

    # ------------------------------------------------------------------
    # Mapping
    # ------------------------------------------------------------------
    @staticmethod
    def _to_response(record: MaterialRecord) -> MaterialResponse:
        """Map a stored record onto the API response shape."""
        return MaterialResponse(
            code=record.code,
            name=record.name,
            # Validated on the way in by the table's CHECK constraint.
            component=record.component,
            resistance=HazardResistance(
                wind=record.resistance_wind,
                flood=record.resistance_flood,
                heat=record.resistance_heat,
            ),
            relative_cost_index=record.relative_cost_index,
            source_reference=record.source_reference,
            notes=record.notes,
        )

    @staticmethod
    def _to_resolved(component: str, record: MaterialRecord) -> ResolvedMaterial:
        """Map a stored record onto a resolved per-component selection."""
        resolved_component: BuildingComponent = component  # type: ignore[assignment]
        return ResolvedMaterial(
            component=resolved_component,
            code=record.code,
            name=record.name,
            resistance=HazardResistance(
                wind=record.resistance_wind,
                flood=record.resistance_flood,
                heat=record.resistance_heat,
            ),
            relative_cost_index=record.relative_cost_index,
        )
