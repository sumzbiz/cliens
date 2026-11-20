"""Integration tests for the material catalogue, against the real test database.

Material codes are untrusted client input, so the resolution rules get the most
attention here: an unknown code, or a code used for the wrong component, must fail
loudly rather than scoring against something nobody chose.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import constants
from app.repositories.materials import MaterialRepository, load_seed_materials

pytestmark = pytest.mark.integration

BASELINE_SELECTION = {
    "foundation": "shallow_strip_footing_masonry",
    "walls": "fired_clay_brick_masonry",
    "roofing": "gi_sheet_roof",
}


class TestSeedData:
    """The shipped catalogue has to satisfy the invariants scoring assumes."""

    def test_every_entry_has_a_source_reference(self) -> None:
        """An undocumented rating is not admissible in a permit context."""
        for material in load_seed_materials():
            assert material["source_reference"].strip(), material["code"]

    def test_resistances_are_within_the_unit_interval(self) -> None:
        for material in load_seed_materials():
            for hazard in constants.HAZARDS:
                value = material[f"resistance_{hazard}"]
                assert 0.0 <= value <= 1.0, f"{material['code']}/{hazard}"

    def test_every_component_has_at_least_two_options(self) -> None:
        """With one option per component there is nothing to recommend."""
        counts = {component: 0 for component in constants.BUILDING_COMPONENTS}
        for material in load_seed_materials():
            counts[material["component"]] += 1
        assert all(count >= 2 for count in counts.values()), counts

    def test_codes_are_unique(self) -> None:
        codes = [material["code"] for material in load_seed_materials()]
        assert len(codes) == len(set(codes))

    def test_components_are_all_known(self) -> None:
        for material in load_seed_materials():
            assert material["component"] in constants.BUILDING_COMPONENTS

    def test_cost_indices_are_positive(self) -> None:
        for material in load_seed_materials():
            assert material["relative_cost_index"] > 0, material["code"]

    def test_a_stronger_roof_option_exists_than_sheet_roofing(self) -> None:
        """The 'apply suggested materials' feature needs headroom to improve into."""
        roofing = [m for m in load_seed_materials() if m["component"] == "roofing"]
        sheet = next(m for m in roofing if m["code"] == "gi_sheet_roof")
        assert any(m["resistance_wind"] > sheet["resistance_wind"] for m in roofing)


class TestCatalogueEndpoint:
    """What the UI's component pickers consume."""

    async def test_returns_materials_grouped_by_component(
        self, client: AsyncClient, seeded_catalogue: None
    ) -> None:
        response = await client.get("/api/materials")
        assert response.status_code == 200

        body = response.json()
        assert set(body) == set(constants.BUILDING_COMPONENTS)
        assert all(body[component] for component in constants.BUILDING_COMPONENTS)

    async def test_each_entry_carries_its_source(
        self, client: AsyncClient, seeded_catalogue: None
    ) -> None:
        response = await client.get("/api/materials")

        for entries in response.json().values():
            for entry in entries:
                assert entry["source_reference"]

    async def test_each_entry_exposes_all_three_resistances(
        self, client: AsyncClient, seeded_catalogue: None
    ) -> None:
        response = await client.get("/api/materials")

        walls = response.json()["walls"]
        assert set(walls[0]["resistance"]) == set(constants.HAZARDS)

    async def test_entries_are_ordered_cheapest_first(
        self, client: AsyncClient, seeded_catalogue: None
    ) -> None:
        """So the picker lists the conventional affordable option first."""
        roofing = (await client.get("/api/materials")).json()["roofing"]
        costs = [entry["relative_cost_index"] for entry in roofing]
        assert costs == sorted(costs)

    async def test_an_unseeded_catalogue_returns_empty_groups(self, client: AsyncClient) -> None:
        """A migrated-but-unseeded database is reported honestly, not as an error."""
        response = await client.get("/api/materials")

        assert response.status_code == 200
        assert response.json() == {"foundation": [], "walls": [], "roofing": []}


