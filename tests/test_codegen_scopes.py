"""Cross-source generation scope regressions."""

from __future__ import annotations

import pytest

from nml_tools.codegen_f2py import build_f2py_namelist_spec, render_f2py_wrappers
from nml_tools.codegen_fortran import (
    ConstantSpec,
    collect_local_derived_types,
    render_fortran,
    render_helper,
)
from nml_tools.schema import resolve_schema


def _schema(
    type_name: str = "period_t", module: str | None = None, kind: str | None = None
) -> dict:
    derived = {
        "type": "object",
        "x-fortran-type": type_name,
        "properties": {"size": {"type": "integer"}, "present": {"type": "integer"}},
    }
    if module is not None:
        derived["x-fortran-module"] = module
    if kind is not None:
        derived["properties"]["size"]["x-fortran-kind"] = kind
    return resolve_schema(
        {
            "type": "object",
            "x-fortran-namelist": "Run",
            "properties": {"value": derived},
        }
    )


def test_helper_constant_type_conflict_is_case_insensitive() -> None:
    local_types = collect_local_derived_types([_schema()])
    with pytest.raises(
        ValueError, match="local derived type 'period_t'.*helper constant 'PERIOD_T'"
    ):
        render_helper(
            file_name="helper.f90",
            local_derived_types=local_types,
            constants=[ConstantSpec("PERIOD_T", "integer", "2", None)],
        )


def test_helper_type_kind_conflict() -> None:
    local_types = collect_local_derived_types([_schema("i4", kind="i4")])
    with pytest.raises(ValueError, match="local derived type 'i4'.*imported symbol 'i4'"):
        render_helper(
            file_name="helper.f90",
            local_derived_types=local_types,
            kind_map={"i4": "int32"},
            kind_allowlist={"int32"},
        )


def test_helper_reuses_identical_definition_without_duplicate_declaration() -> None:
    schema = _schema()
    local_types = collect_local_derived_types([schema, schema])
    assert len(local_types) == 1
    helper = render_helper(file_name="helper.f90", local_derived_types=local_types * 2)
    assert helper.count("type, public :: period_t") == 1


def test_reader_rejects_property_matching_group() -> None:
    with pytest.raises(ValueError, match="property 'rUN'.*namelist group 'Run'.*read__from_file"):
        render_fortran(
            {
                "x-fortran-namelist": "Run",
                "type": "object",
                "properties": {"rUN": {"type": "integer"}},
            },
            file_name="run.f90",
        )


def test_qualified_intrinsic_components_and_repeated_imports_remain_supported() -> None:
    schema = _schema("status", "application_types")
    schema["properties"]["second"] = schema["properties"]["value"]
    native = render_fortran(schema, file_name="run.f90")
    assert native.count("use application_types, only: status") == 1
    assert "%size" in native and "%present" in native


@pytest.mark.parametrize("kind", ["val", "allow_missing", "in_enum", "in_bounds"])
def test_constraint_helpers_do_not_shadow_kind_imports(kind: str) -> None:
    native = render_fortran(
        {
            "type": "object",
            "x-fortran-namelist": "Run",
            "properties": {
                "choice": {
                    "type": "integer",
                    "x-fortran-kind": kind,
                    "enum": [1, 2],
                    "minimum": 1,
                }
            },
        },
        file_name="run.f90",
        kind_map={kind: "int32"},
        kind_allowlist={"int32"},
    )
    assert f"integer({kind}), intent(in) :: nml__val" in native
    assert "present(nml__allow_missing)" in native
    assert "result(nml__in_enum)" in native
    assert "result(nml__in_bounds)" in native
    assert "if (nml__val == -huge(nml__val))" in native


def test_helper_state_uses_reserved_internal_names() -> None:
    helper = render_helper(file_name="helper.f90")
    assert "result(nml__status)" in helper
    assert "iostat=nml__iostat, iomsg=nml__iomsg" in helper
    assert "this%is_open = (nml__iostat == 0)" in helper
    assert "function to__lower(nml__string)" in helper
    assert "function idx__check(nml__idx, nml__extents, nml__field, errmsg)" in helper


