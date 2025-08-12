"""Command line interface for nml-tools."""

from __future__ import annotations

import argparse
from typing import Callable

Handler = Callable[[argparse.Namespace], int]


def _handle_todo(_args: argparse.Namespace) -> int:
    """Print a TODO placeholder."""
    print("TODO")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the CLI."""
    parser = argparse.ArgumentParser(prog="nml-tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ["validate", "gen-fortran", "gen-docs", "gen-template"]:
        sub = subparsers.add_parser(name)
        sub.set_defaults(func=_handle_todo)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    handler: Handler = args.func
    return handler(args)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
