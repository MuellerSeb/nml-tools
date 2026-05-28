"""f2py and Python wrapper code generation."""

from __future__ import annotations

import hashlib
import keyword
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, cast

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ._utils import (
    normalize_constant_values,
    normalize_runtime_dimensions,
    reject_constant_dimension_overlap,
    strip_trailing_whitespace,
    validate_user_fortran_identifier,
)
from .codegen_fortran import (
    FieldSpec,
    FieldTypeInfo,
    _build_context,
    _derived_schema,
    _derived_type_name,
    _field_type_info,
    _reject_runtime_dimension_lengths,
)

_TEMPLATE_ENV = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent / "templates"),
    trim_blocks=True,
    lstrip_blocks=False,
    keep_trailing_newline=True,
    undefined=StrictUndefined,
)


@dataclass
class F2pyDerivedLeafSpec:
    """An intrinsic ABI leaf flattened from a derived Python argument."""

    name: str
    encoded_name: str
    has_name: str
    rank: int
    numpy_dtype: str | None
    dummy_value: str


@dataclass
class F2pyArgumentSpec:
    """Python wrapper argument metadata."""

    name: str
    title: str
    required: bool
    rank: int
    numpy_dtype: str | None
    dummy_value: str
    doc_type: str
    requirement: str
    has_flag: str | None = None
    fixed_shape: list[int] | None = None
    python_name: str | None = None
    derived_leaves: list[F2pyDerivedLeafSpec] | None = None
    derived_type_name: str | None = None


@dataclass
class F2pyArrayDimensionSpec:
    """Dimension arguments for a f2py-visible array dummy."""

    field_name: str
    names: list[str]


@dataclass
class F2pyNamelistSpec:
    """Metadata needed for f2py wrapper generation."""

    namelist_name: str
    brief: str
    details: str
    details_lines: list[str]
    module_name: str
    type_name: str
    helper_module: str
    kind_module: str
    kind_imports: list[str]
    f2py_module_name: str
    resolve_handle_name: str
    handle_ctype: str
    errmsg_len: int
    argument_list: list[str]
    argument_declarations: list[str]
    bridge_declarations: list[str]
    bridge_assignments: list[str]
    set_call_arguments: list[str]
    set_dims_argument_list: list[str]
    set_dims_argument_declarations: list[str]
    set_dims_bridge_declarations: list[str]
    set_dims_bridge_assignments: list[str]
    set_dims_call_arguments: list[str]
    set_dims_args: list[F2pyArgumentSpec]
    array_dimensions: list[F2pyArrayDimensionSpec]
    required_args: list[F2pyArgumentSpec]
    optional_args: list[F2pyArgumentSpec]
    all_args: list[F2pyArgumentSpec]
    derived_type_names: list[str]


@dataclass
class PythonWrapperSpec:
    """Metadata needed for Python wrapper generation."""

    class_name: str
    namelist_name: str
    brief: str
    f2py_module_name: str
    extension_module: str
    required_args: list[F2pyArgumentSpec]
    optional_args: list[F2pyArgumentSpec]
    all_args: list[F2pyArgumentSpec]
    set_dims_args: list[F2pyArgumentSpec]


@dataclass
class F2pyKindUsage:
    """Kind aliases used by f2py wrapper dummy arguments."""

    real: set[str]
    integer: set[str]


@dataclass
class F2pyCTypeMap:
    """Explicit C type mapping for f2py kinds."""

    real: dict[str, str]
    integer: dict[str, str]


def generate_f2py_wrappers(
    schemas: Iterable[dict[str, Any]],
    output: str | Path,
    *,
    helper_module: str = "nml_helper",
    kind_module: str | None = None,
    kind_map: dict[str, str] | None = None,
    kind_allowlist: Iterable[str] | None = None,
    constants: dict[str, int] | None = None,
    dimensions: dict[str, int] | None = None,
    errmsg_len: int = 1024,
) -> None:
    """Generate f2py-facing Fortran wrappers for *schemas* at *output*."""
    output_path = Path(output)
    rendered = render_f2py_wrappers(
        schemas,
        file_name=output_path.name,
        helper_module=helper_module,
        kind_module=kind_module,
        kind_map=kind_map,
        kind_allowlist=kind_allowlist,
        constants=constants,
        dimensions=dimensions,
        errmsg_len=errmsg_len,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="ascii")


