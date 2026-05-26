"""Tests for template generation."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from nml_tools.schema import resolve_schema


def _import_render_template():
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    sys.path.insert(0, str(src))
    try:
        module = importlib.import_module("nml_tools.codegen_template")
    finally:
        sys.path.pop(0)
    return module.render_template


def test_render_template_accepts_runtime_dimensions_for_shapes() -> None:
    schema = {
        "title": "Runtime dimension template",
        "x-fortran-namelist": "runtime_nml",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "items": {"type": "integer", "default": 7},
                "x-fortran-shape": "n_values",
            }
        },
    }

    render_template = _import_render_template()
    rendered = render_template(
        [schema],
        doc_mode="plain",
        value_mode="filled",
        dimensions={"n_values": 3},
    )

    assert "values(:) = 7" in rendered


def test_render_template_rejects_runtime_dimensions_for_string_lengths() -> None:
    schema = {
        "title": "Runtime dimension length template",
        "x-fortran-namelist": "runtime_nml",
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "x-fortran-len": "n_values",
            }
        },
    }

    render_template = _import_render_template()
    try:
        render_template(
            [schema],
            doc_mode="plain",
            value_mode="filled",
            dimensions={"n_values": 3},
        )
    except ValueError as exc:
        assert "dimension 'n_values' cannot be used as x-fortran-len" in str(exc)
    else:
        raise AssertionError("expected runtime dimension in string length to fail")


def test_render_template_minimal_filled_overrides_default() -> None:
    schema = {
        "title": "Minimal filled overrides",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "alpha": {"type": "integer", "default": 1},
            "beta": {"type": "integer", "default": 2},
        },
    }

    render_template = _import_render_template()
    rendered = render_template(
        [schema],
        doc_mode="plain",
        value_mode="minimal-filled",
        values={"test_nml": {"beta": 9}},
    )

    assert "beta = 9" in rendered
    assert "alpha =" not in rendered


def test_render_template_array_default_slices() -> None:
    schema = {
        "title": "Array defaults",
        "x-fortran-namelist": "grid_nml",
        "type": "object",
        "properties": {
            "grid": {
                "type": "array",
                "items": {"type": "integer"},
                "x-fortran-shape": [2, 3],
                "default": [1, 2, 3, 4, 5, 6],
            }
        },
    }

    render_template = _import_render_template()
    rendered = render_template(
        [schema],
        doc_mode="plain",
        value_mode="filled",
    )

    assert "grid(:,1) = 1, 2" in rendered
    assert "grid(:,2) = 3, 4" in rendered
    assert "grid(:,3) = 5, 6" in rendered
    assert "(:, " not in rendered


def test_render_template_items_default() -> None:
    schema = {
        "title": "Items default",
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

    render_template = _import_render_template()
    rendered = render_template([schema], doc_mode="plain", value_mode="filled")

    assert "grid(:) = 7" in rendered


def test_render_template_derived_values_use_component_syntax_and_nested_overrides() -> None:
    schema = resolve_schema(
        {
            "x-fortran-namelist": "run",
            "type": "object",
            "$defs": {
                "period": {
                    "type": "object",
                    "x-fortran-type": "period_t",
                    "properties": {
                        "start_year": {"type": "integer", "default": 1900},
                        "label": {"type": "string", "x-fortran-len": 8, "default": "base"},
                    },
                }
            },
            "properties": {
                "period": {"$ref": "#/$defs/period"},
                "periods": {
                    "type": "array",
                    "x-fortran-shape": 2,
                    "items": {"$ref": "#/$defs/period"},
                },
            },
        }
    )

    rendered = _import_render_template()(
        [schema],
        value_mode="filled",
        values={
            "run": {
                "period": {"start_year": 2001, "label": "eval"},
                "periods": [{"start_year": 1980}, {"start_year": 2001, "label": "future"}],
            }
        },
    )

    assert "period%start_year = 2001" in rendered
    assert 'period%label = "eval"' in rendered
    assert "periods(1)%start_year = 1980" in rendered
    assert 'periods(1)%label = "base"' in rendered
    assert 'periods(2)%label = "future"' in rendered