def test_reader_group_cannot_shadow_public_error_dummy() -> None:
    with pytest.raises(
        ValueError, match="'x-fortran-namelist'.*reserved for the generated Fortran API"
    ):
        render_fortran(
            {
                "type": "object",
                "x-fortran-namelist": "ErrMsg",
                "properties": {"value": {"type": "integer"}},
            },
            file_name="errmsg.f90",
        )


@pytest.mark.parametrize("name", ["present", "PrEsEnT", "size", "transfer", "TrAnSfEr"])
def test_native_generation_rejects_intrinsic_namelist_group_names(name: str) -> None:
    with pytest.raises(ValueError, match="'x-fortran-namelist'.*reserved as a Fortran intrinsic"):
        render_fortran(
            {
                "type": "object",
                "x-fortran-namelist": name,
                "properties": {"value": {"type": "integer"}},
            },
            file_name="group.f90",
        )


@pytest.mark.parametrize("name", ["transfer", "TrAnSfEr"])
@pytest.mark.parametrize("source", ["kind", "derived_type"])
def test_handle_resolver_rejects_transfer_imports(name: str, source: str) -> None:
    if source == "kind":
        schema = {
            "type": "object",
            "x-fortran-namelist": "run",
            "properties": {"value": {"type": "integer", "x-fortran-kind": name}},
        }
        options = {"kind_map": {name: "int32"}, "kind_allowlist": {"int32"}}
    else:
        schema = {
            "type": "object",
            "x-fortran-namelist": "run",
            "properties": {
                "value": {
                    "type": "object",
                    "x-fortran-type": name,
                    "x-fortran-module": "application_types",
                    "properties": {"code": {"type": "integer"}},
                }
            },
        }
        options = {}
    with pytest.raises(ValueError, match="reserved as a Fortran intrinsic"):
        render_fortran(schema, file_name="run.f90", f2py_handle_helpers=True, **options)


@pytest.mark.parametrize("name", ["c_intptr_t", "c_ptr", "c_null_ptr", "c_f_pointer"])
def test_resolver_dependencies_do_not_restrict_schema_fields(name: str) -> None:
    schema = {
        "type": "object",
        "x-fortran-namelist": "run",
        "properties": {name: {"type": "integer"}},
    }
    native = render_fortran(schema, file_name="run.f90", f2py_handle_helpers=True)
    assert "use iso_c_binding" not in native.split("contains", maxsplit=1)[0]
    assert f"integer, intent(in), optional :: {name}" in native
    spec = build_f2py_namelist_spec(schema)
    arg = spec.optional_args[0]
    assert arg.name == name
    assert arg.abi_name == ("c_intptr_t__value" if name == "c_intptr_t" else name)


@pytest.mark.parametrize("name", ["c_intptr_t", "c_ptr", "c_null_ptr", "c_f_pointer"])
def test_resolver_dependencies_do_not_restrict_runtime_dimensions(name: str) -> None:
    schema = {
        "type": "object",
        "x-fortran-namelist": "run",
        "properties": {
            "values": {
                "type": "array",
                "items": {"type": "integer"},
                "x-fortran-shape": name,
            }
        },
    }
    native = render_fortran(
        schema, file_name="run.f90", dimensions={name: 2}, f2py_handle_helpers=True
    )
    assert f"integer, intent(in), optional :: {name}" in native
    spec = build_f2py_namelist_spec(schema, dimensions={name: 2})
    assert spec.set_dims_args[0].name == name
    wrapper = render_f2py_wrappers([schema], file_name="wrapper.f90", dimensions={name: 2})
    if name == "c_intptr_t":
        assert "c_intptr_t__value" in wrapper


