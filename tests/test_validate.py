"""Tests for namelist validation."""

from __future__ import annotations

import pytest

from nml_tools._utils import normalize_constant_values, normalize_runtime_dimensions
from nml_tools.validate import validate_namelist, validate_schema_defaults


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


@pytest.mark.parametrize(
    ("namelist_name", "match"),
    [
        ("1config", "valid Fortran identifier"),
        ("config__run", "must not contain '__'"),
        ("config ", "valid Fortran identifier"),
    ],
)
def test_validate_namelist_rejects_invalid_schema_namelist_names(
    namelist_name: str, match: str
) -> None:
    schema = {
        "x-fortran-namelist": namelist_name,
        "type": "object",
        "properties": {"foo": {"type": "integer"}},
    }
    with pytest.raises(ValueError, match=match):
        validate_namelist(schema, {"foo": 1})


def test_normalize_config_values_accept_none_and_reject_empty_names() -> None:
    assert normalize_constant_values(None) == {}
    assert normalize_runtime_dimensions(None) == {}

    with pytest.raises(ValueError, match="constant names must be non-empty"):
        normalize_constant_values({"": 1})

    with pytest.raises(ValueError, match="runtime dimension names must be non-empty"):
        normalize_runtime_dimensions({"": 1})

    with pytest.raises(ValueError, match="duplicates another dimension"):
        normalize_runtime_dimensions({"n": 1, "N": 2})


def test_validate_namelist_rejects_invalid_schema_defaults() -> None:
    scalar_schema = {
        "x-fortran-namelist": "config",
        "type": "object",
        "properties": {"count": {"type": "integer", "minimum": 1, "default": 0}},
    }
    with pytest.raises(ValueError, match="must be >= 1"):
        validate_namelist(scalar_schema, {})

    array_schema = {
        "x-fortran-namelist": "config",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "x-fortran-shape": 2,
                "items": {"type": "integer", "enum": [1, 2]},
                "default": [1],
                "x-fortran-default-pad": 3,
            }
        },
    }
    with pytest.raises(ValueError, match="outside enum"):
        validate_namelist(array_schema, {})

    partial_schema = {
        "x-fortran-namelist": "config",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "x-fortran-shape": 2,
                "items": {"type": "integer"},
                "default": [1],
            }
        },
    }
    with pytest.raises(ValueError, match="shorter than declared x-fortran-shape"):
        validate_namelist(partial_schema, {})

    scalar_array_default_schema = {
        "x-fortran-namelist": "config",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "x-fortran-shape": 1,
                "items": {"type": "integer"},
                "default": 1,
            }
        },
    }
    with pytest.raises(ValueError, match="array default must be a list"):
        validate_namelist(scalar_array_default_schema, {})

    missing_items_schema = {
        "x-fortran-namelist": "config",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "x-fortran-shape": 1,
                "default": [1],
            }
        },
    }
    with pytest.raises(ValueError, match="must define object 'items'"):
        validate_namelist(missing_items_schema, {})

    options_without_default_schema = {
        "x-fortran-namelist": "config",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "x-fortran-default-repeat": True,
            }
        },
    }
    with pytest.raises(ValueError, match="default options require an array default"):
        validate_namelist(options_without_default_schema, {})


def test_validation_rejects_unresolved_schema_references() -> None:
    schema = {
        "x-fortran-namelist": "config",
        "type": "object",
        "$defs": {"count": {"type": "integer"}},
        "properties": {"count": {"$ref": "#/$defs/count"}},
    }

    with pytest.raises(ValueError, match=r"use load_schema\(\) or resolve_schema\(\)"):
        validate_schema_defaults(schema)

    with pytest.raises(ValueError, match=r"use load_schema\(\) or resolve_schema\(\)"):
        validate_namelist(schema, {})


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


def test_validate_namelist_accepts_bare_scalar_for_single_element_array() -> None:
    schema = {
        "x-fortran-namelist": "config",
        "type": "object",
        "properties": {
            "start_time": {
                "type": "array",
                "items": {"type": "string", "x-fortran-len": 32},
                "x-fortran-shape": "n_items",
            },
        },
    }

    validate_namelist(
        schema,
        {"start_time": "1992-07-05 00:00"},
        dimensions={"n_items": 1},
    )


