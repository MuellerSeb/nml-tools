"""Smoke tests for the command line interface."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def test_cli_help_shows_subcommands() -> None:
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PATH"] = f"{root}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        ["nml-tools", "--help"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    stdout = result.stdout
    for sub in ["validate", "gen-fortran", "gen-docs", "gen-template"]:
        assert sub in stdout
