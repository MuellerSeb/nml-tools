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
            minimum-version = "0"

            [tool.nml-tools.kinds]
            module = "iso_fortran_env"
            """
        ),
        encoding="utf-8",
    )

    config, path = cli_module._load_config_checked(pyproject)

    assert path == pyproject
    assert config == {
        "minimum-version": "0",
        "kinds": {"module": "iso_fortran_env"},
    }


def test_load_config_checked_reads_standalone_root_table(tmp_path: Path) -> None:
    config_path = tmp_path / "custom.toml"
    config_path.write_text(
        dedent(
            """
            minimum-version = "0"

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


def test_check_minimum_version_rejects_invalid_values() -> None:
    cli_module._check_minimum_version({})
    cli_module._check_minimum_version({"minimum-version": "0"})

    with pytest.raises(click.ClickException, match="non-empty string"):
        cli_module._check_minimum_version({"minimum-version": ""})

    with pytest.raises(click.ClickException, match="valid version"):
        cli_module._check_minimum_version({"minimum-version": "not a version"})

    with pytest.raises(click.ClickException, match="requires nml-tools"):
        cli_module._check_minimum_version({"minimum-version": "9999"})


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


def test_load_dimensions_validates_values_and_duplicate_names() -> None:
    constants = {"BUF": 128}
    dimensions, specs = cli_module._load_dimensions(
        {"dimensions": {"n_cells": {"value": 3, "doc": "Number of cells."}}},
        constants,
    )

    assert dimensions == {"n_cells": 3}
    assert specs[0].name == "n_cells"
    assert specs[0].value == "3"
    assert specs[0].doc == "Number of cells."

    with pytest.raises(click.ClickException, match="duplicates a constant"):
        cli_module._load_dimensions({"dimensions": {"BUF": {"value": 3}}}, constants)

    with pytest.raises(click.ClickException, match="duplicates another dimension"):
        cli_module._load_dimensions(
            {
                "dimensions": {
                    "n_cells": {"value": 3},
                    "N_CELLS": {"value": 4},
                }
            },
            {},
        )

    with pytest.raises(click.ClickException, match="must be positive"):
        cli_module._load_dimensions({"dimensions": {"n_cells": {"value": 0}}}, {})


def test_parse_cli_dimensions_validates_values() -> None:
    assert cli_module._parse_cli_dimensions(("N_CELLS=3",)) == {"n_cells": 3}

    with pytest.raises(click.ClickException, match="NAME=VALUE"):
        cli_module._parse_cli_dimensions(("n_cells",))

    with pytest.raises(click.ClickException, match="valid identifier"):
        cli_module._parse_cli_dimensions(("1bad=3",))

    with pytest.raises(click.ClickException, match="integer"):
        cli_module._parse_cli_dimensions(("n_cells=3.5",))

    with pytest.raises(click.ClickException, match="positive"):
        cli_module._parse_cli_dimensions(("n_cells=0",))

    with pytest.raises(click.ClickException, match="duplicates another dimension"):
        cli_module._parse_cli_dimensions(("n_cells=3", "N_CELLS=4"))


def test_parse_cli_constants_normalizes_and_rejects_duplicates() -> None:
    assert cli_module._parse_cli_constants(("BUF=128",)) == {"buf": 128}

    with pytest.raises(click.ClickException, match="duplicates another constant"):
        cli_module._parse_cli_constants(("buf=128", "BUF=256"))


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
                value = 2

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
            schemas = ["schema.yml"]
            output = "out/demo.nml"
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

    cli_module.validate.callback(None, (), None, (), (), Path("input.nml"))


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
                schemas = ["schema.yml"]
                output = "out/demo.nml"
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
