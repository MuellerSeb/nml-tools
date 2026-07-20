"""Tests for the optional GUI command."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from typing import Callable

import pytest
from click.testing import CliRunner

from nml_tools.cli import cli
from nml_tools.gui import launch_gui


def _fake_gui(monkeypatch: pytest.MonkeyPatch, launcher: Callable[[Path], int]) -> None:
    module = ModuleType("nml_tools.gui")
    module.launch_gui = launcher  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "nml_tools.gui", module)


def test_gui_requires_config_in_current_directory() -> None:
    with CliRunner().isolated_filesystem():
        result = CliRunner().invoke(cli, ["gui"])

    assert result.exit_code != 0
    assert "requires nml-config.toml in the current directory" in result.output


def test_gui_lazily_launches_current_project(monkeypatch: pytest.MonkeyPatch) -> None:
    projects: list[Path] = []
    _fake_gui(monkeypatch, lambda project: projects.append(project) or 0)

    with CliRunner().isolated_filesystem():
        Path("nml-config.toml").write_text("", encoding="utf-8")
        expected = Path.cwd()
        result = CliRunner().invoke(cli, ["gui"])

    assert result.exit_code == 0
    assert projects == [expected]


def test_programmatic_gui_forwards_project_and_initial_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[Path, object]] = []
    initial_values = {"main": {"run": {"input_path": "input.nc"}}}
    module = ModuleType("nml_tools.gui.app")
    module.launch_gui = (  # type: ignore[attr-defined]
        lambda project, values=None: calls.append((project, values)) or 7
    )
    monkeypatch.setitem(sys.modules, "nml_tools.gui.app", module)

    assert launch_gui(tmp_path, initial_values) == 7
    assert calls == [(tmp_path, initial_values)]


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
    def fail(_project: Path) -> int:
        raise error

    _fake_gui(monkeypatch, fail)
    with CliRunner().isolated_filesystem():
        Path("nml-config.toml").write_text("", encoding="utf-8")
        result = CliRunner().invoke(cli, ["gui"])

    assert result.exit_code != 0
    assert message in result.output
