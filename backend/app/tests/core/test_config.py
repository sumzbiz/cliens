"""Tests for configuration loading and validation.

Configuration is the only path by which secrets and environment-specific values
enter the application, so its validators are the guard against a misconfigured
deployment starting up and behaving subtly wrongly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings

VALID_ASYNC_URL = "postgresql+asyncpg://u:p@localhost:5433/db"
VALID_SYNC_URL = "postgresql+psycopg://u:p@localhost:5433/db"


def build_settings(**overrides: object) -> Settings:
    """Construct settings from explicit values, ignoring any ambient .env file."""
    defaults: dict[str, object] = {
        "environment": "test",
        "database_url": VALID_ASYNC_URL,
        "database_url_sync": VALID_SYNC_URL,
        "test_database_url": VALID_ASYNC_URL,
        # Cleared explicitly: pydantic-settings falls back to the ambient .env for
        # any field not passed, so without these a developer with real credentials
        # configured would see these tests fail for no reason of their own.
        "gemini_api_key": None,
        "earth_engine_project_id": None,
        "earth_engine_service_account_email": None,
        "earth_engine_service_account_file": None,
    }
    return Settings(**{**defaults, **overrides})  # type: ignore[arg-type]  # kwargs are validated


class TestDriverValidation:
    """A wrong driver fails deep inside SQLAlchemy with an unhelpful error."""

    def test_rejects_sync_driver_for_the_application_url(self) -> None:
        with pytest.raises(ValidationError, match="async driver required"):
            build_settings(database_url=VALID_SYNC_URL)

    def test_rejects_async_driver_for_the_alembic_url(self) -> None:
        with pytest.raises(ValidationError, match="sync driver required"):
            build_settings(database_url_sync=VALID_ASYNC_URL)

    def test_rejects_a_non_postgres_url(self) -> None:
        with pytest.raises(ValidationError, match="async driver required"):
            build_settings(database_url="sqlite+aiosqlite:///./test.db")

    def test_derives_the_sync_test_url_from_the_async_one(self) -> None:
        """Two separate variables would eventually drift apart."""
        settings = build_settings(test_database_url=VALID_ASYNC_URL)
        assert settings.test_database_url_sync == VALID_SYNC_URL


class TestBlankValuesAreUnset:
    """`.env.example` ships credential keys present but empty.

    Without this handling, ``FOO=`` becomes ``Path("")`` — which resolves to the
    current directory and reads as configured — instead of "not configured".
    """

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_gemini_key_is_unset(self, blank: str) -> None:
        settings = build_settings(gemini_api_key=blank)
        assert settings.gemini_api_key is None
        assert settings.gemini_configured is False

    @pytest.mark.parametrize("blank", ["", "  "])
    def test_blank_service_account_path_is_unset(self, blank: str) -> None:
        settings = build_settings(earth_engine_service_account_file=blank)
        assert settings.earth_engine_service_account_file is None

    def test_blank_earth_engine_values_leave_it_unconfigured(self) -> None:
        settings = build_settings(
            earth_engine_project_id="",
            earth_engine_service_account_email="",
            earth_engine_service_account_file="",
        )
        assert settings.earth_engine_configured is False


class TestCredentialDetection:
    """`*_configured` decides whether an endpoint errors or proceeds."""

    def test_gemini_is_configured_when_a_key_is_present(self) -> None:
        assert build_settings(gemini_api_key="test-key").gemini_configured is True

    def test_earth_engine_needs_all_three_values(self, tmp_path: Path) -> None:
        key_file = tmp_path / "sa.json"
        key_file.write_text("{}", encoding="utf-8")

        partial = build_settings(
            earth_engine_project_id="proj",
            earth_engine_service_account_file=key_file,
        )
        assert partial.earth_engine_configured is False

        complete = build_settings(
            earth_engine_project_id="proj",
            earth_engine_service_account_email="sa@proj.iam.gserviceaccount.com",
            earth_engine_service_account_file=key_file,
        )
        assert complete.earth_engine_configured is True

    def test_missing_service_account_file_fails_at_startup(self, tmp_path: Path) -> None:
        """Better than failing on the first Earth Engine request in production."""
        with pytest.raises(ValidationError, match="service account key file not found"):
            build_settings(earth_engine_service_account_file=tmp_path / "absent.json")


class TestCorsOrigins:
    """CORS is the main thing standing between this API and any website."""

    def test_splits_a_comma_separated_list(self) -> None:
        settings = build_settings(cors_allowed_origins="http://a.test,http://b.test")
        assert settings.cors_origins == ("http://a.test", "http://b.test")

    def test_trims_whitespace_and_drops_blanks(self) -> None:
        settings = build_settings(cors_allowed_origins=" http://a.test , , http://b.test ")
        assert settings.cors_origins == ("http://a.test", "http://b.test")

    def test_production_rejects_a_wildcard_origin(self) -> None:
        with pytest.raises(ValidationError, match="must not contain"):
            build_settings(environment="production", cors_allowed_origins="*")

    def test_production_rejects_empty_origins(self) -> None:
        with pytest.raises(ValidationError, match="must be set in production"):
            build_settings(environment="production", cors_allowed_origins="")

    def test_development_permits_a_wildcard(self) -> None:
        """Local development is not a security boundary; production is."""
        settings = build_settings(environment="development", cors_allowed_origins="*")
        assert settings.cors_origins == ("*",)


class TestBoundedValues:
    """Constrained types stop a typo becoming a denial-of-service setting."""

    @pytest.mark.parametrize("value", [0, -1, 10_001])
    def test_rejects_out_of_range_rate_limit(self, value: int) -> None:
        with pytest.raises(ValidationError):
            build_settings(rate_limit_requests=value)

    @pytest.mark.parametrize("value", [0, 3_601])
    def test_rejects_out_of_range_rate_limit_window(self, value: int) -> None:
        with pytest.raises(ValidationError):
            build_settings(rate_limit_window_seconds=value)

    @pytest.mark.parametrize("value", [0.0, -1.0, 61.0])
    def test_rejects_out_of_range_imd_timeout(self, value: float) -> None:
        with pytest.raises(ValidationError):
            build_settings(imd_request_timeout_seconds=value)

    def test_rejects_an_unknown_environment(self) -> None:
        with pytest.raises(ValidationError):
            build_settings(environment="staging")

    def test_rejects_an_unknown_log_level(self) -> None:
        with pytest.raises(ValidationError):
            build_settings(log_level="VERBOSE")


class TestIsProduction:
    """Several behaviours branch on this flag."""

    @pytest.mark.parametrize(
        ("environment", "expected"),
        [("development", False), ("test", False), ("production", True)],
    )
    def test_reports_the_environment(self, environment: str, expected: bool) -> None:
        settings = build_settings(environment=environment, cors_allowed_origins="http://a.test")
        assert settings.is_production is expected