def render_f2py_wrappers(
    schemas: Iterable[dict[str, Any]],
    *,
    file_name: str,
    helper_module: str = "nml_helper",
    kind_module: str | None = None,
    kind_map: dict[str, str] | None = None,
    kind_allowlist: Iterable[str] | None = None,
    constants: dict[str, int] | None = None,
    dimensions: dict[str, int] | None = None,
    errmsg_len: int = 1024,
) -> str:
    """Render f2py-facing Fortran wrappers for *schemas*."""
    specs = [
        build_f2py_namelist_spec(
            schema,
            helper_module=helper_module,
            kind_module=kind_module,
            kind_map=kind_map,
            kind_allowlist=kind_allowlist,
            constants=constants,
            dimensions=dimensions,
            errmsg_len=errmsg_len,
        )
        for schema in schemas
    ]
    rendered = _TEMPLATE_ENV.get_template("f2py_wrappers.f90.j2").render(
        {"file_name": file_name, "specs": specs}
    )
    return strip_trailing_whitespace(rendered)


def generate_python_wrappers(
    specs: Iterable[tuple[F2pyNamelistSpec, str]],
    output: str | Path,
    *,
    py_style: str = "numpy",
) -> None:
    """Generate Python wrapper classes for f2py namelist *specs* at *output*."""
    rendered = render_python_wrappers(specs, py_style=py_style)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="ascii")


def render_python_wrappers(
    specs: Iterable[tuple[F2pyNamelistSpec, str]],
    *,
    py_style: str = "numpy",
) -> str:
    """Render Python wrapper classes for f2py namelist *specs*."""
    if py_style not in {"numpy", "doxygen"}:
        raise ValueError("python documentation style must be 'numpy' or 'doxygen'")
    spec_entries = list(specs)
    extension_modules: set[str] = set()
    for _, extension_module in spec_entries:
        _validate_python_module_name(extension_module)
        extension_modules.add(extension_module)
    classes: list[PythonWrapperSpec] = []
    for spec, extension_module in spec_entries:
        classes.append(
            PythonWrapperSpec(
                class_name=_class_name(spec.namelist_name),
                namelist_name=spec.namelist_name,
                brief=spec.brief,
                f2py_module_name=spec.f2py_module_name,
                extension_module=extension_module,
                required_args=spec.required_args,
                optional_args=spec.optional_args,
                all_args=spec.all_args,
                set_dims_args=spec.set_dims_args,
            )
        )
    rendered = _TEMPLATE_ENV.get_template("python_wrappers.py.j2").render(
        {
            "imports": sorted(extension_modules),
            "classes": classes,
            "py_style": py_style,
            "uses_derived": any(
                arg.derived_leaves is not None
                for cls in classes
                for arg in cls.all_args
            ),
        }
    )
    return strip_trailing_whitespace(rendered)


def generate_f2cmap(
    output: str | Path,
    usage: F2pyKindUsage,
    c_types: F2pyCTypeMap,
) -> None:
    """Generate a .f2py_f2cmap file for the explicitly mapped *usage*."""
    rendered = render_f2cmap(usage, c_types)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="ascii")


def render_f2cmap(
    usage: F2pyKindUsage,
    c_types: F2pyCTypeMap,
) -> str:
    """Render a .f2py_f2cmap file for the explicitly mapped *usage*."""
    missing_real = sorted(usage.real - set(c_types.real))
    missing_integer = sorted(usage.integer - set(c_types.integer))
    if missing_real:
        raise ValueError("missing f2py real C type mappings: " + ", ".join(missing_real))
    if missing_integer:
        raise ValueError(
            "missing f2py integer C type mappings: " + ", ".join(missing_integer)
        )

    integer_map = dict(c_types.integer)
    integer_map.setdefault("c_intptr_t", "long_long")
    real_items = ", ".join(
        f"{name}={c_types.real[name]!r}" for name in sorted(usage.real)
    )
    integer_items = ", ".join(
        f"{name}={integer_map[name]!r}" for name in sorted(usage.integer | {"c_intptr_t"})
    )
    return f"dict(real=dict({real_items}), integer=dict({integer_items}))\n"


