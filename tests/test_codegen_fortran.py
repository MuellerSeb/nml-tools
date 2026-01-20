"""Tests for Fortran code generation."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - python<3.11
    import tomli as tomllib


def _import_generate_fortran():
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    sys.path.insert(0, str(src))
    try:
        module = importlib.import_module("nml_tools.codegen_fortran")
    finally:
        sys.path.pop(0)
    return module.generate_fortran


def _import_load_schema():
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    sys.path.insert(0, str(src))
    try:
        module = importlib.import_module("nml_tools.schema")
    finally:
        sys.path.pop(0)
    return module.load_schema


def test_generate_fortran_matches_reference(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    fixture_root = root / "tests" / "fixtures" / "01_simple"
    schema_path = fixture_root / "optimization.yml"
    expected_path = fixture_root / "out" / "nml_optimization.f90"
    config_path = fixture_root / "nml-config.toml"

    with config_path.open("rb") as handle:
        config = tomllib.load(handle)
    kinds = config["kinds"]
    kind_module = kinds["module"]
    kind_map = kinds["map"]
    kind_allowlist = set(kinds["real"] + kinds["integer"])
    constants_raw = config.get("constants", {})
    if not isinstance(constants_raw, dict):
        raise ValueError("config constants must be a table")
    constants: dict[str, int | float] = {}
    for name, entry in constants_raw.items():
        if not isinstance(entry, dict) or "value" not in entry:
            raise ValueError("config constant entries must define a value")
        value = entry.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("config constants must be integers or reals")
        constants[name] = value
    doc_raw = config.get("documentation")
    if doc_raw is None:
        module_doc = None
    elif not isinstance(doc_raw, dict):
        raise ValueError("config documentation must be a table")
    else:
        module_raw = doc_raw.get("module")
        if not isinstance(module_raw, str):
            raise ValueError("config documentation module must be a string")
        module_doc = module_raw.strip() or None

    load_schema = _import_load_schema()
    schema = load_schema(schema_path)
    output = tmp_path / "nml_optimization.f90"

    generate_fortran = _import_generate_fortran()
    generate_fortran(
        schema,
        output,
        kind_module=kind_module,
        kind_map=kind_map,
        kind_allowlist=kind_allowlist,
        constants=constants,
        module_doc=module_doc,
    )

    generated = output.read_text()
    expected = expected_path.read_text()

    assert generated == expected


def test_generate_fortran_allows_scalar_array_default(tmp_path: Path) -> None:
    schema = {
        "title": "Scalar array default",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "items": {"type": "integer", "x-fortran-kind": "i4"},
                "x-fortran-shape": 3,
                "x-fortran-default-repeat": True,
                "default": 1,
            }
        },
    }

    output = tmp_path / "nml_test.f90"
    generate_fortran = _import_generate_fortran()
    generate_fortran(schema, output, kind_module="mo_kind")

    generated = output.read_text()
    assert "integer(i4), parameter, public :: values_default = 1_i4" in generated
    assert "this%values = values_default" in generated


def test_generate_fortran_accepts_dimension_constants(tmp_path: Path) -> None:
    schema = {
        "title": "Constant shapes",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "items": {"type": "integer", "x-fortran-kind": "i4"},
                "x-fortran-shape": "max_layers",
                "x-fortran-default-repeat": True,
                "default": 1,
            }
        },
    }

    output = tmp_path / "nml_test.f90"
    generate_fortran = _import_generate_fortran()
    generate_fortran(
        schema,
        output,
        kind_module="mo_kind",
        constants={"max_layers": 3},
    )

    generated = output.read_text()
    assert "dimension(max_layers)" in generated
    assert "use nml_helper, only:" in generated
    assert "max_layers" in generated
    assert "integer(i4), parameter, public :: values_default = 1_i4" in generated
    assert "this%values = values_default" in generated


def test_generate_fortran_requires_array_shape(tmp_path: Path) -> None:
    schema = {
        "title": "Missing shape",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "items": {"type": "integer", "x-fortran-kind": "i4"},
            }
        },
    }

    generate_fortran = _import_generate_fortran()
    with pytest.raises(ValueError, match=r".*x-fortran-shape"):
        generate_fortran(schema, tmp_path / "nml_test.f90", kind_module="mo_kind")


def test_generate_fortran_rejects_nested_arrays(tmp_path: Path) -> None:
    schema = {
        "title": "Nested arrays",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "x-fortran-shape": 2,
                "items": {
                    "type": "array",
                    "x-fortran-shape": 3,
                    "items": {"type": "integer", "x-fortran-kind": "i4"},
                },
            }
        },
    }

    generate_fortran = _import_generate_fortran()
    with pytest.raises(ValueError, match=r".*nested array properties"):
        generate_fortran(schema, tmp_path / "nml_test.f90", kind_module="mo_kind")


def test_generate_fortran_requires_dimension_constants(tmp_path: Path) -> None:
    schema = {
        "title": "Missing constant",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "items": {"type": "integer", "x-fortran-kind": "i4"},
                "x-fortran-shape": "max_layers",
            }
        },
    }

    generate_fortran = _import_generate_fortran()
    with pytest.raises(
        ValueError,
        match=r".*dimension constant 'max_layers' is not defined in config",
    ):
        generate_fortran(schema, tmp_path / "nml_test.f90", kind_module="mo_kind")


def test_generate_fortran_accepts_string_length_constants(tmp_path: Path) -> None:
    schema = {
        "title": "String length constants",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "x-fortran-len": "name_len",
            }
        },
    }

    output = tmp_path / "nml_test.f90"
    generate_fortran = _import_generate_fortran()
    generate_fortran(
        schema,
        output,
        kind_module="mo_kind",
        constants={"name_len": 32},
    )

    generated = output.read_text()
    assert "character(len=name_len) :: name" in generated
    assert "use nml_helper, only:" in generated
    assert "name_len" in generated


def test_generate_fortran_array_default_pad_order(tmp_path: Path) -> None:
    schema = {
        "title": "Array default pad",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "matrix": {
                "type": "array",
                "items": {"type": "integer", "x-fortran-kind": "i4"},
                "x-fortran-shape": [2, 2],
                "x-fortran-default-order": "C",
                "x-fortran-default-pad": 0,
                "default": [1, 2, 3],
            }
        },
    }

    output = tmp_path / "nml_test.f90"
    generate_fortran = _import_generate_fortran()
    generate_fortran(schema, output, kind_module="mo_kind")

    generated = output.read_text()
    assert "matrix_default(3) = [1_i4, 2_i4, 3_i4]" in generated
    assert "matrix_pad = 0_i4" in generated
    assert "order=[2, 1]" in generated
    assert "pad=[matrix_pad]" in generated


def test_generate_fortran_allows_plain_kinds(tmp_path: Path) -> None:
    schema = {
        "title": "Plain kinds",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "count": {"type": "integer"},
            "ratio": {"type": "number"},
        },
    }

    output = tmp_path / "nml_test.f90"
    generate_fortran = _import_generate_fortran()
    generate_fortran(schema, output, kind_module="mo_kind")

    generated = output.read_text()
    assert "integer :: count" in generated
    assert "real :: ratio" in generated
