"""Convert namelist-oriented JSON values to Fortran namelist text."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

from ._utils import validate_user_fortran_identifier

__all__ = ["json_to_namelist"]

_WRAPPER_KEYS = {"format_version", "profile", "dimensions"}


def json_to_namelist(data: Mapping[str, Any]) -> str:
    """Render namelist-oriented JSON *data* as Fortran namelist text."""
    if not isinstance(data, Mapping):
        raise ValueError("JSON root must be an object")

    values = _unwrap_values(data)
    blocks: list[str] = []
    seen_namelists: dict[str, str] = {}

    for namelist_name, fields in values.items():
        _validate_name(namelist_name, seen_namelists, "namelist")
        if not isinstance(fields, Mapping):
            raise ValueError(f"namelist '{namelist_name}' must be an object")

        lines = [f"&{namelist_name}"]
        seen_fields: dict[str, str] = {}
        for field_name, value in fields.items():
            _validate_name(field_name, seen_fields, f"field in namelist '{namelist_name}'")
            path = f"{namelist_name}.{field_name}"
            if isinstance(value, list):
                _array_shape(value, path)
                lines.extend(_array_assignments(field_name, value, path, ()))
            else:
                lines.append(f"  {field_name} = {_format_scalar(value, path)}")
        lines.append("/")
        blocks.append("\n".join(lines))

    if not blocks:
        return ""
    return "\n\n".join(blocks) + "\n"


def _unwrap_values(data: Mapping[str, Any]) -> Mapping[str, Any]:
    if "values" not in data:
        return data

    candidate = data["values"]
    has_wrapper_metadata = any(key in data for key in _WRAPPER_KEYS)
    is_values_only_wrapper = (
        len(data) == 1
        and isinstance(candidate, Mapping)
        and all(isinstance(value, Mapping) for value in candidate.values())
    )
    if not has_wrapper_metadata and not is_values_only_wrapper:
        return data
    if not isinstance(candidate, Mapping):
        raise ValueError("JSON wrapper 'values' must be an object")
    return candidate


def _validate_name(name: object, seen: dict[str, str], label: str) -> None:
    if not isinstance(name, str):
        raise ValueError(f"{label} names must be strings")
    validate_user_fortran_identifier(name, label=f"{label} name '{name}'")
    key = name.lower()
    if key in seen:
        raise ValueError(f"{label} name '{name}' duplicates '{seen[key]}' case-insensitively")
    seen[key] = name


def _array_shape(values: list[Any], path: str) -> tuple[int, ...]:
    if not values:
        raise ValueError(f"array '{path}' must not be empty; omit unset fields")

    child_shape: tuple[int, ...] | None = None
    for index, value in enumerate(values, start=1):
        shape = _array_shape(value, f"{path}[{index}]") if isinstance(value, list) else ()
        if child_shape is None:
            child_shape = shape
        elif shape != child_shape:
            raise ValueError(f"array '{path}' must be rectangular with a consistent rank")
    return (len(values), *(child_shape or ()))


def _array_assignments(
    field_name: str,
    values: list[Any],
    path: str,
    indices: tuple[int, ...],
) -> Iterable[str]:
    for index, value in enumerate(values, start=1):
        item_indices = (*indices, index)
        item_path = f"{path}[{index}]"
        if isinstance(value, list):
            yield from _array_assignments(field_name, value, item_path, item_indices)
            continue
        subscript = ",".join(str(item) for item in item_indices)
        yield f"  {field_name}({subscript}) = {_format_scalar(value, item_path)}"


def _format_scalar(value: Any, path: str) -> str:
    if isinstance(value, bool):
        return ".true." if value else ".false."
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"value '{path}' must be a finite number")
        return repr(value).replace("E", "e")
    if isinstance(value, str):
        if "\n" in value or "\r" in value:
            raise ValueError(f"string value '{path}' must not contain newlines")
        escaped = value.replace('"', '""')
        return f'"{escaped}"'
    if value is None:
        raise ValueError(f"value '{path}' must not be null; omit unset fields")
    if isinstance(value, Mapping):
        raise ValueError(f"value '{path}' must be a scalar or array, not an object")
    raise ValueError(f"value '{path}' has unsupported JSON type '{type(value).__name__}'")
