"""Fortran code generation."""

from __future__ import annotations

import math
import re
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
    length_expr: str | None = None


@dataclass
class FieldTypeInfo:
    """Information about a field (scalar or array) Fortran type."""

    type_spec: str
    arg_type_spec: str
    dimensions: list[str]
    kind: str | None
    category: str
    length_expr: str | None = None
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


@dataclass
class ConstantSpec:
    """Constant definition for helper modules."""

    name: str
    type_spec: str
    value: str
    doc: str | None


def generate_fortran(
    schema: dict[str, Any],
    output: str | Path,
    *,
    helper_module: str = "nml_helper",
    kind_module: str | None = None,
    kind_map: dict[str, str] | None = None,
    kind_allowlist: Iterable[str] | None = None,
    constants: dict[str, int | float] | None = None,
    module_doc: str | None = None,
) -> None:
    """Generate a Fortran module from *schema* at *output*."""
    output_path = Path(output)
    context = _build_context(
        schema,
        helper_module=helper_module,
        kind_module=kind_module,
        kind_map=kind_map,
        kind_allowlist=kind_allowlist,
        constants=constants,
        module_doc=module_doc,
    )
    context["file_name"] = output_path.name
    rendered = _TEMPLATE_ENV.get_template("fortran_module.f90.j2").render(context)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="ascii")


def generate_helper(
    output: str | Path,
    *,
    module_name: str = "nml_helper",
    len_buf: int = 1024,
    constants: list[ConstantSpec] | None = None,
    module_doc: str | None = None,
    helper_header: str | None = None,
) -> None:
    """Generate the helper Fortran module at *output*."""
    if not module_name:
        raise ValueError("helper module name must be a non-empty string")
    if len_buf <= 0:
        raise ValueError("helper len_buf must be positive")
    output_path = Path(output)
    rendered = _TEMPLATE_ENV.get_template("nml_helper.f90.j2").render(
        {
            "file_name": output_path.name,
            "module_name": module_name,
            "len_buf": len_buf,
            "constants": constants or [],
            "module_doc": module_doc,
            "helper_header": helper_header,
        }
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="ascii")


