"""Optional Qt namelist editor; Qt is imported only when launching the GUI."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

__all__ = ["launch_gui"]


def launch_gui(
    schemas_dir: Path | str | None = None,
    output_dir: Path | str | None = None,
    file_profiles: Mapping[str, list[str]] | None = None,
    initial_values: Mapping[str, Any] | None = None,
    initial_dimensions: Mapping[str, int] | None = None,
) -> int:
    """Edit selected profiles; empty lists select all namelists in that profile.

    None or an empty mapping selects all configured profiles. Values are nested
    by profile, namelist, and field, and override existing namelist input.
    Dimensions override TOML defaults. Output defaults to schemas_dir.
    """
    from .app import launch_gui as _launch_gui

    return _launch_gui(schemas_dir, output_dir, file_profiles, initial_values, initial_dimensions)