@pytest.mark.parametrize("source", ["helper", "kind", "derived_type"])
def test_native_module_rejects_self_use(source: str) -> None:
    options = {}
    if source == "derived_type":
        schema = _schema("status", "NML_RUN")
    else:
        schema = {
            "type": "object",
            "x-fortran-namelist": "run",
            "properties": {"value": {"type": "integer"}},
        }
        if source == "helper":
            options["helper_module"] = "NML_RUN"
        else:
            options["kind_module"] = "NML_RUN"
            schema["properties"]["value"]["x-fortran-kind"] = "int32"
    with pytest.raises(ValueError, match="module 'nml_[Rr]un' cannot USE itself"):
        render_fortran(schema, file_name="run.f90", **options)


def test_default_helper_module_conflicts_with_helper_namelist() -> None:
    with pytest.raises(ValueError, match="module 'nml_helper' cannot USE itself"):
        render_fortran(
            {
                "type": "object",
                "x-fortran-namelist": "helper",
                "properties": {"value": {"type": "integer"}},
            },
            file_name="helper.f90",
        )
    native = render_fortran(
        {
            "type": "object",
            "x-fortran-namelist": "helper",
            "properties": {"value": {"type": "integer"}},
        },
        file_name="helper.f90",
        helper_module="helper_support",
    )
    assert "module nml_helper" in native
    assert "use helper_support" in native


def test_helper_rejects_self_use_of_kind_module() -> None:
    with pytest.raises(ValueError, match="module 'shared_kinds' cannot USE itself"):
        render_helper(
            file_name="helper.f90",
            module_name="shared_kinds",
            kind_module="SHARED_KINDS",
            local_derived_types=collect_local_derived_types([_schema(kind="int32")]),
        )


@pytest.mark.parametrize("source", ["helper", "kind"])
def test_wrapper_rejects_self_use(source: str) -> None:
    if source == "helper":
        schema = _schema()
        options = {"helper_module": "F2PY_RUN"}
    else:
        schema = {
            "type": "object",
            "x-fortran-namelist": "run",
            "properties": {"value": {"type": "integer", "x-fortran-kind": "int32"}},
        }
        options = {"kind_module": "F2PY_RUN"}
    with pytest.raises(ValueError, match="module 'f2py_[Rr]un' cannot USE itself"):
        render_f2py_wrappers([schema], file_name="wrapper.f90", **options)


def test_unused_kind_or_helper_module_configuration_is_not_a_self_use() -> None:
    schema = {
        "type": "object",
        "x-fortran-namelist": "run",
        "properties": {"value": {"type": "integer"}},
    }
    native = render_fortran(schema, file_name="run.f90", kind_module="NML_RUN")
    assert "use NML_RUN" not in native
    helper = render_helper(file_name="helper.f90", kind_module="NML_HELPER")
    assert "use NML_HELPER" not in helper
    wrapper = render_f2py_wrappers(
        [schema], file_name="wrapper.f90", helper_module="F2PY_RUN", kind_module="F2PY_RUN"
    )
    assert "use F2PY_RUN" not in wrapper


@pytest.mark.parametrize("name", ["file", "name", "idx", "filled"])
@pytest.mark.parametrize("source", ["kind", "derived_type"])
def test_control_procedures_allow_shadowing_unused_schema_imports(name: str, source: str) -> None:
    if source == "derived_type":
        schema = _schema(name, "application_types")
        options = {}
    else:
        schema = {
            "type": "object",
            "x-fortran-namelist": "Run",
            "properties": {"value": {"type": "integer", "x-fortran-kind": name}},
        }
        options = {"kind_map": {name: "int32"}, "kind_allowlist": {"int32"}}
    schema["properties"]["values"] = {
        "type": "array",
        "items": {"type": "integer"},
        "x-fortran-shape": 2,
        "x-fortran-flex-tail-dims": 1,
    }
    native = render_fortran(schema, file_name="run.f90", f2py_handle_helpers=True, **options)
    assert "_filled_shape(nml__obj, name, filled, errmsg)" in native
