"""Shared fixtures: test database lifecycle, HTTP client, mocked external services.

Two rules govern everything here:

* **No real network calls.** Third-party clients are always mocked. ``block_network``
  is autouse, so a test that forgets to mock something fails loudly instead of
  quietly reaching the internet.
* **No shared state between tests.** Every table is truncated and the engine is
  disposed after each test, so tests can run in any order.

The schema is built once per session by running the real Alembic migrations against
the disposable ``test-db`` container, so the migrations themselves are exercised on
every test run rather than assumed correct.

Async fixtures are function-scoped throughout. A session-scoped engine would be
bound to the event loop that created it, and asyncpg fails when a connection is
used from a different loop than the one it was opened on.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import Base, Database, dispose_database, init_database
from app.core.rate_limit import FixedWindowRateLimiter
from app.external.http import close_client as close_http_client
from app.main import create_app
from app.ml.registry import load_registry, reset_registry
from app.repositories.materials import MaterialRepository, load_seed_materials

BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"

# High enough that ordinary tests never trip the limiter. Its behaviour is tested
# directly against the class, and through HTTP by a test that lowers this itself.
TEST_RATE_LIMIT_REQUESTS = 10_000


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Settings pointed at the disposable test database."""
    base = Settings()
    return base.model_copy(
        update={
            "environment": "test",
            "database_url": base.test_database_url,
            "database_url_sync": base.test_database_url_sync,
            "rate_limit_requests": TEST_RATE_LIMIT_REQUESTS,
            # Third-party credentials are cleared unconditionally, whatever the
            # developer's .env holds. Without this the suite changes behaviour the
            # moment someone configures a real key — the "unconfigured" tests start
            # failing, and worse, a client can reach the real upstream. Tests that
            # need credentials build their own Settings.
            "gemini_api_key": None,
            "earth_engine_project_id": None,
            "earth_engine_service_account_email": None,
            "earth_engine_service_account_file": None,
        }
    )


@pytest.fixture(scope="session", autouse=True)
def migrated_schema(settings: Settings) -> Iterator[None]:
    """Build the test schema by running the real migrations, then tear it down.

    Running Alembic rather than ``metadata.create_all`` means a migration that is
    wrong or missing fails the suite, which is the point of keeping them reviewable.
    """
    config = AlembicConfig(str(ALEMBIC_INI))
    # env.py honours a URL already set on the config, so this redirects the
    # migrations at the test database without mutating the environment.
    config.set_main_option("sqlalchemy.url", settings.test_database_url_sync)

    command.upgrade(config, "head")
    yield
    command.downgrade(config, "base")


@pytest.fixture
async def database(settings: Settings) -> AsyncIterator[Database]:
    """A database bound to the test database, truncated and disposed afterwards."""
    instance = init_database(settings)
    try:
        yield instance
    finally:
        table_names = ", ".join(
            f'"{table.name}"' for table in reversed(Base.metadata.sorted_tables)
        )
        async with instance.engine.begin() as connection:
            await connection.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
        await dispose_database()


@pytest.fixture(autouse=True)
async def close_shared_http_client() -> AsyncIterator[None]:
    """Dispose the shared outbound client after each test.

    It is process-wide and would otherwise stay bound to a closed event loop,
    making the next test's first external call fail.
    """
    yield
    await close_http_client()


@pytest.fixture(autouse=True)
def reset_settings_cache() -> Iterator[None]:
    """Clear the settings singleton so one test's overrides cannot leak."""
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that attempts a real outbound connection.

    The brief requires that tests never call Earth Engine, IMD or Gemini for real.
    Guarding the socket layer catches that regardless of which HTTP library a
    client uses.
    """
    import socket

    loopback = {"localhost", "127.0.0.1", "::1"}
    real_create_connection = socket.create_connection
    real_connect = socket.socket.connect

    def guarded_create_connection(
        address: tuple[str, int],
        *args: Any,  # noqa: ANN401 — mirrors socket.create_connection's own signature
        **kwargs: Any,  # noqa: ANN401
    ) -> socket.socket:
        host = address[0] if isinstance(address, tuple) else address
        # The PostGIS test container is a genuine dependency of integration tests,
        # so loopback stays reachable. Everything else is refused.
        if host in loopback:
            return real_create_connection(address, *args, **kwargs)
        raise RuntimeError(
            f"Test attempted a real network connection to {host!r}. "
            "Mock the external client instead."
        )

    def guarded_connect(
        self: socket.socket,
        address: Any,  # noqa: ANN401 — address form varies by address family
    ) -> None:
        # socket.create_connection is not the only route out. The Google API client
        # used by earthengine-api calls socket.connect directly, so guarding only
        # the former let a real request reach Google during a test run.
        host = address[0] if isinstance(address, tuple) else address
        if host in loopback:
            return real_connect(self, address)
        raise RuntimeError(
            f"Test attempted a real network connection to {host!r}. "
            "Mock the external client instead."
        )

    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


@pytest.fixture
async def session(database: Database) -> AsyncIterator[AsyncSession]:
    """A database session for repository-level tests."""
    async with database.session_factory() as db_session:
        yield db_session


@pytest.fixture(scope="session", autouse=True)
def loaded_models() -> Iterator[None]:
    """Load the real trained artifacts once for the whole session.

    Session-scoped deliberately: the registry is process-wide and immutable once
    loaded, and unpickling both artifacts per test costs more than the rest of the
    suite combined.

    Tests run against the shipped models rather than fakes, so an artifact that
    fails to load, or one built by a mismatched scikit-learn version, fails the
    suite instead of only failing in production.
    """
    load_registry()
    yield
    reset_registry()


@pytest.fixture
def app(settings: Settings, database: Database) -> FastAPI:
    """The application under test, wired to the test database.

    Depending on ``database`` guarantees the engine is initialised before any
    request runs; httpx's ASGITransport does not execute the lifespan handler.
    """
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An HTTP client that speaks to the app in-process.

    ASGITransport dispatches straight to the application, so no socket is opened
    and no port needs to be free.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client


@pytest.fixture
async def seeded_catalogue(session: AsyncSession) -> None:
    """Load the real material seed data into the test database.

    Tests exercise the shipped catalogue rather than a fixture copy, so a broken
    seed file fails the suite instead of only failing in production.
    """
    await MaterialRepository(session).upsert_many(load_seed_materials())
    await session.commit()


@pytest.fixture
def rate_limiter() -> FixedWindowRateLimiter:
    """A limiter with a frozen clock, for direct unit testing."""
    return FixedWindowRateLimiter(max_requests=3, window_seconds=60, clock=lambda: 0.0)
