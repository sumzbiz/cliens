"""Tests for the administrative CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.cli import main


class TestExportOpenapi:
    """``export-openapi`` writes the spec the frontend types are generated from."""

    def test_writes_the_served_spec(self, tmp_path: Path) -> None:
        output = tmp_path / "openapi.json"

        assert main(["export-openapi", str(output)]) == 0

        spec = json.loads(output.read_text(encoding="utf-8"))
        assert spec["openapi"].startswith("3.")
        # Both report endpoints must be present: the area one is the route whose
        # absence from the committed frontend types prompted this command.
        assert "/api/reports" in spec["paths"]
        assert "/api/reports/area" in spec["paths"]

    def test_unwritable_destination_fails_cleanly(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # A directory cannot be opened as a file, so the write raises OSError.
        assert main(["export-openapi", str(tmp_path)]) == 1
        assert "Could not write the OpenAPI spec" in capsys.readouterr().err

    def test_requires_a_destination(self) -> None:
        with pytest.raises(SystemExit):
            main(["export-openapi"])
