"""Tests for Qt-independent GUI array metadata and data transforms."""

from __future__ import annotations

import pytest

from nml_tools.gui.arrays import (
    axis_labels,
    canonical_array,
    display_array,
    initial_array,
    resolve_shape,
    table_axes,
)


def test_resolve_shape_supports_literals_names_and_saved_flexible_axes() -> None:
    assert resolve_shape(
        {"x-fortran-shape": [5, "N_DOMAINS"]}, {"n_domains": 3}
    ) == (5, 3)
    assert resolve_shape({"x-fortran-shape": ":"}, {}, [1, 2, 3]) == (3,)

    with pytest.raises(ValueError, match="unknown array dimension"):
        resolve_shape({"x-fortran-shape": "missing"}, {})


def test_axis_labels_support_explicit_values_and_index_templates() -> None:
    schema = {
        "x-nml-tools-ui": {
            "axes": {
                "1": {"labels": ["Lower", "Upper", "Value"]},
                "2": {"label-template": "Domain {index}"},
            }
        }
    }

    assert axis_labels(schema, 1, 3) == ["Lower", "Upper", "Value"]
    assert axis_labels(schema, 2, 2) == ["Domain 1", "Domain 2"]
    assert axis_labels(schema, 3, 4) is None

    with pytest.raises(ValueError, match="2 labels for extent 3"):
        axis_labels(
            {"x-nml-tools-ui": {"axes": {"1": {"labels": ["a", "b"]}}}},
            1,
            3,
        )


def test_table_axes_uses_one_based_schema_metadata() -> None:
    schema = {
        "x-nml-tools-ui": {
            "table": {"row-axis": 2, "column-axis": 1},
        }
    }

    assert table_axes(schema, 2) == (1, 0)
    assert table_axes({}, 2) == (0, 1)
    assert table_axes({}, 1) is None

    with pytest.raises(ValueError, match="distinct valid one-based axes"):
        table_axes(
            {"x-nml-tools-ui": {"table": {"row-axis": 1, "column-axis": 1}}},
            2,
        )


def test_parameter_array_display_round_trip_preserves_canonical_axis_order() -> None:
    pytest.importorskip("numpy")
    schema = {
        "x-fortran-shape": [5, "n_units"],
        "x-nml-tools-ui": {
            "table": {"row-axis": 2, "column-axis": 1},
        },
    }
    canonical = [
        [10.0, 11.0],
        [20.0, 21.0],
        [30.0, 31.0],
        [0, 1],
        [1, 0],
    ]

    displayed = display_array(canonical, schema)

    assert displayed.tolist() == [
        [10.0, 20.0, 30.0, 0.0, 1.0],
        [11.0, 21.0, 31.0, 1.0, 0.0],
    ]
    assert canonical_array(displayed, schema, rank=2) == canonical


def test_initial_array_broadcasts_parameter_vector_across_second_axis() -> None:
    schema = {"x-fortran-shape": [5, "n_units"]}

    initialized = initial_array(
        schema,
        {"n_units": 2},
        [75.0, 200.0, 85.0, 1, 1],
        0.0,
    )

    assert initialized == [
        [75.0, 75.0],
        [200.0, 200.0],
        [85.0, 85.0],
        [1, 1],
        [1, 1],
    ]


def test_derived_array_initialization_does_not_share_mutable_defaults() -> None:
    initialized = initial_array(
        {"x-fortran-shape": 2},
        {},
        None,
        {"enabled": False},
    )

    initialized[0]["enabled"] = True
    assert initialized == [{"enabled": True}, {"enabled": False}]


def test_saved_array_shapes_are_preserved_or_rejected_without_coercion() -> None:
    flexible = {
        "x-fortran-shape": "max_items",
        "x-fortran-flex-tail-dims": 1,
    }
    assert initial_array(
        flexible,
        {"max_items": 5},
        [10, 20],
        0,
        strict=True,
    ) == [10, 20]

    with pytest.raises(ValueError, match="does not match declared shape"):
        initial_array(
            {"x-fortran-shape": 5},
            {},
            [10, 20],
            0,
            strict=True,
        )
