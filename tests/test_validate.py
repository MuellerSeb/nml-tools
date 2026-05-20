"""Tests for namelist validation."""

from __future__ import annotations

import pytest

from nml_tools.validate import validate_namelist


def test_validate_namelist_rejects_unknown_property() -> None:
    schema = {
        "x-fortran-namelist": "config",
        "type": "object",
        "properties": {
            "foo": {"type": "integer"},
        },
    }
    namelist = {"foo": 1, "bar": 2}
    with pytest.raises(ValueError, match="unknown property"):
        validate_namelist(schema, namelist)


def test_validate_namelist_flex_array_shape() -> None:
    schema = {
        "x-fortran-namelist": "config",
        "type": "object",
        "properties": {
            "arr": {
                "type": "array",
                "items": {"type": "integer"},
                "x-fortran-shape": [3, 2, 4],
                "x-fortran-flex-tail-dims": 2,
            }
        },
    }
    # f90nml-style nesting: outermost dimension is the last Fortran index.
    namelist = {"arr": [[[1, 2, 3], [4, 5, 6]]]}
    validate_namelist(schema, namelist)


def test_validate_namelist_allows_dimensions_only_for_array_shapes() -> None:
    schema = {
        "x-fortran-namelist": "config",
        "type": "object",
        "properties": {
            "arr": {
                "type": "array",
                "items": {"type": "integer"},
                "x-fortran-shape": ["n_values"],
            },
            "name": {
                "type": "string",
                "x-fortran-len": "n_values",
            },
        },
    }

    with pytest.raises(ValueError, match="must not use runtime dimension"):
        validate_namelist(
            schema,
            {"arr": [1, 2, 3], "name": "abc"},
            dimensions={"n_values": 3},
        )


def test_validate_namelist_accepts_scalar_shape_with_dimension() -> None:
    schema = {
        "x-fortran-namelist": "config",
        "type": "object",
        "properties": {
            "arr": {
                "type": "array",
                "items": {"type": "integer"},
                "x-fortran-shape": "n_values",
            },
        },
    }

    validate_namelist(schema, {"arr": [1, 2, 3]}, dimensions={"n_values": 3})


def test_validate_namelist_rejects_constant_dimension_name_overlap() -> None:
    schema = {
        "x-fortran-namelist": "config",
        "type": "object",
        "properties": {
            "arr": {
                "type": "array",
                "items": {"type": "integer"},
                "x-fortran-shape": "n_values",
            },
        },
    }

    with pytest.raises(ValueError, match="constants and dimensions"):
        validate_namelist(
            schema,
            {"arr": [1, 2, 3]},
            constants={"n_values": 3},
            dimensions={"n_values": 3},
        )
