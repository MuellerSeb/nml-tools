"""Tests for Fortran code generation."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - python<3.11
    import tomli as tomllib


def _import_generate_fortran():
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    sys.path.insert(0, str(src))
    try:
        module = importlib.import_module("nml_tools.codegen_fortran")
    finally:
        sys.path.pop(0)
    return module.generate_fortran


def _import_load_schema():
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    sys.path.insert(0, str(src))
    try:
        module = importlib.import_module("nml_tools.schema")
    finally:
        sys.path.pop(0)
    return module.load_schema


def _import_codegen_module():
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    sys.path.insert(0, str(src))
    try:
        module = importlib.import_module("nml_tools.codegen_fortran")
    finally:
        sys.path.pop(0)
    return module


def test_generate_fortran_matches_reference(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    fixture_root = root / "tests" / "fixtures" / "01_simple"
    schema_path = fixture_root / "optimization.yml"
    expected_path = fixture_root / "out" / "nml_optimization.f90"
    config_path = fixture_root / "nml-config.toml"

    with config_path.open("rb") as handle:
        config = tomllib.load(handle)
    kinds = config["kinds"]
    kind_module = kinds["module"]
    kind_map = kinds["map"]
    kind_allowlist = set(kinds["real"] + kinds["integer"])
    constants_raw = config.get("constants", {})
    if not isinstance(constants_raw, dict):
        raise ValueError("config constants must be a table")
    constants: dict[str, int] = {}
    for name, entry in constants_raw.items():
        if not isinstance(entry, dict) or "value" not in entry:
            raise ValueError("config constant entries must define a value")
        value = entry.get("value")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("config constants must be integers")
        constants[name] = value
    dimensions_raw = config.get("dimensions", {})
    if not isinstance(dimensions_raw, dict):
        raise ValueError("config dimensions must be a table")
    dimensions: dict[str, int] = {}
    for name, entry in dimensions_raw.items():
        if not isinstance(entry, dict) or "value" not in entry:
            raise ValueError("config dimension entries must define a value")
        value = entry.get("value")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("config dimensions must be integers")
        dimensions[name] = value
    doc_raw = config.get("documentation")
    if doc_raw is None:
        module_doc = None
    elif not isinstance(doc_raw, dict):
        raise ValueError("config documentation must be a table")
    else:
        module_raw = doc_raw.get("module")
        if not isinstance(module_raw, str):
            raise ValueError("config documentation module must be a string")
        module_doc = module_raw.strip() or None

    load_schema = _import_load_schema()
    schema = load_schema(schema_path)
    output = tmp_path / "nml_optimization.f90"

    generate_fortran = _import_generate_fortran()
    generate_fortran(
        schema,
        output,
        kind_module=kind_module,
        kind_map=kind_map,
        kind_allowlist=kind_allowlist,
        constants=constants,
        dimensions=dimensions,
        module_doc=module_doc,
    )

    generated = output.read_text()
    expected = expected_path.read_text()

    assert generated == expected


def test_generate_fortran_rejects_scalar_array_default(tmp_path: Path) -> None:
    schema = {
        "title": "Scalar array default",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "items": {"type": "integer", "x-fortran-kind": "i4"},
                "x-fortran-shape": 3,
                "x-fortran-default-repeat": True,
                "default": 1,
            }
        },
    }

    generate_fortran = _import_generate_fortran()
    with pytest.raises(ValueError, match=r".*array default must be a list"):
        generate_fortran(schema, tmp_path / "nml_test.f90", kind_module="mo_kind")


def test_generate_fortran_handle_helper_uses_explicit_transfer_mold(tmp_path: Path) -> None:
    schema = {
        "title": "Handle helper",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "value": {"type": "integer", "x-fortran-kind": "i4"},
        },
    }
    output = tmp_path / "nml_test.f90"

    generate_fortran = _import_generate_fortran()
    generate_fortran(
        schema,
        output,
        kind_module="mo_kind",
        kind_allowlist={"i4"},
        f2py_handle_helpers=True,
    )

    generated = output.read_text()
    assert "use iso_c_binding, only: c_f_pointer, c_intptr_t, c_null_ptr, c_ptr" in generated
    assert "ptr = transfer(handle, c_null_ptr)" in generated
    assert "ptr = transfer(handle, ptr)" not in generated


def test_generate_fortran_allows_items_default(tmp_path: Path) -> None:
    schema = {
        "title": "Items default",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "items": {"type": "integer", "x-fortran-kind": "i4", "default": 2},
                "x-fortran-shape": 4,
            }
        },
    }

    output = tmp_path / "nml_test.f90"
    generate_fortran = _import_generate_fortran()
    generate_fortran(schema, output, kind_module="mo_kind")

    generated = output.read_text()
    assert "integer(i4), parameter, public :: values_default = 2_i4" in generated
    assert "this%values = values_default" in generated


def test_generate_fortran_accepts_static_shape_constants(tmp_path: Path) -> None:
    schema = {
        "title": "Constant shapes",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "items": {"type": "integer", "x-fortran-kind": "i4", "default": 1},
                "x-fortran-shape": "max_layers",
            }
        },
    }

    output = tmp_path / "nml_test.f90"
    generate_fortran = _import_generate_fortran()
    generate_fortran(
        schema,
        output,
        kind_module="mo_kind",
        constants={"max_layers": 3},
    )

    generated = output.read_text()
    assert "integer :: dim_max_layers" not in generated
    assert "integer(i4), dimension(max_layers) :: values" in generated
    assert "procedure :: set_dims" not in generated
    assert "allocate(this%values" not in generated
    assert "use nml_helper, only:" in generated
    assert "max_layers" in generated
    assert "integer(i4), parameter, public :: values_default = 1_i4" in generated
    assert "this%values = values_default" in generated


def test_generate_fortran_matches_constants_case_insensitively(tmp_path: Path) -> None:
    schema = {
        "title": "Constant shapes",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "items": {"type": "integer", "x-fortran-kind": "i4", "default": 1},
                "x-fortran-shape": "MAX_LAYERS",
            },
            "name": {
                "type": "string",
                "x-fortran-len": "BUF",
            },
        },
    }

    output = tmp_path / "nml_test.f90"
    generate_fortran = _import_generate_fortran()
    generate_fortran(
        schema,
        output,
        kind_module="mo_kind",
        constants={"max_layers": 3, "buf": 32},
    )

    generated = output.read_text()
    assert "integer(i4), dimension(MAX_LAYERS) :: values" in generated
    assert "character(len=BUF) :: name" in generated


def test_generate_fortran_rejects_non_integer_constants(tmp_path: Path) -> None:
    schema = {
        "title": "Constant shapes",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "items": {"type": "integer", "x-fortran-kind": "i4"},
                "x-fortran-shape": "max_layers",
            },
        },
    }

    generate_fortran = _import_generate_fortran()
    with pytest.raises(ValueError, match="must be an integer"):
        generate_fortran(
            schema,
            tmp_path / "nml_test.f90",
            kind_module="mo_kind",
            constants={"max_layers": 3.5},
        )


def test_generate_fortran_accepts_runtime_dimensions(tmp_path: Path) -> None:
    schema = {
        "title": "Runtime dimensions",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "items": {"type": "integer", "x-fortran-kind": "i4", "default": 1},
                "x-fortran-shape": "max_layers",
            }
        },
    }

    output = tmp_path / "nml_test.f90"
    generate_fortran = _import_generate_fortran()
    generate_fortran(
        schema,
        output,
        kind_module="mo_kind",
        dimensions={"max_layers": 3},
    )

    generated = output.read_text()
    assert "integer :: dim_max_layers = max_layers_default" in generated
    assert "integer(i4), allocatable, dimension(:) :: values" in generated
    assert "procedure :: set_dims => nml_test_nml_set_dims" in generated
    assert "allocate(this%values(this%dim_max_layers))" in generated
    assert "use nml_helper, only:" in generated
    assert "max_layers_default=>max_layers" in generated
    assert "integer(i4), parameter, public :: values_default = 1_i4" in generated
    assert "this%values = values_default" in generated


def test_generate_fortran_normalizes_runtime_dimension_names(tmp_path: Path) -> None:
    schema = {
        "title": "Runtime dimensions",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "items": {"type": "integer", "x-fortran-kind": "i4", "default": 1},
                "x-fortran-shape": "MAX_LAYERS",
            }
        },
    }

    output = tmp_path / "nml_test.f90"
    generate_fortran = _import_generate_fortran()
    generate_fortran(
        schema,
        output,
        kind_module="mo_kind",
        dimensions={"max_layers": 3},
    )

    generated = output.read_text()
    assert "integer :: dim_max_layers = max_layers_default" in generated
    assert "max_layers_default=>max_layers" in generated


def test_generate_fortran_renames_runtime_dimension_field_collisions(
    tmp_path: Path,
) -> None:
    schema = {
        "title": "Runtime dimension field collision",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "dim_max_layers": {"type": "integer", "x-fortran-kind": "i4"},
            "values": {
                "type": "array",
                "items": {"type": "integer", "x-fortran-kind": "i4"},
                "x-fortran-shape": "max_layers",
            },
        },
    }

    output = tmp_path / "nml_test.f90"
    generate_fortran = _import_generate_fortran()
    generate_fortran(
        schema,
        output,
        kind_module="mo_kind",
        dimensions={"max_layers": 3},
    )

    generated = output.read_text()
    assert "integer :: dim_max_layers_1 = max_layers_default" in generated


def test_generate_fortran_renames_runtime_dimension_default_aliases(
    tmp_path: Path,
) -> None:
    schema = {
        "title": "Runtime dimension alias collision",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "x-fortran-len": "max_layers_default",
            },
            "values": {
                "type": "array",
                "items": {"type": "integer", "x-fortran-kind": "i4"},
                "x-fortran-shape": "max_layers",
            },
        },
    }

    output = tmp_path / "nml_test.f90"
    generate_fortran = _import_generate_fortran()
    generate_fortran(
        schema,
        output,
        kind_module="mo_kind",
        constants={"max_layers_default": 32},
        dimensions={"max_layers": 3},
    )

    generated = output.read_text()
    assert "max_layers_default, &" in generated
    assert "max_layers_default_1=>max_layers" in generated
    assert "integer :: dim_max_layers = max_layers_default_1" in generated


def test_generate_fortran_renames_runtime_dimension_alias_when_property_default_exists(
    tmp_path: Path,
) -> None:
    schema = {
        "title": "Runtime dimension/property default collision",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "max_layers": {
                "type": "integer",
                "x-fortran-kind": "i4",
                "default": 2,
            },
            "values": {
                "type": "array",
                "items": {"type": "integer", "x-fortran-kind": "i4"},
                "x-fortran-shape": "max_layers",
            },
        },
    }

    output = tmp_path / "nml_test.f90"
    generate_fortran = _import_generate_fortran()
    generate_fortran(
        schema,
        output,
        kind_module="mo_kind",
        dimensions={"max_layers": 3},
    )

    generated = output.read_text()
    assert "integer(i4), parameter, public :: max_layers_default = 2_i4" in generated
    assert "max_layers_default=>max_layers" not in generated
    assert "max_layers_default_1=>max_layers" in generated
    assert "integer :: dim_max_layers = max_layers_default_1" in generated


def test_generate_fortran_does_not_alias_runtime_dimension_names_in_type_specs(
    tmp_path: Path,
) -> None:
    schema = {
        "title": "Runtime dimension kind collision",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "items": {"type": "number", "x-fortran-kind": "dp", "default": 1.0},
                "x-fortran-shape": "dp",
            },
            "limit": {
                "type": "number",
                "x-fortran-kind": "dp",
                "minimum": 0.0,
            },
        },
    }

    output = tmp_path / "nml_test.f90"
    generate_fortran = _import_generate_fortran()
    generate_fortran(
        schema,
        output,
        kind_module="mo_kind",
        dimensions={"dp": 3},
    )

    generated = output.read_text()
    assert "real(dp), parameter, public :: values_default = 1.0_dp" in generated
    assert "real(dp), parameter, public :: limit_min = 0.0_dp" in generated
    assert "real(dp_default)" not in generated


def test_generate_fortran_rejects_invalid_runtime_dimensions(tmp_path: Path) -> None:
    schema = {
        "title": "Runtime dimensions",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "items": {"type": "integer", "x-fortran-kind": "i4", "default": 1},
                "x-fortran-shape": "max_layers",
            }
        },
    }

    generate_fortran = _import_generate_fortran()

    with pytest.raises(ValueError, match="valid Fortran identifier"):
        generate_fortran(
            schema,
            tmp_path / "nml_test_invalid_name.f90",
            kind_module="mo_kind",
            dimensions={"1bad": 3},
        )

    with pytest.raises(ValueError, match="must be an integer"):
        generate_fortran(
            schema,
            tmp_path / "nml_test_bool.f90",
            kind_module="mo_kind",
            dimensions={"max_layers": True},
        )

    with pytest.raises(ValueError, match="must be positive"):
        generate_fortran(
            schema,
            tmp_path / "nml_test_zero.f90",
            kind_module="mo_kind",
            dimensions={"max_layers": 0},
        )


def test_generate_fortran_requires_array_shape(tmp_path: Path) -> None:
    schema = {
        "title": "Missing shape",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "items": {"type": "integer", "x-fortran-kind": "i4"},
            }
        },
    }

    generate_fortran = _import_generate_fortran()
    with pytest.raises(ValueError, match=r".*x-fortran-shape"):
        generate_fortran(schema, tmp_path / "nml_test.f90", kind_module="mo_kind")


def test_generate_fortran_rejects_nested_arrays(tmp_path: Path) -> None:
    schema = {
        "title": "Nested arrays",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "x-fortran-shape": 2,
                "items": {
                    "type": "array",
                    "x-fortran-shape": 3,
                    "items": {"type": "integer", "x-fortran-kind": "i4"},
                },
            }
        },
    }

    generate_fortran = _import_generate_fortran()
    with pytest.raises(ValueError, match=r".*nested array properties"):
        generate_fortran(schema, tmp_path / "nml_test.f90", kind_module="mo_kind")


def test_generate_fortran_rejects_flex_dim_on_scalar(tmp_path: Path) -> None:
    schema = {
        "title": "Flex dim scalar",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "count": {"type": "integer", "x-fortran-flex-tail-dims": 1},
        },
    }

    generate_fortran = _import_generate_fortran()
    with pytest.raises(
        ValueError,
        match=r".*x-fortran-flex-tail-dims is only supported for arrays",
    ):
        generate_fortran(schema, tmp_path / "nml_test.f90", kind_module="mo_kind")


def test_generate_fortran_rejects_flex_dim_with_default(tmp_path: Path) -> None:
    schema = {
        "title": "Flex dim default",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "x-fortran-shape": [2, 3],
                "x-fortran-flex-tail-dims": 1,
                "items": {"type": "integer", "x-fortran-kind": "i4"},
                "default": [1, 2, 3],
            }
        },
    }

    generate_fortran = _import_generate_fortran()
    with pytest.raises(ValueError, match=r".*flex arrays cannot define defaults"):
        generate_fortran(schema, tmp_path / "nml_test.f90", kind_module="mo_kind")


def test_generate_fortran_rejects_partial_array_default(tmp_path: Path) -> None:
    schema = {
        "title": "Partial default",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "items": {"type": "integer", "x-fortran-kind": "i4"},
                "x-fortran-shape": [2, 2],
                "default": [1, 2, 3],
            }
        },
    }

    generate_fortran = _import_generate_fortran()
    with pytest.raises(
        ValueError,
        match=r".*array default shorter than declared x-fortran-shape",
    ):
        generate_fortran(schema, tmp_path / "nml_test.f90", kind_module="mo_kind")


def test_generate_fortran_emits_bounds_helpers(tmp_path: Path) -> None:
    schema = {
        "title": "Bounds test",
        "x-fortran-namelist": "bounds_nml",
        "type": "object",
        "properties": {
            "tolerance": {
                "type": "number",
                "x-fortran-kind": "dp",
                "minimum": 0.0,
                "exclusiveMaximum": 1.0,
            },
            "counts": {
                "type": "array",
                "x-fortran-shape": 2,
                "items": {"type": "integer", "x-fortran-kind": "i4", "minimum": 1},
            },
        },
    }

    output = tmp_path / "nml_bounds.f90"
    generate_fortran = _import_generate_fortran()
    generate_fortran(schema, output, kind_module="mo_kind")

    generated = output.read_text()
    assert "real(dp), parameter, public :: tolerance_min = 0.0_dp" in generated
    assert "real(dp), parameter, public :: tolerance_max_excl = 1.0_dp" in generated
    assert "integer(i4), parameter, public :: counts_min = 1_i4" in generated
    assert "elemental logical function tolerance_in_bounds" in generated
    assert "elemental logical function counts_in_bounds" in generated
    assert "all(counts_in_bounds(this%counts, allow_missing=.true.))" in generated


def test_generate_fortran_rejects_flex_dim_boolean_array(tmp_path: Path) -> None:
    schema = {
        "title": "Flex dim boolean",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "flags": {
                "type": "array",
                "x-fortran-shape": 2,
                "x-fortran-flex-tail-dims": 1,
                "items": {"type": "boolean"},
            }
        },
    }

    generate_fortran = _import_generate_fortran()
    with pytest.raises(ValueError, match=r".*flex arrays cannot use boolean elements"):
        generate_fortran(schema, tmp_path / "nml_test.f90", kind_module="mo_kind")


def test_generate_fortran_rejects_flex_dim_exceeds_rank(tmp_path: Path) -> None:
    schema = {
        "title": "Flex dim exceeds rank",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "x-fortran-shape": [2, 3],
                "x-fortran-flex-tail-dims": 3,
                "items": {"type": "integer", "x-fortran-kind": "i4"},
            }
        },
    }

    generate_fortran = _import_generate_fortran()
    with pytest.raises(
        ValueError,
        match=r".*x-fortran-flex-tail-dims must not exceed",
    ):
        generate_fortran(schema, tmp_path / "nml_test.f90", kind_module="mo_kind")


def test_generate_fortran_rejects_case_insensitive_duplicates(tmp_path: Path) -> None:
    schema = {
        "title": "Duplicate case",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "Foo": {"type": "integer"},
            "foo": {"type": "integer"},
        },
    }

    generate_fortran = _import_generate_fortran()
    with pytest.raises(ValueError, match=r"case-insensitive"):
        generate_fortran(schema, tmp_path / "nml_test.f90", kind_module="mo_kind")


def test_generate_fortran_accepts_required_case_insensitive(tmp_path: Path) -> None:
    schema = {
        "title": "Required case",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "Foo": {"type": "integer"},
        },
        "required": ["foo"],
    }

    generate_fortran = _import_generate_fortran()
    generate_fortran(schema, tmp_path / "nml_test.f90", kind_module="mo_kind")


def test_generate_fortran_rejects_required_unknown_property(tmp_path: Path) -> None:
    schema = {
        "title": "Required missing",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "Foo": {"type": "integer"},
        },
        "required": ["Bar"],
    }

    generate_fortran = _import_generate_fortran()
    with pytest.raises(ValueError, match=r"required property 'Bar' is not defined"):
        generate_fortran(schema, tmp_path / "nml_test.f90", kind_module="mo_kind")


def test_generate_fortran_emits_filled_shape_for_flex_arrays(tmp_path: Path) -> None:
    schema = {
        "title": "Flex arrays",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "required": ["values"],
        "properties": {
            "values": {
                "type": "array",
                "x-fortran-shape": [2, 3],
                "x-fortran-flex-tail-dims": 1,
                "items": {"type": "integer", "x-fortran-kind": "i4"},
            }
        },
    }

    output = tmp_path / "nml_test.f90"
    generate_fortran = _import_generate_fortran()
    generate_fortran(schema, output, kind_module="mo_kind")

    generated = output.read_text()
    assert "procedure :: filled_shape" in generated
    assert "_filled_shape(this, name, filled, errmsg)" in generated
    assert "NML_ERR_PARTLY_SET" in generated


def test_generate_fortran_requires_dimension_constants(tmp_path: Path) -> None:
    schema = {
        "title": "Missing constant",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "items": {"type": "integer", "x-fortran-kind": "i4"},
                "x-fortran-shape": "max_layers",
            }
        },
    }

    generate_fortran = _import_generate_fortran()
    with pytest.raises(
        ValueError,
        match=r".*dimension constant 'max_layers' is not defined in config",
    ):
        generate_fortran(schema, tmp_path / "nml_test.f90", kind_module="mo_kind")


def test_generate_fortran_accepts_string_length_constants(tmp_path: Path) -> None:
    schema = {
        "title": "String length constants",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "x-fortran-len": "name_len",
            }
        },
    }

    output = tmp_path / "nml_test.f90"
    generate_fortran = _import_generate_fortran()
    generate_fortran(
        schema,
        output,
        kind_module="mo_kind",
        constants={"name_len": 32},
    )

    generated = output.read_text()
    assert "integer :: dim_name_len" not in generated
    assert "character(len=name_len) :: name" in generated
    assert "procedure :: set_dims" not in generated
    assert "allocate(character" not in generated
    assert "use nml_helper, only:" in generated
    assert "name_len" in generated


def test_generate_fortran_rejects_runtime_dimensions_as_string_lengths(
    tmp_path: Path,
) -> None:
    schema = {
        "title": "String length dimensions",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "x-fortran-len": "name_len",
            }
        },
    }

    generate_fortran = _import_generate_fortran()
    with pytest.raises(ValueError, match="dimension 'name_len' cannot be used as x-fortran-len"):
        generate_fortran(
            schema,
            tmp_path / "nml_test.f90",
            kind_module="mo_kind",
            dimensions={"name_len": 32},
        )


def test_generate_fortran_set_dims_validates_before_assignment(tmp_path: Path) -> None:
    schema = {
        "title": "Transactional constants",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "items": {"type": "integer", "x-fortran-kind": "i4"},
                "x-fortran-shape": "max_layers",
                "default": [1, 2, 3, 4],
            },
        },
    }

    output = tmp_path / "nml_test.f90"
    generate_fortran = _import_generate_fortran()
    generate_fortran(
        schema,
        output,
        kind_module="mo_kind",
        dimensions={"max_layers": 4},
    )

    generated = output.read_text()
    assert "if (candidate_max_layers < 4) then" in generated
    assert "shape constants for 'values' must allow at least 4 default values" in generated
    assert "namelist not configured; call set or from_file" in generated

    is_set_idx = generated.index("integer function nml_test_nml_is_set")
    is_valid_idx = generated.index("integer function nml_test_nml_is_valid")
    generated.index("if (.not. this%is_configured) then", is_set_idx)
    generated.index("if (.not. this%is_configured) then", is_valid_idx)

    validate_idx = generated.index("if (candidate_max_layers <= 0) then")
    assign_idx = generated.index("this%dim_max_layers = candidate_max_layers")
    assert assign_idx > validate_idx


def test_generate_fortran_runtime_sized_array_with_default_uses_partial_set(tmp_path: Path) -> None:
    schema = {
        "title": "Dynamic array partial set",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "items": {"type": "integer", "x-fortran-kind": "i4"},
                "x-fortran-shape": "max_layers",
                "default": [1, 2, 3, 4],
            }
        },
    }

    output = tmp_path / "nml_test.f90"
    generate_fortran = _import_generate_fortran()
    generate_fortran(
        schema,
        output,
        kind_module="mo_kind",
        dimensions={"max_layers": 4},
    )

    generated = output.read_text()
    assert "if (size(values, 1) > size(this%values, 1)) then" in generated
    assert "this%values(lb_1:ub_1) = values" in generated
    assert "dimension 1 mismatch for 'values'" not in generated


def test_generate_fortran_fixed_array_setters_use_assumed_shape(
    tmp_path: Path,
) -> None:
    schema = {
        "title": "Fixed array partial set",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "items": {"type": "integer", "x-fortran-kind": "i4"},
                "x-fortran-shape": 3,
            }
        },
    }

    output = tmp_path / "nml_test.f90"
    generate_fortran = _import_generate_fortran()
    generate_fortran(schema, output, kind_module="mo_kind")

    generated = output.read_text()
    assert "integer(i4), dimension(:), intent(in), optional :: values" in generated
    assert "if (size(values, 1) > size(this%values, 1)) then" in generated
    assert "this%values(lb_1:ub_1) = values" in generated
    assert "dimension(3), intent(in), optional :: values" not in generated


def test_generate_fortran_runtime_sized_string_array_uses_static_length(
    tmp_path: Path,
) -> None:
    schema = {
        "title": "Dynamic string array",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "names": {
                "type": "array",
                "items": {"type": "string", "x-fortran-len": "name_len"},
                "x-fortran-shape": "max_names",
            }
        },
    }

    output = tmp_path / "nml_test.f90"
    generate_fortran = _import_generate_fortran()
    generate_fortran(
        schema,
        output,
        kind_module="mo_kind",
        constants={"name_len": 16},
        dimensions={"max_names": 2},
    )

    generated = output.read_text()
    assert "character(len=name_len), allocatable, dimension(:) :: names" in generated
    assert "allocate(character(len=name_len) :: this%names(this%dim_max_names))" in generated
    assert "character(len=:), allocatable" not in generated
    assert "this%names = names" in generated


def test_generate_fortran_multidimensional_string_array_sentinels(
    tmp_path: Path,
) -> None:
    schema = {
        "title": "Two dimensional string array",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "names": {
                "type": "array",
                "items": {"type": "string", "x-fortran-len": "name_len"},
                "x-fortran-shape": ["nrow", "ncol"],
            }
        },
    }

    output = tmp_path / "nml_test.f90"
    generate_fortran = _import_generate_fortran()
    generate_fortran(
        schema,
        output,
        kind_module="mo_kind",
        constants={"name_len": 16, "nrow": 2, "ncol": 3},
    )

    generated = output.read_text()
    assert "this%names = achar(0)" in generated
    assert "all(this%names == achar(0))" in generated


def test_generate_fortran_array_default_pad_order(tmp_path: Path) -> None:
    schema = {
        "title": "Array default pad",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "matrix": {
                "type": "array",
                "items": {"type": "integer", "x-fortran-kind": "i4"},
                "x-fortran-shape": [2, 2],
                "x-fortran-default-order": "C",
                "x-fortran-default-pad": 0,
                "default": [1, 2, 3],
            }
        },
    }

    output = tmp_path / "nml_test.f90"
    generate_fortran = _import_generate_fortran()
    generate_fortran(schema, output, kind_module="mo_kind")

    generated = output.read_text()
    assert "matrix_default(3) = [1_i4, 2_i4, 3_i4]" in generated
    assert "matrix_pad = 0_i4" in generated
    assert "order=[2, 1]" in generated
    assert "pad=[matrix_pad]" in generated


def test_generate_fortran_allows_plain_kinds(tmp_path: Path) -> None:
    schema = {
        "title": "Plain kinds",
        "x-fortran-namelist": "test_nml",
        "type": "object",
        "properties": {
            "count": {"type": "integer"},
            "ratio": {"type": "number"},
        },
    }

    output = tmp_path / "nml_test.f90"
    generate_fortran = _import_generate_fortran()
    generate_fortran(schema, output, kind_module="mo_kind")

    generated = output.read_text()
    assert "integer :: count" in generated
    assert "real :: ratio" in generated


def test_generate_fortran_emits_local_derived_types_and_typed_fields() -> None:
    from nml_tools.schema import resolve_schema

    codegen = _import_codegen_module()
    schema = resolve_schema(
        {
            "title": "Run",
            "x-fortran-namelist": "run",
            "type": "object",
            "$defs": {
                "period": {
                    "title": "Time period",
                    "description": "Bounds for one time interval.",
                    "type": "object",
                    "x-fortran-type": "period_t",
                    "properties": {
                        "start_year": {
                            "title": "Start year",
                            "type": "integer",
                            "x-fortran-kind": "i4",
                            "minimum": 1900,
                        },
                        "end_year": {
                            "title": "End year",
                            "type": "integer",
                            "x-fortran-kind": "i4",
                        },
                        "label": {
                            "title": "Label",
                            "type": "string",
                            "x-fortran-len": 16,
                            "default": "default",
                            "enum": ["default", "archive"],
                        },
                    },
                    "required": ["start_year", "end_year"],
                }
            },
            "required": ["period", "periods"],
            "properties": {
                "period": {"$ref": "#/$defs/period"},
                "periods": {
                    "type": "array",
                    "x-fortran-shape": "n_periods",
                    "items": {"$ref": "#/$defs/period"},
                },
            },
        }
    )

    local_types = codegen.collect_local_derived_types([schema])
    helper = codegen.render_helper(
        file_name="nml_helper.f90",
        local_derived_types=local_types,
        kind_module="iso_fortran_env",
        kind_map={"i4": "int32"},
        kind_allowlist={"int32"},
    )
    generated = codegen.render_fortran(
        schema,
        file_name="nml_run.f90",
        kind_module="iso_fortran_env",
        kind_map={"i4": "int32"},
        kind_allowlist={"int32"},
        dimensions={"n_periods": 2},
    )

    assert "!> \\class period_t" in helper
    assert "!> \\brief Time period" in helper
    assert "type, public :: period_t" in helper
    assert "integer(i4) :: start_year !< Start year" in helper
    assert "use nml_helper, only:" in generated and "period_t" in generated
    assert "type(period_t) :: period" in generated
    assert "type(period_t), allocatable, dimension(:) :: periods" in generated
    assert "procedure :: init_type => nml_run_init_type" in generated
    assert "this%period%start_year" in generated
    assert 'case ("period%start_year")' in generated
    assert 'case ("periods%start_year")' in generated
    assert " .and. &" in generated
    assert " .or. &" in generated
    assert "integer(i4), parameter, public :: period_start_year_min = 1900_i4" in generated
    assert "elemental logical function period_start_year_in_bounds" in generated
    assert "period_label_in_enum(this%period%label)" in generated
    assert "periods_start_year_in_bounds(this%periods%start_year" in generated
    assert "if (allocated(this%periods)) then" in generated


def test_generate_fortran_imports_application_owned_derived_type() -> None:
    from nml_tools.schema import resolve_schema

    codegen = _import_codegen_module()
    schema = resolve_schema(
        {
            "x-fortran-namelist": "run",
            "type": "object",
            "$defs": {
                "location": {
                    "type": "object",
                    "x-fortran-type": "location_t",
                    "x-fortran-module": "application_types",
                    "properties": {
                        "name": {
                            "type": "string",
                            "x-fortran-len": 8,
                            "default": "default",
                        }
                    },
                }
            },
            "required": ["location", "locations"],
            "properties": {
                "location": {"$ref": "#/$defs/location"},
                "locations": {
                    "type": "array",
                    "x-fortran-shape": 2,
                    "items": {"$ref": "#/$defs/location"},
                },
            },
        }
    )

    generated = codegen.render_fortran(schema, file_name="nml_run.f90")

    assert "use application_types, only: location_t" in generated
    assert "type(location_t) :: location" in generated
    assert "if (len(this%location%name) < 8) then" in generated
    assert 'this%location%name(8 + 1:) = ""' in generated
    assert "if (len(this%locations%name) < 8) then" in generated
    assert 'this%locations(:)%name(8 + 1:) = ""' in generated
