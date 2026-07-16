"""Tests for CLI config loading helpers."""

from __future__ import annotations

import importlib
from pathlib import Path
from textwrap import dedent
from typing import Any

import click
import pytest
from click.testing import CliRunner

cli_module: Any = importlib.import_module("nml_tools.cli")


def test_resolve_config_path_errors_without_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(click.ClickException, match="no config found"):
        cli_module._resolve_config_path(None)


def test_resolve_config_path_prefers_nml_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "nml-config.toml").write_text("[kinds]\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[tool.nml-tools]\nminimum-version = \"9999\"\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert cli_module._resolve_config_path(None) == Path("nml-config.toml")


def test_load_config_checked_reads_pyproject_tool_section(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        dedent(
            """
            [project]
            name = "demo"
            version = "0.1.0"

            [tool.nml-tools]
            required-version = ">=0"

            [tool.nml-tools.kinds]
            module = "iso_fortran_env"
            """
        ),
        encoding="utf-8",
    )

    config, path = cli_module._load_config_checked(pyproject)

    assert path == pyproject
    assert config == {
        "required-version": ">=0",
        "kinds": {"module": "iso_fortran_env"},
    }


def test_load_config_checked_reads_standalone_root_table(tmp_path: Path) -> None:
    config_path = tmp_path / "custom.toml"
    config_path.write_text(
        dedent(
            """
            required-version = ">=0"

            [kinds]
            module = "iso_fortran_env"
            """
        ),
        encoding="utf-8",
    )

    config, path = cli_module._load_config_checked(config_path)

    assert path == config_path
    assert config["kinds"] == {"module": "iso_fortran_env"}


def test_extract_pyproject_config_rejects_missing_tool_section() -> None:
    with pytest.raises(click.ClickException, match=r"\[tool.nml-tools\]"):
        cli_module._extract_pyproject_config({})

    with pytest.raises(click.ClickException, match=r"\[tool.nml-tools\]"):
        cli_module._extract_pyproject_config({"tool": {}})


def test_has_pyproject_config_requires_tool_table() -> None:
    assert cli_module._has_pyproject_config({"tool": {"nml-tools": {}}}) is True
    assert cli_module._has_pyproject_config({"tool": {"nml-tools": ""}}) is False
    assert cli_module._has_pyproject_config({"project": {"name": "demo"}}) is False


def test_check_required_version_accepts_valid_specifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_module, "__version__", "0.3.1")

    cli_module._check_required_version({})
    cli_module._check_required_version({"required-version": ">=0.3,<0.4"})


def test_check_required_version_rejects_invalid_values() -> None:
    with pytest.raises(click.ClickException, match="non-empty string"):
        cli_module._check_required_version({"required-version": ""})

    with pytest.raises(click.ClickException, match="non-empty string"):
        cli_module._check_required_version({"required-version": 1})

    with pytest.raises(click.ClickException, match="required-version"):
        cli_module._check_required_version({"required-version": "not a specifier"})


def test_check_required_version_rejects_mismatched_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_module, "__version__", "0.3.1")

    with pytest.raises(click.ClickException, match="requires nml-tools"):
        cli_module._check_required_version({"required-version": ">=0.4"})

    with pytest.raises(click.ClickException, match="requires nml-tools"):
        cli_module._check_required_version({"required-version": ">=0.2,<0.3"})


def test_check_required_version_supports_legacy_minimum_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_module, "__version__", "0.3.1")

    cli_module._check_required_version({"minimum-version": "0.3"})

    with pytest.raises(click.ClickException, match="non-empty string"):
        cli_module._check_required_version({"minimum-version": ""})

    with pytest.raises(click.ClickException, match="valid version"):
        cli_module._check_required_version({"minimum-version": "not a version"})

    with pytest.raises(click.ClickException, match="requires nml-tools"):
        cli_module._check_required_version({"minimum-version": "9999"})


def test_check_required_version_rejects_minimum_and_required_conflict() -> None:
    with pytest.raises(click.ClickException, match="use 'required-version'"):
        cli_module._check_required_version(
            {
                "minimum-version": "0.3",
                "required-version": ">=0.3,<0.4",
            }
        )


def test_load_constants_normalizes_names_case_insensitively() -> None:
    constants, specs = cli_module._load_constants(
        {"constants": {"BUF": {"value": 128, "doc": "Buffer length."}}}
    )

    assert constants == {"buf": 128}
    assert specs[0].name == "buf"
    assert specs[0].doc == "Buffer length."

    with pytest.raises(click.ClickException, match="duplicates another constant"):
        cli_module._load_constants(
            {
                "constants": {
                    "buf": {"value": 128},
                    "BUF": {"value": 256},
                }
            }
        )

    with pytest.raises(click.ClickException, match="must be integers"):
        cli_module._load_constants({"constants": {"ratio": {"value": 1.5}}})

    with pytest.raises(click.ClickException, match="must not contain '__'"):
        cli_module._load_constants({"constants": {"buf__len": {"value": 128}}})


