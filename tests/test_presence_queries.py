"""Schema removal and generation contracts for general array presence queries."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from nml_tools._namelist_eval import evaluate_group
from nml_tools._namelist_parser import parse_namelist
from nml_tools.codegen_f2py import render_f2py_wrappers
from nml_tools.codegen_fortran import ConstantSpec, render_fortran, render_helper
from nml_tools.codegen_markdown import render_docs
from nml_tools.codegen_template import render_template
from nml_tools.schema import load_schema, resolve_schema
from nml_tools.validate import validate_schema_defaults


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "x-fortran-namelist": "run",
        "properties": {"value": {"type": "integer"}},
    }


@pytest.mark.parametrize("value", [0, 1, None, False])
@pytest.mark.parametrize("location", ["root", "property", "items", "definition", "ref"])
def test_removed_keyword_rejected_at_schema_nodes(value: Any, location: str) -> None:
    schema = _schema()
    node = schema
    pointer = ""
    if location in {"property", "items", "ref"}:
        node = schema["properties"]["value"]
        pointer = "/properties/value"
    if location == "items":
        node.update(type="array", items={"type": "integer"})
        node = node["items"]
        pointer += "/items"
    if location in {"definition", "ref"}:
        schema["$defs"] = {"unused": {"type": "integer"}}
        if location == "definition":
            node = schema["$defs"]["unused"]
            pointer = "/$defs/unused"
        else:
            node["$ref"] = "#/$defs/unused"
    node["x-fortran-flex-tail-dims"] = value
    with pytest.raises(ValueError, match="x-fortran-flex-tail-dims.*was removed") as error:
        resolve_schema(schema)
    assert f"<mapping>#{pointer}:" in str(error.value)
    assert "set_mask()" in str(error.value)


@pytest.mark.parametrize("container", ["$defs", "types"])
def test_removed_keyword_rejected_in_external_document(tmp_path: Path, container: str) -> None:
    referenced = tmp_path / "common.json"
    referenced.write_text(
        json.dumps({container: {"values": {
            "type": "array", "x-fortran-shape": 2, "items": {"type": "integer"},
            "x-fortran-flex-tail-dims": 0,
        }}}),
        encoding="ascii",
    )
    schema = _schema()
    schema["properties"]["value"] = {"$ref": f"common.json#/{container}/values"}
    root = tmp_path / "run.json"
    root.write_text(json.dumps(schema), encoding="ascii")
    with pytest.raises(ValueError, match="x-fortran-flex-tail-dims.*was removed") as error:
        load_schema(root)
    assert f"{referenced}#/{container}/values:" in str(error.value)


def test_removed_keyword_in_annotation_data_is_not_a_schema_keyword() -> None:
    schema = _schema()
    schema["properties"]["value"]["examples"] = [{"x-fortran-flex-tail-dims": 1}]
    assert resolve_schema(schema) == schema


@pytest.mark.parametrize("consumer", ["fortran", "markdown", "template", "f2py", "evaluate"])
def test_direct_consumers_reject_removed_keyword(consumer: str) -> None:
    schema = _schema()
    schema["properties"]["value"]["x-fortran-flex-tail-dims"] = 0
    with pytest.raises(ValueError, match="x-fortran-flex-tail-dims.*was removed"):
        if consumer == "fortran":
            render_fortran(schema, file_name="run.f90")
        elif consumer == "markdown":
            render_docs(schema)
        elif consumer == "template":
            render_template([schema])
        elif consumer == "f2py":
            render_f2py_wrappers([schema], file_name="wrapper.f90")
        else:
            evaluate_group(parse_namelist("&run value=1 /").groups[0], schema)


def test_presence_overloads_are_deduplicated_and_only_emitted_for_arrays() -> None:
    schema = _schema()
    scalar = render_fortran(schema, file_name="run.f90")
    assert "generic :: set_mask" not in scalar
    assert "procedure :: filled_shape" not in scalar
    for name, shape in (("first", [2]), ("second", [3]), ("cube", [2, 3, 4])):
        schema["properties"][name] = {
            "type": "array", "items": {"type": "integer"}, "x-fortran-shape": shape,
        }
    generated = render_fortran(schema, file_name="run.f90")
    assert generated.count("procedure, private :: set_mask__rank__1 =>") == 1
    assert generated.count("procedure, private :: set_mask__rank__3 =>") == 1
    assert "set_mask__rank__2" not in generated
    validation = generated.split("integer function nml_run_is_valid(", 1)[1]
    assert "filled_shape" not in validation


def test_sparse_optional_array_retains_ordinary_evaluator_rules() -> None:
    schema = _schema()
    schema["properties"] = {"values": {
        "type": "array", "items": {"type": "integer", "minimum": 0},
        "x-fortran-shape": [2, 3],
    }}
    validate_schema_defaults(schema)
    parsed = parse_namelist("&run values(2,3)=4 /")
    result = evaluate_group(parsed.groups[0], schema)
    assert result.states[("values", (2, 3), None)].value == 4
    assert len(result.states) == 1


def _compile_and_run(
    tmp_path: Path, schema: dict[str, Any], program: str, constants: dict[str, int]
) -> None:
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran is required for the generated-code regression test")
    (tmp_path / "nml_helper.f90").write_text(
        render_helper(
            file_name="nml_helper.f90",
            constants=[
                ConstantSpec(name=name, type_spec="integer", value=str(value), doc=None)
                for name, value in constants.items()
            ],
        ),
        encoding="ascii",
    )
    (tmp_path / "config.f90").write_text(
        render_fortran(schema, file_name="config.f90", constants=constants), encoding="ascii"
    )
    (tmp_path / "main.f90").write_text(program, encoding="ascii")
    compiled = subprocess.run(
        [compiler, "-std=f2008", "-fcheck=all", "nml_helper.f90", "config.f90",
         "main.f90", "-o", "conformance"],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    subprocess.run([str(tmp_path / "conformance")], cwd=tmp_path, check=True)


@pytest.mark.parametrize("constant", ["max", "shape", "MaX", "ShApE"])
def test_presence_queries_compile_with_intrinsic_named_constants(
    tmp_path: Path, constant: str
) -> None:
    schema = _schema()
    items: dict[str, Any] = {"type": "integer"}
    if constant.lower() == "shape":
        items["default"] = 7
    schema["properties"] = {"values": {
        "type": "array", "x-fortran-shape": [constant], "items": items,
    }}
    expected = 3 if constant.lower() == "shape" else 2
    program = f"""