def collect_f2py_kind_usage(
    schemas: Iterable[dict[str, Any]],
    *,
    constants: dict[str, int] | None = None,
    dimensions: dict[str, int] | None = None,
) -> F2pyKindUsage:
    """Collect schema kind aliases used in f2py wrapper arguments."""
    usage = F2pyKindUsage(real=set(), integer=set())
    runtime_dimension_values = normalize_runtime_dimensions(dimensions)
    for schema in schemas:
        properties = _normalized_properties(schema)
        field_infos = _iter_field_type_infos(schema, constants, dimensions)
        expanded: list[FieldTypeInfo] = []
        for name, type_info in field_infos:
            derived = _derived_schema(properties[name])
            if derived is None:
                expanded.append(type_info)
                continue
            components = derived.get("properties")
            if not isinstance(components, dict):
                continue
            for component in components.values():
                if isinstance(component, dict):
                    _reject_runtime_dimension_lengths(component, runtime_dimension_values)
                    expanded.append(
                        _field_type_info(component, normalize_constant_values(constants))
                    )
        for type_info in expanded:
            category = (
                type_info.element_category
                if type_info.category == "array"
                else type_info.category
            )
            if type_info.kind is None:
                continue
            if category == "real":
                usage.real.add(type_info.kind)
            elif category == "integer":
                usage.integer.add(type_info.kind)
    return usage


def merge_f2py_kind_usage(usages: Iterable[F2pyKindUsage]) -> F2pyKindUsage:
    """Merge multiple f2py kind usage objects."""
    merged = F2pyKindUsage(real=set(), integer=set())
    for usage in usages:
        merged.real.update(usage.real)
        merged.integer.update(usage.integer)
    return merged


