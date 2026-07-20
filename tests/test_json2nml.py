"""Tests for converting namelist-oriented JSON to Fortran namelists."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from nml_tools import json_to_namelist
from nml_tools.cli import cli


def test_json_to_namelist_renders_scalars_and_empty_groups() -> None:
    rendered = json_to_namelist(
        {
            "solver": {
                "count": 3,
                "ratio": 1.25,
                "enabled": True,
                "disabled": False,
                "label": 'a "quoted" value',
            },
            "empty": {},
        }
    )

    assert rendered == (
        "&solver\n"
        "  count = 3\n"
        "  ratio = 1.25\n"
        "  enabled = .true.\n"
        "  disabled = .false.\n"
        '  label = "a ""quoted"" value"\n'
        "/\n"
        "\n"
        "&empty\n"
        "/\n"
    )


def test_json_to_namelist_accepts_canonical_wrapper() -> None:
    values = {"run": {"count": 2}}
    wrapped = {
        "format_version": 1,
        "profile": "main",
        "dimensions": {"max_domains": 2},
        "values": values,
    }

    assert json_to_namelist(wrapped) == json_to_namelist(values)
    assert json_to_namelist(wrapped) == "&run\n  count = 2\n/\n"


def test_json_to_namelist_indexes_every_array_element() -> None:
    rendered = json_to_namelist(
        {
            "arrays": {
                "vector": [10, 20],
                "matrix": [[11, 12], [21, 22]],
                "cube": [[[1, 2]], [[3, 4]]],
            }
        }
    )

    assert rendered == (
        "&arrays\n"
        "  vector(1) = 10\n"
        "  vector(2) = 20\n"
        "  matrix(1,1) = 11\n"
        "  matrix(1,2) = 12\n"
        "  matrix(2,1) = 21\n"
        "  matrix(2,2) = 22\n"
        "  cube(1,1,1) = 1\n"
        "  cube(1,1,2) = 2\n"
        "  cube(2,1,1) = 3\n"
        "  cube(2,1,2) = 4\n"
        "/\n"
    )


def test_json_to_namelist_renders_derived_fields_and_omitted_components() -> None:
    rendered = json_to_namelist(
        {
            "run": {
                "setting": {
                    "enabled": True,
                    "count": 2,
                    "label": 'a "quoted" value',
                },
                "empty": {},
            }
        }
    )

    assert rendered == (
        "&run\n"
        "  setting%enabled = .true.\n"
        "  setting%count = 2\n"
        '  setting%label = "a ""quoted"" value"\n'
        "/\n"
    )


def test_json_to_namelist_renders_rectangular_derived_arrays() -> None:
    rendered = json_to_namelist(
        {
            "run": {
                "settings": [
                    [{"enabled": True}, {}],
                    [{"count": 3}, {"enabled": False, "count": 4}],
                ]
            }
        }
    )

    assert rendered == (
        "&run\n"
        "  settings(1,1)%enabled = .true.\n"
        "  settings(2,1)%count = 3\n"
        "  settings(2,2)%enabled = .false.\n"
        "  settings(2,2)%count = 4\n"
        "/\n"
    )


@pytest.mark.parametrize(
    "data",
    [
        [],
        {"run": 1},
        {"run": {"value": None}},
        {"run": {"value": []}},
        {"run": {"value": [[1], [2, 3]]}},
        {"run": {"value": [1, [2]]}},
    ],
)
def test_json_to_namelist_rejects_unsupported_structures(data: Any) -> None:
    with pytest.raises(ValueError):
        json_to_namelist(data)


@pytest.mark.parametrize(
    "value",
    [
        {"nested": {"value": 1}},
        {"items": [1]},
        {"missing": None},
    ],
)
def test_json_to_namelist_rejects_non_scalar_derived_components(
    value: dict[str, Any],
) -> None:
    with pytest.raises(ValueError, match="intrinsic scalar"):
        json_to_namelist({"run": {"setting": value}})


@pytest.mark.parametrize(
    "value",
    [
        [{"count": 1}, 2],
        [1, {"count": 2}],
        [[{"count": 1}], [2]],
    ],
)
def test_json_to_namelist_rejects_mixed_scalar_and_object_array_leaves(
    value: list[Any],
) -> None:
    with pytest.raises(ValueError, match="must not mix scalar and object elements"):
        json_to_namelist({"run": {"settings": value}})


@pytest.mark.parametrize(
    "components",
    [
        {"bad-name": 1},
        {"count": 1, "COUNT": 2},
    ],
)
def test_json_to_namelist_rejects_invalid_or_duplicate_component_names(
    components: dict[str, Any],
) -> None:
    with pytest.raises(ValueError):
        json_to_namelist({"run": {"setting": components}})


@pytest.mark.parametrize(
    "data",
    [
        {"bad-name": {"value": 1}},
        {"run": {"1value": 1}},
    ],
)
def test_json_to_namelist_rejects_invalid_identifiers(data: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="identifier"):
        json_to_namelist(data)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_json_to_namelist_rejects_nonfinite_numbers(value: float) -> None:
    with pytest.raises(ValueError):
        json_to_namelist({"run": {"value": value}})


@pytest.mark.parametrize(
    ("input_flag", "output_flag"),
    [("-i", "-o"), ("--input-file", "--output-file")],
)
def test_json2nml_cli_converts_files(
    tmp_path: Path,
    input_flag: str,
    output_flag: str,
) -> None:
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "nested" / "output.nml"
    payload = {
        "dimensions": {"max_domains": 2},
        "values": {"run": {"enabled": [True, False]}},
    }
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "json2nml",
            input_flag,
            str(input_path),
            output_flag,
            str(output_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert output_path.read_text(encoding="utf-8") == json_to_namelist(payload)


def test_json2nml_cli_reports_malformed_json(tmp_path: Path) -> None:
    input_path = tmp_path / "broken.json"
    output_path = tmp_path / "output.nml"
    input_path.write_text('{"values":', encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        ["json2nml", "-i", str(input_path), "-o", str(output_path)],
    )

    assert result.exit_code != 0
    assert "json" in result.output.lower()
    assert not output_path.exists()
