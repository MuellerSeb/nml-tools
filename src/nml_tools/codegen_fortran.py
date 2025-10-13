"""Fortran code generation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_TEMPLATE_ENV = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent / "templates"),
    trim_blocks=True,
    lstrip_blocks=False,
    keep_trailing_newline=True,
    undefined=StrictUndefined,
)


@dataclass
class ScalarTypeInfo:
    """Information about a scalar Fortran type."""

    type_spec: str
    arg_type_spec: str
    kind: str | None
    category: str


@dataclass
class FieldTypeInfo:
    """Information about a field (scalar or array) Fortran type."""

    type_spec: str
    arg_type_spec: str
    dimensions: list[str]
    kind: str | None
    category: str
    element_category: str | None = None


@dataclass
class FieldSpec:
    """Information required to render a schema property."""

    order: int
    name: str
    title: str
    description: str | None
    declaration: str
    local_declaration: str
    required: bool
    sentinel_assignment: str | None
    sentinel_check: str | None
    default_assignment: str | None
    set_default_assignment: str | None
    set_present_assignment: str | None
    argument_declaration: str
    type_category: str


@dataclass
class ArrayDefaultSpec:
    """Normalized representation of an array default value."""

    source_values: list[Any]
    pad_values: list[Any] | None
    order_values: list[int] | None


def generate_fortran(schema: dict[str, Any], output: str | Path) -> None:
    """Generate a Fortran module from *schema* at *output*."""
    context = _build_context(schema)
    rendered = _TEMPLATE_ENV.get_template("fortran_module.f90.j2").render(context)

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="ascii")


def _build_context(schema: dict[str, Any]) -> dict[str, Any]:
    namelist_name = schema.get("x-fortran-namelist")
    if not isinstance(namelist_name, str):
        raise ValueError("schema must define 'x-fortran-namelist'")

    if schema.get("type") != "object":
        raise ValueError("schema root must be of type 'object'")

    properties = schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        raise ValueError("schema must define object 'properties'")

    required_fields = _ordered_unique(schema.get("required", []))
    required_set = set(required_fields)
    module_name = f"nml_{namelist_name}"
    type_name = f"{module_name}_t"
    doc_class = f"{namelist_name}_t"
    brief_text = schema.get("title", namelist_name)
    details_text = schema.get("description", brief_text)

    fields: list[FieldSpec] = []
    sentinel_assignments: list[str] = []
    required_checks: list[str] = []
    default_assignments: list[str] = []
    set_optional_defaults: list[str] = []
    set_required_assignments: list[str] = []
    kind_imports: list[str] = []
    requires_ieee = False

    for index, (name, prop) in enumerate(properties.items()):
        if not isinstance(prop, dict):
            raise ValueError(f"property '{name}' must be an object")
        type_info = _field_type_info(prop)
        if type_info.kind and type_info.kind not in kind_imports:
            kind_imports.append(type_info.kind)

        declaration = _render_declaration(type_info.type_spec, type_info.dimensions, name)
        title = prop.get("title", name)
        description = prop.get("description")
        declaration_with_doc = f"{declaration} !< {title}"

        local_decl = _render_declaration(type_info.type_spec, type_info.dimensions, name)

        argument_decl = _render_argument_declaration(
            name=name,
            type_info=type_info,
            is_required=name in required_set,
        )

        sentinel_assignment: str | None = None
        sentinel_check: str | None = None
        if name in required_set:
            sentinel_assignment, sentinel_check = _build_sentinel(
                module_name=module_name,
                namelist_name=namelist_name,
                field_name=name,
                type_info=type_info,
            )
            if sentinel_assignment:
                sentinel_assignments.append(sentinel_assignment)
            if sentinel_check:
                required_checks.append(sentinel_check)
                if type_info.category == "real":
                    requires_ieee = True
        elif type_info.category == "real" and type_info.element_category == "real":
            # arrays of reals use real sentinel logic when needed in future
            pass

        default_assignment: str | None = None
        set_default_assignment: str | None = None
        if "default" in prop and name in required_set:
            raise ValueError(f"required property '{name}' cannot define a default")
        if "default" in prop:
            default_literal = _format_default(prop["default"], type_info, prop)
            if type_info.category == "boolean":
                default_assignment = (
                    f"{name} = {default_literal} ! bool values always need a default"
                )
            else:
                default_assignment = f"{name} = {default_literal}"
            set_default_assignment = f"this%{name} = {default_literal}"
            default_assignments.append(default_assignment)
            set_optional_defaults.append(set_default_assignment)

        if name in required_set:
            set_required_assignments.append(f"this%{name} = {name}")

        fields.append(
            FieldSpec(
                order=index,
                name=name,
                title=title,
                description=description,
                declaration=declaration_with_doc,
                local_declaration=local_decl,
                required=name in required_set,
                sentinel_assignment=sentinel_assignment,
                sentinel_check=sentinel_check,
                default_assignment=default_assignment,
                set_default_assignment=set_default_assignment,
                set_present_assignment=(
                    f"if (present({name})) this%{name} = {name}"
                    if name not in required_set
                    else None
                ),
                argument_declaration=argument_decl,
                type_category=type_info.category,
            )
        )

    namelist_vars = [field.name for field in fields]
    required_fields_specs = [field for field in fields if field.required]
    optional_fields_specs = [field for field in fields if not field.required]

    context = {
        "module_name": module_name,
        "type_name": type_name,
        "type_prefix": module_name,
        "doc_class": doc_class,
        "brief_text": brief_text,
        "details_text": details_text,
        "namelist_name": namelist_name,
        "fields": fields,
        "namelist_vars": namelist_vars,
        "sentinel_assignments": sentinel_assignments,
        "default_assignments": default_assignments,
        "required_checks": required_checks,
        "assignments": [f"this%{field.name} = {field.name}" for field in fields],
        "argument_list": [field.name for field in required_fields_specs + optional_fields_specs],
        "required_argument_declarations": [
            field.argument_declaration for field in required_fields_specs
        ],
        "optional_argument_declarations": [
            field.argument_declaration for field in optional_fields_specs
        ],
        "set_required_assignments": set_required_assignments,
        "set_optional_defaults": set_optional_defaults,
        "set_optional_present": [
            field.set_present_assignment
            for field in optional_fields_specs
            if field.set_present_assignment
        ],
        "kind_module": schema.get("x-fortran-kind-module", "iso_fortran_env"),
        "kind_imports": kind_imports,
        "use_ieee": requires_ieee,
    }

    return context


def _ordered_unique(values: Iterable[Any]) -> list[Any]:
    seen: set[Any] = set()
    ordered: list[Any] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _field_type_info(prop: dict[str, Any]) -> FieldTypeInfo:
    prop_type = prop.get("type")
    if prop_type == "array":
        dimensions: list[str] = []
        current = prop
        while current.get("type") == "array":
            dimensions.extend(_extract_dimensions(current))
            items = current.get("items")
            if not isinstance(items, dict):
                raise ValueError("array property must define 'items'")
            current = items
        scalar = _scalar_type_info(current)
        return FieldTypeInfo(
            type_spec=scalar.type_spec,
            arg_type_spec=scalar.arg_type_spec,
            dimensions=dimensions,
            kind=scalar.kind,
            category="array",
            element_category=scalar.category,
        )

    scalar = _scalar_type_info(prop)
    return FieldTypeInfo(
        type_spec=scalar.type_spec,
        arg_type_spec=scalar.arg_type_spec,
        dimensions=[],
        kind=scalar.kind,
        category=scalar.category,
        element_category=None,
    )


def _scalar_type_info(prop: dict[str, Any]) -> ScalarTypeInfo:
    prop_type = prop.get("type")
    if prop_type == "string":
        length = prop.get("x-fortran-len")
        if not isinstance(length, int):
            raise ValueError("string property must define integer 'x-fortran-len'")
        return ScalarTypeInfo(
            type_spec=f"character(len={length})",
            arg_type_spec="character(len=*)",
            kind=None,
            category="string",
        )
    if prop_type == "integer":
        kind = prop.get("x-fortran-kind")
        if not isinstance(kind, str):
            raise ValueError("integer property must define 'x-fortran-kind'")
        return ScalarTypeInfo(
            type_spec=f"integer({kind})",
            arg_type_spec=f"integer({kind})",
            kind=kind,
            category="integer",
        )
    if prop_type == "number":
        kind = prop.get("x-fortran-kind")
        if not isinstance(kind, str):
            raise ValueError("number property must define 'x-fortran-kind'")
        return ScalarTypeInfo(
            type_spec=f"real({kind})",
            arg_type_spec=f"real({kind})",
            kind=kind,
            category="real",
        )
    if prop_type == "boolean":
        return ScalarTypeInfo(
            type_spec="logical",
            arg_type_spec="logical",
            kind=None,
            category="boolean",
        )
    raise ValueError(f"unsupported property type '{prop_type}'")


def _extract_dimensions(prop: dict[str, Any]) -> list[str]:
    shape = prop.get("x-fortran-shape")
    if isinstance(shape, int):
        return [str(shape)]
    if isinstance(shape, list) and all(isinstance(dim, int) for dim in shape):
        return [str(dim) for dim in shape]
    if shape is None:
        return [":"]
    raise ValueError("array property 'x-fortran-shape' must be an int or list of ints")


def _render_declaration(type_spec: str, dimensions: list[str], name: str) -> str:
    parts = [type_spec]
    if dimensions:
        dims = ", ".join(dimensions)
        parts.append(f"dimension({dims})")
    return f"{', '.join(parts)} :: {name}"


def _render_argument_declaration(
    *,
    name: str,
    type_info: FieldTypeInfo,
    is_required: bool,
) -> str:
    intent = "intent(in)"
    parts = [type_info.arg_type_spec]
    if type_info.dimensions:
        dims = ", ".join(type_info.dimensions)
        parts.append(f"dimension({dims})")
    if not is_required:
        parts.append(intent)
        parts.append("optional")
        decl = f"{', '.join(parts[:-1])}, {parts[-1]} :: {name}"
    else:
        parts.append(intent)
        decl = f"{', '.join(parts)} :: {name}"
    return decl


def _build_sentinel(
    *,
    module_name: str,
    namelist_name: str,
    field_name: str,
    type_info: FieldTypeInfo,
) -> tuple[str | None, str | None]:
    if type_info.category == "string":
        assignment = f"{field_name} = achar(0) ! NULL string as sentinel for required string"
        check = (
            f"if (trim({field_name}) == achar(0)) error stop "
            f"\"{module_name}%from_file: '{field_name}' is required\""
        )
        return assignment, check
    if type_info.category == "integer":
        assignment = f"{field_name} = -huge({field_name}) ! sentinel for required integer"
        check = (
            f"if ({field_name} == -huge({field_name})) error stop "
            f"\"{module_name}%from_file: '{field_name}' is required\""
        )
        return assignment, check
    if type_info.category == "real":
        assignment = (
            f"{field_name} = ieee_value({field_name}, ieee_quiet_nan) ! sentinel for required real"
        )
        check = (
            f"if (ieee_is_nan({field_name})) error stop "
            f"\"{module_name}%from_file: '{field_name}' is required\""
        )
        return assignment, check
    if type_info.category == "boolean":
        raise ValueError(f"required boolean '{field_name}' is not supported")
    if type_info.category == "array":
        raise ValueError(f"required array '{field_name}' is not supported")
    raise ValueError(f"unsupported sentinel category '{type_info.category}'")


def _format_default(value: Any, type_info: FieldTypeInfo, prop: dict[str, Any]) -> str:
    if type_info.category == "array":
        if not isinstance(value, list):
            raise ValueError("array default must be a list")
        parsed_dims = _parse_default_dimensions(type_info.dimensions)
        array_default = _prepare_array_default(value, parsed_dims, prop)
        elements = [
            _format_scalar_default(element, type_info.kind, type_info.element_category)
            for element in array_default.source_values
        ]
        if (
            len(parsed_dims) == 1
            and array_default.order_values is None
            and array_default.pad_values is None
        ):
            return f"[{', '.join(elements)}]"

        shape_literal = ", ".join(str(dim) for dim in parsed_dims)
        arguments = [f"[{', '.join(elements)}]", f"shape=[{shape_literal}]"]

        if array_default.order_values is not None:
            order_literal = ", ".join(str(index) for index in array_default.order_values)
            arguments.append(f"order=[{order_literal}]")

        if array_default.pad_values is not None:
            pad_elements = [
                _format_scalar_default(element, type_info.kind, type_info.element_category)
                for element in array_default.pad_values
            ]
            arguments.append(f"pad=[{', '.join(pad_elements)}]")

        return f"reshape({', '.join(arguments)})"
    return _format_scalar_default(value, type_info.kind, type_info.category)


def _format_scalar_default(value: Any, kind: str | None, category: str | None) -> str:
    if category == "integer":
        if not isinstance(value, int):
            raise ValueError("integer default must be an int")
        suffix = f"_{kind}" if kind else ""
        return f"{value}{suffix}"
    if category == "real":
        number = float(value)
        literal = repr(number)
        if literal.lower() == "nan":
            raise ValueError("NaN defaults are not supported")
        if "e" in literal:
            literal = literal.replace("e", "e")
        if "." not in literal and "e" not in literal and "E" not in literal:
            literal = f"{literal}.0"
        suffix = f"_{kind}" if kind else ""
        return f"{literal}{suffix}"
    if category == "boolean":
        if not isinstance(value, bool):
            raise ValueError("boolean default must be a bool")
        return ".true." if value else ".false."
    if category == "string":
        if not isinstance(value, str):
            raise ValueError("string default must be a str")
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    raise ValueError(f"unsupported default category '{category}'")


def _parse_default_dimensions(dimensions: list[str]) -> list[int]:
    if not dimensions:
        raise ValueError("array property missing dimensions")
    parsed: list[int] = []
    for dim in dimensions:
        if dim == ":":
            raise ValueError("defaults not supported for deferred-size dimensions")
        try:
            parsed.append(int(dim))
        except (TypeError, ValueError) as err:  # pragma: no cover - defensive
            raise ValueError("array default dimensions must be integer literals") from err
    return parsed


def _prepare_array_default(
    value: list[Any],
    dims: list[int],
    prop: dict[str, Any],
) -> ArrayDefaultSpec:
    default_values = _ensure_flat_scalar_list(value, "array default")
    if not default_values:
        raise ValueError("array default must contain at least one value")

    total_size = math.prod(dims)
    if len(default_values) > total_size:
        raise ValueError("array default longer than declared x-fortran-shape")

    order_raw = prop.get("x-fortran-default-order", "F")
    if not isinstance(order_raw, str):
        raise ValueError("array default order must be 'F' or 'C'")
    order = order_raw.upper()
    if order not in {"F", "C"}:
        raise ValueError("array default order must be 'F' or 'C'")

    repeat_raw = prop.get("x-fortran-default-repeat", False)
    if not isinstance(repeat_raw, bool):
        raise ValueError("array default repeat must be a boolean")
    repeat = bool(repeat_raw)

    pad_raw = prop.get("x-fortran-default-pad")
    pad_values: list[Any] | None = None
    if pad_raw is not None:
        if repeat:
            raise ValueError("array default cannot set both pad and repeat")
        if not isinstance(pad_raw, list):
            raise ValueError("array default pad must be a list")
        pad_values = _ensure_flat_scalar_list(pad_raw, "array default pad")
        if not pad_values:
            raise ValueError("array default pad must contain at least one value")

    if len(default_values) < total_size and pad_values is None and not repeat:
        raise ValueError(
            "array default shorter than declared x-fortran-shape without pad or repeat"
        )

    if repeat:
        pad_values = list(default_values)
        if not pad_values:
            raise ValueError("array default repeat requires at least one value")

    order_values: list[int] | None = None
    if order == "C" and len(dims) > 1:
        rank = len(dims)
        order_values = list(range(rank, 0, -1))

    return ArrayDefaultSpec(
        source_values=list(default_values),
        pad_values=pad_values,
        order_values=order_values,
    )


def _ensure_flat_scalar_list(values: list[Any], description: str) -> list[Any]:
    normalized: list[Any] = []
    for element in values:
        if isinstance(element, list):
            raise ValueError(f"{description} must be a flat list")
        normalized.append(element)
    return normalized
