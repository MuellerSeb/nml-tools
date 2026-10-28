# mypy: disable-error-code="import-not-found, no-untyped-call"
"""Designer resource loading shared by GUI components."""

from importlib.resources import path
from typing import Any

from qtpy import uic


def load_ui(name: str, widget: Any) -> Any:
    """Populate *widget* from a packaged Qt Designer file."""
    with path(__package__, name) as ui_path:
        return uic.loadUi(str(ui_path), widget)
