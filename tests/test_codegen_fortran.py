"""Tests for Fortran code generation."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

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
    schema_path = root / "examples" / "optimization.yml"
    expected_path = root / "examples" / "nml_optimization.f90"
    config_path = root / "nml-config.toml"

    with config_path.open("rb") as handle:
        config = tomllib.load(handle)
    kinds = config["kinds"]
    kind_module = kinds["module"]
    kind_map = kinds["map"]
    kind_allowlist = set(kinds["real"] + kinds["integer"])

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
    assert "reshape([1_i4], shape=[3], pad=[1_i4])" in generated
