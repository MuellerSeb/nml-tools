"""Regenerate checked-in files for the pybind example."""

from __future__ import annotations

from pathlib import Path

from nml_tools.cli import main

ROOT = Path(__file__).resolve().parents[1]

raise SystemExit(main(["generate", "--config", str(ROOT / "nml-config.toml")]))
