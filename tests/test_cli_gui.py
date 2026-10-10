"""GUI CLI wiring without starting a Qt event loop."""

import subprocess
import sys

from click.testing import CliRunner

import nml_tools.gui
from nml_tools.cli import cli


def test_gui_command_paths_and_help(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(nml_tools.gui, "launch_gui", lambda *args: calls.append(args) or 0)
    result = CliRunner().invoke(cli, ["gui", "-i", str(tmp_path), "-o", str(tmp_path / "out")])
    assert result.exit_code == 0
    assert calls == [(tmp_path, tmp_path / "out")]
    help_text = CliRunner().invoke(cli, ["gui", "--help"]).output
    assert "--input-path" in help_text and "--output-path" in help_text
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
