"""Command line interface for nml-tools."""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Any

import click
from click.exceptions import Exit

from .codegen_fortran import ConstantSpec, generate_fortran, generate_helper
from .codegen_markdown import generate_docs
from .codegen_template import generate_template
from .schema import load_schema

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - python<3.11
    import tomli as tomllib

logger = logging.getLogger(__name__)
_FORTRAN_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _configure_logging(verbose: int, quiet: int) -> None:
    base_level = logging.INFO
    level = base_level - (10 * verbose) + (10 * quiet)
    level = max(logging.DEBUG, min(logging.CRITICAL, level))
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def _load_config(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    if not isinstance(data, dict):
        raise click.ClickException("config must be a table")
    return data


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
    if not isinstance(integer_raw, list) or not all(
        isinstance(item, str) for item in integer_raw
    ):
        raise click.ClickException("config 'kinds.integer' must be a list of strings")
    allowlist = set(real_raw) | set(integer_raw)

    return module, kind_map, allowlist


def _format_constant_literal(value: int | float) -> tuple[str, str]:
    if isinstance(value, bool):
        raise click.ClickException("config constants must not be boolean")
    if isinstance(value, int):
        return "integer", str(value)
    if isinstance(value, float):
        literal = repr(float(value))
        if literal.lower() == "nan":
            raise click.ClickException("config constants must not be NaN")
        if "." not in literal and "e" not in literal and "E" not in literal:
            literal = f"{literal}.0"
        return "real", literal
    raise click.ClickException("config constants must be integers or reals")


def _load_constants(config: dict[str, Any]) -> tuple[dict[str, int | float], list[ConstantSpec]]:
    constants_raw = config.get("constants", {})
    if constants_raw is None:
        constants_raw = {}
    if not isinstance(constants_raw, dict):
        raise click.ClickException("config 'constants' must be a table")

    constants: dict[str, int | float] = {}
    specs: list[ConstantSpec] = []
    for name_raw, entry in constants_raw.items():
        if not isinstance(name_raw, str):
            raise click.ClickException("config constants must use string keys")
        name = name_raw.strip()
        if not name:
            raise click.ClickException("config constants must have non-empty names")
        if not _FORTRAN_IDENTIFIER.match(name):
            raise click.ClickException(
                f"config constant '{name}' must be a valid Fortran identifier"
            )
        if not isinstance(entry, dict):
            raise click.ClickException(
                f"config constant '{name}' must be a table with 'value'"
            )
        if "value" not in entry:
            raise click.ClickException(f"config constant '{name}' must define 'value'")
        value = entry.get("value")
        if not isinstance(value, (int, float)):
            raise click.ClickException("config constants must be integers or reals")
        type_spec, literal = _format_constant_literal(value)
        doc = entry.get("doc")
        if doc is not None:
            if not isinstance(doc, str):
                raise click.ClickException(
                    f"config constant '{name}' doc must be a string"
                )
            doc = " ".join(doc.splitlines()).strip() or None
        specs.append(
            ConstantSpec(
                name=name,
                type_spec=type_spec,
                value=literal,
                doc=doc,
            )
        )
        constants[name] = value
    return constants, specs


def _load_documentation(config: dict[str, Any]) -> str | None:
    doc_raw = config.get("documentation")
    if doc_raw is None:
        return None
    if not isinstance(doc_raw, dict):
        raise click.ClickException("config 'documentation' must be a table")
    module_raw = doc_raw.get("module")
    if not isinstance(module_raw, str):
        raise click.ClickException("config 'documentation.module' must be a string")
    module_doc = module_raw.strip()
    return module_doc or None


def _iter_namelists(config: dict[str, Any], base_dir: Path) -> list[dict[str, Path | None]]:
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
        entries.append(
            {
                "schema": schema_path,
                "mod_path": _resolve_optional_path(
                    entry.get("mod_path"),
                    base_dir=base_dir,
                    key="mod_path",
                ),
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


@click.group()
@click.option("--verbose", "-v", count=True, help="Increase verbosity (repeatable).")
@click.option("--quiet", "-q", count=True, help="Decrease verbosity (repeatable).")
def cli(verbose: int, quiet: int) -> None:
    """nml-tools command line interface."""
    _configure_logging(verbose, quiet)


@cli.command("generate")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default="nml-config.toml",
    show_default=True,
)
def generate(config_path: Path) -> None:
    """Generate outputs from a configuration file."""
    logger.info("Loading config from %s", config_path)
    config = _load_config(config_path)
    base_dir = config_path.parent
    logger.debug("Base directory: %s", base_dir)
    helper_path, helper_module, helper_buffer, helper_header = _load_helper_settings(
        config,
        base_dir,
    )
    module_doc = _load_documentation(config)
    constants, constant_specs = _load_constants(config)
    kind_module, kind_map, kind_allowlist = _load_kind_settings(config)
    if helper_path is not None:
        try:
            logger.info("Generating helper module at %s", helper_path)
            generate_helper(
                helper_path,
                module_name=helper_module,
                len_buf=helper_buffer,
                constants=constant_specs,
                module_doc=module_doc,
                helper_header=helper_header,
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    entries = _iter_namelists(config, base_dir)
    logger.info("Found %d schema entries", len(entries))
    for namelist_entry in entries:
        schema_path = namelist_entry["schema"]
        if schema_path is None:
            raise click.ClickException("namelists entry missing schema path")
        try:
            logger.info("Loading schema %s", schema_path)
            schema = load_schema(schema_path)
        except (FileNotFoundError, ValueError) as exc:
            raise click.ClickException(str(exc)) from exc
        mod_path = namelist_entry["mod_path"]
        if mod_path is not None:
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
                    module_doc=module_doc,
                )
            except ValueError as exc:
                raise click.ClickException(str(exc)) from exc
        doc_path = namelist_entry["doc_path"]
        if doc_path is not None:
            try:
                logger.info("Generating Markdown docs at %s", doc_path)
                generate_docs(schema, doc_path, constants=constants)
            except ValueError as exc:
                raise click.ClickException(str(exc)) from exc

    template_entries = _iter_templates(config, base_dir)
    if template_entries:
        logger.info("Found %d template entries", len(template_entries))
    for template_entry in template_entries:
        try:
            schemas = []
            for schema_path in template_entry["schemas"]:
                logger.info("Loading schema %s", schema_path)
                schemas.append(load_schema(schema_path))
            logger.info("Generating template at %s", template_entry["output"])
            generate_template(
                schemas,
                template_entry["output"],
                doc_mode=template_entry["doc_mode"],
                value_mode=template_entry["value_mode"],
                constants=constants,
                kind_map=kind_map,
                kind_allowlist=kind_allowlist,
                values=template_entry["values"],
            )
        except (FileNotFoundError, ValueError) as exc:
            raise click.ClickException(str(exc)) from exc


@cli.command("gen-fortran")
def gen_fortran() -> None:
    """Generate Fortran module(s)."""
    click.echo("TODO")


@cli.command("gen-markdown")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default="nml-config.toml",
    show_default=True,
)
def gen_markdown(config_path: Path) -> None:
    """Generate Markdown docs."""
    logger.info("Loading config from %s", config_path)
    config = _load_config(config_path)
    base_dir = config_path.parent
    constants, _ = _load_constants(config)
    entries = _iter_namelists(config, base_dir)
    logger.info("Found %d schema entries", len(entries))
    for entry in entries:
        schema_path = entry["schema"]
        if schema_path is None:
            raise click.ClickException("namelists entry missing schema path")
        try:
            logger.info("Loading schema %s", schema_path)
            schema = load_schema(schema_path)
        except (FileNotFoundError, ValueError) as exc:
            raise click.ClickException(str(exc)) from exc
        doc_path = entry["doc_path"]
        if doc_path is None:
            continue
        try:
            logger.info("Generating Markdown docs at %s", doc_path)
            generate_docs(schema, doc_path, constants=constants)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc


@cli.command("gen-template")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default="nml-config.toml",
    show_default=True,
)
def gen_template(config_path: Path) -> None:
    """Generate template namelist(s)."""
    logger.info("Loading config from %s", config_path)
    config = _load_config(config_path)
    base_dir = config_path.parent
    constants, _ = _load_constants(config)
    _, kind_map, kind_allowlist = _load_kind_settings(config)
    templates = _iter_templates(config, base_dir)
    if not templates:
        raise click.ClickException("config must define non-empty 'templates'")
    logger.info("Found %d template entries", len(templates))
    for entry in templates:
        try:
            schemas = []
            for schema_path in entry["schemas"]:
                logger.info("Loading schema %s", schema_path)
                schemas.append(load_schema(schema_path))
            logger.info("Generating template at %s", entry["output"])
            generate_template(
                schemas,
                entry["output"],
                doc_mode=entry["doc_mode"],
                value_mode=entry["value_mode"],
                constants=constants,
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