def _build_context(
    schema: dict[str, Any],
    *,
    helper_module: str,
    kind_module: str | None,
    kind_map: dict[str, str] | None,
    kind_allowlist: Iterable[str] | None,
    constants: dict[str, int | float] | None,
    module_doc: str | None,
) -> dict[str, Any]:
    if not helper_module:
        raise ValueError("helper module name must be a non-empty string")
    if "x-fortran-kind-module" in schema:
        raise ValueError("schema must not define 'x-fortran-kind-module'")
    namelist_name = schema.get("x-fortran-namelist")
    if not isinstance(namelist_name, str):
        raise ValueError("schema must define 'x-fortran-namelist'")

    if schema.get("type") != "object":
        raise ValueError("schema root must be of type 'object'")

    properties = schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        raise ValueError("schema must define object 'properties'")

    property_items: list[tuple[str, str, dict[str, Any]]] = []
    property_name_map: dict[str, str] = {}
    for prop_name, prop in properties.items():
        if not isinstance(prop_name, str) or not prop_name.strip():
            raise ValueError("property names must be non-empty strings")
        key = prop_name.lower()
        if key in property_name_map:
            raise ValueError(
                "property names must be unique (case-insensitive): "
                f"'{property_name_map[key]}' and '{prop_name}'"
            )
        property_name_map[key] = prop_name
        if not isinstance(prop, dict):
            raise ValueError(f"property '{prop_name}' must be an object")
        property_items.append((prop_name, key, prop))

    required_fields_raw = _ordered_unique(schema.get("required", []))
    required_fields: list[str] = []
    for req_name in required_fields_raw:
        if not isinstance(req_name, str):
            raise ValueError("schema 'required' entries must be strings")
        req_key = req_name.lower()
        if req_key not in property_name_map:
            raise ValueError(f"required property '{req_name}' is not defined")
        if req_key not in required_fields:
            required_fields.append(req_key)
    required_set = set(required_fields)
    module_name = f"nml_{namelist_name}"
    type_name = f"{module_name}_t"
    doc_class = f"{module_name}_t"
    brief_text = schema.get("title", namelist_name)
    details_text = schema.get("description", brief_text)

    fields: list[FieldSpec] = []
    sentinel_assignments: list[str] = []
    default_assignments: list[str] = []
    set_optional_defaults: list[str] = []
    local_init_assignments: list[str] = []
    set_required_assignments: list[str] = []
    presence_cases: list[dict[str, Any]] = []
    required_scalar_names: set[str] = set()
    required_array_by_name: dict[str, dict[str, Any]] = {}
    flex_bound_vars: set[str] = set()
    flex_arrays: list[dict[str, Any]] = []
    default_parameters: list[str] = []
    enum_parameters: list[str] = []
    enum_functions: list[dict[str, Any]] = []
    enum_checks: list[dict[str, Any]] = []
    bounds_parameters: list[str] = []
    bounds_functions: list[dict[str, Any]] = []
    bounds_checks: list[dict[str, Any]] = []
    kind_ids: list[str] = []
    requires_ieee = False
    uses_partly_set = False
    helper_imports = [
        "nml_file_t",
        "nml_line_buffer",
        "NML_OK",
        "NML_ERR_FILE_NOT_FOUND",
        "NML_ERR_OPEN",
        "NML_ERR_NOT_OPEN",
        "NML_ERR_NML_NOT_FOUND",
        "NML_ERR_READ",
        "NML_ERR_CLOSE",
        "NML_ERR_REQUIRED",
        "NML_ERR_ENUM",
        "NML_ERR_BOUNDS",
        "NML_ERR_NOT_SET",
        "NML_ERR_INVALID_NAME",
        "NML_ERR_INVALID_INDEX",
        "idx_check",
        "to_lower",
    ]

    current_property: str | None = None
    try:
        for index, (display_name, attr_name, prop) in enumerate(property_items):
            current_property = display_name
            name = attr_name
            type_info = _field_type_info(prop, constants)
            for const_name in _collect_dimension_constants(type_info.dimensions, constants):
                if const_name not in helper_imports:
                    helper_imports.append(const_name)
            if type_info.length_expr and not _is_int_literal(type_info.length_expr):
                if type_info.length_expr not in helper_imports:
                    helper_imports.append(type_info.length_expr)
            if type_info.kind:
                kind_ids.append(type_info.kind)

            array_default_info: tuple[Any, bool] | None = None
            if type_info.category == "array":
                array_default_info = _array_default_value(prop)

            flex_dim = _parse_flex_dim(prop, type_info)
            if flex_dim > 0:
                if type_info.element_category == "boolean":
                    raise ValueError("flex arrays cannot use boolean elements")
                if array_default_info is not None or any(
                    key in prop
                    for key in (
                        "x-fortran-default-order",
                        "x-fortran-default-repeat",
                        "x-fortran-default-pad",
                    )
                ):
                    raise ValueError("flex arrays cannot define defaults")

            declaration = _render_declaration(type_info.type_spec, type_info.dimensions, name)
            title_raw = prop.get("title")
            if title_raw is None:
                title = display_name
            elif not isinstance(title_raw, str):
                raise ValueError(f"property '{display_name}' title must be a string")
            else:
                title = title_raw.strip() or name
            description = prop.get("description")
            declaration_with_doc = f"{declaration} !< {title}"

            local_decl = _render_declaration(type_info.type_spec, type_info.dimensions, name)

            is_required = name in required_set
            if type_info.category == "array":
                has_default = array_default_info is not None
            else:
                has_default = "default" in prop

            default_from_items = False
            default_values: list[Any] | None = None
            parsed_dims: list[int] | None = None
            array_default_spec: ArrayDefaultSpec | None = None

            if type_info.category == "array" and has_default:
                if array_default_info is None:
                    raise ValueError(f"missing array default for '{display_name}'")
                default_raw, default_from_items = array_default_info
                if default_from_items:
                    if isinstance(default_raw, list):
                        raise ValueError("array items default must be a scalar")
                    default_values = [default_raw]
                else:
                    if not isinstance(default_raw, list):
                        raise ValueError("array default must be a list")
                    default_values = default_raw
                    parsed_dims = _parse_default_dimensions(type_info.dimensions, constants)
                    array_default_spec = _prepare_array_default(default_values, parsed_dims, prop)

            needs_sentinel = (not is_required) and (not has_default)
            requires_sentinel = is_required or needs_sentinel

            arg_dimensions = type_info.dimensions
            if type_info.category == "array" and (flex_dim > 0 or has_default):
                arg_dimensions = [":" for _ in type_info.dimensions]
            argument_decl = _render_argument_declaration(
                name=name,
                type_info=type_info,
                is_required=is_required,
                dimensions=arg_dimensions,
            )
            local_init_assignments.append(f"{name} = this%{name}")

            sentinel_assignment: str | None = None
            sentinel_condition: str | None = None
            set_sentinel_condition: str | None = None
            if requires_sentinel:
                if is_required and type_info.category == "boolean":
                    raise ValueError(
                        f"required {type_info.category} '{display_name}' is not supported"
                    )
                if is_required and type_info.category == "array":
                    if type_info.element_category == "boolean":
                        raise ValueError("required boolean arrays are not supported")
                if needs_sentinel and type_info.category == "boolean":
                    raise ValueError(f"optional boolean '{display_name}' must define a default")
                if needs_sentinel and type_info.category == "array":
                    if type_info.element_category == "boolean":
                        raise ValueError("optional boolean arrays must define a default")
                value_expr, condition_expr, uses_ieee = _sentinel_expressions(
                    type_info,
                    var_ref=f"this%{name}",
                )
                sentinel_assignment = (
                    f"this%{name} = {value_expr}"
                    f"{_sentinel_comment(type_info, required=is_required)}"
                )
                sentinel_condition = condition_expr
                sentinel_assignments.append(sentinel_assignment)
                if uses_ieee:
                    requires_ieee = True
                if not has_default and type_info.category != "boolean":
                    set_value_expr, set_condition_expr, set_uses_ieee = _sentinel_expressions(
                        type_info,
                        var_ref=f"this%{name}",
                    )
                    if set_uses_ieee:
                        requires_ieee = True
                    set_sentinel_condition = set_condition_expr
                    if needs_sentinel:
                        sent_com = _sentinel_comment(type_info, required=False)
                        set_optional_defaults.append(f"this%{name} = {set_value_expr}{sent_com}")

            if is_required and type_info.category != "array":
                required_scalar_names.add(name)

            if is_required and type_info.category == "array" and flex_dim == 0:
                element_category = type_info.element_category
                if element_category is None:
                    raise ValueError("array field missing element category")
                all_missing, any_missing, uses_ieee = _array_missing_conditions(
                    element_category,
                    var_ref=f"this%{name}",
                    len_ref=f"this%{name}",
                )
                required_array_by_name[name] = {
                    "name": display_name,
                    "attr_name": name,
                    "all_missing_condition": all_missing,
                    "any_missing_condition": any_missing,
                }
                uses_partly_set = True
                if uses_ieee:
                    requires_ieee = True

            flex_bounds: list[dict[str, Any]] | None = None
            partial_bounds: list[dict[str, Any]] | None = None
            if flex_dim > 0:
                rank = len(type_info.dimensions)
                element_category = type_info.element_category
                if element_category is None:
                    raise ValueError("array field missing element category")
                flex_dims = list(range(rank - flex_dim + 1, rank + 1))
                slice_missing_conditions: list[str] = []
                slice_uses_ieee = False
                bounds: list[dict[str, Any]] = []
                lb_vars: dict[int, str] = {}
                ub_vars: dict[int, str] = {}
                for dim in flex_dims:
                    lb_var, ub_var = _flex_bound_vars(dim)
                    lb_vars[dim] = lb_var
                    ub_vars[dim] = ub_var
                    bounds.append({"dim": dim, "lb_var": lb_var, "ub_var": ub_var})
                    flex_bound_vars.add(lb_var)
                    flex_bound_vars.add(ub_var)
                    slice_ref = _slice_ref(name, rank, dim, "idx")
                    slice_missing_expr, uses_ieee = _element_missing_expression(
                        element_category,
                        var_ref=slice_ref,
                        len_ref=f"this%{name}",
                    )
                    slice_missing_conditions.append(
                        f"all({slice_missing_expr})" if rank > 1 else slice_missing_expr
                    )
                    slice_uses_ieee = slice_uses_ieee or uses_ieee
                prefix_ref = _slice_ref_bounds(name, rank, flex_dims, lb_vars, ub_vars)
                prefix_missing_expr, uses_ieee_prefix = _element_missing_expression(
                    element_category,
                    var_ref=prefix_ref,
                    len_ref=f"this%{name}",
                )
                prefix_any_missing_condition = f"any({prefix_missing_expr})"
                flex_bounds = bounds
                flex_arrays.append(
                    {
                        "name": name,
                        "display_name": display_name,
                        "rank": rank,
                        "flex_dims": flex_dims,
                        "required": is_required,
                        "bounds": bounds,
                        "slice_missing_conditions": slice_missing_conditions,
                        "prefix_any_missing_condition": prefix_any_missing_condition,
                    }
                )
                uses_partly_set = True
                if slice_uses_ieee or uses_ieee_prefix:
                    requires_ieee = True
            elif type_info.category == "array" and has_default:
                rank = len(type_info.dimensions)
                bounds = []
                for dim in range(1, rank + 1):
                    lb_var, ub_var = _flex_bound_vars(dim)
                    bounds.append({"dim": dim, "lb_var": lb_var, "ub_var": ub_var})
                    flex_bound_vars.add(lb_var)
                    flex_bound_vars.add(ub_var)
                partial_bounds = bounds

            default_assignment: str | None = None
            set_default_assignment: str | None = None
            if has_default and is_required:
                raise ValueError(f"required property '{display_name}' cannot define a default")
            if has_default:
                default_const_name = f"{name}_default"
                if type_info.category == "array":
                    if default_values is None:
                        raise ValueError(f"missing array default for '{display_name}'")
                    default_is_scalar = default_from_items

                    repeat = False
                    pad_raw = None
                    pad_const_name: str | None = None
                    pad_is_scalar = False

                    if not default_from_items:
                        repeat_raw = prop.get("x-fortran-default-repeat", False)
                        if not isinstance(repeat_raw, bool):
                            raise ValueError("array default repeat must be a boolean")
                        repeat = bool(repeat_raw)
                        pad_raw = prop.get("x-fortran-default-pad")
                        if pad_raw is not None:
                            pad_const_name = f"{name}_pad"
                            pad_is_scalar = not isinstance(pad_raw, list)
                            pad_values = pad_raw if isinstance(pad_raw, list) else [pad_raw]
                            pad_values = _ensure_flat_scalar_list(pad_values, "array default pad")
                            pad_elements = [
                                _format_scalar_default(
                                    element, type_info.kind, type_info.element_category
                                )
                                for element in pad_values
                            ]
                            if pad_is_scalar:
                                pad_literal = _format_scalar_default(
                                    pad_raw, type_info.kind, type_info.element_category
                                )
                                default_parameters.append(
                                    f"{type_info.type_spec}, parameter, public :: "
                                    f"{pad_const_name} = {pad_literal}"
                                )
                            else:
                                default_parameters.append(
                                    f"{type_info.type_spec}, parameter, public :: "
                                    f"{pad_const_name}({len(pad_elements)}) = "
                                    f"[{', '.join(pad_elements)}]"
                                )

                        if parsed_dims is None:
                            parsed_dims = _parse_default_dimensions(type_info.dimensions, constants)
                        if array_default_spec is None:
                            array_default_spec = _prepare_array_default(
                                default_values, parsed_dims, prop
                            )

                    if default_is_scalar:
                        default_literal = _format_scalar_default(
                            default_values[0], type_info.kind, type_info.element_category
                        )
                        default_parameters.append(
                            f"{type_info.type_spec}, parameter, public :: "
                            f"{default_const_name} = {default_literal}"
                        )
                    else:
                        if array_default_spec is None:
                            raise ValueError(
                                f"missing array default specification for '{display_name}'"
                            )
                        default_elements = [
                            _format_scalar_default(
                                element, type_info.kind, type_info.element_category
                            )
                            for element in array_default_spec.source_values
                        ]
                        default_parameters.append(
                            f"{type_info.type_spec}, parameter, public :: "
                            f"{default_const_name}({len(default_elements)}) = "
                            f"[{', '.join(default_elements)}]"
                        )

                    if default_from_items:
                        default_assignment = f"this%{name} = {default_const_name}"
                    elif (
                        len(type_info.dimensions) == 1
                        and array_default_spec is not None
                        and array_default_spec.order_values is None
                        and array_default_spec.pad_values is None
                    ):
                        default_assignment = f"this%{name} = {default_const_name}"
                    else:
                        source_expr = default_const_name
                        shape_expr = ", ".join(type_info.dimensions)
                        arguments = [source_expr, f"shape=[{shape_expr}]"]
                        if array_default_spec is not None:
                            if array_default_spec.order_values is not None:
                                order_literal = ", ".join(
                                    str(index) for index in array_default_spec.order_values
                                )
                                arguments.append(f"order=[{order_literal}]")
                            if array_default_spec.pad_values is not None:
                                if repeat:
                                    pad_expr = default_const_name
                                else:
                                    if pad_const_name is None:
                                        raise ValueError(
                                            f"missing pad values for array default '{display_name}'"
                                        )
                                    pad_expr = (
                                        pad_const_name
                                        if not pad_is_scalar
                                        else f"[{pad_const_name}]"
                                    )
                                arguments.append(f"pad={pad_expr}")
                        default_assignment = _format_reshape_assignment(name, arguments)
                    set_default_assignment = default_assignment
                else:
                    default_literal = _format_default(prop["default"], type_info, prop, constants)
                    default_parameters.append(
                        f"{type_info.type_spec}, parameter, public :: "
                        f"{default_const_name} = {default_literal}"
                    )
                    if type_info.category == "boolean":
                        default_assignment = (
                            f"this%{name} = {default_const_name} "
                            "! bool values always need a default"
                        )
                    else:
                        default_assignment = f"this%{name} = {default_const_name}"
                    set_default_assignment = f"this%{name} = {default_const_name}"

                if default_assignment is None or set_default_assignment is None:
                    raise ValueError(f"missing default assignment for '{display_name}'")
                default_assignments.append(default_assignment)
                set_optional_defaults.append(set_default_assignment)

            enum_values = _enum_values(prop, type_info, constants)
            if enum_values is not None:
                enum_category = _enum_category(type_info)
                enum_const_name = f"{name}_enum_values"
                enum_literals = [
                    _format_scalar_default(value, type_info.kind, enum_category)
                    for value in enum_values
                ]
                if enum_category == "string":
                    enum_array_literal = (
                        f"[{type_info.type_spec} :: {', '.join(enum_literals)}]"
                    )
                else:
                    enum_array_literal = f"[{', '.join(enum_literals)}]"
                if enum_category == "string":
                    enum_parameters.append(
                        f"{type_info.type_spec}, parameter, public :: &\n"
                        f"    {enum_const_name}({len(enum_literals)}) = {enum_array_literal}"
                    )
                else:
                    enum_parameters.append(
                        f"{type_info.type_spec}, parameter, public :: "
                        f"{enum_const_name}({len(enum_literals)}) = {enum_array_literal}"
                    )
                enum_type_info = (
                    _element_type_info(type_info) if type_info.category == "array" else type_info
                )
                _, missing_condition, _ = _sentinel_expressions(
                    enum_type_info,
                    var_ref="val",
                    len_ref="val",
                )
                enum_functions.append(
                    {
                        "name": name,
                        "func_name": f"{name}_in_enum",
                        "arg_type_spec": _enum_arg_type_spec(type_info),
                        "enum_values_name": enum_const_name,
                        "use_trim": enum_category == "string",
                        "missing_condition": missing_condition,
                    }
                )
                if type_info.category == "array":
                    enum_checks.append(
                        {
                            "name": name,
                            "display_name": display_name,
                            "func_name": f"{name}_in_enum",
                            "is_array": True,
                            "array_ref": f"this%{name}",
                        }
                    )
                else:
                    enum_checks.append(
                        {
                            "name": name,
                            "display_name": display_name,
                            "func_name": f"{name}_in_enum",
                            "is_array": False,
                            "element_ref": f"this%{name}",
                        }
                    )

            bounds_spec = _bounds_spec(prop, type_info)
            if bounds_spec is not None:
                bounds_category = bounds_spec["category"]
                bounds_type_info = (
                    _element_type_info(type_info) if type_info.category == "array" else type_info
                )
                min_value = bounds_spec["min_value"]
                max_value = bounds_spec["max_value"]
                min_exclusive = bounds_spec["min_exclusive"]
                max_exclusive = bounds_spec["max_exclusive"]
                min_name = None
                max_name = None
                if min_value is not None:
                    min_name = f"{name}_min_excl" if min_exclusive else f"{name}_min"
                    min_literal = _format_scalar_default(
                        min_value, bounds_type_info.kind, bounds_category
                    )
                    bounds_parameters.append(
                        f"{bounds_type_info.type_spec}, parameter, public :: "
                        f"{min_name} = {min_literal}"
                    )
                if max_value is not None:
                    max_name = f"{name}_max_excl" if max_exclusive else f"{name}_max"
                    max_literal = _format_scalar_default(
                        max_value, bounds_type_info.kind, bounds_category
                    )
                    bounds_parameters.append(
                        f"{bounds_type_info.type_spec}, parameter, public :: "
                        f"{max_name} = {max_literal}"
                    )
                _, missing_condition, uses_ieee = _sentinel_expressions(
                    bounds_type_info,
                    var_ref="val",
                    len_ref="val",
                )
                if uses_ieee:
                    requires_ieee = True
                bounds_functions.append(
                    {
                        "name": name,
                        "func_name": f"{name}_in_bounds",
                        "arg_type_spec": bounds_type_info.arg_type_spec,
                        "has_min": min_value is not None,
                        "has_max": max_value is not None,
                        "min_name": min_name,
                        "max_name": max_name,
                        "min_exclusive": min_exclusive,
                        "max_exclusive": max_exclusive,
                        "missing_condition": missing_condition,
                    }
                )
                if type_info.category == "array":
                    bounds_checks.append(
                        {
                            "name": name,
                            "display_name": display_name,
                            "func_name": f"{name}_in_bounds",
                            "is_array": True,
                            "array_ref": f"this%{name}",
                        }
                    )
                else:
                    bounds_checks.append(
                        {
                            "name": name,
                            "display_name": display_name,
                            "func_name": f"{name}_in_bounds",
                            "is_array": False,
                            "element_ref": f"this%{name}",
                        }
                    )

            is_array = type_info.category == "array"
            if is_required:
                if is_array and flex_dim > 0:
                    set_required_assignments.append(
                        _render_flex_set_block(
                            name,
                            len(type_info.dimensions),
                            flex_dim,
                            flex_bounds or [],
                        )
                    )
                elif is_array and has_default:
                    set_required_assignments.append(
                        _render_partial_set_block(
                            name,
                            len(type_info.dimensions),
                            partial_bounds or [],
                        )
                    )
                else:
                    set_required_assignments.append(f"this%{name} = {name}")

            if not is_required:
                if is_array and flex_dim > 0:
                    block = _render_flex_set_block(
                        name,
                        len(type_info.dimensions),
                        flex_dim,
                        flex_bounds or [],
                    )
                    indented_block = "\n".join(f"  {line}" for line in block.splitlines())
                    set_present_assignment = (
                        f"if (present({name})) then\n{indented_block}\nend if"
                    )
                elif is_array and has_default:
                    block = _render_partial_set_block(
                        name,
                        len(type_info.dimensions),
                        partial_bounds or [],
                    )
                    indented_block = "\n".join(f"  {line}" for line in block.splitlines())
                    set_present_assignment = (
                        f"if (present({name})) then\n{indented_block}\nend if"
                    )
                else:
                    set_present_assignment = f"if (present({name})) this%{name} = {name}"
            else:
                set_present_assignment = None

            array_rank = len(type_info.dimensions) if is_array else 0
            element_condition: str | None = None

            if is_array and not has_default:
                element_type = _element_type_info(type_info)
                index_args = ", ".join(f"idx({idx})" for idx in range(1, array_rank + 1))
                element_ref = f"this%{name}({index_args})"
                _, element_condition, element_uses_ieee = _sentinel_expressions(
                    element_type,
                    var_ref=element_ref,
                    len_ref=f"this%{name}",
                )
                if element_uses_ieee:
                    requires_ieee = True

            if has_default or type_info.category == "boolean":
                presence_cases.append(
                    {
                        "name": name,
                        "display_name": display_name,
                        "always_true": True,
                        "sentinel_condition": None,
                        "is_array": is_array,
                        "rank": array_rank,
                        "element_condition": element_condition,
                    }
                )
            else:
                if set_sentinel_condition is None:
                    raise ValueError(f"missing sentinel condition for '{display_name}'")
                presence_cases.append(
                    {
                        "name": name,
                        "display_name": display_name,
                        "always_true": False,
                        "sentinel_condition": set_sentinel_condition,
                        "is_array": is_array,
                        "rank": array_rank,
                        "element_condition": element_condition,
                    }
                )

            fields.append(
                FieldSpec(
                    order=index,
                    name=name,
                    title=title,
                    description=description,
                    declaration=declaration_with_doc,
                    local_declaration=local_decl,
                    required=is_required,
                    sentinel_assignment=sentinel_assignment,
                    sentinel_check=(
                        f"if ({sentinel_condition}) error stop "
                        f"\"{module_name}%from_file: '{name}' is required\""
                        if sentinel_condition and is_required
                        else None
                    ),
                    default_assignment=default_assignment,
                    set_default_assignment=set_default_assignment,
                    set_present_assignment=set_present_assignment,
                    argument_declaration=argument_decl,
                    type_category=type_info.category,
                )
            )

    except ValueError as exc:
        if current_property is None:
            raise
        msg = str(exc)
        if f"property '{current_property}'" in msg:
            raise
        raise ValueError(f"property '{current_property}': {msg}") from exc
    if uses_partly_set and "NML_ERR_PARTLY_SET" not in helper_imports:
        helper_imports.append("NML_ERR_PARTLY_SET")
    required_flex_names = {entry["name"] for entry in flex_arrays if entry["required"]}
    required_scalar_validations: list[str] = []
    for name in required_fields:
        if name in required_scalar_names:
            required_scalar_validations.append(property_name_map[name])
        elif name not in required_array_by_name and name not in required_flex_names:
            required_scalar_validations.append(property_name_map[name])
    required_array_validations = [
        required_array_by_name[name]
        for name in required_fields
        if name in required_array_by_name
    ]
    namelist_vars = [field.name for field in fields]
    required_fields_specs = [field for field in fields if field.required]
    optional_fields_specs = [field for field in fields if not field.required]

    resolved_kind_module = kind_module or "iso_fortran_env"
    if not isinstance(resolved_kind_module, str) or not resolved_kind_module:
        raise ValueError("kind module must be a non-empty string")

    context = {
        "module_name": module_name,
        "type_name": type_name,
        "type_prefix": module_name,
        "doc_class": doc_class,
        "brief_text": brief_text,
        "details_text": details_text,
        "module_doc": module_doc,
        "namelist_name": namelist_name,
        "fields": fields,
        "namelist_vars": namelist_vars,
        "sentinel_assignments": sentinel_assignments,
        "default_assignments": default_assignments,
        "default_parameters": default_parameters,
        "enum_parameters": enum_parameters,
        "bounds_parameters": bounds_parameters,
        "local_init_assignments": local_init_assignments,
        "required_scalar_validations": required_scalar_validations,
        "required_array_validations": required_array_validations,
        "flex_arrays": flex_arrays,
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
        "enum_functions": enum_functions,
        "enum_checks": enum_checks,
        "bounds_functions": bounds_functions,
        "bounds_checks": bounds_checks,
        "kind_module": resolved_kind_module,
        "kind_imports": _resolve_kind_imports(
            kind_ids,
            kind_map=kind_map,
            kind_allowlist=kind_allowlist,
        ),
        "use_ieee": requires_ieee,
        "helper_module": helper_module,
        "helper_imports": helper_imports,
        "presence_cases": presence_cases,
        "flex_bound_vars": _sort_bound_vars(flex_bound_vars),
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


def _resolve_kind_imports(
    kind_ids: list[str],
    *,
    kind_map: dict[str, str] | None,
    kind_allowlist: Iterable[str] | None,
) -> list[str]:
    allowlist = set(kind_allowlist) if kind_allowlist is not None else None
    imports: list[str] = []
    target_aliases: dict[str, str] = {}
    for kind_id in _ordered_unique(kind_ids):
        target = kind_id
        if kind_map is not None and kind_id in kind_map:
            mapped = kind_map[kind_id]
            if not isinstance(mapped, str):
                raise ValueError(f"kind map target for '{kind_id}' must be a string")
            target = mapped
        elif allowlist is not None and kind_id not in allowlist:
            raise ValueError(f"kind '{kind_id}' not present in kind map or kind module list")

        if allowlist is not None and target not in allowlist:
            raise ValueError(
                f"kind map target '{target}' for '{kind_id}' not present in kind module list"
            )

        if target != kind_id:
            existing = target_aliases.get(target)
            if existing is not None and existing != kind_id:
                raise ValueError(
                    f"kind map target '{target}' is shared by '{existing}' and '{kind_id}'"
                )
            target_aliases[target] = kind_id
            imports.append(f"{kind_id}=>{target}")
        else:
            imports.append(kind_id)
    return imports


def _field_type_info(
    prop: dict[str, Any],
    constants: dict[str, int | float] | None,
) -> FieldTypeInfo:
    prop_type = prop.get("type")
    if prop_type == "array":
        dimensions: list[str] = []
        current = prop
        while current.get("type") == "array":
            dimensions.extend(_extract_dimensions(current))
            items = current.get("items")
            if not isinstance(items, dict):
                raise ValueError("array property must define 'items'")
            if items.get("type") == "array":
                raise ValueError("nested array properties are not supported; use x-fortran-shape")
            current = items
        scalar = _scalar_type_info(current, constants)
        return FieldTypeInfo(
            type_spec=scalar.type_spec,
            arg_type_spec=scalar.arg_type_spec,
            dimensions=dimensions,
            kind=scalar.kind,
            category="array",
            length_expr=scalar.length_expr,
            element_category=scalar.category,
        )

    scalar = _scalar_type_info(prop, constants)
    return FieldTypeInfo(
        type_spec=scalar.type_spec,
        arg_type_spec=scalar.arg_type_spec,
        dimensions=[],
        kind=scalar.kind,
        category=scalar.category,
        length_expr=scalar.length_expr,
        element_category=None,
    )


def _element_type_info(type_info: FieldTypeInfo) -> FieldTypeInfo:
    if type_info.category != "array":
        raise ValueError("element type info requires an array field")
    element_category = type_info.element_category
    if element_category is None:
        raise ValueError("array field missing element category")
    return FieldTypeInfo(
        type_spec=type_info.type_spec,
        arg_type_spec=type_info.type_spec,
        dimensions=[],
        kind=type_info.kind,
        category=element_category,
        length_expr=type_info.length_expr,
        element_category=None,
    )


def _enum_category(type_info: FieldTypeInfo) -> str:
    if type_info.category == "array":
        if type_info.element_category is None:
            raise ValueError("array field missing element category")
        return type_info.element_category
    return type_info.category


def _enum_arg_type_spec(type_info: FieldTypeInfo) -> str:
    category = _enum_category(type_info)
    if category == "string":
        return "character(len=*)"
    return type_info.type_spec


def _scalar_type_info(
    prop: dict[str, Any],
    constants: dict[str, int | float] | None,
) -> ScalarTypeInfo:
    prop_type = prop.get("type")
    if prop_type == "string":
        length = prop.get("x-fortran-len")
        if isinstance(length, bool):
            raise ValueError("string property must define integer 'x-fortran-len'")
        if isinstance(length, int):
            if length <= 0:
                raise ValueError("string length must be positive")
            length_expr = str(length)
        elif isinstance(length, str):
            length_expr = length.strip()
            if not length_expr:
                raise ValueError("string length must be a non-empty value")
            _validate_length_token(length_expr)
            if _is_int_literal(length_expr):
                if int(length_expr) <= 0:
                    raise ValueError("string length must be positive")
            else:
                if constants is None or length_expr not in constants:
                    raise ValueError(
                        f"string length constant '{length_expr}' is not defined in config"
                    )
                value = constants[length_expr]
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError(f"string length constant '{length_expr}' must be an integer")
                if value <= 0:
                    raise ValueError(f"string length constant '{length_expr}' must be positive")
        else:
            raise ValueError("string property must define integer 'x-fortran-len'")
        return ScalarTypeInfo(
            type_spec=f"character(len={length_expr})",
            arg_type_spec="character(len=*)",
            kind=None,
            category="string",
            length_expr=length_expr,
        )
    if prop_type == "integer":
        kind = prop.get("x-fortran-kind")
        if kind is None:
            return ScalarTypeInfo(
                type_spec="integer",
                arg_type_spec="integer",
                kind=None,
                category="integer",
            )
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError("integer property 'x-fortran-kind' must be a non-empty string")
        return ScalarTypeInfo(
            type_spec=f"integer({kind})",
            arg_type_spec=f"integer({kind})",
            kind=kind,
            category="integer",
        )
    if prop_type == "number":
        kind = prop.get("x-fortran-kind")
        if kind is None:
            return ScalarTypeInfo(
                type_spec="real",
                arg_type_spec="real",
                kind=None,
                category="real",
            )
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError("number property 'x-fortran-kind' must be a non-empty string")
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
    if isinstance(shape, bool):
        raise ValueError("array property 'x-fortran-shape' must not be a boolean")
    if isinstance(shape, int):
        return [str(shape)]
    if isinstance(shape, str):
        dim = shape.strip()
        if not dim:
            raise ValueError("array property 'x-fortran-shape' entries must be non-empty")
        _validate_dimension_token(dim)
        return [dim]
    if isinstance(shape, list):
        dimensions: list[str] = []
        for dim in shape:
            if isinstance(dim, bool):
                raise ValueError("array property 'x-fortran-shape' must not include booleans")
            if isinstance(dim, int):
                dim_literal = str(dim)
            elif isinstance(dim, str):
                dim_literal = dim.strip()
                if not dim_literal:
                    raise ValueError("array property 'x-fortran-shape' entries must be non-empty")
            else:
                raise ValueError("array property 'x-fortran-shape' must be an int, string, or list")
            _validate_dimension_token(dim_literal)
            dimensions.append(dim_literal)
        return dimensions
    if shape is None:
        raise ValueError("array property must define 'x-fortran-shape'")
    raise ValueError("array property 'x-fortran-shape' must be an int, string, or list")


_FORTRAN_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _is_int_literal(value: str) -> bool:
    try:
        int(value)
    except ValueError:
        return False
    return True


def _validate_dimension_token(dim: str) -> None:
    if dim == ":":
        return
    if _is_int_literal(dim):
        return
    if _FORTRAN_IDENTIFIER.match(dim):
        return
    raise ValueError("array property 'x-fortran-shape' entries must be ints or identifiers")


def _validate_length_token(length_expr: str) -> None:
    if _is_int_literal(length_expr):
        return
    if _FORTRAN_IDENTIFIER.match(length_expr):
        return
    raise ValueError("string length must be an integer literal or identifier")


def _parse_flex_dim(prop: dict[str, Any], type_info: FieldTypeInfo) -> int:
    flex_raw = prop.get("x-fortran-flex-tail-dims")
    if flex_raw is None:
        flex_value = 0
    else:
        if isinstance(flex_raw, bool) or not isinstance(flex_raw, int):
            raise ValueError("x-fortran-flex-tail-dims must be an integer")
        flex_value = flex_raw
    if flex_value < 0:
        raise ValueError("x-fortran-flex-tail-dims must be >= 0")
    if flex_value == 0:
        return 0
    if type_info.category != "array":
        raise ValueError("x-fortran-flex-tail-dims is only supported for arrays")
    if flex_value > len(type_info.dimensions):
        raise ValueError("x-fortran-flex-tail-dims must not exceed array rank")
    if any(dim == ":" for dim in type_info.dimensions):
        raise ValueError(
            "x-fortran-flex-tail-dims does not support deferred-size dimensions"
        )
    return flex_value


def _collect_dimension_constants(
    dimensions: list[str],
    constants: dict[str, int | float] | None,
) -> list[str]:
    used: list[str] = []
    for dim in dimensions:
        if dim == ":" or _is_int_literal(dim):
            continue
        if not _FORTRAN_IDENTIFIER.match(dim):
            raise ValueError("array property 'x-fortran-shape' entries must be ints or identifiers")
        if constants is None or dim not in constants:
            raise ValueError(f"dimension constant '{dim}' is not defined in config")
        value = constants[dim]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"dimension constant '{dim}' must be an integer")
        if dim not in used:
            used.append(dim)
    return used


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
    dimensions: list[str] | None = None,
) -> str:
    intent = "intent(in)"
    parts = [type_info.arg_type_spec]
    arg_dimensions = dimensions if dimensions is not None else type_info.dimensions
    if arg_dimensions:
        dims = ", ".join(arg_dimensions)
        parts.append(f"dimension({dims})")
    if not is_required:
        parts.append(intent)
        parts.append("optional")
        decl = f"{', '.join(parts[:-1])}, {parts[-1]} :: {name}"
    else:
        parts.append(intent)
        decl = f"{', '.join(parts)} :: {name}"
    return decl


