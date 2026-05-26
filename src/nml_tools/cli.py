"""Command line interface for nml-tools."""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path
from typing import Any, cast

import click
import f90nml  # type: ignore
from click.exceptions import Exit
from packaging.version import InvalidVersion, Version

from ._utils import constant_dimension_overlap, is_fortran_identifier
from ._version import __version__
from .codegen_f2py import (
    F2pyCTypeMap,
    build_f2py_namelist_spec,
    collect_f2py_kind_usage,
    merge_f2py_kind_usage,
    render_f2cmap,
    render_f2py_wrappers,
    render_python_wrappers,
)
from .codegen_fortran import (
    ConstantSpec,
    collect_local_derived_types,
    generate_fortran,
    generate_helper,
    render_fortran,
    render_helper,
)
from .codegen_markdown import generate_docs, render_docs
from .codegen_template import generate_template, render_template
from .schema import SchemaResolver, load_schema
from .validate import validate_namelist

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - python<3.11
    import tomli as tomllib

logger = logging.getLogger(__name__)
_CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}
_DEFAULT_CONFIG = Path("nml-config.toml")
_PYPROJECT_CONFIG = Path("pyproject.toml")

_NamedIntegerTypeBase = cast(Any, click.ParamType)


class NamedIntegerType(_NamedIntegerTypeBase):  # type: ignore[valid-type, misc]
    """Parse NAME=INT values for CLI options."""

    name = "NAME=INT"

    def __init__(self, *, label: str, positive: bool = False) -> None:
        self._label = label
        self._positive = positive

    def convert(
        self,
        value: Any,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> tuple[str, int]:
        if not isinstance(value, str) or "=" not in value:
            self.fail("must be NAME=INT", param, ctx)

        raw_name, raw_value = value.split("=", 1)
        name = raw_name.strip()
        if not name:
            self.fail("must use non-empty names", param, ctx)
        if not is_fortran_identifier(name):
            self.fail(f"{self._label} '{name}' must be a valid identifier", param, ctx)

        value_text = raw_value.strip()
        if not value_text:
            self.fail(f"{self._label} '{name}' must define a value", param, ctx)
        value_digits = value_text[1:] if value_text[:1] in {"+", "-"} else value_text
        if not value_digits.isdigit():
            self.fail(f"{self._label} '{name}' value must be an integer", param, ctx)

        parsed_value = int(value_text)
        if self._positive and parsed_value <= 0:
            self.fail(f"{self._label} '{name}' value must be positive", param, ctx)
        return name.lower(), parsed_value


_CONSTANT_TYPE = NamedIntegerType(label="constant")
_DIMENSION_TYPE = NamedIntegerType(label="dimension", positive=True)


@dataclass(frozen=True)
class GeneratedOutput:
    """Generated file content for write/check commands."""

    path: Path
    content: str


def _configure_logging(verbose: int, quiet: int) -> None:
    base_level = logging.INFO
    level = base_level - (10 * verbose) + (10 * quiet)
    level = max(logging.DEBUG, min(logging.CRITICAL, level))
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    if not isinstance(data, dict):
        raise click.ClickException("config must be a table")
    return data


def _load_toml_checked(path: Path) -> dict[str, Any]:
    try:
        return _load_toml(path)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:  # pragma: no cover - tomllib may raise ValueError
        raise click.ClickException(f"failed to read config: {exc}") from exc


def _load_config_checked(path: Path | None) -> tuple[dict[str, Any], Path]:
    config_path = _resolve_config_path(path)
    raw_config = _load_toml_checked(config_path)
    if config_path.name == _PYPROJECT_CONFIG.name:
        config = _extract_pyproject_config(raw_config)
    else:
        config = raw_config
    _check_minimum_version(config)
    return config, config_path


def _resolve_config_path(path: Path | None) -> Path:
    if path is not None:
        return path
    if _DEFAULT_CONFIG.is_file():
        return _DEFAULT_CONFIG
    if _PYPROJECT_CONFIG.is_file():
        raw_config = _load_toml_checked(_PYPROJECT_CONFIG)
        if _has_pyproject_config(raw_config):
            return _PYPROJECT_CONFIG
    raise click.ClickException(
        "no config found; create nml-config.toml or add [tool.nml-tools] to pyproject.toml"
    )


def _has_pyproject_config(config: dict[str, Any]) -> bool:
    tool_raw = config.get("tool")
    return isinstance(tool_raw, dict) and isinstance(tool_raw.get("nml-tools"), dict)


def _extract_pyproject_config(config: dict[str, Any]) -> dict[str, Any]:
    tool_raw = config.get("tool")
    if not isinstance(tool_raw, dict):
        raise click.ClickException("pyproject.toml must define [tool.nml-tools]")
    nml_tools_raw = tool_raw.get("nml-tools")
    if not isinstance(nml_tools_raw, dict):
        raise click.ClickException("pyproject.toml must define [tool.nml-tools]")
    return nml_tools_raw


def _check_minimum_version(config: dict[str, Any]) -> None:
    minimum_raw = config.get("minimum-version")
    if minimum_raw is None:
        return
    if not isinstance(minimum_raw, str) or not minimum_raw.strip():
        raise click.ClickException("config 'minimum-version' must be a non-empty string")
    try:
        minimum = Version(minimum_raw.strip())
    except InvalidVersion as exc:
        raise click.ClickException(
            f"config 'minimum-version' is not a valid version: {minimum_raw}"
        ) from exc
    try:
        current = Version(__version__)
    except InvalidVersion as exc:  # pragma: no cover - package version should be valid
        raise click.ClickException(f"nml-tools version is not valid: {__version__}") from exc
    if current < minimum:
        raise click.ClickException(
            f"config requires nml-tools >= {minimum}, current version is {current}"
        )


def _resolve_optional_path(
    value: Any,
    *,
    base_dir: Path,
    key: str,
) -> Path | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise click.ClickException(f"config '{key}' must be a string")
    return base_dir / value


def _load_helper_settings(
    config: dict[str, Any],
    base_dir: Path,
) -> tuple[Path | None, str, int, str | None]:
    default_buffer = 1024
    helper_raw = config.get("helper")
    if helper_raw is None:
        helper_path = _resolve_optional_path(
            config.get("helper_path"),
            base_dir=base_dir,
            key="helper_path",
        )
        helper_module_raw = config.get("helper_module", "nml_helper")
        if not isinstance(helper_module_raw, str):
            raise click.ClickException("config 'helper_module' must be a string")
        helper_module = helper_module_raw.strip()
        if not helper_module:
            raise click.ClickException("config 'helper_module' must be a non-empty string")
        return helper_path, helper_module, default_buffer, None

    if not isinstance(helper_raw, dict):
        raise click.ClickException("config 'helper' must be a table")
    if "helper_path" in config or "helper_module" in config:
        logger.warning("config uses [helper]; ignoring legacy helper_path/helper_module")
    helper_path = _resolve_optional_path(
        helper_raw.get("path"),
        base_dir=base_dir,
        key="helper.path",
    )
    helper_module_raw = helper_raw.get("module", "nml_helper")
    if not isinstance(helper_module_raw, str):
        raise click.ClickException("config 'helper.module' must be a string")
    helper_module = helper_module_raw.strip()
    if not helper_module:
        raise click.ClickException("config 'helper.module' must be a non-empty string")
    header_raw = helper_raw.get("header")
    if header_raw is None:
        header = None
    else:
        if not isinstance(header_raw, str):
            raise click.ClickException("config 'helper.header' must be a string")
        header = header_raw.rstrip()
        if not header:
            header = None
    buffer_raw = helper_raw.get("buffer", default_buffer)
    if isinstance(buffer_raw, bool) or not isinstance(buffer_raw, int):
        raise click.ClickException("config 'helper.buffer' must be an integer")
    if buffer_raw <= 0:
        raise click.ClickException("config 'helper.buffer' must be positive")
    return helper_path, helper_module, buffer_raw, header


def _load_kind_settings(config: dict[str, Any]) -> tuple[str, dict[str, str], set[str]]:
    kinds_raw = config.get("kinds")
    if not isinstance(kinds_raw, dict):
        raise click.ClickException("config must define a [kinds] table")
    module_raw = kinds_raw.get("module")
    if not isinstance(module_raw, str) or not module_raw.strip():
        raise click.ClickException("config 'kinds.module' must be a non-empty string")
    module = module_raw.strip()

    map_raw = kinds_raw.get("map", {})
    if map_raw is None:
        map_raw = {}
    if not isinstance(map_raw, dict):
        raise click.ClickException("config 'kinds.map' must be a table")
    kind_map: dict[str, str] = {}
    for alias, target in map_raw.items():
        if not isinstance(alias, str) or not isinstance(target, str):
            raise click.ClickException("config 'kinds.map' keys and values must be strings")
        kind_map[alias] = target

    real_raw = kinds_raw.get("real", [])
    integer_raw = kinds_raw.get("integer", [])
    if not isinstance(real_raw, list) or not all(isinstance(item, str) for item in real_raw):
        raise click.ClickException("config 'kinds.real' must be a list of strings")
    if not isinstance(integer_raw, list) or not all(isinstance(item, str) for item in integer_raw):
        raise click.ClickException("config 'kinds.integer' must be a list of strings")
    allowlist = set(real_raw) | set(integer_raw)

    return module, kind_map, allowlist


def _load_f2py_settings(
    config: dict[str, Any],
    base_dir: Path,
) -> tuple[Path | None, F2pyCTypeMap]:
    f2py_raw = config.get("f2py")
    if f2py_raw is None:
        return None, F2pyCTypeMap(real={}, integer={})
    if not isinstance(f2py_raw, dict):
        raise click.ClickException("config 'f2py' must be a table")
    if "python_package" in f2py_raw:
        raise click.ClickException(
            "config 'f2py.python_package' is no longer supported; "
            "place the f2py extension next to the generated Python wrapper"
        )

    f2cmap_path = _resolve_optional_path(
        f2py_raw.get("f2cmap_path"),
        base_dir=base_dir,
        key="f2py.f2cmap_path",
    )

    c_types_raw = f2py_raw.get("c_types", {})
    if c_types_raw is None:
        c_types_raw = {}
    if not isinstance(c_types_raw, dict):
        raise click.ClickException("config 'f2py.c_types' must be a table")

    real = _load_f2py_ctype_table(c_types_raw, "real")
    integer = _load_f2py_ctype_table(c_types_raw, "integer")
    return f2cmap_path, F2pyCTypeMap(real=real, integer=integer)


def _load_f2py_ctype_table(c_types: dict[str, Any], key: str) -> dict[str, str]:
    raw = c_types.get(key, {})
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise click.ClickException(f"config 'f2py.c_types.{key}' must be a table")
    values: dict[str, str] = {}
    for kind, c_type in raw.items():
        if not isinstance(kind, str) or not kind.strip():
            raise click.ClickException(
                f"config 'f2py.c_types.{key}' keys must be non-empty strings"
            )
        if not isinstance(c_type, str) or not c_type.strip():
            raise click.ClickException(
                f"config 'f2py.c_types.{key}.{kind}' must be a non-empty string"
            )
        values[kind.strip()] = c_type.strip()
    return values


def _format_constant_literal(value: int) -> tuple[str, str]:
    if isinstance(value, bool):
        raise click.ClickException("config constants must not be boolean")
    if isinstance(value, int):
        return "integer", str(value)
    raise click.ClickException("config constants must be integers")


def _load_constants(config: dict[str, Any]) -> tuple[dict[str, int], list[ConstantSpec]]:
    constants_raw = config.get("constants", {})
    if constants_raw is None:
        constants_raw = {}
    if not isinstance(constants_raw, dict):
        raise click.ClickException("config 'constants' must be a table")

    constants: dict[str, int] = {}
    specs: list[ConstantSpec] = []
    for name_raw, entry in constants_raw.items():
        if not isinstance(name_raw, str):
            raise click.ClickException("config constants must use string keys")
        name = name_raw.strip()
        if not name:
            raise click.ClickException("config constants must have non-empty names")
        if not is_fortran_identifier(name):
            raise click.ClickException(
                f"config constant '{name}' must be a valid Fortran identifier"
            )
        canonical_name = name.lower()
        if canonical_name in constants:
            raise click.ClickException(
                f"config constant '{name}' duplicates another constant name"
            )
        if not isinstance(entry, dict):
            raise click.ClickException(f"config constant '{name}' must be a table with 'value'")
        if "value" not in entry:
            raise click.ClickException(f"config constant '{name}' must define 'value'")
        value = entry.get("value")
        if isinstance(value, bool) or not isinstance(value, int):
            raise click.ClickException("config constants must be integers")
        type_spec, literal = _format_constant_literal(value)
        doc = entry.get("doc")
        if doc is not None:
            if not isinstance(doc, str):
                raise click.ClickException(f"config constant '{name}' doc must be a string")
            doc = " ".join(doc.splitlines()).strip() or None
        specs.append(
            ConstantSpec(
                name=canonical_name,
                type_spec=type_spec,
                value=literal,
                doc=doc,
            )
        )
        constants[canonical_name] = value
    return constants, specs


def _load_dimensions(
    config: dict[str, Any],
    constants: dict[str, int],
) -> tuple[dict[str, int], list[ConstantSpec]]:
    dimensions_raw = config.get("dimensions", {})
    if dimensions_raw is None:
        dimensions_raw = {}
    if not isinstance(dimensions_raw, dict):
        raise click.ClickException("config 'dimensions' must be a table")

    dimensions: dict[str, int] = {}
    specs: list[ConstantSpec] = []
    constant_names = {name.lower() for name in constants}
    for name_raw, entry in dimensions_raw.items():
        if not isinstance(name_raw, str):
            raise click.ClickException("config dimensions must use string keys")
        name = name_raw.strip()
        if not name:
            raise click.ClickException("config dimensions must have non-empty names")
        if not is_fortran_identifier(name):
            raise click.ClickException(
                f"config dimension '{name}' must be a valid Fortran identifier"
            )
        canonical_name = name.lower()
        if canonical_name in constant_names:
            raise click.ClickException(
                f"config dimension '{name}' duplicates a constant name"
            )
        if canonical_name in dimensions:
            raise click.ClickException(
                f"config dimension '{name}' duplicates another dimension name"
            )
        if not isinstance(entry, dict):
            raise click.ClickException(f"config dimension '{name}' must be a table with 'value'")
        if "value" not in entry:
            raise click.ClickException(f"config dimension '{name}' must define 'value'")
        value = entry.get("value")
        if isinstance(value, bool) or not isinstance(value, int):
            raise click.ClickException(f"config dimension '{name}' value must be an integer")
        if value <= 0:
            raise click.ClickException(f"config dimension '{name}' value must be positive")
        doc = entry.get("doc")
        if doc is not None:
            if not isinstance(doc, str):
                raise click.ClickException(f"config dimension '{name}' doc must be a string")
            doc = " ".join(doc.splitlines()).strip() or None
        specs.append(
            ConstantSpec(
                name=canonical_name,
                type_spec="integer",
                value=str(value),
                doc=doc,
            )
        )
        dimensions[canonical_name] = value
    return dimensions, specs


def _load_bool_field(section: dict[str, Any], key: str, *, label: str) -> bool:
    value = section.get(key, False)
    if isinstance(value, bool):
        return value
    raise click.ClickException(f"config '{label}' must be a boolean")


def _load_documentation_settings(
    config: dict[str, Any],
) -> tuple[str | None, bool, bool, str]:
    doc_raw = config.get("documentation")
    if doc_raw is None:
        return None, False, False, "numpy"
    if not isinstance(doc_raw, dict):
        raise click.ClickException("config 'documentation' must be a table")
    module_doc = None
    if "module" in doc_raw:
        module_raw = doc_raw.get("module")
        if not isinstance(module_raw, str):
            raise click.ClickException("config 'documentation.module' must be a string")
        module_doc = module_raw.strip() or None
    md_doxygen_id_from_name = _load_bool_field(
        doc_raw,
        "md_doxygen_id_from_name",
        label="documentation.md_doxygen_id_from_name",
    )
    md_add_toc_statement = _load_bool_field(
        doc_raw,
        "md_add_toc_statement",
        label="documentation.md_add_toc_statement",
    )
    py_style_raw = doc_raw.get("py-style", "numpy")
    if not isinstance(py_style_raw, str):
        raise click.ClickException("config 'documentation.py-style' must be a string")
    py_style = py_style_raw.strip().lower()
    if py_style not in {"numpy", "doxygen"}:
        raise click.ClickException(
            "config 'documentation.py-style' must be 'numpy' or 'doxygen'"
        )
    return module_doc, md_doxygen_id_from_name, md_add_toc_statement, py_style


def _parse_cli_constants(values: tuple[tuple[str, int], ...]) -> dict[str, int]:
    constants: dict[str, int] = {}
    for name, value in values:
        if name in constants:
            raise click.ClickException(f"constant '{name}' duplicates another constant name")
        constants[name] = value
    return constants


def _parse_cli_dimensions(values: tuple[tuple[str, int], ...]) -> dict[str, int]:
    dimensions: dict[str, int] = {}
    for name, value in values:
        if name in dimensions:
            raise click.ClickException(f"dimension '{name}' duplicates another dimension name")
        if value <= 0:
            raise click.ClickException(f"dimension '{name}' value must be positive")
        dimensions[name] = value
    return dimensions


def _reject_constant_dimension_overlap(
    constants: dict[str, int],
    dimensions: dict[str, int],
) -> None:
    duplicate_names = constant_dimension_overlap(constants, dimensions)
    if duplicate_names:
        raise click.ClickException(
            "constants and dimensions must not share names: " + ", ".join(duplicate_names)
        )


def _iter_namelists(config: dict[str, Any], base_dir: Path) -> list[dict[str, Any]]:
    raw_entries = config.get("namelists")
    if raw_entries is None and "nml-files" in config:
        raise click.ClickException("config uses deprecated 'nml-files'; rename to 'namelists'")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise click.ClickException("config must define non-empty 'namelists'")

    entries: list[dict[str, Path | None]] = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            raise click.ClickException("each namelists entry must be a table")
        schema_raw = entry.get("schema")
        if not isinstance(schema_raw, str):
            raise click.ClickException("namelists entry must define string 'schema'")
        schema_path = base_dir / schema_raw
        f2py_path = _resolve_optional_path(
            entry.get("f2py_path"),
            base_dir=base_dir,
            key="f2py_path",
        )
        py_path = _resolve_optional_path(
            entry.get("py_path"),
            base_dir=base_dir,
            key="py_path",
        )
        mod_path = _resolve_optional_path(
            entry.get("mod_path"),
            base_dir=base_dir,
            key="mod_path",
        )
        if f2py_path is not None and mod_path is None:
            raise click.ClickException(
                "namelists entry with 'f2py_path' must define 'mod_path'"
            )
        if py_path is not None and f2py_path is None:
            raise click.ClickException("namelists entry with 'py_path' must define 'f2py_path'")
        entries.append(
            {
                "schema": schema_path,
                "mod_path": mod_path,
                "doc_path": _resolve_optional_path(
                    entry.get("doc_path"),
                    base_dir=base_dir,
                    key="doc_path",
                ),
                "temp_path": _resolve_optional_path(
                    entry.get("temp_path"),
                    base_dir=base_dir,
                    key="temp_path",
                ),
                "f2py_path": f2py_path,
                "py_path": py_path,
            }
        )
    return entries


def _iter_templates(config: dict[str, Any], base_dir: Path) -> list[dict[str, Any]]:
    raw_entries = config.get("templates")
    if raw_entries is None:
        return []
    if not isinstance(raw_entries, list) or not raw_entries:
        raise click.ClickException("config 'templates' must be a non-empty list")

    entries: list[dict[str, Any]] = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            raise click.ClickException("each templates entry must be a table")
        output_raw = entry.get("output")
        if not isinstance(output_raw, str):
            raise click.ClickException("templates entry must define string 'output'")
        output_path = base_dir / output_raw

        schemas_raw = entry.get("schemas")
        if not isinstance(schemas_raw, list) or not schemas_raw:
            raise click.ClickException("templates entry must define non-empty 'schemas'")
        if not all(isinstance(item, str) for item in schemas_raw):
            raise click.ClickException("templates 'schemas' entries must be strings")
        schema_paths = [base_dir / item for item in schemas_raw]

        doc_mode = entry.get("doc_mode", "plain")
        if not isinstance(doc_mode, str):
            raise click.ClickException("templates 'doc_mode' must be a string")
        value_mode = entry.get("value_mode", "empty")
        if not isinstance(value_mode, str):
            raise click.ClickException("templates 'value_mode' must be a string")
        values_raw = entry.get("values", {})
        if values_raw is None:
            values_raw = {}
        if not isinstance(values_raw, dict):
            raise click.ClickException("templates 'values' must be a table")

        entries.append(
            {
                "output": output_path,
                "schemas": schema_paths,
                "doc_mode": doc_mode,
                "value_mode": value_mode,
                "values": values_raw,
            }
        )
    return entries


def _collect_generated_outputs(
    config: dict[str, Any],
    config_path: Path,
) -> list[GeneratedOutput]:
    base_dir = config_path.parent
    logger.debug("Base directory: %s", base_dir)
    helper_path, helper_module, helper_buffer, helper_header = _load_helper_settings(
        config,
        base_dir,
    )
    (
        module_doc,
        md_doxygen_id_from_name,
        md_add_toc_statement,
        py_style,
    ) = _load_documentation_settings(config)
    constants, constant_specs = _load_constants(config)
    dimensions, dimension_specs = _load_dimensions(config, constants)
    kind_module, kind_map, kind_allowlist = _load_kind_settings(config)
    f2cmap_path, f2py_c_types = _load_f2py_settings(config, base_dir)
    resolver = SchemaResolver()
    outputs: list[GeneratedOutput] = []

    entries = _iter_namelists(config, base_dir)
    logger.debug("Found %d schema entries", len(entries))
    loaded_entries: list[dict[str, Any]] = []
    for namelist_entry in entries:
        schema_path = namelist_entry["schema"]
        if schema_path is None:
            raise click.ClickException("namelists entry missing schema path")
        try:
            logger.debug("Loading schema %s", schema_path)
            schema = load_schema(schema_path, resolver=resolver)
        except (FileNotFoundError, ValueError) as exc:
            raise click.ClickException(str(exc)) from exc
        loaded_entries.append({"entry": namelist_entry, "schema": schema})

        mod_path = namelist_entry["mod_path"]
        if mod_path is not None:
            try:
                logger.debug("Rendering Fortran module at %s", mod_path)
                outputs.append(
                    GeneratedOutput(
                        mod_path,
                        render_fortran(
                            schema,
                            file_name=mod_path.name,
                            helper_module=helper_module,
                            kind_module=kind_module,
                            kind_map=kind_map,
                            kind_allowlist=kind_allowlist,
                            constants=constants,
                            dimensions=dimensions,
                            module_doc=module_doc,
                            f2py_handle_helpers=namelist_entry["f2py_path"] is not None,
                        ),
                    )
                )
            except ValueError as exc:
                raise click.ClickException(str(exc)) from exc

        doc_path = namelist_entry["doc_path"]
        if doc_path is not None:
            try:
                logger.debug("Rendering Markdown docs at %s", doc_path)
                outputs.append(
                    GeneratedOutput(
                        doc_path,
                        render_docs(
                            schema,
                            constants=constants,
                            dimensions=dimensions,
                            md_doxygen_id_from_name=md_doxygen_id_from_name,
                            md_add_toc_statement=md_add_toc_statement,
                        ),
                    )
                )
            except ValueError as exc:
                raise click.ClickException(str(exc)) from exc

    try:
        local_derived_types = collect_local_derived_types(
            [loaded["schema"] for loaded in loaded_entries],
            constants=constants,
        )
        if local_derived_types and helper_path is None:
            raise ValueError("locally generated derived types require a configured helper output")
        if helper_path is not None:
            logger.debug("Rendering helper module at %s", helper_path)
            outputs.append(
                GeneratedOutput(
                    helper_path,
                    render_helper(
                        file_name=helper_path.name,
                        module_name=helper_module,
                        len_buf=helper_buffer,
                        constants=constant_specs + dimension_specs,
                        local_derived_types=local_derived_types,
                        kind_module=kind_module,
                        kind_map=kind_map,
                        kind_allowlist=kind_allowlist,
                        module_doc=module_doc,
                        helper_header=helper_header,
                    ),
                )
            )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    outputs.extend(
        _collect_f2py_outputs(
            loaded_entries,
            helper_module=helper_module,
            helper_buffer=helper_buffer,
            kind_module=kind_module,
            kind_map=kind_map,
            kind_allowlist=kind_allowlist,
            constants=constants,
            dimensions=dimensions,
            f2cmap_path=f2cmap_path,
            f2py_c_types=f2py_c_types,
            py_style=py_style,
            include_python=True,
        )
    )

    template_entries = _iter_templates(config, base_dir)
    if template_entries:
        logger.debug("Found %d template entries", len(template_entries))
    for template_entry in template_entries:
        try:
            schemas = []
            for schema_path in template_entry["schemas"]:
                logger.debug("Loading schema %s", schema_path)
                schemas.append(load_schema(schema_path, resolver=resolver))
            logger.debug("Rendering template at %s", template_entry["output"])
            outputs.append(
                GeneratedOutput(
                    template_entry["output"],
                    render_template(
                        schemas,
                        doc_mode=template_entry["doc_mode"],
                        value_mode=template_entry["value_mode"],
                        constants=constants,
                        dimensions=dimensions,
                        kind_map=kind_map,
                        kind_allowlist=kind_allowlist,
                        values=template_entry["values"],
                    ),
                )
            )
        except (FileNotFoundError, ValueError) as exc:
            raise click.ClickException(str(exc)) from exc

    return outputs


def _collect_f2py_outputs(
    loaded_entries: list[dict[str, Any]],
    *,
    helper_module: str,
    helper_buffer: int,
    kind_module: str,
    kind_map: dict[str, str],
    kind_allowlist: set[str],
    constants: dict[str, int],
    dimensions: dict[str, int],
    f2cmap_path: Path | None,
    f2py_c_types: F2pyCTypeMap,
    py_style: str,
    include_python: bool,
) -> list[GeneratedOutput]:
    outputs: list[GeneratedOutput] = []
    f2py_groups: dict[Path, list[dict[str, Any]]] = {}
    py_groups: dict[Path, list[tuple[dict[str, Any], Path]]] = {}
    for loaded in loaded_entries:
        entry = loaded["entry"]
        schema = loaded["schema"]
        f2py_path = entry["f2py_path"]
        if f2py_path is None:
            continue
        f2py_groups.setdefault(f2py_path, []).append(schema)
        py_path = entry["py_path"]
        if include_python and py_path is not None:
            py_groups.setdefault(py_path, []).append((schema, f2py_path))

    for f2py_path, schemas in f2py_groups.items():
        try:
            logger.debug("Rendering f2py wrappers at %s", f2py_path)
            outputs.append(
                GeneratedOutput(
                    f2py_path,
                    render_f2py_wrappers(
                        schemas,
                        file_name=f2py_path.name,
                        helper_module=helper_module,
                        kind_module=kind_module,
                        kind_map=kind_map,
                        kind_allowlist=kind_allowlist,
                        constants=constants,
                        dimensions=dimensions,
                        errmsg_len=helper_buffer,
                    ),
                )
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc

    if f2cmap_path is not None:
        try:
            usage = merge_f2py_kind_usage(
                collect_f2py_kind_usage(schemas, constants=constants, dimensions=dimensions)
                for schemas in f2py_groups.values()
            )
            logger.debug("Rendering f2py kind map at %s", f2cmap_path)
            outputs.append(
                GeneratedOutput(
                    f2cmap_path,
                    render_f2cmap(usage, f2py_c_types),
                )
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc

    if not include_python:
        return outputs
    for py_path, entries in py_groups.items():
        try:
            logger.debug("Rendering Python f2py wrappers at %s", py_path)
            specs = [
                (
                    build_f2py_namelist_spec(
                        schema,
                        helper_module=helper_module,
                        kind_module=kind_module,
                        kind_map=kind_map,
                        kind_allowlist=kind_allowlist,
                        constants=constants,
                        dimensions=dimensions,
                        errmsg_len=helper_buffer,
                    ),
                    f2py_path.stem,
                )
                for schema, f2py_path in entries
            ]
            outputs.append(
                GeneratedOutput(
                    py_path,
                    render_python_wrappers(
                        specs,
                        py_style=py_style,
                    ),
                )
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    return outputs


def _generate_f2py_outputs(
    loaded_entries: list[dict[str, Any]],
    *,
    helper_module: str,
    helper_buffer: int,
    kind_module: str,
    kind_map: dict[str, str],
    kind_allowlist: set[str],
    constants: dict[str, int],
    dimensions: dict[str, int],
    f2cmap_path: Path | None,
    f2py_c_types: F2pyCTypeMap,
    py_style: str,
    include_python: bool,
) -> None:
    _write_generated_outputs(
        _collect_f2py_outputs(
            loaded_entries,
            helper_module=helper_module,
            helper_buffer=helper_buffer,
            kind_module=kind_module,
            kind_map=kind_map,
            kind_allowlist=kind_allowlist,
            constants=constants,
            dimensions=dimensions,
            f2cmap_path=f2cmap_path,
            f2py_c_types=f2py_c_types,
            py_style=py_style,
            include_python=include_python,
        )
    )


def _write_generated_outputs(outputs: list[GeneratedOutput]) -> None:
    for output in outputs:
        logger.info("Writing generated file %s", output.path)
        output.path.parent.mkdir(parents=True, exist_ok=True)
        output.path.write_text(output.content, encoding="ascii")


def _check_generated_outputs(outputs: list[GeneratedOutput], *, show_diff: bool) -> int:
    failed = 0
    for output in outputs:
        if not output.path.exists():
            failed += 1
            click.echo(f"MISSING: {output.path}", err=True)
            continue
        current = output.path.read_text(encoding="ascii")
        if current != output.content:
            failed += 1
            click.echo(f"DIFF: {output.path}", err=True)
            if show_diff:
                diff = unified_diff(
                    current.splitlines(keepends=True),
                    output.content.splitlines(keepends=True),
                    fromfile=f"current {output.path}",
                    tofile=f"generated {output.path}",
                )
                for line in diff:
                    click.echo(line, nl=False)
            continue
        logger.debug("OK: %s", output.path)
    return failed


@click.group(context_settings=_CONTEXT_SETTINGS)
@click.version_option(__version__, "-V", "--version", prog_name="nml-tools")
@click.option("--verbose", "-v", count=True, help="Increase verbosity (repeatable).")
@click.option("--quiet", "-q", count=True, help="Decrease verbosity (repeatable).")
def cli(verbose: int, quiet: int) -> None:
    """nml-tools command line interface."""
    _configure_logging(verbose, quiet)


@cli.command("generate", context_settings=_CONTEXT_SETTINGS)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    show_default="nml-config.toml, then pyproject.toml [tool.nml-tools]",
)
def generate(config_path: Path | None) -> None:
    """Generate outputs from a configuration file."""
    config, config_path = _load_config_checked(config_path)
    logger.info("Loading config from %s", config_path)
    _write_generated_outputs(_collect_generated_outputs(config, config_path))


@cli.command("check", context_settings=_CONTEXT_SETTINGS)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    show_default="nml-config.toml, then pyproject.toml [tool.nml-tools]",
)
@click.option(
    "--diff",
    "show_diff",
    is_flag=True,
    help="Show unified diffs for generated files that differ.",
)
def check(config_path: Path | None, show_diff: bool) -> None:
    """Check that configured generated files are up to date."""
    config, config_path = _load_config_checked(config_path)
    logger.debug("Loading config from %s", config_path)
    failures = _check_generated_outputs(
        _collect_generated_outputs(config, config_path),
        show_diff=show_diff,
    )
    if failures:
        raise click.ClickException(
            f"generated files are out of date: {failures} file(s) differ or are missing"
        )


@cli.command("gen-fortran", context_settings=_CONTEXT_SETTINGS)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    show_default="nml-config.toml, then pyproject.toml [tool.nml-tools]",
)
def gen_fortran(config_path: Path | None) -> None:
    """Generate Fortran module(s)."""
    config, config_path = _load_config_checked(config_path)
    logger.info("Loading config from %s", config_path)
    base_dir = config_path.parent
    logger.debug("Base directory: %s", base_dir)
    helper_path, helper_module, helper_buffer, helper_header = _load_helper_settings(
        config,
        base_dir,
    )
    module_doc, _, _, py_style = _load_documentation_settings(config)
    constants, constant_specs = _load_constants(config)
    dimensions, dimension_specs = _load_dimensions(config, constants)
    kind_module, kind_map, kind_allowlist = _load_kind_settings(config)
    f2cmap_path, f2py_c_types = _load_f2py_settings(config, base_dir)
    resolver = SchemaResolver()
    entries = _iter_namelists(config, base_dir)
    logger.info("Found %d schema entries", len(entries))
    loaded_entries: list[dict[str, Any]] = []
    for entry in entries:
        schema_path = entry["schema"]
        if schema_path is None:
            raise click.ClickException("namelists entry missing schema path")
        try:
            logger.info("Loading schema %s", schema_path)
            schema = load_schema(schema_path, resolver=resolver)
        except (FileNotFoundError, ValueError) as exc:
            raise click.ClickException(str(exc)) from exc
        loaded_entries.append({"entry": entry, "schema": schema})
        mod_path = entry["mod_path"]
        if mod_path is None:
            continue
        try:
            logger.info("Generating Fortran module at %s", mod_path)
            generate_fortran(
                schema,
                mod_path,
                helper_module=helper_module,
                kind_module=kind_module,
                kind_map=kind_map,
                kind_allowlist=kind_allowlist,
                constants=constants,
                dimensions=dimensions,
                module_doc=module_doc,
                f2py_handle_helpers=entry["f2py_path"] is not None,
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc

    try:
        local_derived_types = collect_local_derived_types(
            [loaded["schema"] for loaded in loaded_entries],
            constants=constants,
        )
        if local_derived_types and helper_path is None:
            raise ValueError("locally generated derived types require a configured helper output")
        if helper_path is not None:
            logger.info("Generating helper module at %s", helper_path)
            generate_helper(
                helper_path,
                module_name=helper_module,
                len_buf=helper_buffer,
                constants=constant_specs + dimension_specs,
                local_derived_types=local_derived_types,
                kind_module=kind_module,
                kind_map=kind_map,
                kind_allowlist=kind_allowlist,
                module_doc=module_doc,
                helper_header=helper_header,
            )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    _generate_f2py_outputs(
        loaded_entries,
        helper_module=helper_module,
        helper_buffer=helper_buffer,
        kind_module=kind_module,
        kind_map=kind_map,
        kind_allowlist=kind_allowlist,
        constants=constants,
        dimensions=dimensions,
        f2cmap_path=f2cmap_path,
        f2py_c_types=f2py_c_types,
        py_style=py_style,
        include_python=False,
    )


@cli.command("validate", context_settings=_CONTEXT_SETTINGS)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
)
@click.option(
    "--schema",
    "schema_paths",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
)
@click.option(
    "--input",
    "input_option",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--constants",
    "constant_args",
    metavar="NAME=INT",
    type=_CONSTANT_TYPE,
    multiple=True,
    help="Additional integer constants as NAME=INT (repeatable).",
)
@click.option(
    "--dimensions",
    "dimension_args",
    metavar="NAME=INT",
    type=_DIMENSION_TYPE,
    multiple=True,
    help="Runtime dimensions as NAME=INT (repeatable).",
)
@click.argument(
    "input_path",
    required=False,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def validate(
    config_path: Path | None,
    schema_paths: tuple[Path, ...],
    input_option: Path | None,
    constant_args: tuple[tuple[str, int], ...],
    dimension_args: tuple[tuple[str, int], ...],
    input_path: Path | None,
) -> None:
    """Validate a namelist file against schema definitions."""
    if input_option is not None and input_path is not None:
        raise click.ClickException("input path provided twice")
    input_path = input_option or input_path
    if input_path is None:
        raise click.ClickException("input path is required")
    constants = _parse_cli_constants(constant_args)
    dimension_overrides = _parse_cli_dimensions(dimension_args)
    dimensions: dict[str, int] = {}
    schemas: list[dict[str, Any]] = []
    resolver = SchemaResolver()

    if schema_paths:
        if config_path is not None:
            config, config_path = _load_config_checked(config_path)
            logger.info("Loading config from %s", config_path)
            cfg_constants, _ = _load_constants(config)
            dimensions, _ = _load_dimensions(config, cfg_constants)
            constants = {**cfg_constants, **constants}
            dimensions = {**dimensions, **dimension_overrides}
        else:
            dimensions = dimension_overrides
        for schema_file in schema_paths:
            try:
                logger.info("Loading schema %s", schema_file)
                schemas.append(load_schema(schema_file, resolver=resolver))
            except (FileNotFoundError, ValueError) as exc:
                raise click.ClickException(str(exc)) from exc
        require_all = True
    else:
        config, config_path = _load_config_checked(config_path)
        logger.info("Loading config from %s", config_path)
        base_dir = config_path.parent
        cfg_constants, _ = _load_constants(config)
        dimensions, _ = _load_dimensions(config, cfg_constants)
        constants = {**cfg_constants, **constants}
        dimensions = {**dimensions, **dimension_overrides}
        entries = _iter_namelists(config, base_dir)
        logger.info("Found %d schema entries", len(entries))
        for entry in entries:
            schema_path = entry["schema"]
            if schema_path is None:
                raise click.ClickException("namelists entry missing schema path")
            try:
                logger.info("Loading schema %s", schema_path)
                schemas.append(load_schema(schema_path, resolver=resolver))
            except (FileNotFoundError, ValueError) as exc:
                raise click.ClickException(str(exc)) from exc
        require_all = False

    if not schemas:
        raise click.ClickException("no schemas provided for validation")
    _reject_constant_dimension_overlap(constants, dimensions)

    try:
        logger.info("Reading namelist %s", input_path)
        namelist_file = f90nml.read(input_path)
    except Exception as exc:  # pragma: no cover - f90nml raises custom errors
        raise click.ClickException(f"failed to read namelist: {exc}") from exc

    file_entries: dict[str, tuple[str, Any]] = {}
    for name, values in namelist_file.items():
        if not isinstance(name, str):
            raise click.ClickException("namelist names must be strings")
        key = name.lower()
        if key in file_entries:
            raise click.ClickException(f"namelist '{name}' appears multiple times")
        file_entries[key] = (name, values)

    schema_entries: dict[str, dict[str, Any]] = {}
    for schema in schemas:
        namelist_name = schema.get("x-fortran-namelist")
        if not isinstance(namelist_name, str) or not namelist_name.strip():
            raise click.ClickException("schema must define non-empty 'x-fortran-namelist'")
        key = namelist_name.lower()
        if key in schema_entries:
            raise click.ClickException(f"duplicate schema for namelist '{namelist_name}'")
        schema_entries[key] = schema

    for key, (name, _) in file_entries.items():
        if key not in schema_entries:
            raise click.ClickException(f"input contains unknown namelist '{name}'")

    validated = 0
    for key, schema in schema_entries.items():
        if key not in file_entries:
            if require_all:
                raise click.ClickException(
                    f"input is missing namelist '{schema.get('x-fortran-namelist')}'"
                )
            continue
        try:
            validate_namelist(
                schema,
                file_entries[key][1],
                constants=constants,
                dimensions=dimensions,
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        validated += 1
    logger.info("Validation completed (%d namelist%s).", validated, "" if validated == 1 else "s")


@cli.command("gen-markdown", context_settings=_CONTEXT_SETTINGS)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    show_default="nml-config.toml, then pyproject.toml [tool.nml-tools]",
)
def gen_markdown(config_path: Path | None) -> None:
    """Generate Markdown docs."""
    config, config_path = _load_config_checked(config_path)
    logger.info("Loading config from %s", config_path)
    base_dir = config_path.parent
    constants, _ = _load_constants(config)
    dimensions, _ = _load_dimensions(config, constants)
    _, md_doxygen_id_from_name, md_add_toc_statement, _ = _load_documentation_settings(
        config
    )
    entries = _iter_namelists(config, base_dir)
    resolver = SchemaResolver()
    logger.info("Found %d schema entries", len(entries))
    for entry in entries:
        schema_path = entry["schema"]
        if schema_path is None:
            raise click.ClickException("namelists entry missing schema path")
        try:
            logger.info("Loading schema %s", schema_path)
            schema = load_schema(schema_path, resolver=resolver)
        except (FileNotFoundError, ValueError) as exc:
            raise click.ClickException(str(exc)) from exc
        doc_path = entry["doc_path"]
        if doc_path is None:
            continue
        try:
            logger.info("Generating Markdown docs at %s", doc_path)
            generate_docs(
                schema,
                doc_path,
                constants=constants,
                dimensions=dimensions,
                md_doxygen_id_from_name=md_doxygen_id_from_name,
                md_add_toc_statement=md_add_toc_statement,
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc


@cli.command("gen-template", context_settings=_CONTEXT_SETTINGS)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    show_default="nml-config.toml, then pyproject.toml [tool.nml-tools]",
)
def gen_template(config_path: Path | None) -> None:
    """Generate template namelist(s)."""
    config, config_path = _load_config_checked(config_path)
    logger.info("Loading config from %s", config_path)
    base_dir = config_path.parent
    constants, _ = _load_constants(config)
    dimensions, _ = _load_dimensions(config, constants)
    _, kind_map, kind_allowlist = _load_kind_settings(config)
    templates = _iter_templates(config, base_dir)
    resolver = SchemaResolver()
    if not templates:
        raise click.ClickException("config must define non-empty 'templates'")
    logger.info("Found %d template entries", len(templates))
    for entry in templates:
        try:
            schemas = []
            for schema_path in entry["schemas"]:
                logger.info("Loading schema %s", schema_path)
                schemas.append(load_schema(schema_path, resolver=resolver))
            logger.info("Generating template at %s", entry["output"])
            generate_template(
                schemas,
                entry["output"],
                doc_mode=entry["doc_mode"],
                value_mode=entry["value_mode"],
                constants=constants,
                dimensions=dimensions,
                kind_map=kind_map,
                kind_allowlist=kind_allowlist,
                values=entry["values"],
            )
        except (FileNotFoundError, ValueError) as exc:
            raise click.ClickException(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    """Entry point for the CLI."""
    try:
        cli.main(args=argv, prog_name="nml-tools", standalone_mode=False)
    except Exit as exc:
        return exc.exit_code
    except click.ClickException as exc:
        exc.show()
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
