"""f2py and Python wrapper code generation."""

from __future__ import annotations

import keyword
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, cast

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ._utils import strip_trailing_whitespace
from .codegen_fortran import (
    FieldSpec,
    FieldTypeInfo,
    _array_default_value,
    _build_context,
    _field_type_info,
    _normalize_constant_values,
    _parse_default_dimensions,
    _parse_flex_dim,
    _reject_runtime_dimension_lengths,
    _validate_runtime_dimensions,
)

_TEMPLATE_ENV = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent / "templates"),
    trim_blocks=True,
    lstrip_blocks=False,
    keep_trailing_newline=True,
    undefined=StrictUndefined,
)


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
    constants: dict[str, int | float] | None = None,
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
    constants: dict[str, int | float] | None = None,
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
        {"imports": sorted(extension_modules), "classes": classes, "py_style": py_style}
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
    constants: dict[str, int | float] | None = None,
    dimensions: dict[str, int] | None = None,
) -> F2pyKindUsage:
    """Collect schema kind aliases used in f2py wrapper arguments."""
    usage = F2pyKindUsage(real=set(), integer=set())
    for schema in schemas:
        for _, type_info in _iter_field_type_infos(schema, constants, dimensions):
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
    constants: dict[str, int | float] | None = None,
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
    properties = _normalized_properties(schema)
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
    for field in fields:
        type_info = type_infos[field.name]
        prop = properties[field.name]
        rank = len(type_info.dimensions) if type_info.category == "array" else 0
        has_flag = None if field.required else f"has_{field.name}"
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
            fixed_shape=_fixed_python_array_shape(prop, type_info, constants, dimensions),
        )
        if field.required:
            required_args.append(spec)
        else:
            optional_args.append(spec)
        field_arguments, field_declarations = _f2py_field_arguments(field, type_info)
        argument_list.extend(field_arguments)
        argument_declarations.extend(field_declarations)
        if rank > 0:
            dim_names = _array_dimension_argument_names(field.name, rank)
            array_dimensions.append(
                F2pyArrayDimensionSpec(field_name=field.name, names=dim_names)
            )
        if has_flag is not None:
            argument_list.append(has_flag)
            argument_declarations.append(
                f"logical, intent(in) :: {has_flag} !< whether {field.name} was provided"
            )
            bridge_declarations.append(_optional_bridge_declaration(field.name, type_info))
            bridge_assignments.append(_optional_bridge_assignment(field.name, type_info))
            set_call_arguments.append(f"{field.name}=maybe_{field.name}")
        else:
            set_call_arguments.append(f"{field.name}={field.name}")

    runtime_dimension_args = cast("list[dict[str, str]]", context["set_dims_arguments"])
    for entry in runtime_dimension_args:
        const_name = entry["name"]
        arg_name = entry["arg_name"]
        python_name = _python_parameter_name(const_name)
        has_flag = f"has_{const_name}"
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
        maybe_name = f"maybe_{const_name}"
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
    )


def _iter_field_type_infos(
    schema: dict[str, Any],
    constants: dict[str, int | float] | None,
    dimensions: dict[str, int] | None = None,
) -> list[tuple[str, FieldTypeInfo]]:
    properties = _normalized_properties(schema)
    constants = _normalize_constant_values(constants)
    runtime_dimension_values = _validate_runtime_dimensions(dimensions)
    overlap = sorted(set(constants) & set(runtime_dimension_values))
    if overlap:
        raise ValueError(
            "constants and dimensions must not share names: " + ", ".join(overlap)
        )
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
        if not isinstance(prop, dict):
            raise ValueError(f"property '{raw_name}' must be an object")
        name = raw_name.lower()
        if name in seen:
            raise ValueError(f"duplicate property '{raw_name}'")
        seen.add(name)
        normalized[name] = prop
    return normalized


def _fixed_python_array_shape(
    prop: dict[str, Any],
    type_info: FieldTypeInfo,
    constants: dict[str, int | float] | None,
    dimensions: dict[str, int] | None = None,
) -> list[int] | None:
    if type_info.category != "array":
        return None
    if _array_default_value(prop) is not None:
        return None
    if _parse_flex_dim(prop, type_info) > 0:
        return None
    constants = _normalize_constant_values(constants)
    dimensions = _validate_runtime_dimensions(dimensions)
    overlap = sorted(set(constants) & set(dimensions))
    if overlap:
        raise ValueError(
            "constants and dimensions must not share names: " + ", ".join(overlap)
        )
    for dim in type_info.dimensions:
        if dim.lower() in dimensions:
            return None
    shape_constants: dict[str, int | float] = {**constants, **dimensions}
    return _parse_default_dimensions(type_info.dimensions, shape_constants)


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
    return [f"{name}_n{idx}" for idx in range(1, rank + 1)]


def _f2py_field_arguments(
    field: FieldSpec,
    type_info: FieldTypeInfo,
) -> tuple[list[str], list[str]]:
    requirement = "required" if field.required else "optional"
    if type_info.category != "array":
        return [field.name], [
            f"{type_info.arg_type_spec}, intent(in) :: {field.name} "
            f"!< {_one_line(field.title)} ({requirement})"
        ]

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


def _optional_bridge_declaration(name: str, type_info: FieldTypeInfo) -> str:
    if type_info.category == "array":
        dims = ", ".join(":" for _ in type_info.dimensions)
        if type_info.element_category == "string":
            return f"character(len=:), dimension({dims}), allocatable :: maybe_{name}"
        return f"{type_info.arg_type_spec}, dimension({dims}), allocatable :: maybe_{name}"
    if type_info.category == "string":
        return f"character(len=:), allocatable :: maybe_{name}"
    return f"{type_info.arg_type_spec}, allocatable :: maybe_{name}"


def _optional_bridge_assignment(name: str, type_info: FieldTypeInfo) -> str:
    has_flag = f"has_{name}"
    maybe_name = f"maybe_{name}"
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
