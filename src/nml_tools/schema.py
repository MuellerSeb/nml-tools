"""Schema loading utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def load_schema(path: str | Path) -> dict[str, Any]:
    """Load a schema definition from *path*.

    Parameters
    ----------
    path:
        Location of the schema file.
    """
    raise NotImplementedError
