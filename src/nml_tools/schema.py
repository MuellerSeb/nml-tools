"""Schema loading utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


def load_schema(path: str | Path) -> dict[str, Any]:
    """Load a schema definition from *path*.

    Parameters
    ----------
    path:
        Location of the schema file.
    """
    schema_path = Path(path)
    if not schema_path.exists():
        raise FileNotFoundError(schema_path)

    suffix = schema_path.suffix.lower()
    if suffix == ".json":
        data = json.loads(schema_path.read_text(encoding="utf-8"))
    elif suffix in {".yml", ".yaml"}:
        data = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    else:
        raise ValueError("schema must be a .json, .yml, or .yaml file")

    if not isinstance(data, dict):
        raise ValueError("schema root must be an object")

    return data