def test_validate_namelist_accepts_bare_flat_multidimensional_array_buffer() -> None:
    schema = {
        "x-fortran-namelist": "profile",
        "type": "object",
        "properties": {
            "layer_depth": {
                "type": "array",
                "items": {"type": "integer"},
                "x-fortran-shape": [5, 1],
            },
        },
    }

    validate_namelist(schema, {"layer_depth": [200, 0, 0, 0, 0]})


def test_validate_namelist_rejects_bare_array_buffer_longer_than_shape() -> None:
    schema = {
        "x-fortran-namelist": "profile",
        "type": "object",
        "properties": {
            "layer_depth": {
                "type": "array",
                "items": {"type": "integer"},
                "x-fortran-shape": [2, 2],
            },
        },
    }

    with pytest.raises(ValueError, match="buffer is longer than shape"):
        validate_namelist(schema, {"layer_depth": [1, 2, 3, 4, 5]})


def test_validate_namelist_applies_scalar_constraints_to_bare_array_buffer() -> None:
    schema = {
        "x-fortran-namelist": "profile",
        "type": "object",
        "properties": {
            "layer_depth": {
                "type": "array",
                "items": {"type": "integer", "enum": [0, 200]},
                "x-fortran-shape": [5, 1],
            },
        },
    }

    with pytest.raises(ValueError, match="outside enum"):
        validate_namelist(schema, {"layer_depth": [200, 0, 1]})


def test_validate_namelist_matches_constants_and_dimensions_case_insensitively() -> None:
    schema = {
        "x-fortran-namelist": "config",
        "type": "object",
        "properties": {
            "arr": {
                "type": "array",
                "items": {"type": "integer"},
                "x-fortran-shape": "MAX_VALUES",
            },
            "name": {
                "type": "string",
                "x-fortran-len": "BUF",
            },
        },
    }

    validate_namelist(
        schema,
        {"arr": [1, 2, 3], "name": "abc"},
        constants={"buf": 16},
        dimensions={"max_values": 3},
    )


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
            dimensions={"N_VALUES": 3},
        )

    with pytest.raises(ValueError, match="duplicates another constant"):
        validate_namelist(
            schema,
            {"arr": [1, 2, 3]},
            constants={"n_values": 3, "N_VALUES": 4},
        )

    with pytest.raises(ValueError, match="must be an integer"):
        validate_namelist(
            schema,
            {"arr": [1, 2, 3]},
            constants={"n_values": 3.5},
        )


def test_validate_namelist_rejects_invalid_dimensions() -> None:
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

    with pytest.raises(ValueError, match="valid Fortran identifier"):
        validate_namelist(schema, {"arr": [1]}, dimensions={"1bad": 1})

    with pytest.raises(ValueError, match="must be an integer"):
        validate_namelist(schema, {"arr": [1]}, dimensions={"n_values": True})

    with pytest.raises(ValueError, match="must be positive"):
        validate_namelist(schema, {"arr": [1]}, dimensions={"n_values": 0})


def _derived_schema(*, optional: bool = False) -> dict[str, object]:
    return {
        "x-fortran-namelist": "run",
        "type": "object",
        "properties": {
            "period": {
                "type": "object",
                "x-fortran-type": "period_t",
                "_nml_tools_ref_origin": {
                    "identity": ["<mapping>", "/$defs/period"],
                    "definition": {},
                },
                "properties": {
                    "start_year": {"type": "integer", "minimum": 1900},
                    "label": {"type": "string", "x-fortran-len": 8, "default": "default"},
                },
                "required": ["start_year"],
            },
            "periods": {
                "type": "array",
                "x-fortran-shape": 2,
                "items": {
                    "type": "object",
                    "x-fortran-type": "period_t",
                    "_nml_tools_ref_origin": {
                        "identity": ["<mapping>", "/$defs/period"],
                        "definition": {},
                    },
                    "properties": {"start_year": {"type": "integer", "minimum": 1900}},
                    "required": ["start_year"],
                },
            },
        },
        "required": [] if optional else ["period", "periods"],
    }


