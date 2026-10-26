"""Optional Qt namelist editor; Qt is imported only when launching the GUI."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from .model import GuiProjectRequest

__all__ = ["GuiProjectRequest", "launch_gui"]


def launch_gui(
    schemas_dir: Path | str | None = None,
    projects: Sequence[GuiProjectRequest] = (),
    *,
    default_output_dir: Path | str | None = None,
) -> int:
    """Edit zero or more independently configured projects.

    With no project requests, configured projects remain available in the GUI
    without being preloaded. The default output directory is used for projects
    added interactively and otherwise defaults to ``schemas_dir``.
    """
    from .app import launch_gui as _launch_gui

    return _launch_gui(schemas_dir, projects, default_output_dir=default_output_dir)
