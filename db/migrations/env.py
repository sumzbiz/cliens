"""Alembic migration environment.

The connection URL comes from the application settings rather than alembic.ini, so
credentials live only in the environment and there is a single source of truth for
where the database is.

Migrations run synchronously (psycopg), while the application runs asynchronously
(asyncpg). That is why two URLs exist in configuration.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from geoalchemy2 import alembic_helpers
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.core.database import Base, register_orm_models

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Importing the models attaches every table to Base.metadata; without this,
# autogenerate would see an empty schema and propose dropping everything.
register_orm_models()
target_metadata = Base.metadata

# A programmatic caller (the test suite) may already have set the URL on this
# config object. Respect it, so tests can migrate the test database without
# mutating the environment; otherwise fall back to application settings.
if not config.get_main_option("sqlalchemy.url", None):
    config.set_main_option("sqlalchemy.url", get_settings().database_url_sync)


def include_object(
    obj: object,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: object,
) -> bool:
    """Restrict autogenerate to tables this application actually owns.

    Two filters, in order:

    1. GeoAlchemy2's own filter, which hides PostGIS internals such as
       ``spatial_ref_sys`` and the geometry-column views.
    2. An ownership check. The ``postgis/postgis`` image also installs
       ``postgis_tiger_geocoder``, which creates around forty US census lookup
       tables. They are reflected but absent from our metadata, so autogenerate
       would otherwise propose dropping all of them.
    """
    if not alembic_helpers.include_object(obj, name, type_, reflected, compare_to):
        return False

    if not reflected:
        return True

    if type_ == "table":
        return name in target_metadata.tables
    if type_ == "index":
        table = getattr(obj, "table", None)
        return table is not None and table.name in target_metadata.tables
    return True


# GeoAlchemy2 hooks. Without these, autogenerate emits unusable migrations for
# spatial columns: it would render Geometry columns without their import and try
# to manage PostGIS's internal tables.
GEOALCHEMY_OPTIONS = {
    "include_object": include_object,
    "process_revision_directives": alembic_helpers.writer,
    "render_item": alembic_helpers.render_item,
}


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting to a database.

    Used to review the exact statements a migration will run before applying it to
    a production database.
    """
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        **GEOALCHEMY_OPTIONS,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against a live database."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Detect column type and server-default changes, which Alembic ignores
            # by default and which would otherwise drift silently.
            compare_type=True,
            compare_server_default=True,
            **GEOALCHEMY_OPTIONS,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