def _sentinel_comment(type_info: FieldTypeInfo, *, required: bool) -> str:
    label = "required" if required else "optional"
    category = type_info.category
    if category == "array":
        element = type_info.element_category or "array"
        return f" ! sentinel for {label} {element} array"
    if category == "string":
        if required:
            return " ! NULL string as sentinel for required string"
        return " ! sentinel for optional string"
    if category == "integer":
        return f" ! sentinel for {label} integer"
    if category == "real":
        return f" ! sentinel for {label} real"
    return ""


def _sentinel_expressions(
    type_info: FieldTypeInfo,
    *,
    var_ref: str,
    len_ref: str | None = None,
) -> tuple[str, str, bool]:
    category = type_info.category
    if category == "array":
        element = type_info.element_category
        if element == "string":
            length_ref = len_ref or var_ref
            value_expr = f"repeat(achar(0), len({length_ref}))"
            return value_expr, f"all({var_ref} == {value_expr})", False
        if element == "integer":
            return f"-huge({var_ref})", f"all({var_ref} == -huge({var_ref}))", False
        if element == "real":
            return (
                f"ieee_value({var_ref}, ieee_quiet_nan)",
                f"all(ieee_is_nan({var_ref}))",
                True,
            )
        if element == "boolean":
            raise ValueError("boolean arrays cannot use sentinels")
        raise ValueError(f"unsupported sentinel array element '{element}'")
    if category == "string":
        length_ref = len_ref or var_ref
        value_expr = f"repeat(achar(0), len({length_ref}))"
        return value_expr, f"{var_ref} == {value_expr}", False
    if category == "integer":
        return f"-huge({var_ref})", f"{var_ref} == -huge({var_ref})", False
    if category == "real":
        return (
            f"ieee_value({var_ref}, ieee_quiet_nan)",
            f"ieee_is_nan({var_ref})",
            True,
        )
    if category == "boolean":
        raise ValueError("boolean values cannot use sentinels")
    raise ValueError(f"unsupported sentinel category '{category}'")


