"""Convert namelist-oriented JSON values to Fortran namelist text."""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Iterable, Mapping
from pathlib import PureWindowsPath
from typing import Any

from ._utils import validate_user_fortran_identifier

__all__ = ["json_to_namelist"]

_WRAPPER_KEYS = {"format_version", "profile", "default_filename", "dimensions"}


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
                _array_layout(value, path)
                lines.extend(_array_assignments(field_name, value, path, ()))
            elif isinstance(value, Mapping):
                lines.extend(_derived_assignments(field_name, value, path))
            else:
                lines.append(f"  {field_name} = {_format_scalar(value, path)}")
        lines.append("/")
        blocks.append("\n".join(lines))

    if not blocks:
        return ""
    return "\n\n".join(blocks) + "\n"


def _profile_namelists(data: Mapping[str, Any], default_profile: str) -> dict[str, str]:
    """Render an aggregate document, or one legacy payload, by output filename."""
    if not isinstance(data, Mapping):
        raise ValueError("JSON root must be an object")

    profiles = data.get("file_profiles")
    if profiles is None:
        name = data.get("profile", default_profile) if "values" in data else default_profile
        if not isinstance(name, str):
            raise ValueError("JSON wrapper 'profile' must be a string")
        _validate_profile_name(name, {})
        filename = data.get("default_filename", f"{name}.nml")
        _validate_output_filename(filename, {})
        return {filename: json_to_namelist(data)}
    if not isinstance(profiles, Mapping) or not profiles:
        raise ValueError("JSON 'file_profiles' must be a non-empty object")

    rendered: dict[str, str] = {}
    seen_profiles: dict[str, str] = {}
    seen_filenames: dict[str, str] = {}
    for profile_name, entry in profiles.items():
        if not isinstance(profile_name, str) or not isinstance(entry, Mapping):
            raise ValueError("file profile entries must be named objects")
        declared = entry.get("profile", profile_name)
        if not isinstance(declared, str) or declared.casefold() != profile_name.casefold():
            raise ValueError(
                f"file profile '{profile_name}' has mismatched 'profile' metadata"
            )
        try:
            _validate_profile_name(declared, seen_profiles)
            filename = entry.get("default_filename", f"{declared}.nml")
            _validate_output_filename(filename, seen_filenames)
            rendered[filename] = json_to_namelist(entry)
        except ValueError as exc:
            raise ValueError(f"file profile '{profile_name}': {exc}") from exc
    return rendered


def _validate_profile_name(name: str, seen: dict[str, str]) -> None:
    if (
        not name
        or name != name.strip()
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or any(unicodedata.category(character) == "Cc" for character in name)
    ):
        raise ValueError(f"file profile name '{name}' is invalid")
    key = name.casefold()
    if key in seen:
        raise ValueError(
            f"file profile name '{name}' collides with '{seen[key]}' case-insensitively"
        )
    seen[key] = name


def _validate_output_filename(name: object, seen: dict[str, str]) -> None:
    if (
        not isinstance(name, str)
        or not name
        or name != name.strip()
        or "\\" in name
        or PureWindowsPath(name).drive
        or any(unicodedata.category(character) == "Cc" for character in name)
    ):
        raise ValueError(f"default filename '{name}' is not a safe relative path")
    parts = name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"default filename '{name}' is not a safe relative path")
    key = name.casefold()
    if key in seen:
        raise ValueError(
            f"default filename '{name}' collides with '{seen[key]}' case-insensitively"
        )
    seen[key] = name


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


def _array_layout(values: list[Any], path: str) -> tuple[tuple[int, ...], str]:
    if not values:
        raise ValueError(f"array '{path}' must not be empty; omit unset fields")

    child_shape: tuple[int, ...] | None = None
    leaf_kind: str | None = None
    for index, value in enumerate(values, start=1):
        if isinstance(value, list):
            shape, kind = _array_layout(value, f"{path}[{index}]")
        else:
            shape = ()
            kind = "object" if isinstance(value, Mapping) else "scalar"
        if child_shape is None:
            child_shape = shape
        elif shape != child_shape:
            raise ValueError(f"array '{path}' must be rectangular with a consistent rank")
        if leaf_kind is None:
            leaf_kind = kind
        elif kind != leaf_kind:
            raise ValueError(f"array '{path}' must not mix scalar and object elements")
    return (len(values), *(child_shape or ())), leaf_kind or "scalar"


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
        designator = f"{field_name}({subscript})"
        if isinstance(value, Mapping):
            yield from _derived_assignments(designator, value, item_path)
        else:
            yield f"  {designator} = {_format_scalar(value, item_path)}"


def _derived_assignments(
    designator: str,
    components: Mapping[str, Any],
    path: str,
) -> Iterable[str]:
    seen_components: dict[str, str] = {}
    for component_name, value in components.items():
        _validate_name(component_name, seen_components, f"component in field '{path}'")
        component_path = f"{path}.{component_name}"
        if value is None or isinstance(value, (list, Mapping)):
            raise ValueError(f"component '{component_path}' must be an intrinsic scalar")
        yield f"  {designator}%{component_name} = {_format_scalar(value, component_path)}"


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
