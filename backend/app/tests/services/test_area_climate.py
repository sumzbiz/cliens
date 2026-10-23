"""Tests for area climate derivation.

This module is the only place in the application that produces a climate value not
read directly from the GRIB record, so its boundaries are tested hard: what counts
as measured, what counts as interpolated, and where interpolation must stop and
refuse instead.
"""

from __future__ import annotations

import pytest

from app.core import constants
from app.repositories.district_profiles import (
    ClimateProfileUnavailableError,
    load_climate_profiles,
)
from app.services.area_climate import AreaBounds, AreaClimateService


@pytest.fixture(scope="module")
def service() -> AreaClimateService:
    """Bound to the real bundled profiles, not a stub."""
    return AreaClimateService(load_climate_profiles())


class TestEnclosedNodes:
    """An area containing measured nodes must use them and nothing else."""

    def test_uses_only_the_nodes_inside_the_area(self, service: AreaClimateService) -> None:
        # A box drawn tightly around the Coimbatore node at 11.0, 77.0.
        result = service.for_area(AreaBounds(south=10.9, north=11.1, west=76.9, east=77.1))

        assert result.enclosed_node_count >= 1
        assert result.interpolated is False

    def test_a_single_enclosed_node_keeps_its_own_name(self, service: AreaClimateService) -> None:
        """One cell means the reading is that cell's, so it may keep its label."""
        result = service.for_area(AreaBounds(south=10.9, north=11.1, west=76.9, east=77.1))

        if result.enclosed_node_count == 1:
            assert result.profile.district == result.source_districts[0]

    def test_a_multi_cell_area_does_not_borrow_a_district_name(
        self, service: AreaClimateService
    ) -> None:
        """A blend of cells must not pass as any one district's measured reading."""
        result = service.for_area(AreaBounds(south=10.0, north=12.0, west=76.8, east=78.5))

        assert result.enclosed_node_count > 1
        assert result.profile.district not in result.source_districts
        assert "Selected area" in result.profile.district

    def test_maxima_are_worst_case_not_averaged(self, service: AreaClimateService) -> None:
        """A peak gust sizes against the worst cell, so averaging would understate it."""
        area = AreaBounds(south=10.0, north=12.0, west=76.8, east=78.5)
        result = service.for_area(area)

        profiles = load_climate_profiles().profiles
        enclosed = [
            profile
            for profile in profiles
            if area.contains(profile.grid_latitude, profile.grid_longitude)
        ]
        expected = max(profile.max_wind_gust_ms for profile in enclosed)

        assert result.profile.max_wind_gust_ms == pytest.approx(expected)

    def test_observation_days_is_the_shortest_contributing_record(
        self, service: AreaClimateService
    ) -> None:
        """The blend is only as long as its shortest input."""
        area = AreaBounds(south=10.0, north=12.0, west=76.8, east=78.5)
        result = service.for_area(area)

        profiles = load_climate_profiles().profiles
        enclosed = [
            profile
            for profile in profiles
            if area.contains(profile.grid_latitude, profile.grid_longitude)
        ]
        assert result.profile.observation_days == min(p.observation_days for p in enclosed)


class TestInterpolation:
    """A gap between cells may be filled, but only from real neighbours, and flagged."""

    def test_an_area_between_cells_is_flagged_as_interpolated(
        self, service: AreaClimateService
    ) -> None:
        # A very small box inside the covered region but between grid nodes, which
        # sit on exact 0.25 degree steps.
        result = service.for_area(AreaBounds(south=11.10, north=11.12, west=77.10, east=77.12))

        assert result.enclosed_node_count == 0
        assert result.interpolated is True
        assert result.source_districts, "an interpolated value must name its sources"

    def test_interpolation_is_bounded_by_real_neighbours(self, service: AreaClimateService) -> None:
        """The result cannot exceed the range of the cells it was built from."""
        result = service.for_area(AreaBounds(south=11.10, north=11.12, west=77.10, east=77.12))

        profiles = {p.district: p for p in load_climate_profiles().profiles}
        sources = [profiles[name] for name in result.source_districts]
        lowest = min(p.mean_relative_humidity_percent for p in sources)
        highest = max(p.mean_relative_humidity_percent for p in sources)

        assert lowest <= result.profile.mean_relative_humidity_percent <= highest

    def test_uses_no_more_than_the_permitted_number_of_sources(
        self, service: AreaClimateService
    ) -> None:
        """Averaging over the whole region would flatten every point to a mean."""
        result = service.for_area(AreaBounds(south=11.10, north=11.12, west=77.10, east=77.12))

        assert len(result.source_districts) <= constants.MAX_INTERPOLATION_SOURCES

    def test_nearer_neighbours_dominate(self, service: AreaClimateService) -> None:
        """Inverse-distance weighting means a point beside a node resolves to it."""
        # Almost exactly on the Coimbatore node, but not enclosing it.
        result = service.for_area(
            AreaBounds(south=11.0001, north=11.0002, west=77.0001, east=77.0002)
        )
        # Sources come back distance-ordered, so the first is the closest node.
        nearest = result.source_districts[0]

        profiles = {p.district: p for p in load_climate_profiles().profiles}
        assert result.profile.mean_relative_humidity_percent == pytest.approx(
            profiles[nearest].mean_relative_humidity_percent, abs=1.0
        )


class TestRefusal:
    """Where there is no neighbouring evidence, there must be no number."""

    @pytest.mark.parametrize(
        ("south", "north", "west", "east", "where"),
        [
            (48.8, 48.9, 2.3, 2.4, "Paris"),
            (-23.6, -23.5, -46.7, -46.6, "Sao Paulo"),
            (28.5, 28.7, 77.1, 77.3, "Delhi — same longitude, far north"),
            (-0.1, 0.1, -0.1, 0.1, "the Gulf of Guinea"),
        ],
    )
    def test_refuses_an_area_with_no_nearby_measurement(
        self,
        service: AreaClimateService,
        south: float,
        north: float,
        west: float,
        east: float,
        where: str,
    ) -> None:
        with pytest.raises(ClimateProfileUnavailableError) as error:
            service.for_area(AreaBounds(south=south, north=north, west=west, east=east))

        # The refusal has to be actionable, so it names the nearest real data.
        assert error.value.details is not None
        assert "nearest_district" in error.value.details
        assert where  # keeps the parametrise label meaningful in failure output

    def test_delhi_is_refused_despite_sharing_a_longitude(
        self, service: AreaClimateService
    ) -> None:
        """Guards against a longitude-only proximity check slipping back in."""
        with pytest.raises(ClimateProfileUnavailableError):
            service.for_area(AreaBounds(south=28.5, north=28.7, west=77.1, east=77.3))
