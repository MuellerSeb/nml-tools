"""Fortran code generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def generate_fortran(schema: dict[str, Any], output: str | Path) -> None:
    """Generate a Fortran module from *schema* at *output*."""
    raise NotImplementedError
