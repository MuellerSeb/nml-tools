# mypy: disable-error-code="attr-defined, import-not-found, misc"
"""Launch the project-oriented Qt namelist editor."""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from threading import current_thread, main_thread

from qtpy.QtCore import QThread
from qtpy.QtWidgets import QApplication

from .dialog import AppDialog
from .fields import _exec
from .model import GuiProject, GuiProjectRequest, find_config_path, load_project


def launch_gui(
    config_path: Path | str | None = None,
    projects: Sequence[GuiProjectRequest] = (),
    *,
    default_output_dir: Path | str | None = None,
) -> int:
    """Launch independently or reuse the caller's QApplication."""
    requests = tuple(projects)
    selections: dict[str, dict[str, list[str]]] = {}
    output_dirs: dict[str, Path | str] = {}
    seen: set[str] = set()
    for request in requests:
        if not isinstance(request, GuiProjectRequest):
            raise ValueError("projects must contain GuiProjectRequest objects")
        if not isinstance(request.project_profile, str):
            raise ValueError("project_profile must be a string")
        name = request.project_profile.strip()
        key = name.lower()
        if not name:
            raise ValueError("project_profile must not be empty")
        if key in seen:
            raise ValueError(f"duplicate project profile '{name}'")
        if not isinstance(request.output_dir, (str, Path)):
            raise ValueError("project output_dir must be a directory path")
        selected: dict[str, list[str]] = {}
        if request.file_profiles is not None:
            if not isinstance(request.file_profiles, Mapping):
                raise ValueError("file_profiles must map profile names to namelist names")
            for profile, namelists in request.file_profiles.items():
                if (
                    not isinstance(profile, str)
                    or isinstance(namelists, (str, bytes))
                    or not isinstance(namelists, Sequence)
                ):
                    raise ValueError("file_profiles must map profile names to namelist names")
                selected[profile] = list(namelists)
        selections[name] = selected
        output_dirs[name] = request.output_dir
        seen.add(key)
    output_root = Path(default_output_dir or Path.cwd()).resolve()
    source: Path | str | None = config_path
    if source is not None and Path(source).name not in {
        "nml-config.toml",
        "pyproject.toml",
    }:
        raise ValueError("config must be nml-config.toml or pyproject.toml")
    if source is None:
        try:
            source = find_config_path(Path.cwd())
        except RuntimeError:
            if requests:
                raise ValueError("a config file is required when loading a project") from None
    project = (
        load_project(
            source,
            output_dirs if requests else output_root,
            selections if requests else None,
        )
        if source is not None
        else GuiProject(Path.cwd(), {}, {}, (), output_root)
    )
    if requests and default_output_dir is not None:
        project = replace(project, output_dir=Path(default_output_dir).resolve())
    application = QApplication.instance()
    owns_application = application is None
    if application is None:
        if current_thread() is not main_thread():
            raise RuntimeError("launch_gui must be called from the main GUI thread")
        application = QApplication(sys.argv[:1])
        application.setApplicationName("nml-tools")
    elif QThread.currentThread() != application.thread():
        raise RuntimeError("launch_gui must be called from the Qt application thread")
    dialog = AppDialog(project, project_requests=requests)
    if not owns_application:
        _exec(dialog)
        return 0
    dialog.show()
    method = getattr(application, "exec", None) or application.exec_
    return int(method())
