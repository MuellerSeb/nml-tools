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


def test_load_toml_checked_reports_missing_file(tmp_path: Path) -> None:
    with pytest.raises(click.ClickException, match="missing.toml"):
        cli_module._load_toml_checked(tmp_path / "missing.toml")


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

    cli_module.validate.callback(None, (), None, (), Path("input.nml"))
