"""Markdown documentation generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def generate_docs(schema: dict[str, Any], output: str | Path) -> None:
    """Generate Markdown docs for *schema* at *output*."""
    raise NotImplementedError