def test_load_dimensions_validates_values_and_duplicate_names() -> None:
    constants = {"BUF": 128}
    dimensions, specs = cli_module._load_dimensions(
        {"dimensions": {"n_cells": {"default": 3, "doc": "Number of cells."}}},
        constants,
    )

    assert dimensions == {"n_cells": 3}
    assert specs[0].name == "n_cells__default"
    assert specs[0].value == "3"
    assert specs[0].doc == "Number of cells."

    with pytest.raises(click.ClickException, match="duplicates a constant"):
        cli_module._load_dimensions({"dimensions": {"BUF": {"default": 3}}}, constants)

    with pytest.raises(click.ClickException, match="default name duplicates a constant"):
        cli_module._load_dimensions(
            {"dimensions": {"n_cells": {"default": 3}}},
            {"n_cells__default": 3},
        )

    with pytest.raises(click.ClickException, match="duplicates another dimension"):
        cli_module._load_dimensions(
            {
                "dimensions": {
                    "n_cells": {"default": 3},
                    "N_CELLS": {"default": 4},
                }
            },
            {},
        )

    with pytest.raises(click.ClickException, match="must be positive"):
        cli_module._load_dimensions({"dimensions": {"n_cells": {"default": 0}}}, {})

    with pytest.raises(click.ClickException, match="must use 'default', not 'value'"):
        cli_module._load_dimensions({"dimensions": {"n_cells": {"value": 3}}}, {})

    with pytest.raises(click.ClickException, match="must not contain '__'"):
        cli_module._load_dimensions({"dimensions": {"n__cells": {"default": 3}}}, {})


def test_named_integer_type_validates_dimension_values() -> None:
    dimension_type = cli_module.NamedIntegerType(label="dimension", positive=True)

    assert dimension_type.convert("N_CELLS=3", None, None) == ("n_cells", 3)

    with pytest.raises(click.BadParameter, match="NAME=INT"):
        dimension_type.convert("n_cells", None, None)

    with pytest.raises(click.BadParameter, match="valid Fortran identifier"):
        dimension_type.convert("1bad=3", None, None)

    with pytest.raises(click.BadParameter, match="must not contain '__'"):
        dimension_type.convert("n__cells=3", None, None)

    with pytest.raises(click.BadParameter, match="integer"):
        dimension_type.convert("n_cells=3.5", None, None)

    with pytest.raises(click.BadParameter, match="positive"):
        dimension_type.convert("n_cells=0", None, None)


def test_parse_cli_dimensions_rejects_duplicates() -> None:
    assert cli_module._parse_cli_dimensions((("n_cells", 3),)) == {"n_cells": 3}

    with pytest.raises(click.ClickException, match="duplicates another dimension"):
        cli_module._parse_cli_dimensions((("n_cells", 3), ("n_cells", 4)))


def test_namelist_config_name_matches_schema_name_case_insensitively(tmp_path: Path) -> None:
    (tmp_path / "run.yml").write_text(
        dedent(
            """
            title: Run
            x-fortran-namelist: Run
            type: object
            properties:
              value:
                type: integer
            """
        ),
        encoding="utf-8",
    )
    config = {"namelists": [{"name": "run", "schema": "run.yml"}]}

    entry = cli_module._iter_namelists(config, tmp_path)[0]
    loaded = cli_module._load_namelist_registry(
        config,
        tmp_path,
        cli_module.SchemaResolver(),
    )[0]

    assert entry["name"] == "run"
    assert loaded.name == "Run"
    assert loaded.key == "run"


def test_namelist_config_name_can_be_omitted(tmp_path: Path) -> None:
    (tmp_path / "run.yml").write_text(
        dedent(
            """
            title: Run
            x-fortran-namelist: run
            type: object
            properties:
              value:
                type: integer
            """
        ),
        encoding="utf-8",
    )
    config = {"namelists": [{"schema": "run.yml"}]}

    entry = cli_module._iter_namelists(config, tmp_path)[0]
    loaded = cli_module._load_namelist_registry(
        config,
        tmp_path,
        cli_module.SchemaResolver(),
    )[0]

    assert entry["name"] is None
    assert loaded.name == "run"


def test_namelist_config_name_rejects_empty_and_non_string_values(tmp_path: Path) -> None:
    (tmp_path / "run.yml").write_text(
        dedent(
            """
            title: Run
            x-fortran-namelist: run
            type: object
            properties:
              value:
                type: integer
            """
        ),
        encoding="utf-8",
    )
    invalid_entries = [
        ({"name": 1, "schema": "run.yml"}, "must be a non-empty string"),
        ({"name": "", "schema": "run.yml"}, "must be a non-empty string"),
    ]
    for entry, message in invalid_entries:
        with pytest.raises(click.ClickException, match=message):
            cli_module._iter_namelists({"namelists": [entry]}, tmp_path)


def test_namelist_config_name_rejects_mismatch(tmp_path: Path) -> None:
    (tmp_path / "run.yml").write_text(
        dedent(
            """
            title: Run
            x-fortran-namelist: run
            type: object
            properties:
              value:
                type: integer
            """
        ),
        encoding="utf-8",
    )

    with pytest.raises(click.ClickException, match="does not match schema"):
        cli_module._load_namelist_registry(
            {"namelists": [{"name": "other", "schema": "run.yml"}]},
            tmp_path,
            cli_module.SchemaResolver(),
        )


@pytest.mark.parametrize(
    ("schema_name", "match"),
    [
        ("1run", "valid Fortran identifier"),
        ("run__config", "must not contain '__'"),
        (" run", "valid Fortran identifier"),
    ],
)
def test_namelist_config_rejects_invalid_schema_namelist_names_when_name_is_omitted(
    tmp_path: Path, schema_name: str, match: str
) -> None:
    (tmp_path / "run.yml").write_text(
        dedent(
            f"""
            title: Run
            x-fortran-namelist: {schema_name!r}
            type: object
            properties:
              value:
                type: integer
            """
        ),
        encoding="utf-8",
    )

    with pytest.raises(click.ClickException, match=match):
        cli_module._load_namelist_registry(
            {"namelists": [{"schema": "run.yml"}]},
            tmp_path,
            cli_module.SchemaResolver(),
        )


