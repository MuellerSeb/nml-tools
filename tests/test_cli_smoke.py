"""Smoke tests for the command line interface."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_cli_help_shows_subcommands() -> None:
    root = Path(__file__).resolve().parents[1] / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{root}{os.pathsep}{env.get('PYTHONPATH', '')}"
    result = subprocess.run(
        [sys.executable, "-m", "nml_tools.cli", "--help"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    stdout = result.stdout
    for sub in ["generate", "gen-fortran", "gen-markdown", "gen-template"]:
        assert sub in stdout
