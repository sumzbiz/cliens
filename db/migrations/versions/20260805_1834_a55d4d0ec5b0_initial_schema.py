"""initial schema

Revision ID: a55d4d0ec5b0
Revises: none (first migration)
Created: 2026-08-05 18:34:35.790148+00:00

An applied migration is never edited. To change the schema, add a new migration.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

revision: str = "a55d4d0ec5b0"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this migration."""
    # The sites table stores PostGIS geometry, so the extension must exist first.
    # The postgis/postgis image installs it already; this makes the migration work
    # against a plain PostgreSQL instance with the extension merely available.
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "external_response_cache",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("service", sa.String(length=40), nullable=False),
        sa.Column("cache_key", sa.String(length=200), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "service IN ('earth_engine', 'imd', 'gemini')",
            name=op.f("ck_external_response_cache_service_is_known"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_response_cache")),
        sa.UniqueConstraint("service", "cache_key", name="uq_external_cache_service_key"),
    )
    op.create_index(
        "ix_external_cache_lookup",
        "external_response_cache",
        ["service", "cache_key", "expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_external_response_cache_created_at"),
        "external_response_cache",
        ["created_at"],
        unique=False,
    )
    op.create_table(
        "materials",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("component", sa.String(length=20), nullable=False),
        sa.Column("resistance_wind", sa.Float(), nullable=False),
        sa.Column("resistance_flood", sa.Float(), nullable=False),
        sa.Column("resistance_heat", sa.Float(), nullable=False),
        sa.Column("relative_cost_index", sa.Float(), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "component IN ('foundation', 'walls', 'roofing')",
            name=op.f("ck_materials_component_is_known"),
        ),
        sa.CheckConstraint(
            "relative_cost_index > 0", name=op.f("ck_materials_cost_index_positive")
        ),
        sa.CheckConstraint(
            "resistance_wind BETWEEN 0 AND 1 AND resistance_flood BETWEEN 0 AND 1 AND resistance_heat BETWEEN 0 AND 1",
            name=op.f("ck_materials_resistances_within_unit_interval"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_materials")),
        sa.UniqueConstraint("code", name=op.f("uq_materials_code")),
    )
    op.create_index(op.f("ix_materials_component"), "materials", ["component"], unique=False)
    op.create_index(op.f("ix_materials_created_at"), "materials", ["created_at"], unique=False)
    op.create_geospatial_table(
        "sites",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "geometry",
            Geometry(
                geometry_type="POLYGON",
                srid=4326,
                spatial_index=False,
                from_text="ST_GeomFromEWKT",
                name="geometry",
                nullable=False,
            ),
            nullable=False,
        ),
        sa.Column("area_sq_ft", sa.Float(), nullable=False),
        sa.Column("centroid_longitude", sa.Float(), nullable=False),
        sa.Column("centroid_latitude", sa.Float(), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "area_sq_ft >= 100.0 AND area_sq_ft <= 1000000.0",
            name=op.f("ck_sites_area_within_supported_bounds"),
        ),
        sa.CheckConstraint(
            "centroid_latitude >= -90.0 AND centroid_latitude <= 90.0",
            name=op.f("ck_sites_centroid_latitude_valid"),
        ),
        sa.CheckConstraint(
            "centroid_longitude >= -180.0 AND centroid_longitude <= 180.0",
            name=op.f("ck_sites_centroid_longitude_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sites")),
    )
    op.create_geospatial_index(
        "idx_sites_geometry",
        "sites",
        ["geometry"],
        unique=False,
        postgresql_using="gist",
        postgresql_ops={},
    )
    op.create_index(op.f("ix_sites_created_at"), "sites", ["created_at"], unique=False)
    op.create_table(
        "scores",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("scenario", sa.String(length=20), nullable=False),
        sa.Column("crossing_year", sa.Integer(), nullable=True),
        sa.Column("crossing_year_lower", sa.Integer(), nullable=True),
        sa.Column("crossing_year_upper", sa.Integer(), nullable=True),
        sa.Column("confidence_label", sa.String(length=20), nullable=False),
        sa.Column("breakdown", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("damage_model_version", sa.String(length=120), nullable=False),
        sa.Column("material_model_version", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence_label IN ('high', 'moderate', 'low')",
            name=op.f("ck_scores_confidence_label_is_known"),
        ),
        sa.CheckConstraint(
            "scenario IN ('baseline', 'improved')",
            name=op.f("ck_scores_scenario_is_known"),
        ),
        sa.CheckConstraint(
            "crossing_year IS NULL OR (crossing_year >= 2025 AND crossing_year <= 2055)",
            name=op.f("ck_scores_crossing_year_within_horizon"),
        ),
        sa.ForeignKeyConstraint(
            ["site_id"],
            ["sites.id"],
            name=op.f("fk_scores_site_id_sites"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scores")),
        sa.UniqueConstraint("input_hash", "scenario", name="uq_scores_input_hash_scenario"),
    )
    op.create_index(op.f("ix_scores_created_at"), "scores", ["created_at"], unique=False)
    op.create_index(op.f("ix_scores_site_id"), "scores", ["site_id"], unique=False)
    op.create_table(
        "reports",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("score_id", sa.UUID(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.String(length=20), nullable=False),
        sa.Column("model_name", sa.String(length=80), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["score_id"],
            ["scores.id"],
            name=op.f("fk_reports_score_id_scores"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reports")),
    )
    op.create_index(op.f("ix_reports_created_at"), "reports", ["created_at"], unique=False)
    op.create_index(op.f("ix_reports_score_id"), "reports", ["score_id"], unique=False)


def downgrade() -> None:
    """Revert this migration.

    The postgis extension is deliberately not dropped: other schemas in the same
    database may depend on it, and dropping it would cascade into them.
    """
    op.drop_index(op.f("ix_reports_score_id"), table_name="reports")
    op.drop_index(op.f("ix_reports_created_at"), table_name="reports")
    op.drop_table("reports")
    op.drop_index(op.f("ix_scores_site_id"), table_name="scores")
    op.drop_index(op.f("ix_scores_created_at"), table_name="scores")
    op.drop_table("scores")
    op.drop_index(op.f("ix_sites_created_at"), table_name="sites")
    op.drop_geospatial_index(
        "idx_sites_geometry",
        table_name="sites",
        postgresql_using="gist",
        column_name="geometry",
    )
    op.drop_geospatial_table("sites")
    op.drop_index(op.f("ix_materials_created_at"), table_name="materials")
    op.drop_index(op.f("ix_materials_component"), table_name="materials")
    op.drop_table("materials")
    op.drop_index(
        op.f("ix_external_response_cache_created_at"),
        table_name="external_response_cache",
    )
    op.drop_index("ix_external_cache_lookup", table_name="external_response_cache")
    op.drop_table("external_response_cache")
    # ### end Alembic commands ###
