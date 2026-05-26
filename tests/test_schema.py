"""Tests for schema reference resolution."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest

from nml_tools.codegen_f2py import (
    F2pyCTypeMap,
    build_f2py_namelist_spec,
    collect_f2py_kind_usage,
    render_f2cmap,
    render_f2py_wrappers,
    render_python_wrappers,
)
from nml_tools.codegen_fortran import render_fortran
from nml_tools.codegen_markdown import render_docs
from nml_tools.codegen_template import render_template
from nml_tools.schema import SchemaResolver, load_schema, resolve_schema
from nml_tools.validate import validate_namelist


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
    validate_namelist(referenced, {"values": [1.0, 2.0]}, dimensions={"n_values": 2})
