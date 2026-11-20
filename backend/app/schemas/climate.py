"""Request and response models for the climate outlook and integration status."""

from __future__ import annotations

from typing import Annotated

from fastapi import Query
from pydantic import Field

from app.schemas.common import SchemaBase

Latitude = Annotated[float, Query(ge=-90.0, le=90.0, description="WGS84 latitude, degrees.")]
Longitude = Annotated[float, Query(ge=-180.0, le=180.0, description="WGS84 longitude, degrees.")]


class ProjectedVariableResponse(SchemaBase):
    """One variable in both decades, with the spread of the change across models."""

    name: str
    unit: str
    baseline: float
    future: float
    change: float = Field(description="Multi-model mean change, future minus baseline.")
    change_low: float = Field(description="Smallest change any model projects.")
    change_high: float = Field(description="Largest change any model projects.")


class ClimateProjectionResponse(SchemaBase):
    """A mid-century outlook at a point. Context only: it does not feed the score."""

    latitude: float
    longitude: float
    scenario: str
    models: tuple[str, ...]
    baseline_years: tuple[int, int]
    future_years: tuple[int, int]
    variables: tuple[ProjectedVariableResponse, ...]
    dataset: str


class IntegrationsResponse(SchemaBase):
    """Which optional Google integrations this server has credentials for."""

    gemini_explanations: bool
    earth_engine_projections: bool