def test_file_profiles_resolve_namelist_names(tmp_path: Path) -> None:
    for name in ["run", "outputs"]:
        (tmp_path / f"{name}.yml").write_text(
            dedent(
                f"""
                title: {name}
                x-fortran-namelist: {name}
                type: object
                properties:
                  value:
                    type: integer
                """
            ),
            encoding="utf-8",
        )
    config = {
        "namelists": [
            {"schema": "run.yml"},
            {"schema": "outputs.yml"},
        ],
        "file_profiles": [
            {
                "name": "main",
                "title": "Main configuration",
                "description": "Runtime settings.",
                "default_file": "run.nml",
                "namelists": ["run", "outputs"],
                "required": ["RUN"],
            }
        ],
    }
    resolver = cli_module.SchemaResolver()
    registry = cli_module._namelist_registry_by_key(
        cli_module._load_namelist_registry(config, tmp_path, resolver)
    )

    profiles = cli_module._iter_file_profiles(config, registry)

    assert profiles["main"].default_file == "run.nml"
    assert profiles["main"].namelists == ["run", "outputs"]
    assert profiles["main"].required == ["run"]
    assert profiles["main"].title == "Main configuration"


def test_file_profiles_default_and_empty_required_are_optional(tmp_path: Path) -> None:
    (tmp_path / "run.yml").write_text(
        dedent(
            """
            title: Run
            x-fortran-namelist: run
            type: object
            properties:
              value:
                type: integer
            """
        ),
        encoding="utf-8",
    )
    config = {
        "namelists": [{"schema": "run.yml"}],
        "file_profiles": [
            {"name": "implicit", "default_file": "run.nml", "namelists": ["run"]},
            {
                "name": "explicit",
                "default_file": "run.nml",
                "namelists": ["run"],
                "required": [],
            },
        ],
    }
    resolver = cli_module.SchemaResolver()
    registry = cli_module._namelist_registry_by_key(
        cli_module._load_namelist_registry(config, tmp_path, resolver)
    )

    profiles = cli_module._iter_file_profiles(config, registry)

    assert profiles["implicit"].required == []
    assert profiles["explicit"].required == []


def test_named_namelists_work_for_profiles_and_templates(tmp_path: Path) -> None:
    (tmp_path / "run.yml").write_text(
        dedent(
            """
            title: Run
            x-fortran-namelist: run
            type: object
            properties:
              value:
                type: integer
                default: 3
            """
        ),
        encoding="utf-8",
    )
    config = {
        "namelists": [{"name": "run", "schema": "run.yml"}],
        "file_profiles": [
            {
                "name": "main",
                "default_file": "run.nml",
                "namelists": ["run"],
            }
        ],
        "templates": [{"path": "out/run.nml", "namelists": ["run"], "value_mode": "filled"}],
    }
    resolver = cli_module.SchemaResolver()
    registry = cli_module._namelist_registry_by_key(
        cli_module._load_namelist_registry(config, tmp_path, resolver)
    )
    profiles = cli_module._iter_file_profiles(config, registry)

    template = cli_module._iter_templates(config, tmp_path, registry, profiles)[0]
    rendered = cli_module.render_template(
        template["schemas"],
        value_mode=template["value_mode"],
    )

    assert profiles["main"].namelists == ["run"]
    assert "&run" in rendered
    assert "value = 3" in rendered


def test_file_profiles_reject_invalid_entries(tmp_path: Path) -> None:
    for name in ["run", "outputs"]:
        (tmp_path / f"{name}.yml").write_text(
            dedent(
                f"""
                title: {name}
                x-fortran-namelist: {name}
                type: object
                properties:
                  value:
                    type: integer
                """
            ),
            encoding="utf-8",
        )
    base_config = {"namelists": [{"schema": "run.yml"}, {"schema": "outputs.yml"}]}
    resolver = cli_module.SchemaResolver()
    registry = cli_module._namelist_registry_by_key(
        cli_module._load_namelist_registry(base_config, tmp_path, resolver)
    )

    invalid_configs = [
        (
            {
                "file_profiles": [
                    {"name": "main", "default_file": "run.nml", "namelists": ["run"]},
                    {"name": "MAIN", "default_file": "other.nml", "namelists": ["run"]},
                ]
            },
            "duplicates another profile",
        ),
        (
            {
                "file_profiles": [
                    {"name": "main", "default_file": "run.nml", "namelists": ["missing"]}
                ]
            },
            "unknown namelist",
        ),
        (
            {
                "file_profiles": [
                    {"name": "main", "default_file": "run.nml", "namelists": ["run", "RUN"]}
                ]
            },
            "duplicates another name",
        ),
        (
            {
                "file_profiles": [
                    {"name": "main", "default_file": "run.nml", "namelists": ["run"], "title": 1}
                ]
            },
            "'title' must be a string",
        ),
        (
            {"file_profiles": [{"name": "main", "namelists": ["run"]}]},
            "must define string 'default_file'",
        ),
        (
            {"file_profiles": [{"default_file": "run.nml", "namelists": ["run"]}]},
            "must define string 'name'",
        ),
        (
            {
                "file_profiles": [
                    {
                        "name": "main",
                        "default_file": "run.nml",
                        "namelists": ["run"],
                        "required": "run",
                    }
                ]
            },
            "'required' must be a list",
        ),
        (
            {
                "file_profiles": [
                    {
                        "name": "main",
                        "default_file": "run.nml",
                        "namelists": ["run"],
                        "required": [1],
                    }
                ]
            },
            "'required' entries must be strings",
        ),
        (
            {
                "file_profiles": [
                    {
                        "name": "main",
                        "default_file": "run.nml",
                        "namelists": ["run"],
                        "required": [""],
                    }
                ]
            },
            "'required' entries must be strings",
        ),
        (
            {
                "file_profiles": [
                    {
                        "name": "main",
                        "default_file": "run.nml",
                        "namelists": ["run"],
                        "required": ["run", "RUN"],
                    }
                ]
            },
            "required namelist 'RUN' duplicates another name",
        ),
        (
            {
                "file_profiles": [
                    {
                        "name": "main",
                        "default_file": "run.nml",
                        "namelists": ["run"],
                        "required": ["missing"],
                    }
                ]
            },
            "references unknown namelist",
        ),
        (
            {
                "file_profiles": [
                    {
                        "name": "main",
                        "default_file": "run.nml",
                        "namelists": ["run"],
                        "required": ["outputs"],
                    }
                ]
            },
            "is not listed in 'namelists'",
        ),
    ]
    for config, message in invalid_configs:
        with pytest.raises(click.ClickException, match=message):
            cli_module._iter_file_profiles(config, registry)


