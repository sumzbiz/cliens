"""Read access to the material catalogue and its resistance ratings.

Also owns seeding, because the seed file's shape is a persistence concern: it maps
one-to-one onto the table, and nothing above this layer should know that.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.repositories.models import Material

logger = get_logger(__name__)

SEED_DATA_PATH = Path(__file__).parent / "data" / "materials_seed.json"


@dataclass(frozen=True, slots=True)
class MaterialRecord:
    """One catalogue entry as stored."""

    code: str
    name: str
    component: str
    resistance_wind: float
    resistance_flood: float
    resistance_heat: float
    relative_cost_index: float
    source_reference: str
    notes: str | None


def load_seed_materials() -> list[dict[str, Any]]:
    """Read the bundled seed file.

    Raises:
        FileNotFoundError: If the seed file is missing from the deployment.
        ValueError: If it is not valid JSON or lacks a ``materials`` list.
    """
    with SEED_DATA_PATH.open(encoding="utf-8") as handle:
        data = json.load(handle)

    materials = data.get("materials")
    if not isinstance(materials, list) or not materials:
        raise ValueError(f"{SEED_DATA_PATH} contains no materials")
    return materials


class MaterialRepository:
    """Reads the material catalogue."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a session owned by the request."""
        self._session = session

    async def list_all(self) -> list[MaterialRecord]:
        """Return every catalogue entry, ordered for stable presentation.

        Ordered by component then cost so the UI's pickers list the cheapest
        conventional option first without re-sorting client side.
        """
        statement = select(Material).order_by(
            Material.component, Material.relative_cost_index, Material.code
        )
        rows = (await self._session.execute(statement)).scalars().all()
        return [self._to_record(row) for row in rows]

    async def get_by_codes(self, codes: set[str]) -> dict[str, MaterialRecord]:
        """Fetch several entries at once, keyed by code.

        One query rather than one per component: the caller needs all three to
        score, and a missing code must be detectable before any of them is used.

        Args:
            codes: Catalogue codes to resolve. Untrusted client input.

        Returns:
            A mapping of code to record, containing only codes that exist.
        """
        if not codes:
            return {}

        statement = select(Material).where(Material.code.in_(codes))
        rows = (await self._session.execute(statement)).scalars().all()
        return {row.code: self._to_record(row) for row in rows}

    async def count(self) -> int:
        """How many entries the catalogue holds.

        Read by the readiness probe and reported by the seeding command. An empty
        catalogue means the database was migrated but never seeded, which makes
        scoring impossible.
        """
        total = (
            await self._session.execute(select(func.count()).select_from(Material))
        ).scalar_one()
        return int(total)

    async def upsert_many(self, materials: list[dict[str, Any]]) -> int:
        """Insert or update catalogue entries by code.

        Idempotent, so re-running the seed after editing a resistance value updates
        the row rather than failing on the unique constraint. That matters because
        these values are expected to be revised as sources are reviewed.

        Returns:
            How many rows were written.
        """
        if not materials:
            return 0

        statement = postgres_insert(Material).values(materials)
        statement = statement.on_conflict_do_update(
            index_elements=[Material.code],
            set_={
                "name": statement.excluded.name,
                "component": statement.excluded.component,
                "resistance_wind": statement.excluded.resistance_wind,
                "resistance_flood": statement.excluded.resistance_flood,
                "resistance_heat": statement.excluded.resistance_heat,
                "relative_cost_index": statement.excluded.relative_cost_index,
                "source_reference": statement.excluded.source_reference,
                "notes": statement.excluded.notes,
            },
        )
        await self._session.execute(statement)
        await self._session.flush()

        logger.info("materials_seeded", count=len(materials))
        return len(materials)

    @staticmethod
    def _to_record(row: Material) -> MaterialRecord:
        """Map an ORM row onto the repository's return type."""
        return MaterialRecord(
            code=row.code,
            name=row.name,
            component=row.component,
            resistance_wind=row.resistance_wind,
            resistance_flood=row.resistance_flood,
            resistance_heat=row.resistance_heat,
            relative_cost_index=row.relative_cost_index,
            source_reference=row.source_reference,
            notes=row.notes,
        )
