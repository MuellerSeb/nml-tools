"""Smoke tests for the command line interface."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent


def test_cli_help_shows_subcommands() -> None:
    root = Path(__file__).resolve().parents[1] / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{root}{os.pathsep}{env.get('PYTHONPATH', '')}"
    result = subprocess.run(
        [sys.executable, "-m", "nml_tools.cli", "--help"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    stdout = result.stdout
    for sub in ["generate", "gen-fortran", "gen-markdown", "gen-template", "validate"]:
        assert sub in stdout


def test_cli_generate_emits_f2py_outputs(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1] / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{root}{os.pathsep}{env.get('PYTHONPATH', '')}"
    (tmp_path / "schema.yml").write_text(
        dedent(
            """
            title: Demo
            x-fortran-namelist: demo
            type: object
            required: [value]
            properties:
              value:
                type: number
                x-fortran-kind: dp
              count:
                type: integer
                x-fortran-kind: i4
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "nml-config.toml").write_text(
        dedent(
            """
            [helper]
            path = "out/nml_helper.f90"
            module = "nml_helper"

            [kinds]
            module = "iso_fortran_env"
            real = ["real64"]
            integer = ["int32"]
            map = { dp = "real64", i4 = "int32" }

            [f2py]
            f2cmap_path = "out/.f2py_f2cmap"

            [f2py.c_types.real]
            dp = "double"

            [f2py.c_types.integer]
            i4 = "int"

            [[namelists]]
            schema = "schema.yml"
            mod_path = "out/nml_demo.f90"
            f2py_path = "out/f2py_config_wrappers.f90"
            py_path = "out/config_wrappers.py"
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nml_tools.cli",
            "generate",
            "--config",
            str(tmp_path / "nml-config.toml"),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    assert (tmp_path / "out" / "nml_demo.f90").exists()
    f2py = (tmp_path / "out" / "f2py_config_wrappers.f90").read_text()
    py = (tmp_path / "out" / "config_wrappers.py").read_text()
    f2cmap = (tmp_path / "out" / ".f2py_f2cmap").read_text()
    assert "module f2py_demo" in f2py
    assert "dp=>real64" in f2py
    assert "from . import f2py_config_wrappers" in py
    assert "class Demo" in py
    assert "Parameters\n    ----------" in py
    assert f2cmap == (
        "dict(real=dict(dp='double'), integer=dict(c_intptr_t='long_long', i4='int'))\n"
    )


def test_cli_rejects_invalid_python_doc_style(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1] / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{root}{os.pathsep}{env.get('PYTHONPATH', '')}"
    (tmp_path / "nml-config.toml").write_text(
        dedent(
            """
            [documentation]
            py-style = "google"
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nml_tools.cli",
            "generate",
            "--config",
            str(tmp_path / "nml-config.toml"),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode != 0
    assert "documentation.py-style" in result.stderr


def test_cli_rejects_f2py_path_without_mod_path(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1] / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{root}{os.pathsep}{env.get('PYTHONPATH', '')}"
    (tmp_path / "schema.yml").write_text(
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
    (tmp_path / "nml-config.toml").write_text(
        dedent(
            """
            [kinds]
            module = "iso_fortran_env"
            real = ["real64"]
            integer = ["int32"]

            [[namelists]]
            schema = "schema.yml"
            f2py_path = "out/f2py_config.f90"
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nml_tools.cli",
            "generate",
            "--config",
            str(tmp_path / "nml-config.toml"),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode != 0
    assert "f2py_path" in result.stderr
    assert "mod_path" in result.stderr


def test_cli_generate_discovers_pyproject_tool_config(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1] / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{root}{os.pathsep}{env.get('PYTHONPATH', '')}"
    (tmp_path / "schema.yml").write_text(
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
    (tmp_path / "pyproject.toml").write_text(
        dedent(
            """
            [project]
            name = "demo"
            version = "0.1.0"

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

    result = subprocess.run(
        [sys.executable, "-m", "nml_tools.cli", "generate"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )

    assert result.returncode == 0
    assert (tmp_path / "out" / "nml_demo.f90").exists()


def test_cli_default_prefers_nml_config_over_pyproject(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1] / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{root}{os.pathsep}{env.get('PYTHONPATH', '')}"
    (tmp_path / "schema.yml").write_text(
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
    (tmp_path / "nml-config.toml").write_text(
        dedent(
            """
            [kinds]
            module = "iso_fortran_env"
            real = ["real64"]
            integer = ["int32"]

            [[namelists]]
            schema = "schema.yml"
            mod_path = "out/from_nml_config.f90"
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        dedent(
            """
            [tool.nml-tools]
            minimum-version = "9999"
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-m", "nml_tools.cli", "generate"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )

    assert result.returncode == 0
    assert (tmp_path / "out" / "from_nml_config.f90").exists()


def test_cli_rejects_pyproject_without_tool_section(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1] / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{root}{os.pathsep}{env.get('PYTHONPATH', '')}"
    (tmp_path / "pyproject.toml").write_text(
        dedent(
            """
            [project]
            name = "demo"
            version = "0.1.0"
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nml_tools.cli",
            "generate",
            "--config",
            str(tmp_path / "pyproject.toml"),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode != 0
    assert "tool.nml-tools" in result.stderr


def test_cli_minimum_version_validation(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1] / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{root}{os.pathsep}{env.get('PYTHONPATH', '')}"
    (tmp_path / "schema.yml").write_text(
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
    (tmp_path / "input.nml").write_text("&demo\nvalue = 1\n/\n", encoding="utf-8")
    (tmp_path / "ok.toml").write_text('minimum-version = "0"\n', encoding="utf-8")
    (tmp_path / "too-new.toml").write_text(
        'minimum-version = "9999"\n',
        encoding="utf-8",
    )
    (tmp_path / "bad.toml").write_text(
        'minimum-version = "not a version"\n',
        encoding="utf-8",
    )

    ok = subprocess.run(
        [
            sys.executable,
            "-m",
            "nml_tools.cli",
            "validate",
            "--config",
            str(tmp_path / "ok.toml"),
            "--schema",
            str(tmp_path / "schema.yml"),
            str(tmp_path / "input.nml"),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert ok.returncode == 0

    too_new = subprocess.run(
        [
            sys.executable,
            "-m",
            "nml_tools.cli",
            "validate",
            "--config",
            str(tmp_path / "too-new.toml"),
            "--schema",
            str(tmp_path / "schema.yml"),
            str(tmp_path / "input.nml"),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert too_new.returncode != 0
    assert "requires nml-tools" in too_new.stderr

    bad = subprocess.run(
        [
            sys.executable,
            "-m",
            "nml_tools.cli",
            "validate",
            "--config",
            str(tmp_path / "bad.toml"),
            "--schema",
            str(tmp_path / "schema.yml"),
            str(tmp_path / "input.nml"),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert bad.returncode != 0
    assert "minimum-version" in bad.stderr
    assert "valid version" in bad.stderr