def _element_missing_expression(
    category: str,
    *,
    var_ref: str,
    len_ref: str | None = None,
) -> tuple[str, bool]:
    if category == "string":
        length_ref = len_ref or var_ref
        return f"{var_ref} == repeat(achar(0), len({length_ref}))", False
    if category == "integer":
        return f"{var_ref} == -huge({var_ref})", False
    if category == "real":
        return f"ieee_is_nan({var_ref})", True
    raise ValueError(f"unsupported missing category '{category}'")


def _array_missing_conditions(
    element_category: str,
    *,
    var_ref: str,
    len_ref: str | None = None,
) -> tuple[str, str, bool]:
    missing_expr, uses_ieee = _element_missing_expression(
        element_category, var_ref=var_ref, len_ref=len_ref
    )
    return f"all({missing_expr})", f"any({missing_expr})", uses_ieee


def _slice_ref(name: str, rank: int, dim: int, index_var: str) -> str:
    dims = [":" for _ in range(rank)]
    dims[dim - 1] = index_var
    return f"this%{name}({', '.join(dims)})"


def _flex_bound_vars(dim: int) -> tuple[str, str]:
    return f"lb_{dim}", f"ub_{dim}"


def _slice_ref_bounds(
    name: str,
    rank: int,
    flex_dims: list[int],
    lb_vars: dict[int, str],
    ub_vars: dict[int, str],
) -> str:
    dims: list[str] = []
    for dim in range(1, rank + 1):
        if dim in flex_dims:
            dims.append(f"{lb_vars[dim]}:{ub_vars[dim]}")
        else:
            dims.append(":")
    return f"this%{name}({', '.join(dims)})"


