"""Tests for Markdown generation."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


def _import_generate_docs():
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    sys.path.insert(0, str(src))
    try:
        module = importlib.import_module("nml_tools.codegen_markdown")
    finally:
        sys.path.pop(0)
    return module.generate_docs


def test_generate_docs_accepts_runtime_dimensions_for_shapes(tmp_path: Path) -> None:
    schema = {
        "title": "Runtime dimension docs",
        "x-fortran-namelist": "runtime_nml",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "items": {"type": "integer", "default": 1},
                "x-fortran-shape": "n_values",
            }
        },
    }

    output = tmp_path / "runtime.md"
    generate_docs = _import_generate_docs()
    generate_docs(schema, output, dimensions={"n_values": 3})

    rendered = output.read_text()
    assert "integer, dimension(n_values)" in rendered
    assert "Default: `1`" in rendered


def test_generate_docs_rejects_runtime_dimensions_for_string_lengths(
    tmp_path: Path,
) -> None:
    schema = {
        "title": "Runtime dimension length docs",
        "x-fortran-namelist": "runtime_nml",
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "x-fortran-len": "n_values",
            }
        },
    }

    output = tmp_path / "runtime.md"
    generate_docs = _import_generate_docs()

    try:
        generate_docs(schema, output, dimensions={"n_values": 3})
    except ValueError as exc:
        assert "dimension 'n_values' cannot be used as x-fortran-len" in str(exc)
    else:
        raise AssertionError("expected runtime dimension in string length to fail")


def test_generate_docs_shows_items_default(tmp_path: Path) -> None:
    schema = {
        "title": "Items default docs",
        "x-fortran-namelist": "grid_nml",
        "type": "object",
        "properties": {
            "grid": {
                "type": "array",
                "items": {"type": "integer", "default": 7},
                "x-fortran-shape": 3,
            }
        },
    }

    output = tmp_path / "grid.md"
    generate_docs = _import_generate_docs()
    generate_docs(schema, output)

    rendered = output.read_text()
    assert "Default: `7`" in rendered
    assert "(repeated)" not in rendered


def test_generate_docs_shows_bounds(tmp_path: Path) -> None:
    schema = {
        "title": "Bounds docs",
        "x-fortran-namelist": "bounds_nml",
        "type": "object",
        "properties": {
            "tolerance": {
                "type": "number",
                "minimum": 0.0,
                "exclusiveMaximum": 1.0,
            },
            "counts": {
                "type": "array",
                "x-fortran-shape": 2,
                "items": {"type": "integer", "minimum": 1},
            },
        },
    }

    output = tmp_path / "bounds.md"
    generate_docs = _import_generate_docs()
    generate_docs(schema, output)

    rendered = output.read_text()
    assert "Minimum: `>= 0.0`" in rendered
    assert "Maximum: `< 1.0`" in rendered
    assert "Minimum: `>= 1`" in rendered


def test_generate_docs_adds_doxygen_id_and_toc(tmp_path: Path) -> None:
    schema = {
        "title": "TOC docs",
        "x-fortran-namelist": "config_optimize",
        "type": "object",
        "properties": {"value": {"type": "integer"}},
    }

    output = tmp_path / "toc.md"
    generate_docs = _import_generate_docs()
    generate_docs(
        schema,
        output,
        md_doxygen_id_from_name=True,
        md_add_toc_statement=True,
    )

    lines = output.read_text().splitlines()
    assert lines[0] == "# TOC docs {#config_optimize}"
    assert lines[1] == ""
    assert lines[2] == "[TOC]"
