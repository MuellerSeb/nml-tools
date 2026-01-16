"""Template namelist generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .codegen_fortran import (
    FieldTypeInfo,
    _collect_dimension_constants,
    _field_type_info,
    _format_scalar_default,
    _parse_default_dimensions,
)


def generate_template(
    schemas: Iterable[dict[str, Any]],
    output: str | Path,
    *,
    doc_mode: str = "plain",
    value_mode: str = "empty",
    constants: dict[str, int | float] | None = None,
    kind_map: dict[str, str] | None = None,
    kind_allowlist: set[str] | None = None,
) -> None:
    """Generate a template namelist file for *schemas* at *output*."""
    doc_mode = doc_mode.strip().lower()
    value_mode = value_mode.strip().lower()
    if doc_mode not in {"plain", "documented"}:
        raise ValueError("template doc_mode must be 'plain' or 'documented'")
    if value_mode not in {"empty", "filled", "minimal-empty", "minimal-filled"}:
        raise ValueError(
            "template value_mode must be one of: empty, filled, minimal-empty, minimal-filled"
        )

    rendered = _render_template(
        schemas,
        doc_mode=doc_mode,
        value_mode=value_mode,
        constants=constants,
        kind_map=kind_map,
        kind_allowlist=kind_allowlist,
    )
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="ascii")


def _render_template(
    schemas: Iterable[dict[str, Any]],
    *,
    doc_mode: str,
    value_mode: str,
    constants: dict[str, int | float] | None,
    kind_map: dict[str, str] | None,
    kind_allowlist: set[str] | None,
) -> str:
    lines: list[str] = []
    for schema in schemas:
        namelist_name = schema.get("x-fortran-namelist")
        if not isinstance(namelist_name, str):
            raise ValueError("schema must define 'x-fortran-namelist'")
        if schema.get("type") != "object":
            raise ValueError("schema root must be of type 'object'")
        properties = schema.get("properties")
        if not isinstance(properties, dict) or not properties:
            raise ValueError("schema must define object 'properties'")

        if doc_mode == "documented":
            title = schema.get("title")
            if isinstance(title, str) and title.strip():
                lines.append(f"! {title.strip()}")

        lines.append(f"&{namelist_name}")

        for name, prop in properties.items():
            if not isinstance(prop, dict):
                raise ValueError(f"property '{name}' must be an object")
            type_info = _field_type_info(prop, constants)
            _collect_dimension_constants(type_info.dimensions, constants)
            _validate_kind_allowlist(type_info, kind_map, kind_allowlist)

            has_default = "default" in prop
            if value_mode in {"minimal-empty", "minimal-filled"} and has_default:
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
                constants=constants,
            )
            for entry_name, value_text in entries:
                if value_text is None:
                    lines.append(f"  {entry_name} =")
                else:
                    lines.append(f"  {entry_name} = {value_text}")

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
    constants: dict[str, int | float] | None,
) -> list[tuple[str, str | None]]:
    if value_mode in {"empty", "minimal-empty"}:
        entry_name = name
        if type_info.category == "array":
            entry_name = f"{name}{_array_slice(len(type_info.dimensions))}"
        return [(entry_name, None)]

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
) -> list[tuple[str, str]]:
    rank = len(type_info.dimensions)
    if rank <= 1:
        entry_name = f"{name}{_array_slice(rank)}"
        return [(entry_name, _format_value_list(values, type_info))]

    dims = _parse_default_dimensions(type_info.dimensions, constants)
    order = _resolve_default_order(prop)
    row_values = _values_for_row_slices(values, dims, order)
    chunk_size = _product(dims[1:])
    entries: list[tuple[str, str]] = []
    offset = 0
    for row_index in range(1, dims[0] + 1):
        if offset >= len(row_values):
            break
        chunk = row_values[offset : offset + chunk_size]
        if not chunk:
            break
        entry_name = _row_slice_name(name, rank, row_index)
        entries.append((entry_name, _format_value_list(chunk, type_info)))
        offset += chunk_size
    if not entries:
        entry_name = f"{name}{_array_slice(rank)}"
        entries.append((entry_name, _format_value_list(row_values, type_info)))
    return entries


def _row_slice_name(name: str, rank: int, row_index: int) -> str:
    slices = [str(row_index)] + [":" for _ in range(rank - 1)]
    return f"{name}({', '.join(slices)})"


def _format_value_list(values: list[Any], type_info: FieldTypeInfo) -> str:
    formatted = [
        _format_scalar_default(value, None, type_info.element_category)
        for value in values
    ]
    return ", ".join(formatted)


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


def _values_for_row_slices(values: list[Any], dims: list[int], order: str) -> list[Any]:
    total = _product(dims)
    if len(values) != total:
        return values
    if order == "C":
        return values
    return _reorder_fortran_to_c(values, dims)


def _reorder_fortran_to_c(values: list[Any], dims: list[int]) -> list[Any]:
    rank = len(dims)
    c_strides = [1] * rank
    for idx in range(rank - 2, -1, -1):
        c_strides[idx] = c_strides[idx + 1] * dims[idx + 1]

    f_strides = [1] * rank
    for idx in range(1, rank):
        f_strides[idx] = f_strides[idx - 1] * dims[idx - 1]

    indexed: list[tuple[int, Any]] = []
    for f_index, value in enumerate(values):
        remainder = f_index
        indices = [0] * rank
        for idx in range(rank):
            stride = f_strides[idx]
            indices[idx] = remainder // stride
            remainder = remainder % stride
        c_index = sum(indices[idx] * c_strides[idx] for idx in range(rank))
        indexed.append((c_index, value))

    indexed.sort(key=lambda item: item[0])
    return [value for _, value in indexed]


def _product(values: list[int]) -> int:
    total = 1
    for value in values:
        total *= value
    return total
