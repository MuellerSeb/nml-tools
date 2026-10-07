"""Cross-source generation scope regressions."""

from __future__ import annotations

import pytest

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
