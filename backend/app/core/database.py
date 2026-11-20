"""Async SQLAlchemy engine and session factory. Only repositories may consume these.

The engine is created once per process at startup and disposed at shutdown. Sessions
are per-request and are handed to repositories through the FastAPI dependency in
``get_session``; nothing above the repository layer should ever hold one.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import MetaData, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings
from app.core.exceptions import DatabaseError
from app.core.logging import get_logger

logger = get_logger(__name__)

# Explicit constraint naming. Without this PostgreSQL invents names, and Alembic
# then generates migrations that cannot drop a constraint it cannot name — which
# only shows up much later, on the migration that needs to alter it.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for every ORM model.

    Lives here rather than in the models module so that Alembic can import the
    metadata without importing the application.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Database:
    """Owns the async engine and session factory for one process."""

    def __init__(self, url: str, *, echo: bool = False) -> None:
        """Create the engine.

        Args:
            url: A ``postgresql+asyncpg://`` URL.
            echo: Whether to log every statement. Verbose; development only.
        """
        self._engine: AsyncEngine = create_async_engine(
            url,
            echo=echo,
            # Verify a pooled connection before handing it out. Without this, a
            # connection dropped by the server (container restart, idle timeout)
            # surfaces as a spurious error on an unrelated request.
            pool_pre_ping=True,
        )
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self._engine,
            expire_on_commit=False,  # keep attributes readable after commit
            autoflush=False,  # repositories flush explicitly, so writes stay obvious
        )

    @property
    def engine(self) -> AsyncEngine:
        """The underlying async engine."""
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Factory producing new sessions bound to this engine."""
        return self._session_factory

    async def check_connection(self) -> bool:
        """Whether the database answers a trivial query.

        Used by the readiness endpoint. Returns ``False`` rather than raising, since
        an unreachable database is a reportable state, not an unexpected failure.
        """
        try:
            async with self._engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except SQLAlchemyError as error:
            logger.warning("database_health_check_failed", error=str(error))
            return False
        return True

    async def postgis_version(self) -> str | None:
        """Return the installed PostGIS version, or ``None`` if the extension is absent.

        Reported by the readiness endpoint: the schema depends on PostGIS, and a
        database without it fails later in a much more confusing way.
        """
        query = text("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")
        try:
            async with self._engine.connect() as connection:
                result = await connection.execute(query)
                version: str | None = result.scalar_one_or_none()
        except SQLAlchemyError as error:
            logger.warning("postgis_version_check_failed", error=str(error))
            return None
        return version

    async def dispose(self) -> None:
        """Close every pooled connection. Called at application shutdown."""
        await self._engine.dispose()
        logger.info("database_disposed")


# ---------------------------------------------------------------------------
# Process-wide instance
# ---------------------------------------------------------------------------
_database: Database | None = None


def init_database(settings: Settings) -> Database:
    """Create the process-wide database instance.

    Called once from the application lifespan. Calling it again replaces the
    instance, which is what integration tests rely on to point at the test database.
    """
    global _database
    _database = Database(
        settings.database_url,
        echo=settings.environment == "development" and settings.log_level == "DEBUG",
    )
    logger.info("database_initialised", environment=settings.environment)
    return _database


def get_database() -> Database:
    """Return the process-wide database instance.

    Raises:
        DatabaseError: If called before ``init_database``, which would otherwise
            surface as an opaque ``AttributeError`` on ``None``.
    """
    if _database is None:
        raise DatabaseError("Database is not initialised; init_database() was never called")
    return _database


async def dispose_database() -> None:
    """Dispose the process-wide instance, if one exists."""
    global _database
    if _database is not None:
        await _database.dispose()
        _database = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a transactional session.

    The session is committed if the handler returns normally and rolled back if it
    raises, so no route can leave a half-written transaction behind. Repositories
    receive this session; nothing else should.

    Raises:
        DatabaseError: If the transaction fails to commit.
    """
    session_factory = get_database().session_factory
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except SQLAlchemyError as error:
            await session.rollback()
            logger.exception("database_transaction_failed", error=str(error))
            raise DatabaseError("The database rejected this operation.") from error
        except Exception:
            # Application errors must also roll back, but they are not database
            # failures, so they propagate unchanged for their own handlers.
            await session.rollback()
            raise


def register_orm_models() -> None:
    """Import the ORM models so their tables attach to ``Base.metadata``.

    Alembic autogenerate and the test-schema builder both need every model imported
    before they read the metadata. Importing here keeps that requirement in one
    place instead of scattering imports through migration scripts.
    """
    # Imported for the side effect of registering tables on Base.metadata.
    from app.repositories import models  # noqa: F401  (side-effect import)