def _render_flex_set_block(
    name: str,
    rank: int,
    flex_dim_count: int,
    bounds: list[dict[str, Any]],
) -> str:
    flex_dims = list(range(rank - flex_dim_count + 1, rank + 1))
    lb_vars = {entry["dim"]: entry["lb_var"] for entry in bounds}
    ub_vars = {entry["dim"]: entry["ub_var"] for entry in bounds}
    lines: list[str] = []
    for dim in range(1, rank - flex_dim_count + 1):
        lines.append(f"if (size({name}, {dim}) /= size(this%{name}, {dim})) then")
        lines.append("  status = NML_ERR_INVALID_INDEX")
        lines.append(
            f"  if (present(errmsg)) errmsg = \"dimension {dim} mismatch for '{name}'\""
        )
        lines.append("  return")
        lines.append("end if")
    for entry in bounds:
        dim = entry["dim"]
        lb_var = entry["lb_var"]
        ub_var = entry["ub_var"]
        lines.append(f"if (size({name}, {dim}) > size(this%{name}, {dim})) then")
        lines.append("  status = NML_ERR_INVALID_INDEX")
        lines.append(
            f"  if (present(errmsg)) errmsg = \"dimension {dim} exceeds bounds for '{name}'\""
        )
        lines.append("  return")
        lines.append("end if")
        lines.append(f"{lb_var} = lbound(this%{name}, {dim})")
        lines.append(f"{ub_var} = {lb_var} + size({name}, {dim}) - 1")
    lines.append(f"{_slice_ref_bounds(name, rank, flex_dims, lb_vars, ub_vars)} = {name}")
    return "\n".join(lines)


