"""Tests for template generation."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


def _import_render_template():
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    sys.path.insert(0, str(src))
    try:
        module = importlib.import_module("nml_tools.codegen_template")
    finally:
        sys.path.pop(0)
    return module.render_template


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

    assert "grid(:, 1) = 1, 2" in rendered
    assert "grid(:, 2) = 3, 4" in rendered
    assert "grid(:, 3) = 5, 6" in rendered
