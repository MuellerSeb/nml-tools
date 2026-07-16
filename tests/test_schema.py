"""Tests for schema reference resolution."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest

from nml_tools._namelist_eval import evaluate_group
from nml_tools._namelist_parser import parse_namelist
from nml_tools.codegen_f2py import (
    F2pyCTypeMap,
    build_f2py_namelist_spec,
    collect_f2py_kind_usage,
    render_f2cmap,
    render_f2py_wrappers,
    render_python_wrappers,
)
from nml_tools.codegen_fortran import collect_local_derived_types, render_fortran, render_helper
from nml_tools.codegen_markdown import render_docs
from nml_tools.codegen_template import render_template
from nml_tools.schema import (
    SchemaResolver,
    _is_simple_derived_schema,
    get_string_format,
    load_schema,
    resolve_schema,
)
from nml_tools.validate import validate_schema_defaults


def test_simple_derived_schema_eligibility_is_structural() -> None:
    base = {
        "type": "object",
        "properties": {
            "flag": {"type": "boolean"},
            "future_value": {"type": "complex"},
        },
    }

    assert _is_simple_derived_schema(base)
    assert not _is_simple_derived_schema(
        {
            **base,
            "properties": {
                "values": {"type": "array", "items": {"type": "integer"}},
            },
        }
    )


def test_resolve_schema_composes_inline_scalar_reference() -> None:
    resolved = resolve_schema(
        {
            "title": "Solver",
            "x-fortran-namelist": "solver",
            "type": "object",
            "$defs": {
                "count": {
                    "title": "Count",
                    "type": "integer",
                    "x-fortran-kind": "i4",
                    "minimum": 0,
                    "maximum": 100,
                    "enum": [0, 2, 4],
                    "default": 0,
                }
            },
            "properties": {
                "iterations": {
                    "$ref": "#/$defs/count",
                    "title": "Iterations",
                    "minimum": 1,
                    "enum": [2, 4, 8],
                    "default": 4,
                }
            },
        }
    )

    assert "$defs" not in resolved
    assert resolved["properties"]["iterations"] == {
        "title": "Iterations",
        "type": "integer",
        "x-fortran-kind": "i4",
        "minimum": 1,
        "maximum": 100,
        "enum": [2, 4],
        "default": 4,
    }


def test_load_schema_resolves_relative_json_pointer_with_escapes(tmp_path: Path) -> None:
    definitions = tmp_path / "common" / "definitions.json"
    definitions.parent.mkdir()
    definitions.write_text(
        json.dumps({"$defs": {"rate/~daily": {"type": "number", "x-fortran-kind": "dp"}}}),
        encoding="utf-8",
    )
    schema_path = tmp_path / "schemas" / "calibration.yml"
    schema_path.parent.mkdir()
    schema_path.write_text(
        dedent(
            """
            title: Calibration
            x-fortran-namelist: calibration
            type: object
            properties:
              rate:
                $ref: "../common/definitions.json#/$defs/rate~1~0daily"
                default: 0.25
            """
        ),
        encoding="utf-8",
    )

    resolved = load_schema(schema_path)

    assert resolved["properties"]["rate"] == {
        "type": "number",
        "x-fortran-kind": "dp",
        "default": 0.25,
    }


def test_root_reference_combines_properties_and_required(tmp_path: Path) -> None:
    base = tmp_path / "base.yml"
    base.write_text(
        dedent(
            """
            type: object
            required: [count]
            properties:
              count:
                title: Shared count
                type: integer
                minimum: 0
            """
        ),
        encoding="utf-8",
    )
    root = tmp_path / "schema.yml"
    root.write_text(
        dedent(
            """
            $ref: "base.yml"
            title: Demo
            x-fortran-namelist: demo
            required: [label]
            properties:
              count:
                title: Local count
                minimum: 1
              label:
                type: string
                x-fortran-len: 16
            """
        ),
        encoding="utf-8",
    )

    resolved = load_schema(root)

    assert list(resolved["properties"]) == ["count", "label"]
    assert resolved["properties"]["count"]["title"] == "Local count"
    assert resolved["properties"]["count"]["minimum"] == 1
    assert resolved["required"] == ["count", "label"]
    assert resolved["x-fortran-namelist"] == "demo"


def test_array_default_override_replaces_referenced_control_bundle() -> None:
    resolved = resolve_schema(
        {
            "x-fortran-namelist": "demo",
            "type": "object",
            "$defs": {
                "values": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "x-fortran-shape": 3,
                    "default": [1],
                    "x-fortran-default-repeat": True,
                }
            },
            "properties": {
                "values": {
                    "$ref": "#/$defs/values",
                    "default": [2, 3, 4],
                }
            },
        }
    )

    prop = resolved["properties"]["values"]
    assert prop["default"] == [2, 3, 4]
    assert "x-fortran-default-repeat" not in prop

    with pytest.raises(ValueError, match="requires a local array-level 'default'"):
        resolve_schema(
            {
                "x-fortran-namelist": "demo",
                "type": "object",
                "$defs": {"values": prop},
                "properties": {
                    "values": {
                        "$ref": "#/$defs/values",
                        "x-fortran-default-repeat": True,
                    }
                },
            }
        )


def test_resolve_schema_preserves_string_format_annotations() -> None:
    resolved = resolve_schema(
        {
            "x-fortran-namelist": "run",
            "type": "object",
            "properties": {
                "forcing_file": {
                    "type": "string",
                    "format": "file-path",
                },
                "output_files": {
                    "type": "array",
                    "x-fortran-shape": 2,
                    "items": {
                        "type": "string",
                        "format": "path",
                    },
                },
                "period": {
                    "type": "object",
                    "x-fortran-type": "period_t",
                    "properties": {
                        "start_time": {
                            "type": "string",
                            "format": "date-time",
                        }
                    },
                },
            },
        }
    )

    properties = resolved["properties"]
    assert properties["forcing_file"]["format"] == "file-path"
    assert properties["output_files"]["items"]["format"] == "path"
    assert properties["period"]["properties"]["start_time"]["format"] == "date-time"


def test_resolve_schema_composes_format_as_use_site_annotation() -> None:
    resolved = resolve_schema(
        {
            "x-fortran-namelist": "run",
            "type": "object",
            "$defs": {
                "path": {
                    "type": "string",
                    "format": "path",
                    "x-fortran-len": 128,
                }
            },
            "properties": {
                "input": {"$ref": "#/$defs/path"},
                "output": {
                    "$ref": "#/$defs/path",
                    "format": "directory-path",
                },
            },
        }
    )

    assert resolved["properties"]["input"]["format"] == "path"
    assert resolved["properties"]["output"]["format"] == "directory-path"


def test_resolve_schema_rejects_non_string_format() -> None:
    with pytest.raises(ValueError, match="'format' must be a string"):
        resolve_schema(
            {
                "x-fortran-namelist": "run",
                "type": "object",
                "properties": {
                    "start_time": {
                        "type": "string",
                        "format": 7,
                    }
                },
            }
        )


def test_resolve_schema_allows_property_named_format() -> None:
    resolved = resolve_schema(
        {
            "x-fortran-namelist": "run",
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "x-fortran-len": 16,
                    "enum": ["netcdf", "csv"],
                    "default": "netcdf",
                }
            },
            "required": ["format"],
        }
    )

    assert resolved["properties"]["format"]["type"] == "string"
    assert "format" not in resolved["properties"]["format"]


def test_get_string_format_returns_string_schema_format_only() -> None:
    assert get_string_format({"type": "string", "format": "file-path"}) == "file-path"
    assert get_string_format({"type": "string", "format": "project-specific"}) == (
        "project-specific"
    )
    assert get_string_format({"type": "string"}) is None
    assert get_string_format({"type": "integer", "format": "date"}) is None
    with pytest.raises(ValueError, match="'format' must be a string"):
        get_string_format({"type": "string", "format": 1})


def test_use_site_default_must_satisfy_referenced_constraints() -> None:
    resolved = resolve_schema(
        {
            "x-fortran-namelist": "demo",
            "type": "object",
            "$defs": {"positive": {"type": "integer", "minimum": 1}},
            "properties": {
                "count": {"$ref": "#/$defs/positive", "default": 0},
            },
        }
    )

    with pytest.raises(ValueError, match="must be >= 1"):
        render_template([resolved], value_mode="filled")


@pytest.mark.parametrize(
    ("property_schema", "match"),
    [
        (
            {"$ref": "https://example.invalid/definitions.yml#/$defs/value"},
            "remote or URI",
        ),
        (
            {"$ref": "#/$defs/value", "x-fortran-kind": "i8"},
            "conflicting 'x-fortran-kind'",
        ),
        (
            {"$ref": "#/$defs/value", "minimum": 3, "maximum": 2},
            "empty interval",
        ),
        (
            {"$ref": "#/$defs/value", "enum": [7]},
            "no common values",
        ),
    ],
)
def test_reference_errors_are_rejected(property_schema: dict[str, object], match: str) -> None:
    schema = {
        "x-fortran-namelist": "demo",
        "type": "object",
        "$defs": {
            "value": {
                "type": "integer",
                "x-fortran-kind": "i4",
                "minimum": 0,
                "maximum": 4,
                "enum": [1, 2],
            }
        },
        "properties": {"value": property_schema},
    }

    with pytest.raises(ValueError, match=match):
        resolve_schema(schema)


def test_reference_cycle_and_declared_old_dialect_are_rejected(tmp_path: Path) -> None:
    cycle = {
        "x-fortran-namelist": "demo",
        "type": "object",
        "$defs": {
            "left": {"$ref": "#/$defs/right"},
            "right": {"$ref": "#/$defs/left"},
        },
        "properties": {"value": {"$ref": "#/$defs/left"}},
    }
    with pytest.raises(ValueError, match="cyclic"):
        resolve_schema(cycle)

    schema_path = tmp_path / "schema.yml"
    schema_path.write_text(
        dedent(
            """
            $schema: "http://json-schema.org/draft-07/schema#"
            x-fortran-namelist: demo
            type: object
            $defs:
              value:
                type: integer
            properties:
              value:
                $ref: "#/$defs/value"
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Draft 2020-12"):
        load_schema(schema_path)