def _render_partial_set_block(name: str, rank: int, bounds: list[dict[str, Any]]) -> str:
    lb_vars = {entry["dim"]: entry["lb_var"] for entry in bounds}
    ub_vars = {entry["dim"]: entry["ub_var"] for entry in bounds}
    dims_all = [entry["dim"] for entry in bounds]
    lines: list[str] = []
    for entry in bounds:
        dim = entry["dim"]
        lb_var = entry["lb_var"]
        ub_var = entry["ub_var"]
        lines.append(f"if (size({name}, {dim}) > size(this%{name}, {dim})) then")
        lines.append("  status = NML_ERR_INVALID_INDEX")
        lines.append(
            f"  if (present(errmsg)) errmsg = \"dimension {dim} exceeds bounds for '{name}'\""
        )
        lines.append("  return")
        lines.append("end if")
        lines.append(f"{lb_var} = lbound(this%{name}, {dim})")
        lines.append(f"{ub_var} = {lb_var} + size({name}, {dim}) - 1")
    lines.append(f"{_slice_ref_bounds(name, rank, dims_all, lb_vars, ub_vars)} = {name}")
    return "\n".join(lines)


def _sort_bound_vars(values: set[str]) -> list[str]:
    def sort_key(name: str) -> tuple[str, int]:
        prefix, _, suffix = name.partition("_")
        try:
            return prefix, int(suffix)
        except ValueError:
            return prefix, 0

    return sorted(values, key=sort_key)


