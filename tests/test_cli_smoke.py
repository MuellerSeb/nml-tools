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