program conformance
  use nml_run, only: nml_run_t
  implicit none
  type(nml_run_t) :: cfg
  integer :: status, filled(1)
  logical, allocatable :: mask(:)
  status = cfg%set(values=[1,2])
  if (status /= 0) stop 1
  status = cfg%set_mask("values", mask)
  if (status /= 0) stop 2
  if (count(mask) /= {expected}) stop 3
  status = cfg%filled_shape("values", filled)
  if (status /= 0 .or. any(filled /= {expected})) stop 4
  status = cfg%is_set("values", [1])
  if (status /= 0) stop 5
  status = cfg%is_set("values", [3,1])
  if (status /= 21) stop 6
  status = cfg%is_set("values", [4])
  if (status /= 21) stop 7
end program conformance
"""
    _compile_and_run(tmp_path, schema, program, {constant: 3})


@pytest.mark.parametrize("name_length", [42, 49])
def test_presence_queries_compile_with_long_namelist_names(
    tmp_path: Path, name_length: int
) -> None:
    name = "long_" + "n" * (name_length - 5)
    schema = _schema()
    schema["x-fortran-namelist"] = name
    schema["properties"] = {
        "values": {"type": "array", "x-fortran-shape": [3], "items": {"type": "integer"}},
        "flags": {
            "type": "array", "x-fortran-shape": [2, 3],
            "items": {"type": "boolean", "default": False},
        },
    }
    program = f"""
program conformance
  use nml_{name}, only: &
    config_t => nml_{name}_t
  implicit none
  type(config_t) :: cfg
  integer :: status, filled(1), full(2)
  logical, allocatable :: mask(:), flags(:,:)
  status = cfg%set(values=[1,2])
  if (status /= 0) stop 1
  status = cfg%set_mask("values", mask)
  if (status /= 0 .or. count(mask) /= 2) stop 2
  status = cfg%set_mask("flags", flags)
  if (status /= 0 .or. .not. all(flags)) stop 3
  status = cfg%filled_shape("values", filled)
  if (status /= 0 .or. any(filled /= 2)) stop 4
  status = cfg%filled_shape("flags", full)
  if (status /= 0 .or. any(full /= [2,3])) stop 5
end program conformance
"""
    _compile_and_run(tmp_path, schema, program, {})


@pytest.mark.parametrize("name,rank", [("mcmc_error_params", 3), ("values_" + "x" * 36, 1)])
def test_partial_set_sections_compile_with_long_fields(
    tmp_path: Path, name: str, rank: int
) -> None:
    schema = _schema()
    schema["properties"] = {name: {
        "type": "array", "x-fortran-shape": [3] * rank, "items": {"type": "number"},
    }}
    prefix = ",".join(str(extent) for extent in [2] + [1] * (rank - 1))
    program = f"""
program conformance
  use nml_run, only: nml_run_t
  implicit none
  type(nml_run_t) :: cfg
  integer :: status, filled({rank})
  status = cfg%set({name}=reshape([1.,2.], [{prefix}]))
  if (status /= 0) stop 1
  status = cfg%filled_shape("{name}", filled)
  if (status /= 0 .or. any(filled /= [{prefix}])) stop 2
end program conformance
"""
    _compile_and_run(tmp_path, schema, program, {})
