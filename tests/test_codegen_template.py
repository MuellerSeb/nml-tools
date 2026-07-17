"""Tests for template generation."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from nml_tools._namelist_eval import evaluate_group
from nml_tools._namelist_parser import parse_namelist
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


def test_render_template_documented_metadata_header() -> None:
    schema = {
        "title": "Run",
        "x-fortran-namelist": "run",
        "type": "object",
        "properties": {"steps": {"type": "integer", "default": 1}},
    }

    rendered = _import_render_template()(
        [schema],
        doc_mode="documented",
        value_mode="filled",
        title="Main template",
        description="Line one\nLine two",
    )

    assert rendered.startswith("! Main template\n!\n! Line one\n! Line two\n\n! Run\n&run")


def test_render_template_plain_omits_metadata_header() -> None:
    schema = {
        "title": "Run",
        "x-fortran-namelist": "run",
        "type": "object",
        "properties": {"steps": {"type": "integer", "default": 1}},
    }

    rendered = _import_render_template()(
        [schema],
        doc_mode="plain",
        value_mode="filled",
        title="Main template",
        description="Line one",
    )

    assert rendered.startswith("&run")
    assert "Main template" not in rendered
    assert "Line one" not in rendered


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


def test_render_template_rejects_non_string_derived_override_keys() -> None:
    schema = resolve_schema(
        {
            "x-fortran-namelist": "run",
            "type": "object",
            "$defs": {
                "period": {
                    "type": "object",
                    "x-fortran-type": "period_t",
                    "properties": {"year": {"type": "integer", "default": 1900}},
                }
            },
            "properties": {"period": {"$ref": "#/$defs/period"}},
        }
    )

    with pytest.raises(ValueError, match="derived template value 'period' must use string keys"):
        _import_render_template()(
            [schema],
            value_mode="filled",
            values={"run": {"period": {2001: 2001}}},
        )


def test_render_template_buffer_scalar_uses_schema_order_and_value_precedence() -> None:
    schema = resolve_schema(
        {
            "x-fortran-namelist": "run",
            "type": "object",
            "$defs": {
                "setting": {
                    "type": "object",
                    "x-fortran-type": "setting_t",
                    "properties": {
                        "flag": {"type": "boolean", "default": False},
                        "exampled": {"type": "integer", "examples": [3]},
                        "choice": {
                            "type": "string",
                            "x-fortran-len": 8,
                            "enum": ["first", "second"],
                        },
                        "fallback": {"type": "number"},
                    },
                }
            },
            "properties": {"setting": {"$ref": "#/$defs/setting"}},
        }
    )

    rendered = _import_render_template()(
        [schema],
        doc_mode="documented",
        value_mode="filled",
        simple_derived_mode=" BUFFER ",
        values={"run": {"setting": {"exampled": 9, "flag": True}}},
    )

    assert "  ! Component order: flag, exampled, choice, fallback\n" in rendered
    assert '  setting = .true., 9, "first", 0.0\n' in rendered
    assert "setting%flag" not in rendered


def test_render_template_buffer_empty_scalar_and_multirank_array() -> None:
    setting = {
        "type": "object",
        "x-fortran-type": "setting_t",
        "properties": {
            "flag": {"type": "boolean"},
            "value": {"type": "integer"},
        },
    }
    schema = {
        "x-fortran-namelist": "run",
        "type": "object",
        "properties": {
            "setting": setting,
            "settings": {
                "type": "array",
                "x-fortran-shape": ["n_settings", 2],
                "items": setting,
            },
        },
    }

    rendered = _import_render_template()(
        [schema],
        value_mode="empty",
        simple_derived_mode="buffer",
        dimensions={"n_settings": 2},
    )

    assert rendered == (
        "&run\n"
        "  setting =\n"
        "  settings(1,1) =\n"
        "  settings(2,1) =\n"
        "  settings(1,2) =\n"
        "  settings(2,2) =\n"
        "/\n"
    )


def test_render_template_buffer_multirank_partial_overrides_follow_fortran_order() -> None:
    schema = {
        "x-fortran-namelist": "run",
        "type": "object",
        "properties": {
            "settings": {
                "type": "array",
                "x-fortran-shape": [2, 2],
                "items": {
                    "type": "object",
                    "x-fortran-type": "setting_t",
                    "properties": {
                        "flag": {"type": "boolean", "default": False},
                        "value": {"type": "integer", "default": 1},
                    },
                },
            }
        },
    }

    rendered = _import_render_template()(
        [schema],
        value_mode="filled",
        simple_derived_mode="buffer",
        values={
            "run": {
                "settings": [
                    {"value": 1, "flag": True},
                    {"value": 2},
                    {"value": 3, "flag": True},
                ]
            }
        },
    )

    assert "settings(1,1) = .true., 1" in rendered
    assert "settings(2,1) = .false., 2" in rendered
    assert "settings(1,2) = .true., 3" in rendered
    assert "settings(2,2)" not in rendered
    evaluated = evaluate_group(parse_namelist(rendered).groups[0], schema)
    assert evaluated.states[("settings", (1, 2), "value")].value == 3


def test_render_template_default_and_explicit_components_are_unchanged() -> None:
    schema = {
        "x-fortran-namelist": "run",
        "type": "object",
        "properties": {
            "setting": {
                "type": "object",
                "x-fortran-type": "setting_t",
                "properties": {"value": {"type": "integer", "default": 1}},
            }
        },
    }
    render_template = _import_render_template()

    implicit = render_template([schema], value_mode="filled")
    explicit = render_template(
        [schema], value_mode="filled", simple_derived_mode="components"
    )

    assert implicit == explicit == "&run\n  setting%value = 1\n/\n"
    with pytest.raises(ValueError, match="simple_derived_mode"):
        render_template([schema], simple_derived_mode="positional")


def test_render_template_derived_object_default_precedence_in_both_styles() -> None:
    schema = {
        "x-fortran-namelist": "run",
        "type": "object",
        "properties": {
            "setting": {
                "type": "object",
                "x-fortran-type": "setting_t",
                "default": {"mode": 3, "value": 4},
                "properties": {
                    "mode": {"type": "integer", "default": 1, "examples": [5]},
                    "value": {"type": "integer", "default": 2},
                },
            },
            "settings": {
                "type": "array",
                "x-fortran-shape": 2,
                "items": {
                    "type": "object",
                    "x-fortran-type": "setting_t",
                    "default": {"mode": 6, "value": 7},
                    "properties": {
                        "mode": {"type": "integer"},
                        "value": {"type": "integer"},
                    },
                },
            },
        },
    }
    render_template = _import_render_template()

    components = render_template(
        [schema],
        value_mode="filled",
        values={"run": {"setting": {"value": 9}}},
    )
    assert "setting%mode = 5" in components
    assert "setting%value = 9" in components
    assert "settings(:)%mode = 6" in components
    assert "settings(:)%value = 7" in components

    buffer = render_template(
        [schema],
        value_mode="filled",
        simple_derived_mode="buffer",
        values={"run": {"setting": {"value": 9}}},
    )
    assert "setting = 5, 9" in buffer
    assert "settings(1) = 6, 7" in buffer
    assert "settings(2) = 6, 7" in buffer


def test_render_template_minimal_omits_only_fully_initialized_derived_fields() -> None:
    schema = {
        "x-fortran-namelist": "run",
        "type": "object",
        "required": ["complete", "partial"],
        "properties": {
            "complete": {
                "type": "object",
                "x-fortran-type": "complete_t",
                "properties": {"value": {"type": "integer", "default": 1}},
            },
            "partial": {
                "type": "object",
                "x-fortran-type": "partial_t",
                "default": {"value": 2},
                "required": ["value"],
                "properties": {
                    "value": {"type": "integer"},
                    "note": {"type": "integer"},
                },
            },
        },
    }

    rendered = _import_render_template()([schema], value_mode="minimal-filled")

    assert "complete%value" not in rendered
    assert "partial%value = 2" in rendered
    assert "partial%note = 0" in rendered