def build_f2py_namelist_spec(
    schema: dict[str, Any],
    *,
    helper_module: str = "nml_helper",
    kind_module: str | None = None,
    kind_map: dict[str, str] | None = None,
    kind_allowlist: Iterable[str] | None = None,
    constants: dict[str, int] | None = None,
    dimensions: dict[str, int] | None = None,
    errmsg_len: int = 1024,
) -> F2pyNamelistSpec:
    """Build f2py wrapper metadata for one namelist schema."""
    context = _build_context(
        schema,
        helper_module=helper_module,
        kind_module=kind_module,
        kind_map=kind_map,
        kind_allowlist=kind_allowlist,
        constants=constants,
        dimensions=dimensions,
        module_doc=None,
    )
    fields = cast("list[FieldSpec]", context["fields"])
    type_infos = {
        name: type_info
        for name, type_info in _iter_field_type_infos(schema, constants, dimensions)
    }
    required_args: list[F2pyArgumentSpec] = []
    optional_args: list[F2pyArgumentSpec] = []
    argument_list: list[str] = []
    argument_declarations: list[str] = []
    bridge_declarations: list[str] = []
    bridge_assignments: list[str] = []
    set_call_arguments: list[str] = []
    set_dims_argument_list: list[str] = []
    set_dims_argument_declarations: list[str] = []
    set_dims_bridge_declarations: list[str] = []
    set_dims_bridge_assignments: list[str] = []
    set_dims_call_arguments: list[str] = []
    set_dims_args: list[F2pyArgumentSpec] = []
    array_dimensions: list[F2pyArrayDimensionSpec] = []
    derived_type_names: list[str] = []

    field_argument_names: set[str] = {"handle", "status", "errmsg"}
    field_argument_names.update(field.name.lower() for field in fields)

    argument_names_in_use: set[str] = set(field_argument_names)
    bridge_names_in_use: set[str] = set(field_argument_names) | {
        "handle",
        "status",
        "errmsg",
        "this",
    }

    for field in fields:
        type_info = type_infos[field.name]
        rank = len(type_info.dimensions) if type_info.category == "array" else 0
        prop = _normalized_properties(schema)[field.name]
        derived = _derived_schema(prop)
        if derived is not None:
            dim_names: list[str] = []
            if rank:
                for dim_name in _array_dimension_argument_names(field.name, rank):
                    generated_dim_name = _unique_generated_name(dim_name, argument_names_in_use)
                    argument_names_in_use.add(generated_dim_name.lower())
                    dim_names.append(generated_dim_name)
            derived_type_name = _derived_type_name(derived)
            if derived_type_name.lower() not in {
                name.lower() for name in derived_type_names
            }:
                derived_type_names.append(derived_type_name)
            leaves = _f2py_derived_leaves(
                field.name,
                derived,
                type_info,
                constants,
                argument_names_in_use,
            )
            outer_has_flag: str | None = None
            if not field.required:
                outer_has_flag = _unique_generated_name(
                    f"has__{field.name}", argument_names_in_use
                )
                argument_names_in_use.add(outer_has_flag.lower())
                argument_list.append(outer_has_flag)
                argument_declarations.append(
                    f"logical, intent(in) :: {outer_has_flag} "
                    f"!< whether {field.name} was provided"
                )
            spec = F2pyArgumentSpec(
                name=field.name,
                title=_one_line(field.title),
                required=field.required,
                rank=rank,
                numpy_dtype=None,
                dummy_value="None",
                doc_type=("sequence of mappings" if rank else "mapping"),
                requirement="required" if field.required else "optional",
                has_flag=outer_has_flag,
                derived_leaves=leaves,
                derived_type_name=derived_type_name,
            )
            if field.required:
                required_args.append(spec)
            else:
                optional_args.append(spec)
            if rank:
                argument_list.extend(dim_names)
                argument_declarations.extend(
                    f"integer, intent(in) :: {dim_name} !< extent for {field.name}"
                    for dim_name in dim_names
                )
                array_dimensions.append(
                    F2pyArrayDimensionSpec(field_name=field.name, names=dim_names)
                )
            for leaf in leaves:
                argument_list.append(leaf.encoded_name)
                if rank:
                    dims = ", ".join(dim_names)
                    leaf_type = _field_type_info(
                        cast("dict[str, Any]", derived["properties"][leaf.name]),
                        normalize_constant_values(constants),
                    )
                    argument_declarations.append(
                        f"{leaf_type.arg_type_spec}, dimension({dims}), intent(in) :: "
                        f"{leaf.encoded_name} !< {field.name}%{leaf.name}"
                    )
                    argument_list.append(leaf.has_name)
                    argument_declarations.append(
                        f"logical, dimension({dims}), intent(in) :: {leaf.has_name} "
                        f"!< provided mask for {field.name}%{leaf.name}"
                    )
                else:
                    leaf_type = _field_type_info(
                        cast("dict[str, Any]", derived["properties"][leaf.name]),
                        normalize_constant_values(constants),
                    )
                    argument_declarations.append(
                        f"{leaf_type.arg_type_spec}, intent(in) :: {leaf.encoded_name} "
                        f"!< {field.name}%{leaf.name}"
                    )
                    argument_list.append(leaf.has_name)
                    argument_declarations.append(
                        f"logical, intent(in) :: {leaf.has_name} "
                        f"!< whether {field.name}%{leaf.name} was provided"
                    )
            bridge_names_in_use.update(argument_names_in_use)
            maybe_name = _unique_generated_name(
                _maybe_bridge_name(field.name), bridge_names_in_use
            )
            bridge_names_in_use.add(maybe_name.lower())
            bridge_declarations.extend(
                _derived_bridge_declarations(maybe_name, derived_type_name, rank, field.required)
            )
            bridge_assignments.extend(
                _derived_bridge_assignments(
                    field.name,
                    maybe_name,
                    leaves,
                    rank,
                    field.required,
                    outer_has_flag,
                    dim_names,
                    init_allocates_array=field.runtime_sized_array,
                )
            )
            set_call_arguments.append(f"{field.name}={maybe_name}")
            continue
        has_flag: str | None = None
        dim_names = []
        if rank:
            for dim_name in _array_dimension_argument_names(field.name, rank):
                generated_dim_name = _unique_generated_name(dim_name, argument_names_in_use)
                argument_names_in_use.add(generated_dim_name.lower())
                dim_names.append(generated_dim_name)
        if not field.required:
            has_base = f"has__{field.name}"
            has_flag = _unique_generated_name(has_base, argument_names_in_use)
            argument_names_in_use.add(has_flag.lower())
        spec = F2pyArgumentSpec(
            name=field.name,
            title=_one_line(field.title),
            required=field.required,
            rank=rank,
            numpy_dtype=_numpy_dtype(type_info),
            dummy_value=_python_dummy_value(type_info),
            doc_type=_python_doc_type(type_info),
            requirement="required" if field.required else "optional",
            has_flag=has_flag,
        )
        if field.required:
            required_args.append(spec)
        else:
            optional_args.append(spec)
        field_arguments, field_declarations = _f2py_field_arguments(
            field, type_info, dim_names=dim_names
        )
        argument_list.extend(field_arguments)
        argument_declarations.extend(field_declarations)
        if rank > 0:
            array_dimensions.append(
                F2pyArrayDimensionSpec(field_name=field.name, names=dim_names)
            )
        if has_flag is not None:
            argument_list.append(has_flag)
            argument_declarations.append(
                f"logical, intent(in) :: {has_flag} !< whether {field.name} was provided"
            )
            bridge_names_in_use.update(argument_names_in_use)
            maybe_base = _maybe_bridge_name(field.name)
            maybe_name = _unique_generated_name(maybe_base, bridge_names_in_use)
            bridge_names_in_use.add(maybe_name.lower())
            bridge_declarations.append(
                _optional_bridge_declaration(field.name, type_info, maybe_name)
            )
            bridge_assignments.append(
                _optional_bridge_assignment(field.name, type_info, has_flag, maybe_name)
            )
            set_call_arguments.append(f"{field.name}={maybe_name}")
        else:
            set_call_arguments.append(f"{field.name}={field.name}")

    runtime_dimension_args = cast("list[dict[str, str]]", context["set_dims_arguments"])
    set_dims_argument_names_in_use: set[str] = {
        str(entry["name"]).lower() for entry in runtime_dimension_args
    }
    set_dims_bridge_names_in_use: set[str] = set(set_dims_argument_names_in_use) | {
        "handle",
        "status",
        "errmsg",
        "this",
    }

    for entry in runtime_dimension_args:
        const_name = entry["name"]
        arg_name = entry["arg_name"]
        python_name = _python_parameter_name(const_name)
        has_base = f"has__{const_name}"
        has_flag = _unique_generated_name(has_base, set_dims_argument_names_in_use)
        set_dims_argument_names_in_use.add(has_flag.lower())
        set_dims_args.append(
            F2pyArgumentSpec(
                name=const_name,
                title=f"Runtime dimension override for {const_name}",
                required=False,
                rank=0,
                numpy_dtype="int",
                dummy_value="0",
                doc_type="int",
                requirement="optional",
                has_flag=has_flag,
                fixed_shape=None,
                python_name=python_name,
            )
        )
        set_dims_argument_list.append(const_name)
        set_dims_argument_declarations.append(
            f"integer, intent(in) :: {const_name} !< runtime dimension override for {const_name}"
        )
        set_dims_argument_list.append(has_flag)
        set_dims_argument_declarations.append(
            f"logical, intent(in) :: {has_flag} !< whether {const_name} was provided"
        )
        maybe_base = _maybe_bridge_name(const_name)
        maybe_name = _unique_generated_name(maybe_base, set_dims_bridge_names_in_use)
        set_dims_bridge_names_in_use.add(maybe_name.lower())
        set_dims_bridge_declarations.append(f"integer, allocatable :: {maybe_name}")
        set_dims_bridge_assignments.append(
            f"if ({has_flag}) then\n"
            f"  allocate({maybe_name})\n"
            f"  {maybe_name} = {const_name}\n"
            "end if"
        )
        set_dims_call_arguments.append(f"{arg_name}={maybe_name}")

    namelist_name = cast("str", context["namelist_name"])
    details = cast("str", context["details_text"])
    return F2pyNamelistSpec(
        namelist_name=namelist_name,
        brief=_one_line(cast("str", context["brief_text"])),
        details=details,
        details_lines=details.splitlines() or [details],
        module_name=cast("str", context["module_name"]),
        type_name=cast("str", context["type_name"]),
        helper_module=helper_module,
        kind_module=cast("str", context["kind_module"]),
        kind_imports=cast("list[str]", context["kind_imports"]),
        f2py_module_name=f"f2py_{namelist_name}",
        resolve_handle_name=f"{context['module_name']}_resolve_handle",
        handle_ctype="c_intptr_t",
        errmsg_len=errmsg_len,
        argument_list=argument_list,
        argument_declarations=argument_declarations,
        bridge_declarations=bridge_declarations,
        bridge_assignments=bridge_assignments,
        set_call_arguments=set_call_arguments,
        set_dims_argument_list=set_dims_argument_list,
        set_dims_argument_declarations=set_dims_argument_declarations,
        set_dims_bridge_declarations=set_dims_bridge_declarations,
        set_dims_bridge_assignments=set_dims_bridge_assignments,
        set_dims_call_arguments=set_dims_call_arguments,
        set_dims_args=set_dims_args,
        array_dimensions=array_dimensions,
        required_args=required_args,
        optional_args=optional_args,
        all_args=required_args + optional_args,
        derived_type_names=derived_type_names,
    )


