"""Tests for the Cloud Logging fields added to structured log lines."""

from __future__ import annotations

import io
import json
import logging
import sys

import pytest

from app.core.config import Settings
from app.core.logging import (
    _cloud_logging_fields,
    configure_logging,
    get_logger,
    reset_request_id,
    reset_trace_id,
    set_request_id,
    set_trace_id,
)

LOGGER = logging.getLogger("test")


class TestCloudLoggingFields:
    """Severity, message and trace are what Cloud Logging indexes a line by."""

    def test_adds_severity_and_message(self) -> None:
        add = _cloud_logging_fields("proj")

        line = add(LOGGER, "warning", {"event": "slow", "level": "warning"})

        assert line["severity"] == "WARNING"
        assert line["message"] == "slow"
        assert "logging.googleapis.com/trace" not in line

    def test_links_the_line_to_the_request_trace(self) -> None:
        add = _cloud_logging_fields("proj")
        token = set_trace_id("abc123/456;o=1")
        try:
            line = add(LOGGER, "info", {"event": "done", "level": "info"})
        finally:
            reset_trace_id(token)

        assert line["logging.googleapis.com/trace"] == "projects/proj/traces/abc123"

    def test_an_empty_header_binds_no_trace(self) -> None:
        add = _cloud_logging_fields("proj")
        token = set_trace_id("")
        try:
            line = add(LOGGER, "info", {"event": "done", "level": "info"})
        finally:
            reset_trace_id(token)

        assert "logging.googleapis.com/trace" not in line


class TestImportTimeLoggers:
    """A logger made before configuration must still use the configuration."""

    def test_renders_json_with_the_request_id(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Logging writes to whatever sys.stdout is when it is configured; a private
        # buffer keeps this independent of pytest's (and colorama's) stream wrappers.
        # Created before configuration, as every module-level logger in the app
        # is at import. (Not at this module's top level: pytest's collection
        # inspects module attributes, which would itself materialise the proxy.)
        early = get_logger("tests.import_time")
        buffer = io.StringIO()
        monkeypatch.setattr(sys, "stdout", buffer)
        configure_logging(settings.model_copy(update={"environment": "production"}))
        token = set_request_id("req-123")
        try:
            early.info("configured_later", value=1)
        finally:
            reset_request_id(token)

        line = json.loads(buffer.getvalue().strip().splitlines()[-1])
        assert line["event"] == "configured_later"
        assert line["request_id"] == "req-123"
        assert line["logger"] == "tests.import_time"
