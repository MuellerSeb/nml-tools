"""GUI CLI wiring without starting a Qt event loop."""

import subprocess
import sys

from click.testing import CliRunner

import nml_tools.gui
from nml_tools.cli import cli
from nml_tools.gui import GuiProjectRequest


def test_gui_command_paths_and_help(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "nml-config.toml"
    config.write_text("")
    calls = []
    monkeypatch.setattr(
        nml_tools.gui,
        "launch_gui",
        lambda *args, **kwargs: calls.append((args, kwargs)) or 0,
    )
    result = CliRunner().invoke(
        cli,
        [
            "gui",
            "-c",
            str(config),
            "-p",
            "simulation",
            "-o",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == 0
    assert calls == [
        (
            (config, (GuiProjectRequest("simulation", tmp_path / "out"),)),
            {"default_output_dir": tmp_path / "out"},
        )
    ]
    calls.clear()
    result = CliRunner().invoke(cli, ["gui", "-c", str(config)])
    assert result.exit_code == 0
    assert calls == [((config, ()), {"default_output_dir": tmp_path})]
    help_text = CliRunner().invoke(cli, ["gui", "--help"]).output
    assert all(option in help_text for option in ("--config", "--project", "--output-path"))
    assert "--input-path" not in help_text
    assert "--fetch-values" not in help_text


def test_gui_import_is_lazy():
    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys, nml_tools.gui; "
                "assert 'qtpy' not in sys.modules; "
                "assert 'guidata' not in sys.modules; "
                "assert 'numpy' not in sys.modules"
            ),
        ],
        check=True,
    )
