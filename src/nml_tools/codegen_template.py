"""Template namelist generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def generate_template(schema: dict[str, Any], output: str | Path) -> None:
    """Generate a template namelist for *schema* at *output*."""
    raise NotImplementedError
