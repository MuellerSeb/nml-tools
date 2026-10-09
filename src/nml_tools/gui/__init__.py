"""Optional Qt namelist editor; Qt is imported only when launching the GUI."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

__all__ = ["launch_gui"]


def launch_gui(
    schemas_dir: Path | str | None = None,
    output_dir: Path | str | None = None,
    project_profiles: str
    | Mapping[str, Mapping[str, list[str]]]
    | Mapping[str, list[str]]
    | None = None,
    initial_values: Mapping[str, Any] | None = None,
    initial_dimensions: Mapping[str, int] | None = None,
) -> int:
    """Edit selected projects; nested mappings select their files/namelists.

    A project-profile name selects it from TOML. None selects all projects. The
    legacy flat file-profile mapping is still accepted. Values remain keyed by
    file profile and override existing namelist input. Output defaults to
    schemas_dir.
    """
    from .app import launch_gui as _launch_gui

    return _launch_gui(
        schemas_dir, output_dir, project_profiles, initial_values, initial_dimensions
    )
