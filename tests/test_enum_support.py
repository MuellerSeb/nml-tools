"""Tests for enum support in generators."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


def _import_generate_fortran():
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    sys.path.insert(0, str(src))
    try:
        module = importlib.import_module("nml_tools.codegen_fortran")
    finally:
        sys.path.pop(0)
    return module.generate_fortran


def _import_generate_docs():
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    sys.path.insert(0, str(src))
    try:
        module = importlib.import_module("nml_tools.codegen_markdown")
    finally:
        sys.path.pop(0)
    return module.generate_docs


def _import_render_template():
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    sys.path.insert(0, str(src))
    try:
        module = importlib.import_module("nml_tools.codegen_template")
    finally:
        sys.path.pop(0)
    return module.render_template


def test_generate_fortran_emits_enum_helpers(tmp_path: Path) -> None:
    schema = {
        "title": "Enum test",
        "x-fortran-namelist": "enum_nml",
        "type": "object",
        "properties": {
            "method": {
                "type": "string",
                "x-fortran-len": 8,
                "enum": ["A", "B"],
            },
            "try_methods": {
                "type": "array",
                "x-fortran-shape": 2,
                "items": {
                    "type": "string",
                    "x-fortran-len": 8,
                    "enum": ["A", "B"],
                },
            },
            "sizes": {
                "type": "array",
                "x-fortran-shape": 3,
                "items": {"type": "integer", "enum": [1, 2, 3]},
            },
        },
        "required": ["method"],
    }

    output = tmp_path / "nml_enum.f90"
    generate_fortran = _import_generate_fortran()
    generate_fortran(schema, output)

    generated = output.read_text()
    assert "method_enum_values(2)" in generated
    assert "try_methods_enum_values(2)" in generated
    assert "sizes_enum_values(3)" in generated
    assert "elemental logical function method_in_enum" in generated
    assert "all(try_methods_in_enum(this%try_methods, allow_missing=.true.))" in generated
    assert "all(sizes_in_enum(this%sizes, allow_missing=.true.))" in generated


def test_generate_fortran_rejects_array_enum_at_top_level(tmp_path: Path) -> None:
    schema = {
        "title": "Bad enum",
        "x-fortran-namelist": "bad_nml",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "x-fortran-shape": 2,
                "enum": [1, 2],
                "items": {"type": "integer"},
            }
        },
    }

    generate_fortran = _import_generate_fortran()
    with pytest.raises(ValueError, match=r".*array enum must be defined on items"):
        generate_fortran(schema, tmp_path / "nml_bad.f90")


def test_template_uses_enum_fallback_value() -> None:
    schema = {
        "title": "Enum template",
        "x-fortran-namelist": "enum_nml",
        "type": "object",
        "properties": {"method": {"type": "string", "x-fortran-len": 4, "enum": ["DDS", "MCMC"]}},
    }

    render_template = _import_render_template()
    rendered = render_template([schema], doc_mode="plain", value_mode="filled")

    assert "method = 'DDS'" in rendered


def test_generate_docs_includes_enum_values_and_example(tmp_path: Path) -> None:
    schema = {
        "title": "Enum docs",
        "x-fortran-namelist": "enum_nml",
        "type": "object",
        "properties": {"method": {"type": "string", "x-fortran-len": 4, "enum": ["DDS", "MCMC"]}},
    }

    output = tmp_path / "enum.md"
    generate_docs = _import_generate_docs()
    generate_docs(schema, output)

    rendered = output.read_text()
    assert "`'DDS'`" in rendered
    assert "`'MCMC'`" in rendered
    assert "method = 'DDS'" in rendered