def _setting_schema(
    *,
    required_components: list[str] | None = None,
    array_shape: object = 2,
    include_array: bool = False,
) -> dict[str, object]:
    required = required_components if required_components is not None else ["flag", "value"]
    setting = {
        "type": "object",
        "x-fortran-type": "setting_t",
        "_nml_tools_ref_origin": {
            "identity": ["<mapping>", "/$defs/setting"],
            "definition": {},
        },
        "properties": {
            "flag": {"type": "boolean"},
            "value": {"type": "integer", "minimum": 1},
        },
        "required": required,
    }
    properties: dict[str, object] = {"setting": setting}
    required_fields = ["setting"]
    if include_array:
        properties["settings"] = {
            "type": "array",
            "x-fortran-shape": array_shape,
            "items": setting,
        }
        required_fields.append("settings")
    return {
        "x-fortran-namelist": "run",
        "type": "object",
        "properties": properties,
        "required": required_fields,
    }


def test_validate_namelist_accepts_nested_derived_values() -> None:
    validate_namelist(
        _derived_schema(),
        {
            "period": {"start_year": 2001, "label": "eval"},
            "periods": [{"start_year": 1980}, {"start_year": 2001}],
        },
    )

    with pytest.raises(ValueError, match=r"period\.start_year.*>= 1900"):
        validate_namelist(
            _derived_schema(),
            {
                "period": {"start_year": 1800},
                "periods": [{"start_year": 1980}, {"start_year": 2001}],
            },
        )
    with pytest.raises(ValueError, match=r"periods\[2\]\.missing.*unknown"):
        validate_namelist(
            _derived_schema(),
            {
                "period": {"start_year": 2001},
                "periods": [{"start_year": 1980}, {"start_year": 2001, "missing": 1}],
            },
        )


def test_validate_namelist_accepts_derived_buffer_values() -> None:
    validate_namelist(
        _setting_schema(include_array=True),
        {
            "setting": [True, 1],
            "settings": [True, 1, False, 2],
        },
    )


def test_validate_namelist_accepts_single_value_derived_buffer() -> None:
    validate_namelist(
        _setting_schema(required_components=["flag"]),
        {"setting": True},
    )


def test_validate_namelist_skips_omitted_derived_buffer_values() -> None:
    validate_namelist(
        _setting_schema(required_components=["value"]),
        {"setting": [None, 1]},
    )

    with pytest.raises(ValueError, match=r"missing required 'setting\.flag'"):
        validate_namelist(
            _setting_schema(required_components=["flag"]),
            {"setting": [None, 1]},
        )


def test_validate_namelist_rejects_overlong_derived_buffer() -> None:
    with pytest.raises(ValueError, match="buffer has too many values"):
        validate_namelist(
            _setting_schema(),
            {"setting": [True, 1, 3]},
        )


def test_validate_namelist_applies_constraints_to_derived_buffer_values() -> None:
    with pytest.raises(ValueError, match=r"setting\.value.*>= 1"):
        validate_namelist(
            _setting_schema(),
            {"setting": [True, 0]},
        )


def test_validate_namelist_accepts_derived_array_buffers_with_concrete_shapes() -> None:
    validate_namelist(
        _setting_schema(include_array=True),
        {"setting": [True, 1], "settings": [True, 1, False, 2]},
    )

    validate_namelist(
        _setting_schema(array_shape="n_settings", include_array=True),
        {"setting": [True, 1], "settings": [True, 1, False, 2]},
        dimensions={"n_settings": 2},
    )


def test_validate_namelist_rejects_partial_required_derived_array_buffer_element() -> None:
    with pytest.raises(ValueError, match=r"missing required 'settings\[2\]\.value'"):
        validate_namelist(
            _setting_schema(include_array=True),
            {"setting": [True, 1], "settings": [True, 1, False]},
        )


