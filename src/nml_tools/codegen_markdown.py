"""Markdown documentation generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .codegen_fortran import FieldTypeInfo, _field_type_info, _format_default


def generate_docs(schema: dict[str, Any], output: str | Path) -> None:
    """Generate Markdown docs for *schema* at *output*."""
    namelist_name = schema.get("x-fortran-namelist")
    if not isinstance(namelist_name, str):
        raise ValueError("schema must define 'x-fortran-namelist'")

    if schema.get("type") != "object":
        raise ValueError("schema root must be of type 'object'")

    properties = schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        raise ValueError("schema must define object 'properties'")

    title = schema.get("title", namelist_name)
    if not isinstance(title, str):
        raise ValueError("schema title must be a string")
    description = schema.get("description")
    if description is not None and not isinstance(description, str):
        raise ValueError("schema description must be a string")

    required_raw = schema.get("required", [])
    if required_raw is None:
        required_raw = []
    if not isinstance(required_raw, list):
        raise ValueError("schema 'required' must be a list")
    required_set = _validate_required(required_raw)

    lines = [f"# {title}", ""]
    if description:
        lines.append(description)
        lines.append("")
    lines.append(f"**Namelist**: `{namelist_name}`")
    lines.append("")
    lines.append("## Fields")
    lines.append("")

    header = ["Name", "Type", "Required", "Info"]
    lines.append(f"| {' | '.join(header)} |")
    lines.append(f"| {' | '.join('---' for _ in header)} |")

    for name, prop in properties.items():
        if not isinstance(prop, dict):
            raise ValueError(f"property '{name}' must be an object")
        type_info = _field_type_info(prop)
        type_label = _format_table_type(type_info)
        info_label = _format_info(prop)
        required_label = "yes" if name in required_set else "no"
        row = [
            f"`{name}`",
            type_label,
            required_label,
            info_label,
        ]
        lines.append(f"| {' | '.join(_escape_table_cell(cell) for cell in row)} |")

    lines.append("")

    lines.append("## Field details")
    lines.append("")

    for name, prop in properties.items():
        if not isinstance(prop, dict):
            raise ValueError(f"property '{name}' must be an object")
        type_info = _field_type_info(prop)
        required_label = "yes" if name in required_set else "no"
        default_label = _get_default_value(prop, type_info)
        enum_label = _get_enum_values(prop, type_info)
        title = _get_title(prop)
        description_text = _get_description(prop)

        if title:
            lines.append(f"### `{name}` - {title}")
        else:
            lines.append(f"### `{name}`")
        lines.append("")
        if description_text:
            lines.append(description_text)
            lines.append("")

        lines.append(f"- Type: `{_format_specific_type(type_info)}`")
        lines.append(f"- Required: {required_label}")
        if default_label is not None:
            lines.append(f"- Default: `{default_label}`")
        if enum_label is not None:
            lines.append(f"- Allowed values: {enum_label}")
        lines.append("")

    rendered = "\n".join(lines) + "\n"
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="ascii")


def _validate_required(values: list[Any]) -> set[str]:
    required: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise ValueError("schema 'required' entries must be strings")
        required.add(value)
    return required


def _format_table_type(type_info: FieldTypeInfo) -> str:
    if type_info.category == "array":
        element = _format_scalar_type_name(type_info.element_category)
        return f"{element} array"
    return _format_scalar_type_name(type_info.category)


def _format_scalar_type_name(category: str | None) -> str:
    if category == "boolean":
        return "logical"
    if category == "string":
        return "string"
    if category == "integer":
        return "integer"
    if category == "real":
        return "real"
    raise ValueError(f"unsupported type category '{category}'")


def _format_specific_type(type_info: FieldTypeInfo) -> str:
    if type_info.category != "array":
        return type_info.type_spec
    dimensions = ", ".join(type_info.dimensions)
    return f"{type_info.type_spec}, dimension({dimensions})"


def _get_default_value(prop: dict[str, Any], type_info: FieldTypeInfo) -> str | None:
    if "default" not in prop:
        return None
    return _format_default(prop["default"], type_info, prop)


def _format_info(prop: dict[str, Any]) -> str:
    title = _get_title(prop)
    return title or "n/a"


def _get_title(prop: dict[str, Any]) -> str | None:
    title = prop.get("title")
    if title is None:
        return None
    if not isinstance(title, str):
        raise ValueError("property title must be a string")
    title = title.strip()
    return title or None


def _get_description(prop: dict[str, Any]) -> str | None:
    description = prop.get("description")
    if description is None:
        return None
    if not isinstance(description, str):
        raise ValueError("property description must be a string")
    description = description.strip()
    return description or None


def _get_enum_values(prop: dict[str, Any], type_info: FieldTypeInfo) -> str | None:
    enum = prop.get("enum")
    if enum is None:
        return None
    if not isinstance(enum, list) or not enum:
        raise ValueError("property enum must be a non-empty list")
    values = [_format_default(value, type_info, prop) for value in enum]
    return ", ".join(f"`{value}`" for value in values)


def _escape_table_cell(value: str) -> str:
    escaped = value.replace("|", "\\|").replace("\n", " ").strip()
    return escaped or "n/a"
