"""Dimension inference operates on source scalars before full evaluation."""

from __future__ import annotations

from typing import Any

import pytest

from nml_tools._dimensions import (
    DimensionSource,
    infer_runtime_dimensions,
    resolve_dimension_source,
)
from nml_tools._namelist_eval import evaluate_group
from nml_tools._namelist_parser import parse_namelist
from nml_tools.schema import resolve_schema


def source_schema(**property_updates: Any) -> dict[str, Any]:
    return resolve_schema(
        {
            "type": "object",
            "x-fortran-namelist": "Settings",
            "properties": {
                "Count": {"type": "integer", "default": 7, **property_updates},
                "values": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "x-fortran-shape": ["n_values"],
                },
                "required_other": {"type": "integer"},
            },
            "required": ["Count", "required_other"],
        }
    )


def infer(text: str, **kwargs: Any) -> dict[str, int]:
    return infer_runtime_dimensions(
        [parse_namelist(text, source="settings.nml")],
        sources={"n_values": DimensionSource("settings", "count")},
        schemas={"settings": source_schema()},
        defaults={"n_values": 1},
        **kwargs,
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("&Settings Count=3 /", 3),
        ("&SETTINGS COUNT=1*+3 /", 3),
        ("&settings count=2 count=3 /", 3),
        ("&settings count=3 count=, /", 3),
        ("&settings count=, /", 1),
        ("&settings count=1* /", 1),
        ("&settings required_other=2 /", 1),
        ("&other count=3 /", 1),
        ("", 1),
    ],
)
def test_inference_assignment_semantics_and_fallback(text: str, expected: int) -> None:
    assert infer(text) == {"n_values": expected}


@pytest.mark.parametrize(
    "assignment",
    [
        "count=0",
        "count=-1",
        "count='3'",
        "count=3.0",
        "count=.true.",
        "count(1)=3",
        "count=2*3",
        "count%value=3",
    ],
)
def test_invalid_sources_report_locations(assignment: str) -> None:
    with pytest.raises(ValueError, match=r"settings.nml:1:\d+:"):
        infer(f"&settings {assignment} /")


def test_overrides_skip_source_extraction_and_ambiguity() -> None:
    assert infer("&settings count=0 / &settings count='bad' /", overrides={"N_VALUES": 4}) == {
        "n_values": 4
    }


def test_source_constraints_use_existing_evaluator() -> None:
    with pytest.raises(ValueError, match=r"settings.nml:1:.*must be <= 3"):
        infer_runtime_dimensions(
            [parse_namelist("&settings count=4 /", source="settings.nml")],
            sources={"n_values": DimensionSource("settings", "count")},
            schemas={"settings": source_schema(maximum=3, default=2)},
            defaults={"n_values": 1},
        )


def test_two_pass_evaluation_avoids_default_shape_and_missing_other_fields() -> None:
    schema = source_schema()
    parsed = parse_namelist("&settings values=1,2,3 count=3 required_other=2 /")
    dimensions = infer_runtime_dimensions(
        [parsed],
        sources={"n_values": DimensionSource("Settings", "Count")},
        schemas={"settings": schema},
        defaults={"n_values": 1},
    )
    assert dimensions == {"n_values": 3}
    evaluate_group(parsed.groups[0], schema, dimensions=dimensions)


def test_inference_accepts_multiple_files_and_dimensions() -> None:
    schemas = {
        "settings": source_schema(),
        "other": resolve_schema(
            {
                "type": "object",
                "x-fortran-namelist": "other",
                "properties": {"size": {"type": "integer"}},
            }
        ),
    }
    assert infer_runtime_dimensions(
        [parse_namelist("&settings count=3 /"), parse_namelist("&other size=4 /")],
        sources={
            "n_values": DimensionSource("settings", "count"),
            "n_other": DimensionSource("other", "size"),
        },
        schemas=schemas,
        defaults={"n_values": 1, "n_other": 2, "unsourced": 5},
        overrides={"additional": 6},
    ) == {"n_values": 3, "n_other": 4, "unsourced": 5, "additional": 6}


@pytest.mark.parametrize("split_files", [False, True])
def test_ambiguous_groups_fail_even_with_equal_values(split_files: bool) -> None:
    texts = ["&settings count=3 /", "&SETTINGS count=3 /"]
    if not split_files:
        texts = [" ".join(texts)]
    with pytest.raises(ValueError, match="ambiguous"):
        infer_runtime_dimensions(
            [parse_namelist(text, source=f"input{i}.nml") for i, text in enumerate(texts)],
            sources={"n_values": DimensionSource("settings", "count")},
            schemas={"settings": source_schema()},
            defaults={"n_values": 1},
        )


def test_source_resolution_handles_references_and_case() -> None:
    schema = resolve_schema(
        {
            "$defs": {"count": {"type": "integer"}},
            "type": "object",
            "x-fortran-namelist": "settings",
            "properties": {"Count": {"$ref": "#/$defs/count"}},
        }
    )
    assert resolve_dimension_source(
        DimensionSource("SETTINGS", "COUNT"), {"settings": schema}
    ) == DimensionSource("settings", "Count")


def test_raw_references_fail_before_inference() -> None:
    with pytest.raises(ValueError, match="unresolved.*ref"):
        resolve_dimension_source(
            DimensionSource("settings", "count"),
            {"settings": {"properties": {"count": {"$ref": "#/$defs/count"}}}},
        )


@pytest.mark.parametrize(
    "overrides", [{"n_values": True}, {"n_values": 0}, {"n_values": 2, "N_VALUES": 3}]
)
def test_invalid_caller_overrides_fail(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        infer("", overrides=overrides)
