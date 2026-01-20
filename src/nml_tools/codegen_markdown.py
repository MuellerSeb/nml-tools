"""Markdown documentation generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .codegen_fortran import (
    FieldTypeInfo,
    _collect_dimension_constants,
    _enum_category,
    _enum_values,
    _field_type_info,
    _format_scalar_default,
    _parse_default_dimensions,
    _prepare_array_default,
)
from .codegen_template import render_template


def generate_docs(
    schema: dict[str, Any],
    output: str | Path,
    *,
    constants: dict[str, int | float] | None = None,
) -> None:
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

    current_property: str | None = None
    try:
        for name, prop in properties.items():
            current_property = name
            if not isinstance(prop, dict):
                raise ValueError(f"property '{name}' must be an object")
            type_info = _field_type_info(prop, constants)
            _collect_dimension_constants(type_info.dimensions, constants)
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
    except ValueError as exc:
        if current_property is None:
            raise
        msg = str(exc)
        if f"property '{current_property}'" in msg:
            raise
        raise ValueError(f"property '{current_property}': {msg}") from exc

    lines.append("")

    lines.append("## Field details")
    lines.append("")

    current_property = None
    try:
        for name, prop in properties.items():
            current_property = name
            if not isinstance(prop, dict):
                raise ValueError(f"property '{name}' must be an object")
            type_info = _field_type_info(prop, constants)
            required_label = "yes" if name in required_set else "no"
            default_label = _get_default_value(prop, type_info, constants)
            enum_label = _get_enum_values(prop, type_info, constants)
            example_values = _get_example_values(prop, type_info)
            flex_tail_dims = _get_flex_tail_dims(prop, type_info)
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

            lines.append("Summary:")
            lines.append(f"- Type: `{_format_specific_type(type_info)}`")
            if type_info.category == "array" and flex_tail_dims > 0:
                lines.append(f"- Flexible tail dims: {flex_tail_dims}")
            lines.append(f"- Required: {required_label}")
            if default_label is not None:
                if isinstance(default_label, tuple):
                    base, note = default_label
                    if note:
                        lines.append(f"- Default: `{base}` {note}")
                    else:
                        lines.append(f"- Default: `{base}`")
                else:
                    lines.append(f"- Default: `{default_label}`")
            if enum_label is not None:
                lines.append(f"- Allowed values: {enum_label}")
            if example_values is not None:
                examples_text = ", ".join(f"`{value}`" for value in example_values)
                lines.append(f"- Examples: {examples_text}")
            lines.append("")
    except ValueError as exc:
        if current_property is None:
            raise
        msg = str(exc)
        if f"property '{current_property}'" in msg:
            raise
        raise ValueError(f"property '{current_property}': {msg}") from exc

    lines.append("## Example")
    lines.append("")
    lines.append("```fortran")
    filled_template = render_template(
        [schema],
        doc_mode="plain",
        value_mode="filled",
        constants=constants,
        kind_map=None,
        kind_allowlist=None,
    )
    lines.extend(filled_template.rstrip("\n").splitlines())
    lines.append("```")
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


def _get_default_value(
    prop: dict[str, Any],
    type_info: FieldTypeInfo,
    constants: dict[str, int | float] | None,
) -> str | tuple[str, str | None] | None:
    if "default" not in prop:
        return None
    if type_info.category == "array":
        return _format_array_default_display(prop, type_info, constants)
    return _format_default_plain(prop["default"], type_info, prop, constants)


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


def _get_enum_values(
    prop: dict[str, Any],
    type_info: FieldTypeInfo,
    constants: dict[str, int | float] | None,
) -> str | None:
    enum_values = _enum_values(prop, type_info, constants)
    if enum_values is None:
        return None
    category = _enum_category(type_info)
    values = [_format_scalar_default(value, None, category) for value in enum_values]
    return ", ".join(f"`{value}`" for value in values)


def _get_flex_tail_dims(
    prop: dict[str, Any],
    type_info: FieldTypeInfo,
) -> int:
    flex_raw = prop.get("x-fortran-flex-tail-dims")
    if flex_raw is None:
        flex_value = 0
    else:
        if isinstance(flex_raw, bool) or not isinstance(flex_raw, int):
            raise ValueError("property flex tail dims must be an integer")
        flex_value = flex_raw
    if flex_value < 0:
        raise ValueError("property flex tail dims must be >= 0")
    if flex_value == 0:
        return 0
    if type_info.category != "array":
        raise ValueError("flex tail dims only apply to arrays")
    if flex_value > len(type_info.dimensions):
        raise ValueError("flex tail dims must not exceed array rank")
    return flex_value


def _escape_table_cell(value: str) -> str:
    escaped = value.replace("|", "\\|").replace("\n", " ").strip()
    return escaped or "n/a"


def _get_example_values(
    prop: dict[str, Any],
    type_info: FieldTypeInfo,
) -> list[str] | None:
    examples = prop.get("examples")
    if examples is None:
        return None
    if not isinstance(examples, list):
        raise ValueError("property examples must be a list")
    if not examples:
        return None
    return [_format_example_value(value, type_info) for value in examples]


def _format_example_value(value: Any, type_info: FieldTypeInfo) -> str:
    if type_info.category == "array":
        if isinstance(value, list):
            formatted = [
                _format_scalar_default(item, None, type_info.element_category) for item in value
            ]
            return f"[{', '.join(formatted)}]"
        return _format_scalar_default(value, None, type_info.element_category)
    if isinstance(value, list):
        raise ValueError("scalar examples must not be lists")
    return _format_scalar_default(value, None, type_info.category)


def _format_default_plain(
    value: Any,
    type_info: FieldTypeInfo,
    prop: dict[str, Any],
    constants: dict[str, int | float] | None,
) -> str:
    if type_info.category == "array":
        if not isinstance(value, list):
            value = [value]
        parsed_dims = _parse_default_dimensions(type_info.dimensions, constants)
        array_default = _prepare_array_default(value, parsed_dims, prop)
        elements = [
            _format_scalar_default(element, None, type_info.element_category)
            for element in array_default.source_values
        ]
        if (
            len(type_info.dimensions) == 1
            and array_default.order_values is None
            and array_default.pad_values is None
        ):
            return f"[{', '.join(elements)}]"

        shape_literal = ", ".join(type_info.dimensions)
        arguments = [f"[{', '.join(elements)}]", f"shape=[{shape_literal}]"]

        if array_default.order_values is not None:
            order_literal = ", ".join(str(index) for index in array_default.order_values)
            arguments.append(f"order=[{order_literal}]")

        if array_default.pad_values is not None:
            pad_elements = [
                _format_scalar_default(element, None, type_info.element_category)
                for element in array_default.pad_values
            ]
            arguments.append(f"pad=[{', '.join(pad_elements)}]")

        return f"reshape({', '.join(arguments)})"

    return _format_scalar_default(value, None, type_info.category)


def _format_array_default_display(
    prop: dict[str, Any],
    type_info: FieldTypeInfo,
    constants: dict[str, int | float] | None,
) -> tuple[str, str | None]:
    default_value = prop["default"]
    default_is_list = isinstance(default_value, list)
    default_list = default_value if default_is_list else [default_value]

    parsed_dims = _parse_default_dimensions(type_info.dimensions, constants)
    _prepare_array_default(default_list, parsed_dims, prop)

    if default_is_list:
        elements = [
            _format_scalar_default(value, None, type_info.element_category)
            for value in default_list
        ]
        base = f"[{', '.join(elements)}]"
    else:
        base = _format_scalar_default(default_value, None, type_info.element_category)

    repeat_raw = prop.get("x-fortran-default-repeat", False)
    if not isinstance(repeat_raw, bool):
        raise ValueError("array default repeat must be a boolean")
    notes: list[str] = []
    if repeat_raw:
        notes.append("repeated")

    order_raw = prop.get("x-fortran-default-order", "F")
    if not isinstance(order_raw, str):
        raise ValueError("array default order must be 'F' or 'C'")
    order = order_raw.upper()
    if order not in {"F", "C"}:
        raise ValueError("array default order must be 'F' or 'C'")
    if order == "C":
        notes.append("order: C")

    pad_raw = prop.get("x-fortran-default-pad")
    if pad_raw is not None:
        pad_list = pad_raw if isinstance(pad_raw, list) else [pad_raw]
        pad_elements = [
            _format_scalar_default(value, None, type_info.element_category) for value in pad_list
        ]
        if isinstance(pad_raw, list):
            pad_text = f"[{', '.join(pad_elements)}]"
        else:
            pad_text = pad_elements[0]
        notes.append(f"pad: `{pad_text}`")

    if notes:
        return base, f"({', '.join(notes)})"
    return base, None
