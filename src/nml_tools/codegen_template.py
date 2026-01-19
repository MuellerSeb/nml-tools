"""Template namelist generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .codegen_fortran import (
    FieldTypeInfo,
    _collect_dimension_constants,
    _enum_values,
    _field_type_info,
    _format_scalar_default,
    _parse_default_dimensions,
)

_MISSING = object()


def generate_template(
    schemas: Iterable[dict[str, Any]],
    output: str | Path,
    *,
    doc_mode: str = "plain",
    value_mode: str = "empty",
    constants: dict[str, int | float] | None = None,
    kind_map: dict[str, str] | None = None,
    kind_allowlist: set[str] | None = None,
    values: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Generate a template namelist file for *schemas* at *output*."""
    rendered = render_template(
        schemas,
        doc_mode=doc_mode,
        value_mode=value_mode,
        constants=constants,
        kind_map=kind_map,
        kind_allowlist=kind_allowlist,
        values=values,
    )
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="ascii")


def render_template(
    schemas: Iterable[dict[str, Any]],
    *,
    doc_mode: str = "plain",
    value_mode: str = "empty",
    constants: dict[str, int | float] | None = None,
    kind_map: dict[str, str] | None = None,
    kind_allowlist: set[str] | None = None,
    values: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Render a template namelist file for *schemas*."""
    doc_mode = doc_mode.strip().lower()
    value_mode = value_mode.strip().lower()
    if doc_mode not in {"plain", "documented"}:
        raise ValueError("template doc_mode must be 'plain' or 'documented'")
    if value_mode not in {"empty", "filled", "minimal-empty", "minimal-filled"}:
        raise ValueError(
            "template value_mode must be one of: empty, filled, minimal-empty, minimal-filled"
        )

    return _render_template(
        schemas,
        doc_mode=doc_mode,
        value_mode=value_mode,
        constants=constants,
        kind_map=kind_map,
        kind_allowlist=kind_allowlist,
        values=values,
    )


def _render_template(
    schemas: Iterable[dict[str, Any]],
    *,
    doc_mode: str,
    value_mode: str,
    constants: dict[str, int | float] | None,
    kind_map: dict[str, str] | None,
    kind_allowlist: set[str] | None,
    values: dict[str, dict[str, Any]] | None,
) -> str:
    lines: list[str] = []
    schemas_list = list(schemas)
    values_map = values or {}
    if not isinstance(values_map, dict):
        raise ValueError("template values must be a table of namelist tables")

    schema_by_name: dict[str, dict[str, Any]] = {}
    for schema in schemas_list:
        namelist_name = schema.get("x-fortran-namelist")
        if not isinstance(namelist_name, str):
            raise ValueError("schema must define 'x-fortran-namelist'")
        schema_by_name[namelist_name] = schema

    for namelist_name, namelist_values in values_map.items():
        if not isinstance(namelist_name, str):
            raise ValueError("template values namelist names must be strings")
        if namelist_name not in schema_by_name:
            raise ValueError(
                f"template values namelist '{namelist_name}' not found in schemas"
            )
        if not isinstance(namelist_values, dict):
            raise ValueError(
                f"template values for namelist '{namelist_name}' must be a table"
            )
        properties = schema_by_name[namelist_name].get("properties")
        if not isinstance(properties, dict) or not properties:
            raise ValueError("schema must define object 'properties'")
        for key in namelist_values:
            if not isinstance(key, str):
                raise ValueError(
                    f"template values for namelist '{namelist_name}' must use string keys"
                )
            if key not in properties:
                raise ValueError(
                    f"template values for namelist '{namelist_name}' include unknown field '{key}'"
                )

    for schema in schemas_list:
        namelist_name = schema.get("x-fortran-namelist")
        if not isinstance(namelist_name, str):
            raise ValueError("schema must define 'x-fortran-namelist'")
        if schema.get("type") != "object":
            raise ValueError("schema root must be of type 'object'")
        properties = schema.get("properties")
        if not isinstance(properties, dict) or not properties:
            raise ValueError("schema must define object 'properties'")
        override_values = (
            values_map.get(namelist_name, {})
            if value_mode in {"filled", "minimal-filled"}
            else {}
        )

        if doc_mode == "documented":
            title = schema.get("title")
            if isinstance(title, str) and title.strip():
                lines.append(f"! {title.strip()}")

        lines.append(f"&{namelist_name}")

        current_property: str | None = None
        try:
            for name, prop in properties.items():
                current_property = name
                if not isinstance(prop, dict):
                    raise ValueError(f"property '{name}' must be an object")
                type_info = _field_type_info(prop, constants)
                _collect_dimension_constants(type_info.dimensions, constants)
                _validate_kind_allowlist(type_info, kind_map, kind_allowlist)

                has_default = "default" in prop
                has_override = name in override_values
                if value_mode in {"minimal-empty", "minimal-filled"} and has_default:
                    if value_mode == "minimal-filled" and has_override:
                        pass
                    else:
                        continue

                if doc_mode == "documented":
                    title = prop.get("title")
                    if isinstance(title, str) and title.strip():
                        lines.append(f"  ! {title.strip()}")

                entries = _value_entries(
                    name,
                    prop,
                    type_info,
                    value_mode=value_mode,
                    override=override_values.get(name, _MISSING),
                    constants=constants,
                )
                for entry_name, value_text in entries:
                    if value_text is None:
                        lines.append(f"  {entry_name} =")
                    else:
                        lines.append(f"  {entry_name} = {value_text}")
        except ValueError as exc:
            if current_property is None:
                raise
            msg = str(exc)
            if f"property '{current_property}'" in msg:
                raise
            raise ValueError(f"property '{current_property}': {msg}") from exc

        lines.append("/")
        lines.append("")

    if lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def _array_slice(rank: int) -> str:
    return "(" + ", ".join(":" for _ in range(rank)) + ")"


def _value_entries(
    name: str,
    prop: dict[str, Any],
    type_info: FieldTypeInfo,
    *,
    value_mode: str,
    override: Any,
    constants: dict[str, int | float] | None,
) -> list[tuple[str, str | None]]:
    if value_mode in {"empty", "minimal-empty"}:
        entry_name = name
        if type_info.category == "array":
            entry_name = f"{name}{_array_slice(len(type_info.dimensions))}"
        return [(entry_name, None)]

    enum_values = _enum_values(prop, type_info, constants)

    if override is not _MISSING:
        return _entries_from_value(name, override, type_info, prop, constants)

    example_value = _get_first_example(prop, type_info)
    if example_value is not None:
        return _entries_from_value(name, example_value, type_info, prop, constants)

    if "default" in prop:
        default_value = prop["default"]
        if type_info.category == "array":
            if isinstance(default_value, list):
                return _array_list_entries(name, default_value, type_info, prop, constants)
            scalar = _format_scalar_default(
                default_value,
                None,
                type_info.element_category,
            )
            entry_name = f"{name}{_array_slice(len(type_info.dimensions))}"
            return [(entry_name, scalar)]
        scalar = _format_scalar_default(default_value, None, type_info.category)
        return [(name, scalar)]

    if enum_values:
        return _entries_from_value(name, enum_values[0], type_info, prop, constants)

    if type_info.category == "array":
        scalar = _format_scalar_default(
            _fallback_scalar_value(type_info),
            None,
            type_info.element_category,
        )
        entry_name = f"{name}{_array_slice(len(type_info.dimensions))}"
        return [(entry_name, scalar)]

    scalar = _format_scalar_default(
        _fallback_scalar_value(type_info),
        None,
        type_info.category,
    )
    return [(name, scalar)]


def _array_list_entries(
    name: str,
    values: list[Any],
    type_info: FieldTypeInfo,
    prop: dict[str, Any],
    constants: dict[str, int | float] | None,
) -> list[tuple[str, str | None]]:
    rank = len(type_info.dimensions)
    if rank <= 1:
        entry_name = f"{name}{_array_slice(rank)}"
        return [(entry_name, _format_value_list(values, type_info))]

    dims = _parse_default_dimensions(type_info.dimensions, constants)
    order = _resolve_default_order(prop)
    slice_dim = _slice_dim_for_order(rank, order)
    slice_size = dims[slice_dim]
    fixed_dims = [dims[idx] for idx in range(rank) if idx != slice_dim]
    entries: list[tuple[str, str | None]] = []
    offset = 0
    for fixed_indices in _iter_fixed_indices(fixed_dims, order):
        if offset >= len(values):
            break
        chunk = values[offset : offset + slice_size]
        if not chunk:
            break
        entry_name = _slice_entry_name(
            name,
            rank,
            slice_dim,
            [index + 1 for index in fixed_indices],
        )
        entries.append((entry_name, _format_value_list(chunk, type_info)))
        offset += slice_size
    if not entries:
        entry_name = f"{name}{_array_slice(rank)}"
        entries.append((entry_name, _format_value_list(values, type_info)))
    return entries


def _slice_dim_for_order(rank: int, order: str) -> int:
    if order == "F":
        return 0
    return rank - 1


def _iter_fixed_indices(dims: list[int], order: str) -> Iterable[list[int]]:
    if not dims:
        yield []
        return
    indices = [0] * len(dims)
    while True:
        yield indices.copy()
        positions = range(len(dims)) if order == "F" else range(len(dims) - 1, -1, -1)
        for pos in positions:
            indices[pos] += 1
            if indices[pos] < dims[pos]:
                break
            indices[pos] = 0
        else:
            break


def _slice_entry_name(
    name: str,
    rank: int,
    slice_dim: int,
    fixed_indices: list[int],
) -> str:
    indices: list[str] = []
    fixed_iter = iter(fixed_indices)
    for idx in range(rank):
        if idx == slice_dim:
            indices.append(":")
        else:
            indices.append(str(next(fixed_iter)))
    return f"{name}({', '.join(indices)})"


def _format_value_list(values: list[Any], type_info: FieldTypeInfo) -> str:
    formatted = [
        _format_scalar_default(value, None, type_info.element_category)
        for value in values
    ]
    return ", ".join(formatted)


def _entries_from_value(
    name: str,
    value: Any,
    type_info: FieldTypeInfo,
    prop: dict[str, Any],
    constants: dict[str, int | float] | None,
) -> list[tuple[str, str | None]]:
    if type_info.category == "array":
        if isinstance(value, list):
            _validate_example_list(value)
            return _array_list_entries(name, value, type_info, prop, constants)
        scalar = _format_scalar_default(value, None, type_info.element_category)
        entry_name = f"{name}{_array_slice(len(type_info.dimensions))}"
        return [(entry_name, scalar)]
    if isinstance(value, list):
        raise ValueError("scalar template values must not be lists")
    scalar = _format_scalar_default(value, None, type_info.category)
    return [(name, scalar)]


def _get_first_example(prop: dict[str, Any], type_info: FieldTypeInfo) -> Any | None:
    examples = prop.get("examples")
    if examples is None:
        return None
    if not isinstance(examples, list):
        raise ValueError("property examples must be a list")
    if not examples:
        return None
    first = examples[0]
    if type_info.category == "array":
        if isinstance(first, list):
            _validate_example_list(first)
        return first
    if isinstance(first, list):
        raise ValueError("scalar examples must not be lists")
    return first


def _validate_example_list(values: list[Any]) -> None:
    for value in values:
        if isinstance(value, list):
            raise ValueError("array examples must be flat lists")


def _fallback_scalar_value(type_info: FieldTypeInfo) -> Any:
    category = type_info.element_category if type_info.category == "array" else type_info.category
    if category == "integer":
        return 0
    if category == "real":
        return 0.0
    if category == "boolean":
        return False
    if category == "string":
        return ""
    raise ValueError(f"unsupported template category '{category}'")


def _validate_kind_allowlist(
    type_info: FieldTypeInfo,
    kind_map: dict[str, str] | None,
    allowlist: set[str] | None,
) -> None:
    if type_info.kind is None or allowlist is None:
        return
    kind_id = type_info.kind
    mapped = None
    if kind_map is not None and kind_id in kind_map:
        mapped = kind_map[kind_id]
        if not isinstance(mapped, str) or not mapped:
            raise ValueError(f"kind map target for '{kind_id}' must be a string")
        if mapped not in allowlist:
            raise ValueError(
                f"kind map target '{mapped}' for '{kind_id}' not present in kind module list"
            )
        return
    if kind_id not in allowlist:
        raise ValueError(f"kind '{kind_id}' not present in kind module list")


def _resolve_default_order(prop: dict[str, Any]) -> str:
    order_raw = prop.get("x-fortran-default-order", "F")
    if not isinstance(order_raw, str):
        raise ValueError("array default order must be 'F' or 'C'")
    order = order_raw.upper()
    if order not in {"F", "C"}:
        raise ValueError("array default order must be 'F' or 'C'")
    return order