def test_parse_cli_constants_rejects_duplicates() -> None:
    constant_type = cli_module.NamedIntegerType(label="constant")
    assert constant_type.convert("BUF=128", None, None) == ("buf", 128)

    assert cli_module._parse_cli_constants((("buf", 128),)) == {"buf": 128}

    with pytest.raises(click.ClickException, match="duplicates another constant"):
        cli_module._parse_cli_constants((("buf", 128), ("buf", 256)))

    with pytest.raises(click.BadParameter, match="must be an integer"):
        constant_type.convert("ratio=1.5", None, None)


def test_load_toml_checked_reports_missing_file(tmp_path: Path) -> None:
    with pytest.raises(click.ClickException, match="missing.toml"):
        cli_module._load_toml_checked(tmp_path / "missing.toml")


def test_validate_accepts_cli_dimensions(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("schema.yml").write_text(
            dedent(
                """
                title: Demo
                x-fortran-namelist: demo
                type: object
                properties:
                  values:
                    type: array
                    items:
                      type: integer
                    x-fortran-shape: n_values
                """
            ),
            encoding="utf-8",
        )
        Path("input.nml").write_text("&demo\nvalues = 1, 2, 3\n/\n", encoding="utf-8")

        result = runner.invoke(
            cli_module.cli,
            [
                "validate",
                "--schema",
                "schema.yml",
                "--dimensions",
                "n_values=3",
                "input.nml",
            ],
        )

        assert result.exit_code == 0, result.output


def test_validate_reports_parse_errors_separately_from_read_errors(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("schema.yml").write_text(
            dedent(
                """
                x-fortran-namelist: demo
                type: object
                properties:
                  value:
                    type: integer
                """
            ),
            encoding="utf-8",
        )
        Path("input.nml").write_text("&demo\nvalue = 1\n", encoding="utf-8")

        result = runner.invoke(
            cli_module.cli,
            ["validate", "--schema", "schema.yml", "input.nml"],
        )

        assert result.exit_code == 1
        assert "failed to parse namelist:" in result.output
        assert "failed to read namelist:" not in result.output


def test_validate_accepts_whole_array_buffer_assignments(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("schema.yml").write_text(
            dedent(
                """
                title: Demo
                x-fortran-namelist: demo
                type: object
                properties:
                  start_time:
                    type: array
                    items:
                      type: string
                      x-fortran-len: 32
                    x-fortran-shape: n_items
                  layer_depth:
                    type: array
                    items:
                      type: integer
                    x-fortran-shape: [5, 1]
                """
            ),
            encoding="utf-8",
        )
        Path("input.nml").write_text(
            dedent(
                """
                &demo
                  start_time = "1992-07-05 00:00"
                  layer_depth = 200, 0, 0, 0, 0
                /
                """
            ),
            encoding="utf-8",
        )

        result = runner.invoke(
            cli_module.cli,
            [
                "validate",
                "--schema",
                "schema.yml",
                "--dimensions",
                "n_items=1",
                "input.nml",
            ],
        )

        assert result.exit_code == 0, result.output


def test_validate_resolves_external_references_with_cli_shape_values(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("definitions.yml").write_text(
            dedent(
                """
                $defs:
                  values:
                    type: array
                    x-fortran-shape: n_values
                    items:
                      type: integer
                      minimum: 1
                  label:
                    type: string
                    x-fortran-len: label_len
                """
            ),
            encoding="utf-8",
        )
        Path("schema.yml").write_text(
            dedent(
                """
                x-fortran-namelist: demo
                type: object
                properties:
                  values:
                    $ref: "definitions.yml#/$defs/values"
                  label:
                    $ref: "definitions.yml#/$defs/label"
                required: [values, label]
                """
            ),
            encoding="utf-8",
        )
        Path("input.nml").write_text(
            "&demo\nvalues = 1, 2, 3\nlabel = 'valid'\n/\n",
            encoding="utf-8",
        )

        result = runner.invoke(
            cli_module.cli,
            [
                "validate",
                "--schema",
                "schema.yml",
                "--constants",
                "label_len=8",
                "--dimensions",
                "n_values=3",
                "input.nml",
            ],
        )

        assert result.exit_code == 0, result.output


def test_validate_accepts_indexed_derived_array_components(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("schema.yml").write_text(
            dedent(
                """
                x-fortran-namelist: run
                type: object
                $defs:
                  period:
                    type: object
                    x-fortran-type: period_t
                    properties:
                      start_year:
                        type: integer
                    required: [start_year]
                required: [periods]
                properties:
                  periods:
                    type: array
                    x-fortran-shape: n_periods
                    items:
                      $ref: "#/$defs/period"
                """
            ),
            encoding="utf-8",
        )
        Path("input.nml").write_text(
            "&run\nperiods(1)%start_year = 1980\nperiods(2)%start_year = 2001\n/\n",
            encoding="utf-8",
        )

        result = runner.invoke(
            cli_module.cli,
            [
                "validate",
                "--schema",
                "schema.yml",
                "--dimensions",
                "n_periods=2",
                "input.nml",
            ],
        )

        assert result.exit_code == 0, result.output


def test_validate_accepts_derived_buffer_assignment(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("schema.yml").write_text(
            dedent(
                """
                x-fortran-namelist: run
                type: object
                properties:
                  setting:
                    type: object
                    x-fortran-type: setting_t
                    properties:
                      flag:
                        type: boolean
                      value:
                        type: integer
                    required: [flag, value]
                required: [setting]
                """
            ),
            encoding="utf-8",
        )
        Path("input.nml").write_text(
            "&run\nsetting = .true., 1\n/\n",
            encoding="utf-8",
        )

        result = runner.invoke(
            cli_module.cli,
            [
                "validate",
                "--schema",
                "schema.yml",
                "input.nml",
            ],
        )

        assert result.exit_code == 0, result.output


def test_validate_accepts_derived_array_buffer_assignment(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("schema.yml").write_text(
            dedent(
                """
                x-fortran-namelist: run
                type: object
                properties:
                  settings:
                    type: array
                    x-fortran-shape: n_settings
                    items:
                      type: object
                      x-fortran-type: setting_t
                      properties:
                        flag:
                          type: boolean
                        value:
                          type: integer
                      required: [flag, value]
                required: [settings]
                """
            ),
            encoding="utf-8",
        )
        Path("input.nml").write_text(
            "&run\nsettings = .true., 1, .false., 2\n/\n",
            encoding="utf-8",
        )

        result = runner.invoke(
            cli_module.cli,
            [
                "validate",
                "--schema",
                "schema.yml",
                "--dimensions",
                "n_settings=2",
                "input.nml",
            ],
        )

        assert result.exit_code == 0, result.output


def test_validate_accepts_single_value_derived_array_buffer(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("schema.yml").write_text(
            dedent(
                """
                x-fortran-namelist: run
                type: object
                properties:
                  settings:
                    type: array
                    x-fortran-shape: 1
                    items:
                      type: object
                      x-fortran-type: setting_t
                      properties:
                        flag:
                          type: boolean
                        value:
                          type: integer
                      required: [flag]
                required: [settings]
                """
            ),
            encoding="utf-8",
        )
        Path("input.nml").write_text(
            "&run\nsettings = .true.\n/\n",
            encoding="utf-8",
        )

        result = runner.invoke(
            cli_module.cli,
            [
                "validate",
                "--schema",
                "schema.yml",
                "input.nml",
            ],
        )

        assert result.exit_code == 0, result.output


def test_validate_rejects_null_only_required_derived_array_buffer(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("schema.yml").write_text(
            dedent(
                """
                x-fortran-namelist: run
                type: object
                properties:
                  settings:
                    type: array
                    x-fortran-shape: n_settings
                    items:
                      type: object
                      x-fortran-type: setting_t
                      properties:
                        flag:
                          type: boolean
                        value:
                          type: integer
                      required: [flag, value]
                required: [settings]
                """
            ),
            encoding="utf-8",
        )
        Path("input.nml").write_text(
            "&run\nsettings = 2*\n/\n",
            encoding="utf-8",
        )

        result = runner.invoke(
            cli_module.cli,
            [
                "validate",
                "--schema",
                "schema.yml",
                "--dimensions",
                "n_settings=1",
                "input.nml",
            ],
        )

        assert result.exit_code != 0
        assert "missing required 'settings'" in result.output


def test_validate_treats_derived_buffer_nulls_as_omitted(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("schema.yml").write_text(
            dedent(
                """
                x-fortran-namelist: run
                type: object
                properties:
                  setting:
                    type: object
                    x-fortran-type: setting_t
                    properties:
                      flag:
                        type: boolean
                      value:
                        type: integer
                    required: [value]
                required: [setting]
                """
            ),
            encoding="utf-8",
        )
        Path("input.nml").write_text(
            "&run\nsetting = , 1\n/\n",
            encoding="utf-8",
        )

        result = runner.invoke(
            cli_module.cli,
            [
                "validate",
                "--schema",
                "schema.yml",
                "input.nml",
            ],
        )

        assert result.exit_code == 0, result.output

        Path("schema.yml").write_text(
            dedent(
                """
                x-fortran-namelist: run
                type: object
                properties:
                  setting:
                    type: object
                    x-fortran-type: setting_t
                    properties:
                      flag:
                        type: boolean
                      value:
                        type: integer
                    required: [flag]
                required: [setting]
                """
            ),
            encoding="utf-8",
        )

        result = runner.invoke(
            cli_module.cli,
            [
                "validate",
                "--schema",
                "schema.yml",
                "input.nml",
            ],
        )

        assert result.exit_code != 0
        assert "missing required 'setting%flag'" in result.output


def test_validate_cli_dimensions_override_config_dimensions(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("schema.yml").write_text(
            dedent(
                """
                title: Demo
                x-fortran-namelist: demo
                type: object
                properties:
                  values:
                    type: array
                    items:
                      type: integer
                    x-fortran-shape: n_values
                """
            ),
            encoding="utf-8",
        )
        Path("input.nml").write_text("&demo\nvalues = 1, 2, 3\n/\n", encoding="utf-8")
        Path("pyproject.toml").write_text(
            dedent(
                """
                [tool.nml-tools]
                minimum-version = "0"

                [tool.nml-tools.dimensions.n_values]
                default = 2

                [[tool.nml-tools.namelists]]
                schema = "schema.yml"
                """
            ),
            encoding="utf-8",
        )

        result = runner.invoke(
            cli_module.cli,
            ["validate", "--dimensions", "n_values=3", "input.nml"],
        )

        assert result.exit_code == 0, result.output


def test_generate_command_uses_pyproject_config_in_process(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("schema.yml").write_text(
            dedent(
                """
                title: Demo
                x-fortran-namelist: demo
                type: object
                properties:
                  value:
                    type: integer
                """
            ),
            encoding="utf-8",
        )
        Path("pyproject.toml").write_text(
            dedent(
                """
                [tool.nml-tools]
                minimum-version = "0"

                [tool.nml-tools.kinds]
                module = "iso_fortran_env"
                real = ["real64"]
                integer = ["int32"]

                [[tool.nml-tools.namelists]]
                schema = "schema.yml"
                mod_path = "out/nml_demo.f90"
                """
            ),
            encoding="utf-8",
        )

        result = runner.invoke(cli_module.cli, ["generate"])

        assert result.exit_code == 0, result.output
        assert Path("out/nml_demo.f90").exists()


def test_generate_command_resolves_definitions_for_all_outputs(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("definitions.yml").write_text(
            dedent(
                """
                $defs:
                  value:
                    type: integer
                    x-fortran-kind: i4
                    minimum: 0
                """
            ),
            encoding="utf-8",
        )
        Path("schema.yml").write_text(
            dedent(
                """
                title: Demo
                x-fortran-namelist: demo
                type: object
                properties:
                  value:
                    $ref: "definitions.yml#/$defs/value"
                    title: Demo value
                    default: 2
                """
            ),
            encoding="utf-8",
        )
        Path("nml-config.toml").write_text(
            dedent(
                """
                [kinds]
                module = "iso_fortran_env"
                real = ["real64"]
                integer = ["int32"]
                map = { i4 = "int32" }

                [[namelists]]
                schema = "schema.yml"
                mod_path = "out/nml_demo.f90"
                doc_path = "out/nml_demo.md"

                [[templates]]
                path = "out/demo.nml"
                namelists = ["demo"]
                value_mode = "filled"
                doc_mode = "documented"
                """
            ),
            encoding="utf-8",
        )

        result = runner.invoke(cli_module.cli, ["generate", "--config", "nml-config.toml"])

        assert result.exit_code == 0, result.output
        assert "integer(i4)" in Path("out/nml_demo.f90").read_text(encoding="ascii")
        assert "Default: `2`" in Path("out/nml_demo.md").read_text(encoding="ascii")
        assert "value = 2" in Path("out/demo.nml").read_text(encoding="ascii")


def test_template_profile_metadata_and_order(tmp_path: Path) -> None:
    for name in ["run", "outputs"]:
        (tmp_path / f"{name}.yml").write_text(
            dedent(
                f"""
                title: {name.title()}
                x-fortran-namelist: {name}
                type: object
                properties:
                  value:
                    type: integer
                    default: 1
                """
            ),
            encoding="utf-8",
        )
    config = {
        "namelists": [
            {"schema": "run.yml"},
            {"schema": "outputs.yml"},
        ],
        "file_profiles": [
            {
                "name": "main",
                "title": "Main profile",
                "description": "Profile description.",
                "default_file": "run.nml",
                "namelists": ["outputs", "run"],
            }
        ],
        "templates": [
            {
                "profile": "main",
                "path": "out/main.nml",
                "description": "Template description.",
                "doc_mode": "documented",
                "value_mode": "filled",
            }
        ],
    }
    resolver = cli_module.SchemaResolver()
    registry = cli_module._namelist_registry_by_key(
        cli_module._load_namelist_registry(config, tmp_path, resolver)
    )
    profiles = cli_module._iter_file_profiles(config, registry)

    template = cli_module._iter_templates(config, tmp_path, registry, profiles)[0]
    rendered = cli_module.render_template(
        template["schemas"],
        doc_mode=template["doc_mode"],
        value_mode=template["value_mode"],
        title=template["title"],
        description=template["description"],
    )

    assert template["path"] == tmp_path / "out/main.nml"
    assert rendered.startswith("! Main profile\n!\n! Template description.")
    assert rendered.index("&outputs") < rendered.index("&run")


def test_templates_accept_legacy_schemas_for_namelist_inclusion(tmp_path: Path) -> None:
    for name in ["run", "outputs"]:
        (tmp_path / f"{name}.yml").write_text(
            dedent(
                f"""
                title: {name.title()}
                x-fortran-namelist: {name}
                type: object
                properties:
                  value:
                    type: integer
                """
            ),
            encoding="utf-8",
        )
    config = {
        "namelists": [
            {"schema": "run.yml"},
            {"schema": "outputs.yml"},
        ],
        "templates": [
            {
                "path": "out/legacy.nml",
                "schemas": ["outputs.yml", "run.yml"],
            }
        ],
    }
    resolver = cli_module.SchemaResolver()
    registry = cli_module._namelist_registry_by_key(
        cli_module._load_namelist_registry(config, tmp_path, resolver)
    )

    template = cli_module._iter_templates(config, tmp_path, registry, {})[0]
    rendered = cli_module.render_template(template["schemas"])

    assert template["path"] == tmp_path / "out/legacy.nml"
    assert rendered.index("&outputs") < rendered.index("&run")


def test_templates_reject_deprecated_keys(tmp_path: Path) -> None:
    (tmp_path / "run.yml").write_text(
        dedent(
            """
            title: Run
            x-fortran-namelist: run
            type: object
            properties:
              value:
                type: integer
            """
        ),
        encoding="utf-8",
    )
    config = {"namelists": [{"schema": "run.yml"}]}
    resolver = cli_module.SchemaResolver()
    registry = cli_module._namelist_registry_by_key(
        cli_module._load_namelist_registry(config, tmp_path, resolver)
    )

    with pytest.raises(click.ClickException, match="not deprecated 'output'"):
        cli_module._iter_templates(
            {"templates": [{"output": "out/run.nml", "namelists": ["run"]}]},
            tmp_path,
            registry,
            {},
        )


def test_templates_reject_invalid_legacy_schemas(tmp_path: Path) -> None:
    (tmp_path / "run.yml").write_text(
        dedent(
            """
            title: Run
            x-fortran-namelist: run
            type: object
            properties:
              value:
                type: integer
            """
        ),
        encoding="utf-8",
    )
    config = {"namelists": [{"schema": "run.yml"}]}
    resolver = cli_module.SchemaResolver()
    registry = cli_module._namelist_registry_by_key(
        cli_module._load_namelist_registry(config, tmp_path, resolver)
    )

    with pytest.raises(click.ClickException, match="must not define 'profile' or 'namelists'"):
        cli_module._iter_templates(
            {"templates": [{"path": "out/run.nml", "schemas": ["run.yml"], "namelists": ["run"]}]},
            tmp_path,
            registry,
            {},
        )
    with pytest.raises(click.ClickException, match="does not match a configured namelist schema"):
        cli_module._iter_templates(
            {"templates": [{"path": "out/run.nml", "schemas": ["missing.yml"]}]},
            tmp_path,
            registry,
            {},
        )
    with pytest.raises(click.ClickException, match="duplicates another schema"):
        cli_module._iter_templates(
            {"templates": [{"path": "out/run.nml", "schemas": ["run.yml", "run.yml"]}]},
            tmp_path,
            registry,
            {},
        )


def test_generation_subcommands_use_discovered_pyproject_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "schema.yml").write_text(
        dedent(
            """
            title: Demo
            x-fortran-namelist: demo
            type: object
            properties:
              value:
                title: Demo value
                type: integer
                default: 1
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        dedent(
            """
            [tool.nml-tools]
            minimum-version = "0"

            [tool.nml-tools.kinds]
            module = "iso_fortran_env"
            real = ["real64"]
            integer = ["int32"]

            [[tool.nml-tools.namelists]]
            schema = "schema.yml"
            mod_path = "out/nml_demo.f90"
            doc_path = "out/nml_demo.md"

            [[tool.nml-tools.templates]]
            path = "out/demo.nml"
            namelists = ["demo"]
            value_mode = "filled"
            doc_mode = "plain"
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    cli_module.gen_fortran.callback(None)
    cli_module.gen_markdown.callback(None)
    cli_module.gen_template.callback(None)

    assert (tmp_path / "out/nml_demo.f90").exists()
    assert (tmp_path / "out/nml_demo.md").exists()
    assert (tmp_path / "out/demo.nml").read_text(encoding="utf-8").startswith("&demo")


def test_validate_uses_discovered_pyproject_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "schema.yml").write_text(
        dedent(
            """
            title: Demo
            x-fortran-namelist: demo
            type: object
            properties:
              value:
                type: integer
                minimum: 0
            required: [value]
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "input.nml").write_text("&demo\nvalue = 2\n/\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        dedent(
            """
            [tool.nml-tools]
            minimum-version = "0"

            [tool.nml-tools.kinds]
            module = "iso_fortran_env"

            [[tool.nml-tools.namelists]]
            schema = "schema.yml"
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    cli_module.validate.callback(None, (), None, None, (), (), Path("input.nml"))


def test_validate_profile_filters_config_schemas(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        for name in ["run", "outputs"]:
            Path(f"{name}.yml").write_text(
                dedent(
                    f"""
                    title: {name}
                    x-fortran-namelist: {name}
                    type: object
                    required: [value]
                    properties:
                      value:
                        type: integer
                    """
                ),
                encoding="utf-8",
            )
        Path("nml-config.toml").write_text(
            dedent(
                """
                [[namelists]]
                schema = "run.yml"

                [[namelists]]
                schema = "outputs.yml"

                [[file_profiles]]
                name = "main"
                default_file = "run.nml"
                namelists = ["run"]
                """
            ),
            encoding="utf-8",
        )
        Path("run.nml").write_text("&run\nvalue = 1\n/\n", encoding="utf-8")
        Path("mixed.nml").write_text(
            "&run\nvalue = 1\n/\n&outputs\nvalue = 2\n/\n",
            encoding="utf-8",
        )

        ok = runner.invoke(cli_module.cli, ["validate", "--profile", "main", "run.nml"])
        unknown = runner.invoke(cli_module.cli, ["validate", "--profile", "main", "mixed.nml"])
        explicit_schema = runner.invoke(
            cli_module.cli,
            ["validate", "--schema", "run.yml", "--profile", "main", "run.nml"],
        )

        assert ok.exit_code == 0, ok.output
        assert unknown.exit_code != 0
        assert "unknown namelist 'outputs'" in unknown.output
        assert explicit_schema.exit_code != 0
        assert "--profile can only be used with config-based validation" in explicit_schema.output


def test_validate_profile_requires_only_required_namelists(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        for name in ["run", "outputs"]:
            Path(f"{name}.yml").write_text(
                dedent(
                    f"""
                    title: {name}
                    x-fortran-namelist: {name}
                    type: object
                    required: [value]
                    properties:
                      value:
                        type: integer
                    """
                ),
                encoding="utf-8",
            )
        Path("nml-config.toml").write_text(
            dedent(
                """
                [[namelists]]
                schema = "run.yml"

                [[namelists]]
                schema = "outputs.yml"

                [[file_profiles]]
                name = "main"
                default_file = "run.nml"
                namelists = ["run", "outputs"]
                required = ["run"]
                """
            ),
            encoding="utf-8",
        )
        Path("run.nml").write_text("&run\nvalue = 1\n/\n", encoding="utf-8")
        Path("outputs.nml").write_text("&outputs\nvalue = 2\n/\n", encoding="utf-8")
        Path("full.nml").write_text(
            "&run\nvalue = 1\n/\n&outputs\nvalue = 2\n/\n",
            encoding="utf-8",
        )

        optional_missing = runner.invoke(
            cli_module.cli,
            ["validate", "--profile", "main", "run.nml"],
        )
        required_missing = runner.invoke(
            cli_module.cli,
            ["validate", "--profile", "main", "outputs.nml"],
        )
        all_present = runner.invoke(
            cli_module.cli,
            ["validate", "--profile", "main", "full.nml"],
        )
        explicit_schema_missing = runner.invoke(
            cli_module.cli,
            ["validate", "--schema", "run.yml", "--schema", "outputs.yml", "run.nml"],
        )

        assert optional_missing.exit_code == 0, optional_missing.output
        assert required_missing.exit_code != 0
        assert "input is missing namelist 'run'" in required_missing.output
        assert all_present.exit_code == 0, all_present.output
        assert explicit_schema_missing.exit_code != 0
        assert "input is missing namelist 'outputs'" in explicit_schema_missing.output


def test_check_command_passes_and_reports_differences(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("schema.yml").write_text(
            dedent(
                """
                title: Demo
                x-fortran-namelist: demo
                type: object
                properties:
                  value:
                    title: Demo value
                    type: integer
                    default: 1
                """
            ),
            encoding="utf-8",
        )
        Path("pyproject.toml").write_text(
            dedent(
                """
                [tool.nml-tools]
                minimum-version = "0"

                [tool.nml-tools.kinds]
                module = "iso_fortran_env"
                real = ["real64"]
                integer = ["int32"]

                [[tool.nml-tools.namelists]]
                schema = "schema.yml"
                mod_path = "out/nml_demo.f90"
                doc_path = "out/nml_demo.md"

                [[tool.nml-tools.templates]]
                path = "out/demo.nml"
                namelists = ["demo"]
                value_mode = "filled"
                doc_mode = "plain"
                """
            ),
            encoding="utf-8",
        )

        generate_result = runner.invoke(cli_module.cli, ["generate"])
        assert generate_result.exit_code == 0, generate_result.output

        check_result = runner.invoke(cli_module.cli, ["check"])
        assert check_result.exit_code == 0, check_result.output

        Path("out/demo.nml").write_text("&demo\nvalue = 2\n/\n", encoding="ascii")
        diff_result = runner.invoke(cli_module.cli, ["check", "--diff"])

        assert diff_result.exit_code != 0
        assert "DIFF: out/demo.nml" in diff_result.output
        assert "--- current out/demo.nml" in diff_result.output
        assert "+++ generated out/demo.nml" in diff_result.output
        assert "generated files are out of date: 1 file(s) differ or are missing" in (
            diff_result.output
        )


def test_check_command_reports_missing_files(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("schema.yml").write_text(
            dedent(
                """
                title: Demo
                x-fortran-namelist: demo
                type: object
                properties:
                  value:
                    type: integer
                """
            ),
            encoding="utf-8",
        )
        Path("nml-config.toml").write_text(
            dedent(
                """
                [kinds]
                module = "iso_fortran_env"
                real = ["real64"]
                integer = ["int32"]

                [[namelists]]
                schema = "schema.yml"
                mod_path = "out/nml_demo.f90"
                """
            ),
            encoding="utf-8",
        )

        result = runner.invoke(cli_module.cli, ["check"])

        assert result.exit_code != 0
        assert "MISSING: out/nml_demo.f90" in result.output


def test_collect_generated_outputs_groups_shared_f2py_files(tmp_path: Path) -> None:
    for name in ["first", "second"]:
        (tmp_path / f"{name}.yml").write_text(
            dedent(
                f"""
                title: {name.title()}
                x-fortran-namelist: {name}
                type: object
                required: [value]
                properties:
                  value:
                    type: number
                    x-fortran-kind: dp
                """
            ),
            encoding="utf-8",
        )
    config_path = tmp_path / "nml-config.toml"
    config_path.write_text(
        dedent(
            """
            [helper]
            path = "out/nml_helper.f90"
            module = "nml_helper"

            [kinds]
            module = "iso_fortran_env"
            real = ["real64"]
            integer = ["int32"]
            map = { dp = "real64" }

            [f2py]
            f2cmap_path = "out/.f2py_f2cmap"

            [f2py.c_types.real]
            dp = "double"

            [[namelists]]
            schema = "first.yml"
            mod_path = "out/nml_first.f90"
            f2py_path = "out/f2py_config.f90"
            py_path = "out/config.py"

            [[namelists]]
            schema = "second.yml"
            mod_path = "out/nml_second.f90"
            f2py_path = "out/f2py_config.f90"
            py_path = "out/config.py"
            """
        ),
        encoding="utf-8",
    )
    config, resolved_path = cli_module._load_config_checked(config_path)

    outputs = cli_module._collect_generated_outputs(config, resolved_path)
    output_paths = [output.path.relative_to(tmp_path) for output in outputs]
    by_path = {output.path.relative_to(tmp_path): output.content for output in outputs}

    assert output_paths.count(Path("out/f2py_config.f90")) == 1
    assert output_paths.count(Path("out/config.py")) == 1
    assert "module f2py_first" in by_path[Path("out/f2py_config.f90")]
    assert "module f2py_second" in by_path[Path("out/f2py_config.f90")]
    assert "class First" in by_path[Path("out/config.py")]
    assert "class Second" in by_path[Path("out/config.py")]
