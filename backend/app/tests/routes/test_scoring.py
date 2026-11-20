"""Integration tests for the scoring and report endpoints.

These run against the real bundled climate profiles and the real trained model —
nothing here is stubbed — so a broken profile file or a mismatched artifact fails
the suite rather than only failing in production.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration

WEAK_SPEC: dict[str, Any] = {
    "concrete": {
        "grade": "M20",
        "cement_content_kg_m3": 290,
        "water_cement_ratio": 0.58,
        "cement_type": "OPC",
        "admixtures": [],
    },
    "walling_material_id": "burnt_clay_brick",
    "nominal_cover_mm": 25,
    "element_situation": "exposed",
}

STRONG_SPEC: dict[str, Any] = {
    "concrete": {
        "grade": "M40",
        "cement_content_kg_m3": 380,
        "water_cement_ratio": 0.38,
        "cement_type": "PSC",
        "admixtures": ["corrosion inhibitor"],
    },
    "walling_material_id": "fly_ash_brick",
    "nominal_cover_mm": 50,
    "element_situation": "exposed",
}


class TestDistricts:
    """The district list drives the form, so it must reflect the bundled data."""

    async def test_lists_the_priority_districts(self, client: AsyncClient) -> None:
        response = await client.get("/api/score/districts")
        assert response.status_code == 200

        districts = response.json()["districts"]
        for expected in ("Coimbatore", "Salem", "Erode"):
            assert expected in districts

    async def test_excludes_districts_outside_the_grid(self, client: AsyncClient) -> None:
        """Chennai sits east of the bundled GRIB, so it cannot be scored."""
        districts = (await client.get("/api/score/districts")).json()["districts"]
        assert "Chennai" not in districts

    async def test_reports_the_observation_period(self, client: AsyncClient) -> None:
        """Users need to know the score describes measured history, not a forecast."""
        body = (await client.get("/api/score/districts")).json()

        assert body["observation_start"].startswith("2016")
        assert body["source"].endswith(".grib")


class TestResolvePin:
    """A pin dropped on the globe must resolve honestly or not at all.

    This is the highest-risk path in the API. Nearest-node lookup always returns
    *something*, so without a distance limit a pin anywhere on Earth would come back
    with a confident Indian district and a score describing the wrong continent.
    """

    async def test_resolves_a_pin_inside_the_observed_region(self, client: AsyncClient) -> None:
        # Slightly off the Coimbatore grid node, as a real click would be.
        response = await client.post(
            "/api/score/resolve", json={"latitude": 11.02, "longitude": 76.96}
        )
        assert response.status_code == 200

        body = response.json()
        assert body["district"] == "Coimbatore"
        assert body["distance_km"] < 30.0

    async def test_reports_the_distance_to_the_node_it_used(self, client: AsyncClient) -> None:
        """The reading comes from the node, not from where the user clicked."""
        body = (
            await client.post("/api/score/resolve", json={"latitude": 11.0, "longitude": 77.0})
        ).json()

        # Dead on the node, so the honest answer is essentially zero.
        assert body["distance_km"] == pytest.approx(0.0, abs=0.2)
        assert body["grid_latitude"] == pytest.approx(11.0)
        assert body["grid_longitude"] == pytest.approx(77.0)

    @pytest.mark.parametrize(
        ("latitude", "longitude", "where"),
        [
            (-23.5, -46.6, "Sao Paulo"),
            (51.5, -0.13, "London"),
            (13.08, 80.27, "Chennai, just east of the grid"),
            (0.0, 0.0, "the Gulf of Guinea"),
        ],
    )
    async def test_refuses_a_pin_outside_the_observed_region(
        self, client: AsyncClient, latitude: float, longitude: float, where: str
    ) -> None:
        response = await client.post(
            "/api/score/resolve", json={"latitude": latitude, "longitude": longitude}
        )

        assert response.status_code == 404, f"{where} should not be scoreable"
        assert response.json()["error"]["code"] == "LOCATION_NOT_COVERED"

    async def test_rejects_coordinates_outside_the_planet(self, client: AsyncClient) -> None:
        """Validation happens at the boundary, before any lookup runs."""
        response = await client.post(
            "/api/score/resolve", json={"latitude": 200.0, "longitude": 0.0}
        )
        assert response.status_code == 422

    async def test_publishes_the_coverage_the_globe_should_draw(self, client: AsyncClient) -> None:
        """The supported region is discoverable, not something you find by failing."""
        body = (await client.get("/api/score/districts")).json()
        coverage = body["coverage"]

        assert coverage["south"] < coverage["north"]
        assert coverage["west"] < coverage["east"]
        # Every marker must fall inside the box the interface will draw.
        for location in body["locations"]:
            assert coverage["south"] <= location["grid_latitude"] <= coverage["north"]
            assert coverage["west"] <= location["grid_longitude"] <= coverage["east"]


class TestEvaluateMode:
    """Supplying materials scores them and still returns the recommendation."""

    async def test_scores_a_weak_specification_poorly(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/score", json={"district": "Coimbatore", "materials": WEAK_SPEC}
        )
        assert response.status_code == 200

        body = response.json()
        assert body["proposed"]["score"] < 50
        assert body["proposed"]["compliant"] is False

    async def test_scores_a_strong_specification_well(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/score", json={"district": "Coimbatore", "materials": STRONG_SPEC}
        )

        body = response.json()
        assert body["proposed"]["score"] > body["recommended"]["score"] - 20
        assert body["proposed"]["compliant"] is True

    async def test_always_returns_both_sides(self, client: AsyncClient) -> None:
        """The before/after must exist whichever mode was used."""
        body = (
            await client.post("/api/score", json={"district": "Salem", "materials": WEAK_SPEC})
        ).json()

        assert body["proposed"]["score"] >= 0
        assert body["recommended"]["score"] >= 0
        assert body["improvement"] == pytest.approx(
            body["recommended"]["score"] - body["proposed"]["score"], abs=0.11
        )

    async def test_explains_the_exposure_class(self, client: AsyncClient) -> None:
        body = (
            await client.post("/api/score", json={"district": "Coimbatore", "materials": WEAK_SPEC})
        ).json()

        assert body["exposure_class"]
        assert body["exposure_reasons"]

    async def test_every_finding_cites_a_standard(self, client: AsyncClient) -> None:
        body = (
            await client.post("/api/score", json={"district": "Erode", "materials": WEAK_SPEC})
        ).json()

        for finding in body["proposed"]["findings"]:
            assert finding["standard"]

    async def test_reports_the_data_source(self, client: AsyncClient) -> None:
        """Provenance travels with the score; it is not a footnote in the UI."""
        body = (
            await client.post("/api/score", json={"district": "Salem", "materials": WEAK_SPEC})
        ).json()

        assert body["data_source"]["source"].endswith(".grib")


class TestRecommendMode:
    """Omitting materials returns advice against a conventional baseline."""

    async def test_scores_without_a_specification(self, client: AsyncClient) -> None:
        response = await client.post("/api/score", json={"district": "Salem"})
        assert response.status_code == 200

        body = response.json()
        assert body["recommended"]["score"] > body["proposed"]["score"]

    async def test_recommendation_is_compliant(self, client: AsyncClient) -> None:
        """Derived from the exposure minimums, so it cannot fail its own check."""
        body = (await client.post("/api/score", json={"district": "Coimbatore"})).json()

        assert body["recommended"]["compliant"] is True


class TestDeterminism:
    """The same request must always produce the same score."""

    async def test_repeat_requests_match(self, client: AsyncClient) -> None:
        payload = {"district": "Coimbatore", "materials": WEAK_SPEC}
        first = (await client.post("/api/score", json=payload)).json()
        second = (await client.post("/api/score", json=payload)).json()

        assert first["proposed"]["score"] == second["proposed"]["score"]
        assert first["recommended"]["score"] == second["recommended"]["score"]


class TestOneSituation:
    """The user's specification and the advice are judged in the same situation."""

    async def test_an_omitted_nested_situation_follows_the_top_level(
        self, client: AsyncClient
    ) -> None:
        """It used to default to "exposed" while the advice used "buried"."""
        materials = {k: v for k, v in STRONG_SPEC.items() if k != "element_situation"}
        response = await client.post(
            "/api/score",
            json={"district": "Madurai", "materials": materials, "element_situation": "buried"},
        )

        body = response.json()

        def required_grade(side: str) -> float:
            finding = next(
                f for f in body[side]["findings"] if f["parameter"] == "concrete_grade_mpa"
            )
            grade: float = finding["required"]
            return grade

        assert response.status_code == 200
        assert required_grade("proposed") == required_grade("recommended")

    @pytest.mark.parametrize("path", ["/api/score", "/api/reports"])
    async def test_a_contradicting_nested_situation_is_rejected(
        self, client: AsyncClient, path: str
    ) -> None:
        materials = {**STRONG_SPEC, "element_situation": "exposed"}
        response = await client.post(
            path,
            json={"district": "Madurai", "materials": materials, "element_situation": "buried"},
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


class TestAdviceNeverWorse:
    """An over-specified build is told so, not "improved" downwards."""

    async def test_over_specification_returns_the_same_specification(
        self, client: AsyncClient
    ) -> None:
        over = {
            **STRONG_SPEC,
            "concrete": {**STRONG_SPEC["concrete"], "grade": "M45", "water_cement_ratio": 0.35},
            "nominal_cover_mm": 75,
            # The best-scoring walling for Salem's humidity, so nothing is left to improve.
            "walling_material_id": "aac_block",
        }
        response = await client.post("/api/score", json={"district": "Salem", "materials": over})

        body = response.json()
        assert body["improvement"] == 0
        for field in ("concrete", "nominal_cover_mm", "walling_material_id"):
            assert body["recommended"][field] == body["proposed"][field]


class TestValidation:
    """District and material inputs are untrusted."""

    async def test_unknown_district_is_rejected_with_the_alternatives(
        self, client: AsyncClient
    ) -> None:
        response = await client.post("/api/score", json={"district": "Atlantis"})

        # A client error, not an outage: a typo must not look like a server fault.
        assert response.status_code == 404
        error = response.json()["error"]
        assert error["code"] == "LOCATION_NOT_COVERED"
        assert "Coimbatore" in error["details"]["available_districts"]

    async def test_malformed_grade_is_rejected(self, client: AsyncClient) -> None:
        bad = {**WEAK_SPEC, "concrete": {**WEAK_SPEC["concrete"], "grade": "DROP TABLE"}}
        response = await client.post("/api/score", json={"district": "Salem", "materials": bad})

        assert response.status_code == 422

    async def test_out_of_range_water_cement_ratio_is_rejected(self, client: AsyncClient) -> None:
        bad = {**WEAK_SPEC, "concrete": {**WEAK_SPEC["concrete"], "water_cement_ratio": 9.0}}
        response = await client.post("/api/score", json={"district": "Salem", "materials": bad})

        assert response.status_code == 422

    async def test_unknown_fields_are_rejected(self, client: AsyncClient) -> None:
        response = await client.post("/api/score", json={"district": "Salem", "budget": 100000})

        assert response.status_code == 422

    @pytest.mark.parametrize("grade", ["M10", "M50", "M999"])
    async def test_grade_outside_the_scored_range_is_rejected(
        self, client: AsyncClient, grade: str
    ) -> None:
        """Well-formed but unsupported: M999 used to score higher than a real M30."""
        bad = {**WEAK_SPEC, "concrete": {**WEAK_SPEC["concrete"], "grade": grade}}
        response = await client.post("/api/score", json={"district": "Salem", "materials": bad})

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    async def test_grade_spelling_is_normalised(self, client: AsyncClient) -> None:
        loose = {**WEAK_SPEC, "concrete": {**WEAK_SPEC["concrete"], "grade": "m 20"}}
        response = await client.post("/api/score", json={"district": "Salem", "materials": loose})

        assert response.status_code == 200
        assert response.json()["proposed"]["concrete"]["grade"] == "M20"

    async def test_unknown_cement_type_is_rejected(self, client: AsyncClient) -> None:
        bad = {**WEAK_SPEC, "concrete": {**WEAK_SPEC["concrete"], "cement_type": "XYZ"}}
        response = await client.post("/api/score", json={"district": "Salem", "materials": bad})

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.parametrize("path", ["/api/score", "/api/reports"])
    async def test_unknown_walling_material_is_rejected(
        self, client: AsyncClient, path: str
    ) -> None:
        """An invented material used to skip the walling check and score as the best."""
        bad = {**WEAK_SPEC, "walling_material_id": "unobtainium"}
        response = await client.post(path, json={"district": "Salem", "materials": bad})

        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "UNKNOWN_MATERIAL"
        assert error["details"]["unknown_codes"] == ["unobtainium"]
        assert "fly_ash_brick" in error["details"]["known_codes"]

    async def test_unknown_walling_material_is_rejected_for_a_drawn_area(
        self, client: AsyncClient
    ) -> None:
        bad = {**WEAK_SPEC, "walling_material_id": "unobtainium"}
        area = {"south": 11.0, "north": 11.2, "west": 76.9, "east": 77.1}
        response = await client.post("/api/score/area", json={"area": area, "materials": bad})

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "UNKNOWN_MATERIAL"


class TestCover:
    """Cover is required, checked per member, and drives the service life."""

    async def test_cover_is_required(self, client: AsyncClient) -> None:
        missing = {k: v for k, v in STRONG_SPEC.items() if k != "nominal_cover_mm"}
        response = await client.post("/api/score", json={"district": "Salem", "materials": missing})

        assert response.status_code == 422

    @pytest.mark.parametrize("cover", [0, -10, 500])
    async def test_implausible_cover_is_rejected(self, client: AsyncClient, cover: float) -> None:
        bad = {**STRONG_SPEC, "nominal_cover_mm": cover}
        response = await client.post("/api/score", json={"district": "Salem", "materials": bad})

        assert response.status_code == 422

    async def test_member_is_echoed_and_sets_the_requirement(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/score",
            json={
                "district": "Salem",
                "materials": {**STRONG_SPEC, "nominal_cover_mm": 45, "element_situation": "buried"},
                "element_situation": "buried",
                "member": "footing",
            },
        )

        body = response.json()
        assert body["proposed"]["member"] == "footing"
        cover = next(
            f for f in body["proposed"]["findings"] if f["parameter"] == "nominal_cover_mm"
        )
        assert cover["required"] == 50.0
        assert cover["compliant"] is False
        assert body["recommended"]["nominal_cover_mm"] == 50.0

    async def test_thinner_cover_shortens_the_service_life(self, client: AsyncClient) -> None:
        async def life(cover: float) -> float:
            spec = {**STRONG_SPEC, "nominal_cover_mm": cover}
            response = await client.post(
                "/api/score", json={"district": "Salem", "materials": spec}
            )
            years: float = response.json()["proposed"]["service_life"]["years"]
            return years

        assert await life(25) < await life(45) < await life(60)


class TestReportDownload:
    """The report must be a real file, not an on-screen view."""

    async def test_returns_a_pdf(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/reports", json={"district": "Coimbatore", "materials": WEAK_SPEC}
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        # A real PDF starts with this magic number.
        assert response.content.startswith(b"%PDF-")

    async def test_is_sent_as_a_download(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/reports", json={"district": "Salem", "materials": WEAK_SPEC}
        )

        disposition = response.headers["content-disposition"]
        assert disposition.startswith("attachment")
        assert "salem" in disposition

    async def test_works_in_recommend_only_mode(self, client: AsyncClient) -> None:
        response = await client.post("/api/reports", json={"district": "Erode"})

        assert response.status_code == 200
        assert response.content.startswith(b"%PDF-")

    async def test_has_meaningful_content(self, client: AsyncClient) -> None:
        """A PDF of a few hundred bytes would be an empty page."""
        response = await client.post(
            "/api/reports", json={"district": "Coimbatore", "materials": WEAK_SPEC}
        )

        assert len(response.content) > 3000

    async def test_unknown_district_fails_before_rendering(self, client: AsyncClient) -> None:
        response = await client.post("/api/reports", json={"district": "Atlantis"})

        assert response.status_code == 404
