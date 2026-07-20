"""Optional Qt user interface for nml-tools.

Importing this package does not import Qt, guidata, or NumPy.  Those optional
dependencies are loaded only when :func:`launch_gui` is called.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["launch_gui"]


def launch_gui(project_dir: Path | str | None = None) -> int:
    """Open the schema-driven editor for *project_dir* (the CWD by default)."""
    from .app import launch_gui as _launch_gui

    return _launch_gui(project_dir)