def _format_reshape_assignment(name: str, arguments: list[str]) -> str:
    lines = [f"this%{name} = reshape( &"]
    for index, arg in enumerate(arguments):
        suffix = ", &" if index < len(arguments) - 1 else ")"
        lines.append(f"  {arg}{suffix}")
    return "\n".join(lines)


def _format_default(
    value: Any,
    type_info: FieldTypeInfo,
    prop: dict[str, Any],
    constants: dict[str, int | float] | None = None,
) -> str:
    if type_info.category == "array":
        if not isinstance(value, list):
            raise ValueError("array default must be a list")
        parsed_dims = _parse_default_dimensions(type_info.dimensions, constants)
        array_default = _prepare_array_default(value, parsed_dims, prop)
        elements = [
            _format_scalar_default(element, type_info.kind, type_info.element_category)
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
        if "E" in literal:
            literal = literal.replace("E", "e")
        if "." not in literal and "e" not in literal:
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
        escaped = value.replace('"', '""')
        return f'"{escaped}"'
    raise ValueError(f"unsupported default category '{category}'")


def _parse_default_dimensions(
    dimensions: list[str],
    constants: dict[str, int | float] | None,
) -> list[int]:
    if not dimensions:
        raise ValueError("array property missing dimensions")
    parsed: list[int] = []
    for dim in dimensions:
        if dim == ":":
            raise ValueError("defaults not supported for deferred-size dimensions")
        try:
            parsed.append(int(dim))
        except (TypeError, ValueError) as err:  # pragma: no cover - defensive
            if constants is None or dim not in constants:
                raise ValueError(
                    "array default dimensions must be integer literals or defined constants"
                ) from err
            value = constants[dim]
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("array default dimension constants must be integers") from err
            parsed.append(value)
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
            pad_raw = [pad_raw]
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


def _enum_values(
    prop: dict[str, Any],
    type_info: FieldTypeInfo,
    constants: dict[str, int | float] | None,
) -> list[Any] | None:
    if type_info.category == "array":
        enum_raw = _array_items_enum(prop)
    else:
        enum_raw = prop.get("enum")
    if enum_raw is None:
        return None
    if not isinstance(enum_raw, list) or not enum_raw:
        raise ValueError("property enum must be a non-empty list")
    enum_values = _ensure_flat_scalar_list(enum_raw, "enum")
    category = _enum_category(type_info)
    if category not in {"integer", "string"}:
        raise ValueError("enum only supported for integer or string values")
    for value in enum_values:
        _validate_enum_scalar(value, category, "enum")
    _validate_enum_defaults(prop, type_info, enum_values, category, constants)
    _validate_enum_examples(prop, type_info, enum_values, category)
    return enum_values


def _bounds_spec(
    prop: dict[str, Any],
    type_info: FieldTypeInfo,
) -> dict[str, Any] | None:
    if type_info.category == "array":
        bounds_prop = _array_items_bounds(prop)
        category = type_info.element_category
    else:
        bounds_prop = prop
        category = type_info.category

    min_value, min_exclusive = _extract_bound_value(
        bounds_prop, "minimum", "exclusiveMinimum"
    )
    max_value, max_exclusive = _extract_bound_value(
        bounds_prop, "maximum", "exclusiveMaximum"
    )

    if min_value is None and max_value is None:
        return None

    if category not in {"integer", "real"}:
        raise ValueError("bounds only supported for integer or real values")

    if min_value is not None:
        _validate_bound_scalar(min_value, category, "minimum")
    if max_value is not None:
        _validate_bound_scalar(max_value, category, "maximum")

    if min_value is not None and max_value is not None:
        min_comp = float(min_value) if category == "real" else int(min_value)
        max_comp = float(max_value) if category == "real" else int(max_value)
        if min_exclusive or max_exclusive:
            if min_comp >= max_comp:
                raise ValueError("minimum must be less than maximum for exclusive bounds")
        else:
            if min_comp > max_comp:
                raise ValueError("minimum must be <= maximum")

    return {
        "min_value": min_value,
        "min_exclusive": min_exclusive,
        "max_value": max_value,
        "max_exclusive": max_exclusive,
        "category": category,
    }


def _extract_bound_value(
    prop: dict[str, Any],
    inclusive_key: str,
    exclusive_key: str,
) -> tuple[Any | None, bool]:
    has_inclusive = inclusive_key in prop
    has_exclusive = exclusive_key in prop
    if has_inclusive and has_exclusive:
        raise ValueError(
            f"property must not define both '{inclusive_key}' and '{exclusive_key}'"
        )
    if has_exclusive:
        value = prop.get(exclusive_key)
        if value is None:
            raise ValueError(f"{exclusive_key} must be a number")
        return value, True
    if has_inclusive:
        value = prop.get(inclusive_key)
        if value is None:
            raise ValueError(f"{inclusive_key} must be a number")
        return value, False
    return None, False


def _validate_bound_scalar(value: Any, category: str, label: str) -> None:
    if category == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{label} must be an integer")
        return
    if category == "real":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{label} must be a number")
        if math.isinf(float(value)):
            raise ValueError(f"{label} must not be infinite")
        if math.isnan(float(value)):
            raise ValueError(f"{label} must not be NaN")
        return
    raise ValueError("bounds only supported for integer or real values")


def _array_default_value(prop: dict[str, Any]) -> tuple[Any, bool] | None:
    if prop.get("type") != "array":
        raise ValueError("array default lookup requires array properties")

    default_defined = "default" in prop
    items_default = _array_items_default(prop)
    items_defined = "default" in items_default
    items_value = items_default.get("default") if items_defined else None

    if default_defined and items_defined:
        raise ValueError("array default must be defined on property or items, not both")

    if items_defined:
        for key in ("x-fortran-default-order", "x-fortran-default-repeat", "x-fortran-default-pad"):
            if key in prop:
                raise ValueError("array items default must not use x-fortran-default-* options")
        if isinstance(items_value, list):
            raise ValueError("array items default must be a scalar")
        return items_value, True

    if default_defined:
        default_value = prop.get("default")
        if not isinstance(default_value, list):
            raise ValueError("array default must be a list")
        return default_value, False
    return None


def _array_items_enum(prop: dict[str, Any]) -> list[Any] | None:
    current = prop
    while current.get("type") == "array":
        if "enum" in current:
            raise ValueError("array enum must be defined on items")
        items = current.get("items")
        if not isinstance(items, dict):
            raise ValueError("array property must define 'items'")
        current = items
    return current.get("enum")


def _array_items_default(prop: dict[str, Any]) -> dict[str, Any]:
    current = prop
    while current.get("type") == "array":
        items = current.get("items")
        if not isinstance(items, dict):
            raise ValueError("array property must define 'items'")
        if items.get("type") == "array":
            raise ValueError("nested array properties are not supported; use x-fortran-shape")
        current = items
    return current


def _array_items_bounds(prop: dict[str, Any]) -> dict[str, Any]:
    current = prop
    while current.get("type") == "array":
        for key in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
            if key in current:
                raise ValueError("array bounds must be defined on items")
        items = current.get("items")
        if not isinstance(items, dict):
            raise ValueError("array property must define 'items'")
        if items.get("type") == "array":
            raise ValueError("nested array properties are not supported; use x-fortran-shape")
        current = items
    return current


def _validate_enum_scalar(value: Any, category: str, label: str) -> None:
    if category == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{label} values must be integers")
        return
    if category == "string":
        if not isinstance(value, str):
            raise ValueError(f"{label} values must be strings")
        return
    raise ValueError("enum only supported for integer or string values")


def _ensure_enum_member(value: Any, enum_values: list[Any], category: str, label: str) -> None:
    _validate_enum_scalar(value, category, label)
    if value not in enum_values:
        raise ValueError(f"{label} value must be one of enum values")


def _validate_enum_defaults(
    prop: dict[str, Any],
    type_info: FieldTypeInfo,
    enum_values: list[Any],
    category: str,
    constants: dict[str, int | float] | None,
) -> None:
    if type_info.category == "array":
        array_default = _array_default_value(prop)
        if array_default is None:
            return
        default_value, default_from_items = array_default
        if default_from_items and isinstance(default_value, list):
            raise ValueError("array items default must be a scalar")
        if isinstance(default_value, list):
            values = _ensure_flat_scalar_list(default_value, "array default")
            _parse_default_dimensions(type_info.dimensions, constants)
            for value in values:
                _ensure_enum_member(value, enum_values, category, "default")
        else:
            _ensure_enum_member(default_value, enum_values, category, "default")
        pad_raw = prop.get("x-fortran-default-pad")
        if pad_raw is not None:
            pad_values = pad_raw if isinstance(pad_raw, list) else [pad_raw]
            pad_values = _ensure_flat_scalar_list(pad_values, "array default pad")
            for value in pad_values:
                _ensure_enum_member(value, enum_values, category, "pad")
        return
    if "default" not in prop:
        return
    default_value = prop["default"]
    if isinstance(default_value, list):
        raise ValueError("scalar default must not be a list")
    _ensure_enum_member(default_value, enum_values, category, "default")


def _validate_enum_examples(
    prop: dict[str, Any],
    type_info: FieldTypeInfo,
    enum_values: list[Any],
    category: str,
) -> None:
    examples = prop.get("examples")
    if examples is None:
        return
    if not isinstance(examples, list):
        raise ValueError("property examples must be a list")
    for example in examples:
        if type_info.category == "array":
            if isinstance(example, list):
                values = _ensure_flat_scalar_list(example, "array examples")
                for value in values:
                    _ensure_enum_member(value, enum_values, category, "example")
            else:
                _ensure_enum_member(example, enum_values, category, "example")
        else:
            if isinstance(example, list):
                raise ValueError("scalar examples must not be lists")
            _ensure_enum_member(example, enum_values, category, "example")
