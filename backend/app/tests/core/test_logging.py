"""Tests for the Cloud Logging fields added to structured log lines."""

from __future__ import annotations

import logging

from app.core.logging import _cloud_logging_fields, reset_trace_id, set_trace_id

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
