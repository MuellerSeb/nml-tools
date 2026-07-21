"""Tests for the optional GUI command."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

import pytest
from click.testing import CliRunner

from nml_tools.cli import cli
from nml_tools.gui import launch_gui


def _fake_gui(monkeypatch: pytest.MonkeyPatch, launcher: Callable[..., int]) -> None:
    module = ModuleType("nml_tools.gui")
    module.launch_gui = launcher  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "nml_tools.gui", module)


def test_gui_requires_config_in_input_directory(tmp_path: Path) -> None:
    result = CliRunner().invoke(cli, ["gui", "--input-path", str(tmp_path)])

    assert result.exit_code != 0
    assert "requires nml-config.toml" in result.output


def test_gui_defaults_input_and_output_to_current_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Path, Path, object]] = []
    _fake_gui(
        monkeypatch,
        lambda schemas, output, values: calls.append((schemas, output, values)) or 0,
    )

    with CliRunner().isolated_filesystem():
        Path("nml-config.toml").write_text("", encoding="utf-8")
        expected = Path.cwd()
        result = CliRunner().invoke(cli, ["gui"])

    assert result.exit_code == 0
    assert calls == [(expected, expected, None)]


def test_gui_defaults_output_to_selected_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    schemas_dir = tmp_path / "schemas"
    schemas_dir.mkdir()
    (schemas_dir / "nml-config.toml").write_text("", encoding="utf-8")
    calls: list[tuple[Path, Path, object]] = []
    _fake_gui(
        monkeypatch,
        lambda schemas, output, values: calls.append((schemas, output, values)) or 0,
    )

    result = CliRunner().invoke(cli, ["gui", "-i", str(schemas_dir)])

    assert result.exit_code == 0
    assert calls == [(schemas_dir, schemas_dir, None)]


@pytest.mark.parametrize(
    ("input_flag", "output_flag", "fetch_flag"),
    [
        ("-i", "-o", "-f"),
        ("--input-path", "--output-path", "--fetch-values"),
    ],
)
def test_gui_forwards_paths_and_fetched_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    input_flag: str,
    output_flag: str,
    fetch_flag: str,
) -> None:
    schemas_dir = tmp_path / "schemas"
    output_dir = tmp_path / "output"
    schemas_dir.mkdir()
    output_dir.mkdir()
    (schemas_dir / "nml-config.toml").write_text("", encoding="utf-8")
    initial_values = {"main": {"run": {"input_path": "input.nc"}}}
    values_path = tmp_path / "values.json"
    values_path.write_text(json.dumps(initial_values), encoding="utf-8")
    calls: list[tuple[Path, Path, object]] = []
    _fake_gui(
        monkeypatch,
        lambda schemas, output, values: calls.append((schemas, output, values)) or 0,
    )

    result = CliRunner().invoke(
        cli,
        [
            "gui",
            input_flag,
            str(schemas_dir),
            output_flag,
            str(output_dir),
            fetch_flag,
            str(values_path),
        ],
    )

    assert result.exit_code == 0
    assert calls == [(schemas_dir, output_dir, initial_values)]


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("{", "failed to read initial values"),
        ("[]", "object"),
    ],
)
def test_gui_rejects_invalid_fetched_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    contents: str,
    message: str,
) -> None:
    schemas_dir = tmp_path / "schemas"
    schemas_dir.mkdir()
    (schemas_dir / "nml-config.toml").write_text("", encoding="utf-8")
    values_path = tmp_path / "values.json"
    values_path.write_text(contents, encoding="utf-8")
    calls: list[tuple[Any, ...]] = []
    _fake_gui(monkeypatch, lambda *args: calls.append(args) or 0)

    result = CliRunner().invoke(
        cli,
        ["gui", "-i", str(schemas_dir), "-f", str(values_path)],
    )

    assert result.exit_code != 0
    assert message in result.output
    assert calls == []


def test_programmatic_gui_forwards_paths_values_and_dimensions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[Path, Path, object, object]] = []
    output_dir = tmp_path / "output"
    initial_values = {"main": {"run": {"input_path": "input.nc"}}}
    initial_dimensions = {"n_domains": 1}
    module = ModuleType("nml_tools.gui.app")
    module.launch_gui = (  # type: ignore[attr-defined]
        lambda schemas, output=None, values=None, dimensions=None: calls.append(
            (schemas, output, values, dimensions)
        )
        or 7
    )
    monkeypatch.setitem(sys.modules, "nml_tools.gui.app", module)

    assert (
        launch_gui(
            schemas_dir=tmp_path,
            output_dir=output_dir,
            initial_values=initial_values,
            initial_dimensions=initial_dimensions,
        )
        == 7
    )
    assert calls == [(tmp_path, output_dir, initial_values, initial_dimensions)]


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (ImportError("No module named 'qtpy'"), "install 'nml-tools[gui]'"),
        (RuntimeError("no Qt binding"), "failed to start GUI: no Qt binding"),
        (ValueError("invalid profile"), "failed to start GUI: invalid profile"),
    ],
)
def test_gui_reports_startup_errors(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    message: str,
) -> None:
    def fail(_schemas: Path, _output: Path, _values: object) -> int:
        raise error

    _fake_gui(monkeypatch, fail)
    with CliRunner().isolated_filesystem():
        Path("nml-config.toml").write_text("", encoding="utf-8")
        result = CliRunner().invoke(cli, ["gui"])

    assert result.exit_code != 0
    assert message in result.output
