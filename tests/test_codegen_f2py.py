"""Tests for f2py wrapper generation."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest


def _import_codegen_f2py() -> Any:
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    sys.path.insert(0, str(src))
    try:
        return importlib.import_module("nml_tools.codegen_f2py")
    finally:
        sys.path.pop(0)


def _schema(name: str = "optimization") -> dict[str, Any]:
    return {
        "title": "Optimization",
        "x-fortran-namelist": name,
        "type": "object",
        "required": ["method", "values"],
        "properties": {
            "method": {"type": "string", "x-fortran-len": 16},
            "values": {
                "type": "array",
                "x-fortran-shape": [3, 2],
                "items": {"type": "number", "x-fortran-kind": "dp"},
            },
            "seed": {"type": "integer", "x-fortran-kind": "i4"},
            "weights": {
                "type": "array",
                "x-fortran-shape": [3],
                "items": {"type": "integer", "x-fortran-kind": "i4", "default": 1},
            },
        },
    }


def _runtime_dimension_schema(name: str = "config") -> dict[str, Any]:
    return {
        "title": "Runtime dimensions",
        "x-fortran-namelist": name,
        "type": "object",
        "required": ["iterations", "tolerance", "weights"],
        "properties": {
            "iterations": {"type": "integer", "x-fortran-kind": "i4"},
            "tolerance": {"type": "number", "x-fortran-kind": "dp"},
            "weights": {
                "type": "array",
                "x-fortran-shape": "n_weights",
                "items": {"type": "number", "x-fortran-kind": "dp"},
            },
        },
    }


def test_generate_f2py_wrappers_respects_kind_map(tmp_path: Path) -> None:
    codegen = _import_codegen_f2py()
    output = tmp_path / "f2py_config_wrappers.f90"

    codegen.generate_f2py_wrappers(
        [_schema(), _schema("runtime")],
        output,
        kind_module="iso_fortran_env",
        kind_map={"dp": "real64", "i4": "int32"},
        kind_allowlist={"real64", "int32"},
    )

    generated = output.read_text()
    assert "module f2py_optimization" in generated
    assert "module f2py_runtime" in generated
    assert "!> \\file f2py_config_wrappers.f90" in generated
    assert "!> \\copydoc f2py_optimization" in generated
    assert "!> \\brief Optimization" in generated
    assert "!> \\brief Set optimization values on the handled instance" in generated
    assert (
        "integer(c_intptr_t), intent(in) :: handle "
        "!< opaque handle to a nml_optimization_t instance"
    ) in generated
    assert "integer, intent(in) :: values_n1 !< extent for values" in generated
    assert (
        "real(dp), dimension(values_n1, values_n2), intent(in) :: values "
        "!< values (required)"
    ) in generated
    assert (
        "character(len=1024), intent(out) :: errmsg "
        "!< error message for non-OK status values"
    ) in generated
    assert "use iso_fortran_env, only:" in generated
    assert "dp=>real64" in generated
    assert "i4=>int32" in generated
    assert "integer, intent(in) :: values_n1 !< extent for values" in generated
    assert "integer, intent(in) :: values_n2 !< extent for values" in generated
    assert "real(dp), dimension(values_n1, values_n2), intent(in) :: values" in generated
    assert "integer(i4), intent(in) :: seed !< seed (optional)" in generated
    assert "logical, intent(in) :: has_seed !< whether seed was provided" in generated
    assert "integer, intent(in) :: weights_n1 !< extent for weights" in generated
    assert "integer(i4), dimension(weights_n1), intent(in) :: weights" in generated
    assert "logical, intent(in) :: has_weights !< whether weights was provided" in generated
    assert "integer(i4), allocatable :: maybe_seed" in generated
    assert "integer(i4), dimension(:), allocatable :: maybe_weights" in generated
    assert "if (has_seed) then" in generated
    assert "if (has_weights) then" in generated
    assert "status = this%set(" in generated
    assert "seed=maybe_seed" in generated
    assert "weights=maybe_weights" in generated
    assert "optional ::" not in generated
    assert "dimension(:), intent(in)" not in generated
    assert "function optimization_handle" not in generated
    assert "nml_optimization_resolve_handle" in generated
    assert "call nml_optimization_resolve_handle(handle, this, status, errmsg)" in generated
    assert "c_associated" not in generated
    assert "c_f_pointer" not in generated
    assert "status = NML_OK" not in generated
    assert "type(nml_optimization_t), pointer :: this" in generated
    assert "subroutine optimization_set_wrapper" in generated
    assert "subroutine optimization_from_file_wrapper" in generated
    assert "subroutine optimization_is_set_wrapper" in generated
    assert "subroutine optimization_is_valid_wrapper" in generated


def test_generate_f2py_wrappers_uses_deferred_length_for_string_array_bridges(
    tmp_path: Path,
) -> None:
    codegen = _import_codegen_f2py()
    output = tmp_path / "f2py_config_wrappers.f90"
    schema = {
        "title": "String arrays",
        "x-fortran-namelist": "strings",
        "type": "object",
        "properties": {
            "names": {
                "title": "Names",
                "type": "array",
                "x-fortran-shape": [2, 3],
                "items": {"type": "string", "x-fortran-len": 16},
            },
        },
    }

    codegen.generate_f2py_wrappers([schema], output)

    generated = output.read_text()
    assert (
        "character(len=*), dimension(names_n1, names_n2), intent(in) :: names"
        in generated
    )
    assert (
        "character(len=:), dimension(:, :), allocatable :: maybe_names"
        in generated
    )
    assert (
        "allocate(character(len=len(names)) :: maybe_names(names_n1, names_n2))"
        in generated
    )
    assert "character(len=*), dimension(:, :), allocatable :: maybe_names" not in generated


def test_generate_f2py_wrappers_exposes_set_dims_wrapper(tmp_path: Path) -> None:
    codegen = _import_codegen_f2py()
    output = tmp_path / "f2py_config_wrappers.f90"

    codegen.generate_f2py_wrappers(
        [_runtime_dimension_schema()],
        output,
        kind_module="iso_fortran_env",
        kind_map={"dp": "real64", "i4": "int32"},
        kind_allowlist={"real64", "int32"},
        dimensions={"n_weights": 3},
    )

    generated = output.read_text()
    assert "subroutine config_set_dims_wrapper" in generated
    assert (
        "integer, intent(in) :: n_weights !< runtime dimension override for n_weights"
        in generated
    )
    assert (
        "logical, intent(in) :: has_n_weights "
        "!< whether n_weights was provided"
        in generated
    )
    assert "integer, allocatable :: maybe_n_weights" in generated
    assert "if (has_n_weights) then" in generated
    assert "status = this%set_dims(" in generated
    assert "n_weights=maybe_n_weights" in generated


def test_collect_f2py_kind_usage_rejects_dimension_as_string_length() -> None:
    codegen = _import_codegen_f2py()
    schema = {
        "title": "Invalid runtime string length",
        "x-fortran-namelist": "config",
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "x-fortran-len": "n_weights",
            }
        },
    }

    with pytest.raises(ValueError, match="cannot be used as x-fortran-len"):
        codegen.collect_f2py_kind_usage([schema], dimensions={"n_weights": 3})


def test_generate_f2cmap_requires_explicit_kind_mappings(tmp_path: Path) -> None:
    codegen = _import_codegen_f2py()
    usage = codegen.collect_f2py_kind_usage([_schema()])
    output = tmp_path / ".f2py_f2cmap"

    codegen.generate_f2cmap(
        output,
        usage,
        codegen.F2pyCTypeMap(real={"dp": "double"}, integer={"i4": "int"}),
    )

    assert output.read_text() == (
        "dict(real=dict(dp='double'), integer=dict(c_intptr_t='long_long', i4='int'))\n"
    )

    with pytest.raises(ValueError, match="missing f2py real C type mappings: dp"):
        codegen.generate_f2cmap(
            tmp_path / "missing",
            usage,
            codegen.F2pyCTypeMap(real={}, integer={"i4": "int"}),
        )


def test_generate_python_wrapper_normalizes_arrays_and_handles_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codegen = _import_codegen_f2py()
    spec = codegen.build_f2py_namelist_spec(_schema())
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    output = package_dir / "config_wrappers.py"
    calls: list[tuple[str, dict[str, Any]]] = []

    class FakeF2pyOptimization:
        @staticmethod
        def optimization_set_wrapper(handle: int, **kwargs: Any) -> tuple[int, str]:
            calls.append(("set", kwargs))
            return 0, ""

        @staticmethod
        def optimization_is_set_wrapper(
            handle: int,
            name: str,
            **kwargs: Any,
        ) -> tuple[int, str]:
            calls.append(("is_set", {"name": name, **kwargs}))
            return 12, "field not set"

        @staticmethod
        def optimization_is_valid_wrapper(handle: int) -> tuple[int, str]:
            calls.append(("is_valid", {}))
            return 11, "enum constraint failed"

        @staticmethod
        def optimization_from_file_wrapper(handle: int, file: str) -> tuple[int, str]:
            calls.append(("from_file", {"file": file}))
            return 0, ""

    class FakeExtension:
        f2py_optimization = FakeF2pyOptimization

    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setitem(sys.modules, "pkg.f2py_config_wrappers", FakeExtension)

    codegen.generate_python_wrappers([(spec, "f2py_config_wrappers")], output)

    module_spec = importlib.util.spec_from_file_location("pkg.config_wrappers", output)
    assert module_spec is not None
    assert module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)

    cfg = module.Optimization(123)
    cfg.set(method="DDS", values=0.1, seed=None)

    name, kwargs = calls[-1]
    assert name == "set"
    assert set(kwargs) == {
        "method",
        "values",
        "seed",
        "has_seed",
        "weights",
        "has_weights",
    }
    assert kwargs["values"].shape == (1, 1)
    assert (kwargs["values"] == 0.1).all()
    assert kwargs["values"].flags.f_contiguous
    assert kwargs["seed"] == 0
    assert kwargs["has_seed"] is False
    assert kwargs["weights"].shape == (1,)
    assert kwargs["weights"].flags.f_contiguous
    assert kwargs["has_weights"] is False
    assert cfg.is_set("seed") is False
    assert calls[-1][1]["idx"].shape == (1,)
    assert calls[-1][1]["has_idx"] is False
    cfg.from_file("optimization.nml")
    cfg.invalidate()
    assert cfg.handle == 0
    cfg.from_file("optimization.nml")
    assert calls[-1][1]["file"] == "optimization.nml"
    with pytest.raises(module.NmlError) as exc:
        cfg.is_valid()
    assert exc.value.status == 11

    with pytest.raises(ValueError, match="required argument 'method'"):
        cfg.set(method=None, values=[1.0])
    with pytest.raises(ValueError, match="expected at most 2"):
        cfg.set(method="DDS", values=[[[1.0]]])


def test_generate_python_wrapper_uses_package_relative_import(tmp_path: Path) -> None:
    codegen = _import_codegen_f2py()
    spec = codegen.build_f2py_namelist_spec(_schema())
    output = tmp_path / "config_wrappers.py"

    codegen.generate_python_wrappers([(spec, "f2py_config")], output)

    generated = output.read_text()
    assert "from . import f2py_config" in generated
    assert "importlib" not in generated
    assert "_f2py = f2py_config.f2py_optimization" in generated
    assert "def invalidate(self) -> None:" in generated
    assert "self.handle = 0" in generated
    assert "Parameters\n    ----------" in generated
    assert "Returns\n        -------" in generated
    assert "Raises\n        ------" in generated
    assert "method : str" in generated
    assert "values : array_like of float" in generated
    assert "expected_shape=(3, 2)," not in generated
    assert "expected_shape=None," in generated


def test_generate_python_wrapper_exposes_set_dims(tmp_path: Path) -> None:
    codegen = _import_codegen_f2py()
    spec = codegen.build_f2py_namelist_spec(
        _runtime_dimension_schema(),
        dimensions={"n_weights": 3},
    )
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    output = package_dir / "config_wrappers.py"
    calls: list[dict[str, Any]] = []

    class FakeF2pyConfig:
        @staticmethod
        def config_set_dims_wrapper(handle: int, **kwargs: Any) -> tuple[int, str]:
            calls.append(kwargs)
            return 0, ""

    class FakeExtension:
        f2py_config = FakeF2pyConfig

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setitem(sys.modules, "pkg.f2py_config", FakeExtension)
    try:
        codegen.generate_python_wrappers([(spec, "f2py_config")], output)

        module_spec = importlib.util.spec_from_file_location("pkg.config_wrappers", output)
        assert module_spec is not None
        assert module_spec.loader is not None
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)

        cfg = module.Config(7)
        cfg.set_dims(n_weights=4)
        cfg.set_dims()
    finally:
        monkeypatch.undo()

    assert calls[0]["n_weights"] == 4
    assert calls[0]["has_n_weights"] is True
    assert calls[1]["n_weights"] == 0
    assert calls[1]["has_n_weights"] is False


def test_generate_python_wrapper_set_dims_keyword_dimension_name(tmp_path: Path) -> None:
    codegen = _import_codegen_f2py()
    schema = {
        "title": "Keyword dimensions",
        "x-fortran-namelist": "config",
        "type": "object",
        "required": ["values"],
        "properties": {
            "values": {
                "type": "array",
                "x-fortran-shape": "class",
                "items": {"type": "number", "x-fortran-kind": "dp"},
            },
        },
    }
    spec = codegen.build_f2py_namelist_spec(
        schema,
        dimensions={"class": 3},
    )
    output = tmp_path / "config_wrappers.py"

    codegen.generate_python_wrappers([(spec, "f2py_config")], output)

    generated = output.read_text()
    assert "def set_dims(" in generated
    assert "class_: Any = None" in generated
    assert 'kwargs["class"] = class_' in generated
    assert 'kwargs["has_class"] = class_ is not None' in generated


def test_generate_python_wrapper_supports_doxygen_docstrings(tmp_path: Path) -> None:
    codegen = _import_codegen_f2py()
    spec = codegen.build_f2py_namelist_spec(_schema())
    output = tmp_path / "config_wrappers.py"

    codegen.generate_python_wrappers([(spec, "f2py_config")], output, py_style="doxygen")

    generated = output.read_text()
    assert '"""!' in generated
    assert "@param handle (int): Opaque handle to a Fortran namelist instance." in generated
    assert "Clear this wrapper's stored Fortran handle." in generated
    assert "@param method (str): method." in generated
    assert "@retval is_set (bool): True if the field is set, otherwise False." in generated
    assert "@throws NmlError: If validation fails." in generated


def test_generate_python_wrapper_rejects_unknown_docstring_style(tmp_path: Path) -> None:
    codegen = _import_codegen_f2py()
    spec = codegen.build_f2py_namelist_spec(_schema())

    with pytest.raises(ValueError, match="python documentation style"):
        codegen.generate_python_wrappers(
            [(spec, "f2py_config")],
            tmp_path / "config_wrappers.py",
            py_style="google",
        )
