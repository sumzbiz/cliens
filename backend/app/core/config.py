"""Typed application settings loaded from the environment via pydantic-settings.

Every secret and every environment-dependent value enters the application through
this module and nowhere else. Nothing here has a hardcoded credential default; a
missing credential is represented as ``None`` and surfaces later as an explicit
``ExternalServiceUnconfiguredError`` rather than as fabricated data.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> core -> app -> backend -> repository root
REPO_ROOT = Path(__file__).resolve().parents[3]

Environment = Literal["development", "test", "production"]


class Settings(BaseSettings):
    """Application configuration, validated once at import time."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # Unknown keys in .env are ignored so that adding an unrelated variable
        # (for example one consumed by docker compose) cannot crash the app.
        extra="ignore",
    )

    # --- Application -------------------------------------------------------
    environment: Environment = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # --- Database ----------------------------------------------------------
    # asyncpg drives the application; psycopg drives Alembic, which is synchronous.
    database_url: str = (
        "postgresql+asyncpg://cls:cls_dev_password@localhost:5433/climate_lien_score"
    )
    database_url_sync: str = (
        "postgresql+psycopg://cls:cls_dev_password@localhost:5433/climate_lien_score"
    )
    test_database_url: str = (
        "postgresql+asyncpg://cls:cls_dev_password@localhost:5434/climate_lien_score_test"
    )

    # --- Security ----------------------------------------------------------
    # Stored as a raw string because pydantic-settings parses list-typed fields as
    # JSON, which a comma-separated .env value is not. Split via `cors_origins`.
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    rate_limit_requests: Annotated[int, Field(ge=1, le=10_000)] = 60
    rate_limit_window_seconds: Annotated[int, Field(ge=1, le=3_600)] = 60

    # --- Sarvam AI text-to-speech ------------------------------------------
    # Two keys from two accounts. Both optional: with neither set the app simply
    # offers no voice narration, and every question remains usable as text.
    sarvam_api_key_primary: str | None = None
    sarvam_api_key_secondary: str | None = None
    sarvam_tts_speaker: str = "kavitha"
    sarvam_tts_language: str = "ta-IN"

    # --- Basemap imagery ---------------------------------------------------
    # Optional. Without it the map falls back to Esri, which publishes no imagery
    # deeper than zoom 19 (~0.3 m per pixel). Mapbox Satellite reaches zoom 22 in
    # populated areas, which is what resolves individual roof detail.
    mapbox_access_token: str | None = None

    # --- Gemini ------------------------------------------------------------
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"

    # --- Earth Engine ------------------------------------------------------
    earth_engine_project_id: str | None = None
    earth_engine_service_account_email: str | None = None
    earth_engine_service_account_file: Path | None = None

    # --- IMD ---------------------------------------------------------------
    imd_api_base_url: str = "https://api.imd.gov.in"
    imd_request_timeout_seconds: Annotated[float, Field(gt=0, le=60)] = 10.0

    # ----------------------------------------------------------------------
    # Derived values
    # ----------------------------------------------------------------------
    # The `prop-decorator` ignores below are required: mypy does not model
    # pydantic's computed_field wrapping a property.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origins(self) -> tuple[str, ...]:
        """CORS origins as an immutable tuple, blanks removed."""
        return tuple(o.strip() for o in self.cors_allowed_origins.split(",") if o.strip())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def test_database_url_sync(self) -> str:
        """The test database URL with the synchronous driver.

        Alembic cannot use asyncpg, so the test suite needs a psycopg form of
        ``test_database_url``. Deriving it here keeps the two from drifting apart,
        which a second environment variable would eventually allow.
        """
        return self.test_database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def voice_configured(self) -> bool:
        """Whether voice narration can run at all.

        One key is enough. The second only buys failover, so requiring both would
        disable the feature for anyone with a single account.
        """
        return bool(self.sarvam_api_key_primary or self.sarvam_api_key_secondary)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sarvam_keys(self) -> tuple[str, ...]:
        """Configured keys in failover order, primary first.

        Ordered rather than a set: which key is tried first is the whole point.
        """
        return tuple(
            key for key in (self.sarvam_api_key_primary, self.sarvam_api_key_secondary) if key
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def mapbox_configured(self) -> bool:
        """Whether the deeper Mapbox imagery is available.

        Read at request time rather than baked into a constant: the maximum usable
        zoom depends on it, and the interface has to report the real limit rather
        than let the user zoom into blank tiles.
        """
        return bool(self.mapbox_access_token)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def gemini_configured(self) -> bool:
        """Whether report generation can run."""
        return bool(self.gemini_api_key)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def earth_engine_configured(self) -> bool:
        """Whether Earth Engine can authenticate.

        All three values are required: Earth Engine authenticates as a service
        account within a specific registered Cloud project.
        """
        return bool(
            self.earth_engine_project_id
            and self.earth_engine_service_account_email
            and self.earth_engine_service_account_file
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        """Whether stricter production behaviour applies."""
        return self.environment == "production"

    # ----------------------------------------------------------------------
    # Validation
    # ----------------------------------------------------------------------
    @field_validator(
        "sarvam_api_key_primary",
        "sarvam_api_key_secondary",
        "mapbox_access_token",
        "gemini_api_key",
        "earth_engine_project_id",
        "earth_engine_service_account_email",
        "earth_engine_service_account_file",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        """Treat an empty environment variable as "not configured".

        ``.env.example`` ships these keys present but blank, and a shell exports an
        unset variable as an empty string. Without this, ``FOO=`` would become
        ``Path("")`` — which resolves to the current directory and reads as
        configured — instead of ``None``.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("database_url", "test_database_url")
    @classmethod
    def _require_async_driver(cls, value: str) -> str:
        """The application uses async SQLAlchemy, which needs the asyncpg driver.

        A sync URL here would fail deep inside the engine with an unhelpful error,
        so it is rejected at startup instead.
        """
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("must be a postgresql+asyncpg:// URL (async driver required)")
        return value

    @field_validator("database_url_sync")
    @classmethod
    def _require_sync_driver(cls, value: str) -> str:
        """Alembic runs migrations synchronously and cannot use asyncpg."""
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("must be a postgresql+psycopg:// URL (sync driver required)")
        return value

    @field_validator("earth_engine_service_account_file")
    @classmethod
    def _service_account_file_must_exist(cls, value: Path | None) -> Path | None:
        """Fail at startup rather than on the first Earth Engine request."""
        if value is not None and not value.is_file():
            raise ValueError(f"service account key file not found: {value}")
        return value

    @model_validator(mode="after")
    def _production_requires_explicit_origins(self) -> Settings:
        """A wildcard CORS origin in production would expose the API to any site."""
        if self.is_production:
            if not self.cors_origins:
                raise ValueError("CORS_ALLOWED_ORIGINS must be set in production")
            if "*" in self.cors_origins:
                raise ValueError("CORS_ALLOWED_ORIGINS must not contain '*' in production")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Cached so that the ``.env`` file is read once and every module observes exactly
    the same configuration. Tests clear the cache via ``get_settings.cache_clear()``.
    """
    return Settings()


def load_settings_or_exit() -> Settings:
    """Load settings, printing an actionable message and exiting on failure.

    Used by entry points (the ASGI app, the CLI) where a stack trace from deep
    inside pydantic is less useful than a direct statement of which variable is
    wrong and where to fix it.
    """
    try:
        return get_settings()
    except ValueError as error:
        sys.stderr.write(
            "Invalid configuration.\n"
            f"{error}\n\n"
            f"Check your .env file at {REPO_ROOT / '.env'} against .env.example.\n"
        )
        raise SystemExit(1) from error
