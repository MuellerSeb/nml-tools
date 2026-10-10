# mypy: disable-error-code="import-not-found, no-untyped-call"
"""Designer resource loading shared by GUI components."""

from importlib.resources import files
from typing import Any

from qtpy import uic


def load_ui(name: str, widget: Any) -> Any:
    """Populate *widget* from a packaged Qt Designer file."""
    return uic.loadUi(str(files(__package__).joinpath(name)), widget)
