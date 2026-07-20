"""Optional Qt user interface for nml-tools.

Importing this package does not import Qt, guidata, or NumPy.  Those optional
dependencies are loaded only when :func:`launch_gui` is called.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

__all__ = ["launch_gui"]


def launch_gui(
    project_dir: Path | str | None = None,
    initial_values: Mapping[str, Any] | None = None,
) -> int:
    """Open the editor for *project_dir* with optional profile values."""
    from .app import launch_gui as _launch_gui

    return _launch_gui(project_dir, initial_values)