def test_resolve_mapping_external_reference_requires_source_path() -> None:
    schema = {
        "x-fortran-namelist": "demo",
        "type": "object",
        "properties": {"value": {"$ref": "definitions.yml#/$defs/value"}},
    }

    with pytest.raises(ValueError, match="requires a source path"):
        resolve_schema(schema)


@pytest.mark.parametrize(
    "ref",
    [r"C:\schemas\definitions.yml#/$defs/value", "C:/schemas/definitions.yml#/$defs/value"],
)
def test_windows_absolute_references_are_local_file_references(ref: str) -> None:
    schema = {
        "x-fortran-namelist": "demo",
        "type": "object",
        "properties": {"value": {"$ref": ref}},
    }

    with pytest.raises(ValueError, match="requires a source path"):
        resolve_schema(schema)


def test_unresolved_reference_diagnostic_identifies_use_site_and_target(tmp_path: Path) -> None:
    definitions = tmp_path / "definitions.yml"
    definitions.write_text("$defs: {}\n", encoding="utf-8")
    schema_path = tmp_path / "schema.yml"
    schema_path.write_text(
        "x-fortran-namelist: demo\n"
        "type: object\n"
        "properties:\n"
        "  value:\n"
        '    $ref: "definitions.yml#/$defs/value"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as exc_info:
        load_schema(schema_path)

    message = str(exc_info.value)
    assert f"{schema_path.resolve()}#/properties/value" in message
    assert "definitions.yml#/$defs/value" in message
    assert f"{definitions.resolve()}#/$defs/value" in message


def test_shared_resolver_caches_referenced_documents(tmp_path: Path) -> None:
    definitions = tmp_path / "definitions.yml"
    definitions.write_text("$defs:\n  value:\n    type: integer\n", encoding="utf-8")
    for name in ("one", "two"):
        (tmp_path / f"{name}.yml").write_text(
            "x-fortran-namelist: demo\n"
            "type: object\n"
            "properties:\n"
            "  value:\n"
            '    $ref: "definitions.yml#/$defs/value"\n',
            encoding="utf-8",
        )
    resolver = SchemaResolver()
    first = load_schema(tmp_path / "one.yml", resolver=resolver)
    definitions.write_text("$defs:\n  value:\n    type: number\n", encoding="utf-8")
    second = load_schema(tmp_path / "two.yml", resolver=resolver)

    assert first["properties"]["value"]["type"] == "integer"
    assert second["properties"]["value"]["type"] == "integer"


def test_resolved_schema_is_equivalent_for_outputs_and_validation(tmp_path: Path) -> None:
    inline = {
        "title": "Demo",
        "x-fortran-namelist": "demo",
        "type": "object",
        "properties": {
            "values": {
                "title": "Values",
                "type": "array",
                "items": {"type": "number", "x-fortran-kind": "dp", "minimum": 0.0},
                "x-fortran-shape": "n_values",
                "default": [1.0],
                "x-fortran-default-repeat": True,
            }
        },
    }
    referenced = resolve_schema(
        {
            "title": "Demo",
            "x-fortran-namelist": "demo",
            "type": "object",
            "$defs": {"values": inline["properties"]["values"]},
            "properties": {"values": {"$ref": "#/$defs/values"}},
        }
    )
    options = {"constants": None, "dimensions": {"n_values": 2}}

    assert render_fortran(
        referenced, file_name="nml_demo.f90", dimensions={"n_values": 2}
    ) == render_fortran(inline, file_name="nml_demo.f90", dimensions={"n_values": 2})
    assert render_docs(referenced, dimensions={"n_values": 2}) == render_docs(
        inline, dimensions={"n_values": 2}
    )
    assert render_template(
        [referenced], value_mode="filled", dimensions={"n_values": 2}
    ) == render_template([inline], value_mode="filled", dimensions={"n_values": 2})
    assert render_f2py_wrappers(
        [referenced],
        file_name="f2py_demo.f90",
        kind_module="iso_fortran_env",
        kind_map={"dp": "real64"},
        kind_allowlist={"real64"},
        dimensions={"n_values": 2},
    ) == render_f2py_wrappers(
        [inline],
        file_name="f2py_demo.f90",
        kind_module="iso_fortran_env",
        kind_map={"dp": "real64"},
        kind_allowlist={"real64"},
        dimensions={"n_values": 2},
    )
    spec_options = {
        "kind_module": "iso_fortran_env",
        "kind_map": {"dp": "real64"},
        "kind_allowlist": {"real64"},
        "dimensions": {"n_values": 2},
    }
    assert render_python_wrappers(
        [(build_f2py_namelist_spec(referenced, **spec_options), "wrappers")]
    ) == render_python_wrappers([(build_f2py_namelist_spec(inline, **spec_options), "wrappers")])
    usage = collect_f2py_kind_usage([referenced], **options)
    assert render_f2cmap(usage, F2pyCTypeMap(real={"dp": "double"}, integer={})) == (
        "dict(real=dict(dp='double'), integer=dict(c_intptr_t='long_long'))\n"
    )
    parsed = parse_namelist("&demo\nvalues = 1.0, 2.0\n/")
    evaluate_group(parsed.groups[0], referenced, dimensions={"n_values": 2})


def test_resolve_schema_preserves_referenced_derived_type_origin_and_refinements() -> None:
    resolved = resolve_schema(
        {
            "x-fortran-namelist": "run",
            "type": "object",
            "$defs": {
                "period": {
                    "title": "Time period",
                    "description": "Reusable bounds for one period.",
                    "type": "object",
                    "x-fortran-type": "period_t",
                    "properties": {
                        "start_year": {"type": "integer", "minimum": 1900},
                        "label": {"type": "string", "x-fortran-len": 16},
                    },
                    "required": ["start_year"],
                }
            },
            "required": ["period"],
            "properties": {
                "period": {
                    "$ref": "#/$defs/period",
                    "title": "Evaluation period",
                    "properties": {
                        "start_year": {"minimum": 2000},
                        "label": {"default": "calibration"},
                    },
                }
            },
        }
    )

    period = resolved["properties"]["period"]
    assert period["x-fortran-type"] == "period_t"
    assert period["title"] == "Evaluation period"
    assert period["properties"]["start_year"]["minimum"] == 2000
    assert period["properties"]["label"]["default"] == "calibration"
    origin = period["_nml_tools_ref_origin"]
    assert origin["identity"][0].startswith("<mapping:")
    assert origin["identity"][1] == "/$defs/period"
    assert origin["definition"]["title"] == "Time period"
    assert origin["definition"]["properties"]["start_year"]["minimum"] == 1900


def test_resolve_schema_accepts_arrays_of_referenced_derived_values() -> None:
    resolved = resolve_schema(
        {
            "x-fortran-namelist": "run",
            "type": "object",
            "$defs": {
                "period": {
                    "type": "object",
                    "x-fortran-type": "period_t",
                    "properties": {"year": {"type": "integer"}},
                }
            },
            "properties": {
                "periods": {
                    "type": "array",
                    "x-fortran-shape": "n_periods",
                    "items": {"$ref": "#/$defs/period"},
                }
            },
        }
    )

    assert resolved["properties"]["periods"]["items"]["x-fortran-type"] == "period_t"
    identity = resolved["properties"]["periods"]["items"]["_nml_tools_ref_origin"]["identity"]
    assert identity[0].startswith("<mapping:")
    assert identity[1] == "/$defs/period"


def test_resolve_schema_accepts_inline_single_use_derived_definitions() -> None:
    resolved = resolve_schema(
        {
            "x-fortran-namelist": "run",
            "type": "object",
            "required": ["station", "periods"],
            "properties": {
                "station": {
                    "title": "Selected station",
                    "type": "object",
                    "x-fortran-type": "station_t",
                    "x-fortran-module": "application_types",
                    "required": ["code"],
                    "properties": {
                        "code": {"type": "integer"},
                        "label": {"type": "string", "x-fortran-len": 8},
                    },
                },
                "periods": {
                    "type": "array",
                    "x-fortran-shape": 2,
                    "items": {
                        "title": "Period",
                        "type": "object",
                        "x-fortran-type": "period_t",
                        "properties": {"year": {"type": "integer"}},
                    },
                },
            },
        }
    )

    station = resolved["properties"]["station"]
    periods = resolved["properties"]["periods"]["items"]
    assert station["_nml_tools_ref_origin"]["identity"][1] == "/properties/station"
    assert station["_nml_tools_ref_origin"]["definition"]["title"] == "Selected station"
    assert periods["_nml_tools_ref_origin"]["identity"][1] == "/properties/periods/items"
    parsed = parse_namelist(
        "&run\nstation%code = 7\nperiods(1)%year = 1\nperiods(2)%year = 2\n/"
    )
    evaluate_group(parsed.groups[0], resolved)


def test_inline_optional_derived_type_rejects_required_members_during_validation() -> None:
    resolved = resolve_schema(
        {
            "x-fortran-namelist": "run",
            "type": "object",
            "properties": {
                "period": {
                    "type": "object",
                    "x-fortran-type": "period_t",
                    "required": ["year"],
                    "properties": {"year": {"type": "integer"}},
                }
            },
        }
    )

    with pytest.raises(ValueError, match="optional derived property 'period'.*required"):
        validate_schema_defaults(resolved)


def test_inline_derived_type_is_equivalent_to_one_use_reference_for_outputs() -> None:
    type_definition = {
        "title": "Period",
        "description": "One period.",
        "type": "object",
        "x-fortran-type": "period_t",
        "properties": {
            "year": {"title": "Year", "type": "integer", "default": 2001},
        },
    }
    inline = resolve_schema(
        {
            "x-fortran-namelist": "run",
            "type": "object",
            "properties": {"period": type_definition},
        }
    )
    referenced = resolve_schema(
        {
            "x-fortran-namelist": "run",
            "type": "object",
            "$defs": {"period": type_definition},
            "properties": {"period": {"$ref": "#/$defs/period"}},
        }
    )

    assert render_fortran(inline, file_name="nml_run.f90") == render_fortran(
        referenced, file_name="nml_run.f90"
    )
    assert render_docs(inline) == render_docs(referenced)
    assert render_template([inline], value_mode="filled") == render_template(
        [referenced], value_mode="filled"
    )
    inline_helper = render_helper(
        file_name="nml_helper.f90", local_derived_types=collect_local_derived_types([inline])
    )
    reference_helper = render_helper(
        file_name="nml_helper.f90", local_derived_types=collect_local_derived_types([referenced])
    )
    assert inline_helper == reference_helper
    assert render_f2py_wrappers([inline], file_name="f2py_run.f90") == render_f2py_wrappers(
        [referenced], file_name="f2py_run.f90"
    )


def test_source_less_inline_origins_are_unique_and_local_type_reuse_is_rejected() -> None:
    schema = {
        "x-fortran-namelist": "run",
        "type": "object",
        "properties": {
            "period": {
                "type": "object",
                "x-fortran-type": "period_t",
                "properties": {"year": {"type": "integer"}},
            }
        },
    }
    first = resolve_schema(schema)
    second = resolve_schema(schema)
    first_identity = first["properties"]["period"]["_nml_tools_ref_origin"]["identity"]
    second_identity = second["properties"]["period"]["_nml_tools_ref_origin"]["identity"]

    assert first_identity[0].startswith("<mapping:")
    assert second_identity[0].startswith("<mapping:")
    assert first_identity != second_identity
    with pytest.raises(ValueError, match="used by distinct definitions"):
        collect_local_derived_types([first, second])

    mixed = resolve_schema(
        {
            "x-fortran-namelist": "run",
            "type": "object",
            "$defs": {
                "period": {
                    "type": "object",
                    "x-fortran-type": "period_t",
                    "properties": {"year": {"type": "integer"}},
                }
            },
            "properties": {
                "referenced": {"$ref": "#/$defs/period"},
                "inline": {
                    "type": "object",
                    "x-fortran-type": "period_t",
                    "properties": {"year": {"type": "integer"}},
                },
            },
        }
    )
    with pytest.raises(ValueError, match="used by distinct definitions"):
        collect_local_derived_types([mixed])


def test_resolve_schema_rejects_user_authored_derived_origin_marker() -> None:
    with pytest.raises(ValueError, match="_nml_tools_ref_origin.*reserved"):
        resolve_schema(
            {
                "x-fortran-namelist": "run",
                "type": "object",
                "_nml_tools_ref_origin": {},
                "properties": {"year": {"type": "integer"}},
            }
        )


@pytest.mark.parametrize("container", ["$defs", "definitions"])
def test_resolve_schema_validates_identifiers_in_definition_containers(container: str) -> None:
    with pytest.raises(ValueError, match="'x-fortran-type'.*must not contain '__'"):
        resolve_schema(
            {
                "x-fortran-namelist": "run",
                "type": "object",
                container: {
                    "period": {
                        "type": "object",
                        "x-fortran-type": "period__t",
                        "properties": {"year": {"type": "integer"}},
                    }
                },
                "properties": {"year": {"type": "integer"}},
            }
        )


@pytest.mark.parametrize("container", ["allOf", "anyOf", "oneOf"])
def test_resolve_schema_validates_identifiers_in_combinator_containers(container: str) -> None:
    with pytest.raises(ValueError, match="property 'start__year'.*must not contain '__'"):
        resolve_schema(
            {
                "x-fortran-namelist": "run",
                "type": "object",
                container: [
                    {
                        "type": "object",
                        "properties": {"start__year": {"type": "integer"}},
                    }
                ],
                "properties": {"year": {"type": "integer"}},
            }
        )


@pytest.mark.parametrize(
    ("property_schema", "match"),
    [
        (
            {"type": "object", "properties": {"year": {"type": "integer"}}},
            "define 'x-fortran-type' inline or use '\\$ref'",
        ),
        (
            {"$ref": "#/$defs/missing_type"},
            "must define non-empty 'x-fortran-type'",
        ),
        (
            {"$ref": "#/$defs/period", "properties": {"other": {"type": "integer"}}},
            "must not add component",
        ),
        (
            {"$ref": "#/$defs/period", "x-fortran-type": "other_t"},
            "conflicting 'x-fortran-type'",
        ),
        (
            {"$ref": "#/$defs/period", "x-fortran-module": "application_types"},
            "must be declared on the referenced derived definition",
        ),
        (
            {"$ref": "#/$defs/invalid_component"},
            "property 'start-year' must be a valid Fortran identifier",
        ),
    ],
)
def test_referenced_derived_type_rejects_invalid_property_forms(
    property_schema: dict[str, object], match: str
) -> None:
    definitions: dict[str, dict[str, object]] = {
        "missing_type": {
            "type": "object",
            "properties": {"year": {"type": "integer"}},
        },
        "period": {
            "type": "object",
            "x-fortran-type": "period_t",
            "properties": {"year": {"type": "integer"}},
        },
    }
    if property_schema.get("$ref") == "#/$defs/invalid_component":
        definitions["invalid_component"] = {
            "type": "object",
            "x-fortran-type": "invalid_t",
            "properties": {"start-year": {"type": "integer"}},
        }

    with pytest.raises(ValueError, match=match):
        resolve_schema(
            {
                "x-fortran-namelist": "run",
                "type": "object",
                "$defs": definitions,
                "properties": {"period": property_schema},
            }
        )


@pytest.mark.parametrize(
    ("property_schema", "match"),
    [
        (
            {"$ref": "#/$defs/nested"},
            "component 'child' must define an intrinsic scalar type",
        ),
        (
            {"$ref": "#/$defs/array_component"},
            "component 'years' must define an intrinsic scalar type",
        ),
        (
            {
                "type": "array",
                "x-fortran-shape": 2,
                "x-fortran-flex-tail-dims": 1,
                "items": {"$ref": "#/$defs/period"},
            },
            "derived-type arrays must not define 'x-fortran-flex-tail-dims'",
        ),
    ],
)
def test_referenced_derived_types_reject_unsupported_v1_layouts(
    property_schema: dict[str, object], match: str
) -> None:
    schema = {
        "x-fortran-namelist": "run",
        "type": "object",
        "$defs": {
            "period": {
                "type": "object",
                "x-fortran-type": "period_t",
                "properties": {"year": {"type": "integer"}},
            },
            "nested": {
                "type": "object",
                "x-fortran-type": "nested_t",
                "properties": {"child": {"$ref": "#/$defs/period"}},
            },
            "array_component": {
                "type": "object",
                "x-fortran-type": "array_component_t",
                "properties": {
                    "years": {
                        "type": "array",
                        "x-fortran-shape": 2,
                        "items": {"type": "integer"},
                    }
                },
            },
        },
        "properties": {"value": property_schema},
    }

    with pytest.raises(ValueError, match=match):
        resolve_schema(schema)


@pytest.mark.parametrize(
    ("namelist_name", "match"),
    [
        ("1run", "valid Fortran identifier"),
        ("run__config", "must not contain '__'"),
        (" run", "valid Fortran identifier"),
    ],
)
def test_schema_rejects_invalid_fortran_namelist_names(
    namelist_name: str, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        resolve_schema(
            {
                "x-fortran-namelist": namelist_name,
                "type": "object",
                "properties": {"value": {"type": "integer"}},
            }
        )


@pytest.mark.parametrize(
    ("property_schema", "match"),
    [
        (
            {
                "type": "object",
                "x-fortran-type": "parent_t",
                "properties": {
                    "child": {
                        "type": "object",
                        "x-fortran-type": "child_t",
                        "properties": {"value": {"type": "integer"}},
                    }
                },
            },
            "component 'child' must define an intrinsic scalar type",
        ),
        (
            {
                "type": "object",
                "x-fortran-type": "period_t",
                "default": {},
                "properties": {"year": {"type": "integer"}},
            },
            "derived-type object must not define a default",
        ),
        (
            {
                "type": "array",
                "x-fortran-shape": 2,
                "default": [],
                "items": {
                    "type": "object",
                    "x-fortran-type": "period_t",
                    "properties": {"year": {"type": "integer"}},
                },
            },
            "derived-type arrays must not define defaults",
        ),
    ],
)
def test_inline_derived_types_reject_unsupported_v1_layouts(
    property_schema: dict[str, object], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        resolve_schema(
            {
                "x-fortran-namelist": "run",
                "type": "object",
                "properties": {"value": property_schema},
            }
        )


@pytest.mark.parametrize(
    ("property_schema", "match"),
    [
        (
            {"value__generated": {"type": "integer"}},
            "property 'value__generated' must not contain",
        ),
        (
            {
                "period": {
                    "type": "object",
                    "x-fortran-type": "period__t",
                    "properties": {"year": {"type": "integer"}},
                }
            },
            "'x-fortran-type' must not contain",
        ),
        (
            {
                "period": {
                    "type": "object",
                    "x-fortran-type": "period_t",
                    "x-fortran-module": "app__types",
                    "properties": {"year": {"type": "integer"}},
                }
            },
            "'x-fortran-module' must not contain",
        ),
        (
            {
                "period": {
                    "type": "object",
                    "x-fortran-type": "period_t",
                    "properties": {"start__year": {"type": "integer"}},
                }
            },
            "property 'start__year' must not contain",
        ),
    ],
)
def test_schema_rejects_reserved_double_underscore_identifiers(
    property_schema: dict[str, object], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        resolve_schema(
            {
                "x-fortran-namelist": "run",
                "type": "object",
                "properties": property_schema,
            }
        )


@pytest.mark.parametrize(
    ("property_schema", "match"),
    [
        (
            {
                "period": {
                    "type": "object",
                    "x-fortran-type": 1,
                    "properties": {"year": {"type": "integer"}},
                }
            },
            "'x-fortran-type' must be a valid Fortran identifier",
        ),
        (
            {
                "period": {
                    "type": "object",
                    "x-fortran-type": "period_t",
                    "x-fortran-module": 1,
                    "properties": {"year": {"type": "integer"}},
                }
            },
            "'x-fortran-module' must be a valid Fortran identifier",
        ),
        (
            {
                "period": {
                    "type": "object",
                    "x-fortran-type": "period_t",
                    "properties": {1: {"type": "integer"}},
                }
            },
            "property names must be strings",
        ),
    ],
)
def test_schema_rejects_invalid_identifier_container_values(
    property_schema: dict[str, object], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        resolve_schema(
            {
                "x-fortran-namelist": "run",
                "type": "object",
                "properties": property_schema,
            }
        )
