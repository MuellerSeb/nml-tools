"""Tests for schema-aware namelist evaluation and schema defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nml_tools._namelist_eval import evaluate_file, evaluate_group
from nml_tools._namelist_parser import DecimalMode, parse_namelist
from nml_tools._utils import normalize_constant_values, normalize_runtime_dimensions
from nml_tools.schema import load_schema
from nml_tools.validate import validate_schema_defaults


def _evaluate(
    schema: dict[str, Any],
    body: str,
    *,
    constants: dict[str, int] | None = None,
    dimensions: dict[str, int] | None = None,
    decimal_mode: DecimalMode = DecimalMode.POINT,
) -> Any:
    name = schema.get("x-fortran-namelist", "run")
    parsed = parse_namelist(
        f"&{name}\n{body}\n/",
        source="input.nml",
        decimal_mode=decimal_mode,
    )
    return evaluate_group(
        parsed.groups[0],
        schema,
        source="input.nml",
        constants=constants,
        dimensions=dimensions,
        decimal_mode=decimal_mode,
    )


def test_evaluator_rejects_unknown_property_with_source_location() -> None:
    schema = {
        "x-fortran-namelist": "config",
        "type": "object",
        "properties": {"foo": {"type": "integer"}},
    }
    with pytest.raises(ValueError, match=r"input\.nml:2:1:.*unknown property 'bar'"):
        _evaluate(schema, "bar = 2")


def test_evaluate_file_preserves_group_order_and_rejects_duplicate_groups() -> None:
    first = {
        "x-fortran-namelist": "first",
        "type": "object",
        "properties": {"value": {"type": "integer"}},
    }
    second = {**first, "x-fortran-namelist": "second"}
    parsed = parse_namelist("&first\nvalue=1\n/\n&second\nvalue=2\n/")
    assert [group.name for group in evaluate_file(parsed, [first, second])] == [
        "first",
        "second",
    ]

    duplicate = parse_namelist("&first\nvalue=1\n/\n&FIRST\nvalue=2\n/")
    with pytest.raises(ValueError, match="appears multiple times"):
        evaluate_file(duplicate, [first])


def test_shared_fortran_conformance_fixture_has_expected_effective_values() -> None:
    fixture_dir = Path(__file__).parent / "fortran_namelist"
    parsed = parse_namelist(
        (fixture_dir / "standard.nml").read_text(encoding="utf-8"),
        source=str(fixture_dir / "standard.nml"),
    )
    result = evaluate_group(parsed.groups[0], load_schema(fixture_dir / "run.yml"))
    assert result.states[("values", (1, 2), None)].value == 3
    assert result.states[("values", (2, 2), None)].value == 2
    assert result.states[("settings", (1,), "flag")].value is True
    assert result.states[("settings", (2,), "value")].value == 2
    assert result.states[("label", (), None)].value == "abc     "


@pytest.mark.parametrize(
    ("namelist_name", "match"),
    [
        ("1config", "valid Fortran identifier"),
        ("config__run", "must not contain '__'"),
        ("config ", "valid Fortran identifier"),
    ],
)
def test_evaluator_rejects_invalid_schema_namelist_names(
    namelist_name: str, match: str
) -> None:
    schema = {
        "x-fortran-namelist": namelist_name,
        "type": "object",
        "properties": {"foo": {"type": "integer"}},
    }
    parsed = parse_namelist("&config\nfoo = 1\n/")
    with pytest.raises(ValueError, match=match):
        evaluate_group(parsed.groups[0], schema)


def test_normalize_config_values_accept_none_and_reject_invalid_values() -> None:
    assert normalize_constant_values(None) == {}
    assert normalize_runtime_dimensions(None) == {}

    with pytest.raises(ValueError, match="constant names must be non-empty"):
        normalize_constant_values({"": 1})
    with pytest.raises(ValueError, match="runtime dimension names must be non-empty"):
        normalize_runtime_dimensions({"": 1})
    with pytest.raises(ValueError, match="duplicates another dimension"):
        normalize_runtime_dimensions({"n": 1, "N": 2})


@pytest.mark.parametrize(
    ("prop", "match"),
    [
        ({"type": "integer", "minimum": 1, "default": 0}, "must be >= 1"),
        (
            {
                "type": "array",
                "x-fortran-shape": 2,
                "items": {"type": "integer", "enum": [1, 2]},
                "default": [1],
                "x-fortran-default-pad": 3,
            },
            "outside enum",
        ),
        (
            {
                "type": "array",
                "x-fortran-shape": 2,
                "items": {"type": "integer"},
                "default": [1],
            },
            "shorter than declared x-fortran-shape",
        ),
        (
            {
                "type": "array",
                "x-fortran-shape": 1,
                "items": {"type": "integer"},
                "default": 1,
            },
            "array default must be a list",
        ),
    ],
)
def test_validate_schema_defaults_rejects_invalid_defaults(
    prop: dict[str, Any], match: str
) -> None:
    schema = {
        "x-fortran-namelist": "config",
        "type": "object",
        "properties": {"value": prop},
    }
    with pytest.raises(ValueError, match=match):
        validate_schema_defaults(schema)


def test_validation_rejects_unresolved_schema_references() -> None:
    schema = {
        "x-fortran-namelist": "config",
        "type": "object",
        "properties": {"value": {"$ref": "#/$defs/value"}},
        "$defs": {"value": {"type": "integer"}},
    }
    with pytest.raises(ValueError, match="unresolved '\\$ref'"):
        validate_schema_defaults(schema)


def test_intrinsic_values_constraints_and_character_storage() -> None:
    schema = {
        "x-fortran-namelist": "config",
        "type": "object",
        "required": ["count", "ratio", "enabled", "label"],
        "properties": {
            "count": {"type": "integer", "minimum": 1, "maximum": 5},
            "ratio": {"type": "number", "minimum": 100.0},
            "enabled": {"type": "boolean"},
            "label": {"type": "string", "x-fortran-len": 4, "enum": ["abcd"]},
        },
    }
    result = _evaluate(
        schema,
        "count = +3\nratio = 1.5+2\nenabled = .TEXAS$\nlabel = 'abcdef'",
    )
    assert result.states[("count", (), None)].value == 3
    assert result.states[("ratio", (), None)].value == 150.0
    assert result.states[("enabled", (), None)].value is True
    assert result.states[("label", (), None)].value == "abcd"

    with pytest.raises(ValueError, match=r"count.*must be >= 1"):
        _evaluate(schema, "count = 0\nratio = 100\nenabled = F\nlabel = 'abcd'")
    with pytest.raises(ValueError, match="character input must be.*delimited"):
        _evaluate(schema, "count = 1\nratio = 100\nenabled = F\nlabel = abcd")


def test_real_forms_and_nonfinite_values() -> None:
    schema = {
        "x-fortran-namelist": "run",
        "type": "object",
        "required": ["values"],
        "properties": {
            "values": {
                "type": "array",
                "x-fortran-shape": 5,
                "items": {"type": "number"},
            }
        },
    }
    result = _evaluate(schema, "values = .5, 1., 1d2, 1.25-1, 0x1.0p+2")
    assert [state.value for state in result.states.values()] == [0.5, 1.0, 100.0, 0.125, 4.0]
    with pytest.raises(ValueError, match="must not be infinite"):
        _evaluate(schema, "values(1) = inf")
    with pytest.raises(ValueError, match="must not be NaN"):
        _evaluate(schema, "values(1) = nan")
    with pytest.raises(ValueError, match="must not be NaN"):
        _evaluate(schema, "values(1) = NaN(payload)")
    with pytest.raises(ValueError, match="expected a standard real input value"):
        _evaluate(schema, "values(1) = 1q2")

    comma_schema = {
        "x-fortran-namelist": "run",
        "type": "object",
        "properties": {"value": {"type": "number"}},
    }
    comma_result = _evaluate(
        comma_schema,
        "value = 1,25",
        decimal_mode=DecimalMode.COMMA,
    )
    assert comma_result.states[("value", (), None)].value == 1.25


def test_arrays_use_fortran_order_sections_and_serial_assignment() -> None:
    schema = {
        "x-fortran-namelist": "run",
        "type": "object",
        "required": ["values"],
        "properties": {
            "values": {
                "type": "array",
                "x-fortran-shape": [2, 3],
                "items": {"type": "integer"},
            }
        },
    }
    result = _evaluate(
        schema,
        "values = 6*0\nvalues(:,2) = 1, 2\nvalues(2:1:-1,3) = 3, 4\nvalues(1,2) = 9",
    )
    assert [key[1] for key in result.states] == [
        (1, 1),
        (2, 1),
        (1, 2),
        (2, 2),
        (1, 3),
        (2, 3),
    ]
    assert result.states[("values", (1, 2), None)].value == 9
    assert result.states[("values", (2, 2), None)].value == 2
    assert result.states[("values", (2, 3), None)].value == 3
    assert result.states[("values", (1, 3), None)].value == 4


def test_array_bounds_rank_and_excess_values_are_diagnosed() -> None:
    schema = {
        "x-fortran-namelist": "run",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "x-fortran-shape": [2, 2],
                "items": {"type": "integer"},
            }
        },
    }
    with pytest.raises(ValueError, match="outside 1:2"):
        _evaluate(schema, "values(3,1) = 1")
    with pytest.raises(ValueError, match="rank mismatch"):
        _evaluate(schema, "values(1) = 1")
    with pytest.raises(ValueError, match="supplies 5 values for 4 effective items"):
        _evaluate(schema, "values = 1, 2, 3, 4, 5")
    with pytest.raises(ValueError, match="supplies 10000000 values for 4 effective items"):
        _evaluate(schema, "values = 10000000*0")
    with pytest.raises(ValueError, match="must not be empty"):
        _evaluate(schema, "values(2:1,1) = 1")


def test_runtime_and_deferred_rank_one_shapes() -> None:
    runtime = {
        "x-fortran-namelist": "run",
        "type": "object",
        "required": ["values"],
        "properties": {
            "values": {
                "type": "array",
                "x-fortran-shape": "n_values",
                "items": {"type": "integer"},
            }
        },
    }
    _evaluate(runtime, "values = 1, 2, 3", dimensions={"N_VALUES": 3})
    with pytest.raises(ValueError, match="supplies 4 values for 3"):
        _evaluate(runtime, "values = 1, 2, 3, 4", dimensions={"n_values": 3})

    deferred = {
        "x-fortran-namelist": "run",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "x-fortran-shape": ":",
                "items": {"type": "integer"},
            }
        },
    }
    result = _evaluate(deferred, "values = 1, 2, 3")
    assert len(result.states) == 3
    with pytest.raises(ValueError, match="expands to 100000000 items.*safety limit"):
        _evaluate(deferred, "values = 100000000*0")


def _setting_schema(*, shape: object | None = None) -> dict[str, Any]:
    setting = {
        "type": "object",
        "x-fortran-type": "setting_t",
        "properties": {
            "flag": {"type": "boolean", "default": False},
            "value": {"type": "integer", "minimum": 1},
        },
        "required": ["value"],
    }
    prop: dict[str, Any]
    if shape is None:
        prop = setting
    else:
        prop = {"type": "array", "x-fortran-shape": shape, "items": setting}
    return {
        "x-fortran-namelist": "run",
        "type": "object",
        "required": ["settings"],
        "properties": {"settings": prop},
    }


def test_derived_scalar_positional_component_and_null_assignment() -> None:
    schema = _setting_schema()
    result = _evaluate(schema, "settings = , 2\nsettings%flag = T")
    assert result.states[("settings", (), "flag")].value is True
    assert result.states[("settings", (), "value")].value == 2

    with pytest.raises(ValueError, match=r"missing required 'settings%value'"):
        _evaluate(schema, "settings = T")
    with pytest.raises(ValueError, match="supplies 3 values for 2"):
        _evaluate(schema, "settings = T, 1, 2")


def test_derived_required_components_must_exist_during_schema_compilation() -> None:
    schema = _setting_schema()
    schema["properties"]["settings"]["required"].append("missing")

    with pytest.raises(
        ValueError,
        match="derived property 'settings' required component 'missing'.*not declared",
    ):
        _evaluate(schema, "settings = T, 1")


def test_derived_components_must_be_unique_case_insensitively() -> None:
    schema = _setting_schema()
    schema["properties"]["settings"]["properties"]["Flag"] = {"type": "boolean"}

    with pytest.raises(
        ValueError,
        match="derived property 'settings' defines duplicate component 'Flag'.*'flag'",
    ):
        _evaluate(schema, "settings = T, 1")


def test_indexed_and_sectioned_derived_arrays_preserve_record_boundaries() -> None:
    schema = _setting_schema(shape=[2, 2])
    result = _evaluate(
        schema,
        "settings(1,1) = T, 1\n"
        "settings(2,1) = F, 2\n"
        "settings(:,2)%value = 3, 4",
    )
    assert result.states[("settings", (1, 1), "value")].value == 1
    assert result.states[("settings", (2, 1), "value")].value == 2
    assert result.states[("settings", (1, 2), "value")].value == 3
    assert result.states[("settings", (2, 2), "value")].value == 4
    assert ("settings", (2, 2), "flag") not in result.states


def test_whole_derived_array_expands_element_then_component() -> None:
    schema = _setting_schema(shape=2)
    result = _evaluate(schema, "settings = T, 1, F, 2")
    assert [state.value for state in result.states.values()] == [True, 1, False, 2]

    with pytest.raises(ValueError, match=r"settings\(2\).*settings\(2\)%value"):
        _evaluate(schema, "settings = T, 1, F")


def test_null_only_required_value_does_not_establish_presence() -> None:
    schema = _setting_schema(shape=1)
    with pytest.raises(ValueError, match="missing required 'settings'"):
        _evaluate(schema, "settings = 2*")


def test_defaults_are_tracked_but_do_not_satisfy_required_input() -> None:
    schema = {
        "x-fortran-namelist": "run",
        "type": "object",
        "required": ["count"],
        "properties": {"count": {"type": "integer", "default": 4}},
    }
    with pytest.raises(ValueError, match="missing required 'count'"):
        _evaluate(schema, "count = ")

    optional = {**schema, "required": []}
    result = _evaluate(optional, "count = ,")
    state = result.states[("count", (), None)]
    assert state.value == 4
    assert state.initialized_by_default is True
    assert state.explicitly_assigned is False
    assert state.null_consumed is True

    string_schema = {
        "x-fortran-namelist": "run",
        "type": "object",
        "properties": {
            "label": {"type": "string", "x-fortran-len": 4, "default": "a"}
        },
    }
    string_state = _evaluate(string_schema, "label = ,").states[("label", (), None)]
    assert string_state.value == "a   "


def test_character_substrings_and_component_arrays_are_capability_errors() -> None:
    string_schema = {
        "x-fortran-namelist": "run",
        "type": "object",
        "properties": {"label": {"type": "string", "x-fortran-len": 8}},
    }
    with pytest.raises(ValueError, match="substring assignment.*not yet supported"):
        _evaluate(string_schema, "label(2:4) = 'abc'")

    derived = _setting_schema()
    with pytest.raises(ValueError, match="array-valued component selection"):
        _evaluate(derived, "settings%value(1) = 2")

    complex_schema = {
        "x-fortran-namelist": "run",
        "type": "object",
        "properties": {"value": {"type": "complex"}},
    }
    with pytest.raises(ValueError, match="complex.*not supported"):
        _evaluate(complex_schema, "value = (1.0, -2.0)")


def test_optional_derived_values_with_required_members_remain_rejected() -> None:
    schema = _setting_schema()
    schema["required"] = []
    with pytest.raises(ValueError, match="optional derived property 'settings'.*required"):
        validate_schema_defaults(schema)


def test_validate_schema_defaults_traverses_derived_members() -> None:
    schema = _setting_schema()
    schema["properties"]["settings"]["properties"]["flag"] = {
        "type": "string",
        "x-fortran-len": 3,
        "default": "long",
    }
    with pytest.raises(ValueError, match=r"settings\.flag.*exceeds length"):
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
                "properties": {"years": {"type": "array", "items": {"type": "integer"}}},
            },
            "component 'years' must define an intrinsic scalar type",
        ),
    ],
)
def test_validation_rejects_invalid_raw_derived_declarations(
    prop: dict[str, Any], match: str
) -> None:
    schema = {
        "x-fortran-namelist": "run",
        "type": "object",
        "properties": {"period": prop},
    }
    with pytest.raises(ValueError, match=match):
        validate_schema_defaults(schema)