class TestSelectionResolution:
    """Untrusted codes are always checked before they can reach the score engine."""

    async def test_resolves_a_valid_selection(
        self, client: AsyncClient, seeded_catalogue: None
    ) -> None:
        response = await client.post("/api/materials/resolve", json=BASELINE_SELECTION)
        assert response.status_code == 200

        resolved = response.json()
        assert [entry["component"] for entry in resolved] == list(constants.BUILDING_COMPONENTS)

    async def test_returns_components_in_canonical_order(
        self, client: AsyncClient, seeded_catalogue: None
    ) -> None:
        """Order must not depend on JSON key order, or scoring stops being stable."""
        shuffled = {
            "roofing": BASELINE_SELECTION["roofing"],
            "foundation": BASELINE_SELECTION["foundation"],
            "walls": BASELINE_SELECTION["walls"],
        }
        response = await client.post("/api/materials/resolve", json=shuffled)

        assert [entry["component"] for entry in response.json()] == list(
            constants.BUILDING_COMPONENTS
        )

    async def test_rejects_an_unknown_code(
        self, client: AsyncClient, seeded_catalogue: None
    ) -> None:
        response = await client.post(
            "/api/materials/resolve",
            json={**BASELINE_SELECTION, "walls": "unobtainium_panel"},
        )

        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "UNKNOWN_MATERIAL"
        assert error["details"]["unknown_codes"] == ["unobtainium_panel"]

    async def test_rejects_a_material_used_for_the_wrong_component(
        self, client: AsyncClient, seeded_catalogue: None
    ) -> None:
        """Structurally valid, semantically meaningless — a roof used as a wall."""
        response = await client.post(
            "/api/materials/resolve",
            json={**BASELINE_SELECTION, "walls": "rcc_flat_slab"},
        )

        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "UNKNOWN_MATERIAL"
        assert error["details"]["mismatches"][0]["component"] == "walls"
        assert error["details"]["mismatches"][0]["belongs_to"] == "roofing"

    async def test_rejects_a_missing_component(
        self, client: AsyncClient, seeded_catalogue: None
    ) -> None:
        """Defaulting a component would score a building nobody described."""
        response = await client.post(
            "/api/materials/resolve",
            json={"foundation": BASELINE_SELECTION["foundation"]},
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    async def test_rejects_a_malformed_code(
        self, client: AsyncClient, seeded_catalogue: None
    ) -> None:
        """Obvious junk is stopped by the schema before it reaches the database."""
        response = await client.post(
            "/api/materials/resolve",
            json={**BASELINE_SELECTION, "walls": "DROP TABLE materials;--"},
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    async def test_rejects_unknown_fields(
        self, client: AsyncClient, seeded_catalogue: None
    ) -> None:
        response = await client.post(
            "/api/materials/resolve",
            json={**BASELINE_SELECTION, "chimney": "brick"},
        )

        assert response.status_code == 422


class TestSeedIdempotency:
    """Resistance values are expected to be revised, so re-seeding must work."""

    async def test_reseeding_updates_rather_than_duplicating(self, session: AsyncSession) -> None:
        repository = MaterialRepository(session)
        materials = load_seed_materials()

        await repository.upsert_many(materials)
        first_count = await repository.count()
        await repository.upsert_many(materials)
        second_count = await repository.count()

        assert first_count == second_count == len(materials)

    async def test_reseeding_applies_a_revised_value(self, session: AsyncSession) -> None:
        repository = MaterialRepository(session)
        materials = load_seed_materials()
        await repository.upsert_many(materials)

        revised = [dict(material) for material in materials]
        revised[0]["resistance_wind"] = 0.99
        await repository.upsert_many(revised)

        found = await repository.get_by_codes({revised[0]["code"]})
        assert found[revised[0]["code"]].resistance_wind == pytest.approx(0.99)