def _iter_field_type_infos(
    schema: dict[str, Any],
    constants: dict[str, int] | None,
    dimensions: dict[str, int] | None = None,
) -> list[tuple[str, FieldTypeInfo]]:
    properties = _normalized_properties(schema)
    constants = normalize_constant_values(constants)
    runtime_dimension_values = normalize_runtime_dimensions(dimensions)
    reject_constant_dimension_overlap(constants, runtime_dimension_values)
    field_types: list[tuple[str, FieldTypeInfo]] = []
    for name, prop in properties.items():
        _reject_runtime_dimension_lengths(prop, runtime_dimension_values)
        field_types.append((name, _field_type_info(prop, constants)))
    return field_types


def _normalized_properties(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("schema must define object 'properties'")
    normalized: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for raw_name, prop in properties.items():
        if not isinstance(raw_name, str):
            raise ValueError("property names must be strings")
        validate_user_fortran_identifier(raw_name, label=f"property '{raw_name}'")
        if not isinstance(prop, dict):
            raise ValueError(f"property '{raw_name}' must be an object")
        name = raw_name.lower()
        if name in seen:
            raise ValueError(f"duplicate property '{raw_name}'")
        seen.add(name)
        normalized[name] = prop
    return normalized


def _class_name(namelist_name: str) -> str:
    parts = [part for part in re.split(r"[^0-9A-Za-z]+", namelist_name) if part]
    if not parts:
        return "Namelist"
    name = "".join(part[:1].upper() + part[1:] for part in parts)
    if name[0].isdigit():
        name = f"Namelist{name}"
    if keyword.iskeyword(name):
        name = f"{name}Namelist"
    return name


def _python_parameter_name(name: str) -> str:
    if not name.isidentifier():
        raise ValueError(f"name '{name}' is not a valid Python identifier")
    if keyword.iskeyword(name):
        return f"{name}_"
    return name


def _numpy_dtype(type_info: FieldTypeInfo) -> str | None:
    category = (
        type_info.element_category
        if type_info.category == "array"
        else type_info.category
    )
    if category == "real":
        return "float"
    if category == "integer":
        return "int"
    if category == "boolean":
        return "bool"
    if category == "string":
        return "str"
    return None


def _python_dummy_value(type_info: FieldTypeInfo) -> str:
    category = (
        type_info.element_category
        if type_info.category == "array"
        else type_info.category
    )
    if category == "real":
        return "0.0"
    if category == "integer":
        return "0"
    if category == "boolean":
        return "False"
    if category == "string":
        return '""'
    return "None"


def _python_doc_type(type_info: FieldTypeInfo) -> str:
    category = (
        type_info.element_category
        if type_info.category == "array"
        else type_info.category
    )
    if category == "real":
        type_name = "float"
    elif category == "integer":
        type_name = "int"
    elif category == "boolean":
        type_name = "bool"
    elif category == "string":
        type_name = "str"
    else:
        type_name = "Any"
    if type_info.category == "array":
        return f"array_like of {type_name}"
    return type_name


def _one_line(value: str) -> str:
    return " ".join(value.splitlines()).strip()


def _array_dimension_argument_names(name: str, rank: int) -> list[str]:
    return [f"{name}__n{idx}" for idx in range(1, rank + 1)]


def _unique_generated_name(base_name: str, taken_names: set[str]) -> str:
    candidate = _bounded_generated_name(base_name)
    if candidate.lower() not in taken_names:
        return candidate
    index = 1
    while True:
        candidate = _bounded_generated_name(f"{base_name}_{index}")
        if candidate.lower() not in taken_names:
            return candidate
        index += 1


def _bounded_generated_name(base_name: str) -> str:
    if len(base_name) <= 63:
        return base_name
    suffix = hashlib.sha1(base_name.encode("ascii")).hexdigest()[:10]
    return f"{base_name[:52]}_{suffix}"


def _maybe_bridge_name(name: str) -> str:
    return f"maybe__{name}"


def _f2py_field_arguments(
    field: FieldSpec,
    type_info: FieldTypeInfo,
    *,
    dim_names: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    requirement = "required" if field.required else "optional"
    if type_info.category != "array":
        return [field.name], [
            f"{type_info.arg_type_spec}, intent(in) :: {field.name} "
            f"!< {_one_line(field.title)} ({requirement})"
        ]

    if dim_names is None:
        dim_names = _array_dimension_argument_names(field.name, len(type_info.dimensions))
    dims = ", ".join(dim_names)
    declarations = [
        f"integer, intent(in) :: {dim_name} !< extent for {field.name}"
        for dim_name in dim_names
    ]
    declarations.append(
        f"{type_info.arg_type_spec}, dimension({dims}), intent(in) :: {field.name} "
        f"!< {_one_line(field.title)} ({requirement})"
    )
    return [*dim_names, field.name], declarations


def _f2py_derived_leaves(
    field_name: str,
    derived: dict[str, Any],
    type_info: FieldTypeInfo,
    constants: dict[str, int] | None,
    argument_names_in_use: set[str],
) -> list[F2pyDerivedLeafSpec]:
    properties = derived.get("properties")
    if not isinstance(properties, dict):
        raise ValueError(f"derived property '{field_name}' must define properties")
    rank = len(type_info.dimensions) if type_info.category == "array" else 0
    static_constants = normalize_constant_values(constants)
    leaves: list[F2pyDerivedLeafSpec] = []
    for name, prop in properties.items():
        if not isinstance(name, str) or not isinstance(prop, dict):
            raise ValueError(f"derived property '{field_name}' components must be objects")
        leaf_info = _field_type_info(prop, static_constants)
        encoded_name = _unique_generated_name(f"{field_name}__{name}", argument_names_in_use)
        argument_names_in_use.add(encoded_name.lower())
        has_name = _unique_generated_name(f"has__{encoded_name}", argument_names_in_use)
        argument_names_in_use.add(has_name.lower())
        leaves.append(
            F2pyDerivedLeafSpec(
                name=name,
                encoded_name=encoded_name,
                has_name=has_name,
                rank=rank,
                numpy_dtype=_numpy_dtype(leaf_info),
                dummy_value=_python_dummy_value(leaf_info),
            )
        )
    return leaves


def _derived_bridge_declarations(
    maybe_name: str,
    type_name: str,
    rank: int,
    required: bool,
) -> list[str]:
    if rank:
        dims = ", ".join(":" for _ in range(rank))
        return [f"type({type_name}), dimension({dims}), allocatable :: {maybe_name}"]
    if required:
        return [f"type({type_name}) :: {maybe_name}"]
    return [f"type({type_name}), allocatable :: {maybe_name}"]


def _derived_bridge_assignments(
    name: str,
    maybe_name: str,
    leaves: list[F2pyDerivedLeafSpec],
    rank: int,
    required: bool,
    outer_has_flag: str | None,
    dim_names: list[str],
    *,
    init_allocates_array: bool,
) -> list[str]:
    lines: list[str] = []
    gated = not required
    if gated:
        if outer_has_flag is None:
            raise ValueError(f"optional derived property '{name}' is missing presence metadata")
        lines.append(f"if ({outer_has_flag}) then")
        indent = "  "
        if rank == 0:
            lines.append(f"  allocate({maybe_name})")
    else:
        indent = ""
    if rank and not init_allocates_array:
        dims = ", ".join(dim_names)
        lines.append(f"{indent}allocate({maybe_name}({dims}))")
    lines.append(f"{indent}status = this%init_type({name}={maybe_name}, errmsg=errmsg)")
    lines.append(f"{indent}if (status /= NML_OK) return")
    if rank:
        if init_allocates_array:
            for dim_index, dim_name in enumerate(dim_names, start=1):
                lines.extend(
                    [
                        f"{indent}if ({dim_name} > size({maybe_name}, {dim_index})) then",
                        f"{indent}  status = NML_ERR_INVALID_INDEX",
                        f'{indent}  errmsg = "dimension {dim_index} exceeds bounds for \'{name}\'"',
                        f"{indent}  return",
                        f"{indent}end if",
                    ]
                )
        bounds = ", ".join(f"1:{dim_name}" for dim_name in dim_names)
        for leaf in leaves:
            lines.append(f"{indent}where ({leaf.has_name})")
            lines.append(
                f"{indent}  {maybe_name}({bounds})%{leaf.name} = {leaf.encoded_name}"
            )
            lines.append(f"{indent}end where")
    else:
        for leaf in leaves:
            lines.append(
                f"{indent}if ({leaf.has_name}) "
                f"{maybe_name}%{leaf.name} = {leaf.encoded_name}"
            )
    if gated:
        lines.append("end if")
    return ["\n".join(lines)]


def _optional_bridge_declaration(name: str, type_info: FieldTypeInfo, maybe_name: str) -> str:
    if type_info.category == "array":
        dims = ", ".join(":" for _ in type_info.dimensions)
        if type_info.element_category == "string":
            return f"character(len=:), dimension({dims}), allocatable :: {maybe_name}"
        return f"{type_info.arg_type_spec}, dimension({dims}), allocatable :: {maybe_name}"
    if type_info.category == "string":
        return f"character(len=:), allocatable :: {maybe_name}"
    return f"{type_info.arg_type_spec}, allocatable :: {maybe_name}"


def _optional_bridge_assignment(
    name: str,
    type_info: FieldTypeInfo,
    has_flag: str,
    maybe_name: str,
) -> str:
    if type_info.category == "array":
        dims = ", ".join(_array_dimension_argument_names(name, len(type_info.dimensions)))
        allocate_stmt = f"allocate({maybe_name}({dims}))"
        if type_info.element_category == "string":
            allocate_stmt = f"allocate(character(len=len({name})) :: {maybe_name}({dims}))"
        return (
            f"if ({has_flag}) then\n"
            f"  {allocate_stmt}\n"
            f"  {maybe_name} = {name}\n"
            "end if"
        )
    if type_info.category == "string":
        return (
            f"if ({has_flag}) then\n"
            f"  {maybe_name} = {name}\n"
            "end if"
        )
    return (
        f"if ({has_flag}) then\n"
        f"  allocate({maybe_name})\n"
        f"  {maybe_name} = {name}\n"
        "end if"
    )


def _validate_python_module_name(module_name: str) -> None:
    if not module_name.isidentifier() or keyword.iskeyword(module_name):
        raise ValueError(
            f"f2py extension module name '{module_name}' must be a valid Python identifier"
        )
