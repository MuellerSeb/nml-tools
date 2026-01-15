"""Command line interface for nml-tools."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import click
from click.exceptions import Exit

from .codegen_fortran import generate_fortran, generate_helper
from .codegen_markdown import generate_docs
from .schema import load_schema

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - python<3.11
    import tomli as tomllib

logger = logging.getLogger(__name__)


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


def _load_helper_settings(config: dict[str, Any], base_dir: Path) -> tuple[Path | None, str]:
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
    return helper_path, helper_module


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


def _iter_nml_files(config: dict[str, Any], base_dir: Path) -> list[dict[str, Path | None]]:
    raw_entries = config.get("nml-files")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise click.ClickException("config must define non-empty 'nml-files'")

    entries: list[dict[str, Path | None]] = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            raise click.ClickException("each nml-files entry must be a table")
        schema_raw = entry.get("schema")
        if not isinstance(schema_raw, str):
            raise click.ClickException("nml-files entry must define string 'schema'")
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
    helper_path, helper_module = _load_helper_settings(config, base_dir)
    kind_module, kind_map, kind_allowlist = _load_kind_settings(config)
    if helper_path is not None:
        try:
            logger.info("Generating helper module at %s", helper_path)
            generate_helper(helper_path, module_name=helper_module)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    entries = _iter_nml_files(config, base_dir)
    logger.info("Found %d schema entries", len(entries))
    for entry in entries:
        schema_path = entry["schema"]
        if schema_path is None:
            raise click.ClickException("nml-files entry missing schema path")
        try:
            logger.info("Loading schema %s", schema_path)
            schema = load_schema(schema_path)
        except (FileNotFoundError, ValueError) as exc:
            raise click.ClickException(str(exc)) from exc
        mod_path = entry["mod_path"]
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
                )
            except ValueError as exc:
                raise click.ClickException(str(exc)) from exc
        doc_path = entry["doc_path"]
        if doc_path is not None:
            try:
                logger.info("Generating Markdown docs at %s", doc_path)
                generate_docs(schema, doc_path)
            except ValueError as exc:
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
    entries = _iter_nml_files(config, base_dir)
    logger.info("Found %d schema entries", len(entries))
    for entry in entries:
        schema_path = entry["schema"]
        if schema_path is None:
            raise click.ClickException("nml-files entry missing schema path")
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
            generate_docs(schema, doc_path)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc


@cli.command("gen-template")
def gen_template() -> None:
    """Generate template namelist(s)."""
    click.echo("TODO")


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