def test_validate_namelist_rejects_null_only_required_derived_array_buffer() -> None:
    with pytest.raises(ValueError, match=r"missing required 'settings\[1\]\.flag'"):
        validate_namelist(
            _setting_schema(include_array=True),
            {"setting": [True, 1], "settings": [None, None]},
        )


def test_validate_namelist_rejects_overlong_derived_array_buffer() -> None:
    with pytest.raises(ValueError, match="buffer is longer than shape"):
        validate_namelist(
            _setting_schema(include_array=True),
            {"setting": [True, 1], "settings": [True, 1, False, 2, True]},
        )


def test_validate_namelist_rejects_mapping_as_derived_array() -> None:
    with pytest.raises(ValueError, match="array property 'settings' must be a list"):
        validate_namelist(
            _setting_schema(include_array=True),
            {
                "setting": [True, 1],
                "settings": {"flag": True, "value": 1},
            },
        )


def test_validate_namelist_rejects_multirank_derived_array_buffer_without_shape() -> None:
    with pytest.raises(
        ValueError,
        match="derived array 'settings' flat buffer assignment requires concrete shape",
    ):
        validate_namelist(
            _setting_schema(array_shape=[":", ":"], include_array=True),
            {"setting": [True, 1], "settings": [True, 1]},
        )


def test_validate_namelist_reports_missing_derived_array_item_properties() -> None:
    schema = {
        "x-fortran-namelist": "run",
        "type": "object",
        "properties": {
            "settings": {
                "type": "array",
                "x-fortran-shape": 2,
                "items": {
                    "type": "object",
                    "x-fortran-type": "setting_t",
                    "properties": {},
                },
            }
        },
        "required": ["settings"],
    }

    with pytest.raises(
        ValueError,
        match="derived array 'settings' items must define non-empty object 'properties'",
    ):
        validate_namelist(schema, {"settings": [True, 1]})


def test_validate_namelist_rejects_optional_derived_values_with_required_members() -> None:
    with pytest.raises(ValueError, match="optional derived property 'period'.*required"):
        validate_schema_defaults(_derived_schema(optional=True))


def test_validate_schema_defaults_traverses_derived_members() -> None:
    schema = _derived_schema()
    period = schema["properties"]["period"]  # type: ignore[index]
    period["properties"]["label"]["default"] = "too-long-value"  # type: ignore[index]

    with pytest.raises(ValueError, match=r"period\.label.*exceeds length"):
        validate_schema_defaults(schema)


@pytest.mark.parametrize(
    ("prop", "match"),
    [
        (
            {"type": "object", "properties": {"year": {"type": "integer"}}},
            "must define non-empty 'x-fortran-type'",
        ),
        (
            {
                "type": "object",
                "x-fortran-type": "not-a-type",
                "properties": {"year": {"type": "integer"}},
            },
            "x-fortran-type must be a valid identifier",
        ),
        (
            {
                "type": "object",
                "x-fortran-type": "period_t",
                "x-fortran-module": "not-a-module",
                "properties": {"year": {"type": "integer"}},
            },
            "x-fortran-module must be a valid identifier",
        ),
        (
            {
                "type": "object",
                "x-fortran-type": "period_t",
                "properties": {
                    "years": {"type": "array", "items": {"type": "integer"}}
                },
            },
            "component 'years' must define an intrinsic scalar type",
        ),
        (
            {
                "type": "object",
                "x-fortran-type": "period_t",
                "properties": {
                    "child": {
                        "type": "object",
                        "x-fortran-type": "child_t",
                        "properties": {"year": {"type": "integer"}},
                    }
                },
            },
            "component 'child' must define an intrinsic scalar type",
        ),
    ],
)
def test_validation_rejects_invalid_raw_derived_declarations(
    prop: dict[str, object], match: str
) -> None:
    schema = {
        "x-fortran-namelist": "run",
        "type": "object",
        "properties": {"period": prop},
    }

    with pytest.raises(ValueError, match=match):
        validate_namelist(schema, {})
