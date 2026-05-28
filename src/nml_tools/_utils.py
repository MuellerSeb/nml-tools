"""Internal shared helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping

FORTRAN_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
RESERVED_IDENTIFIER_SEPARATOR = "__"


def is_fortran_identifier(name: str) -> bool:
    """Return whether *name* is a valid Fortran identifier."""
    return FORTRAN_IDENTIFIER.match(name) is not None


def validate_user_fortran_identifier(name: str, *, label: str) -> None:
    """Validate a user-controlled Fortran identifier.

    nml-tools reserves double underscores for generated support identifiers.
    """
    if not is_fortran_identifier(name):
        raise ValueError(f"{label} must be a valid Fortran identifier")
    if RESERVED_IDENTIFIER_SEPARATOR in name:
        raise ValueError(f"{label} must not contain '{RESERVED_IDENTIFIER_SEPARATOR}'")


def strip_trailing_whitespace(text: str) -> str:
    """Strip trailing horizontal whitespace from each line while preserving final newline."""
    cleaned = "\n".join(line.rstrip() for line in text.splitlines())
    if text.endswith("\n"):
        cleaned += "\n"
    return cleaned


def normalize_constant_values(
    constants: Mapping[str, object] | None,
) -> dict[str, int]:
    """Validate and normalize static integer constants by lowercase name."""
    if constants is None:
        return {}
    normalized: dict[str, int] = {}
    for name, value in constants.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("constant names must be non-empty strings")
        validate_user_fortran_identifier(name, label=f"constant '{name}'")
        canonical_name = name.lower()
        if canonical_name in normalized:
            raise ValueError(f"constant '{name}' duplicates another constant name")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"constant '{name}' must be an integer")
        normalized[canonical_name] = value
    return normalized


def normalize_runtime_dimensions(
    dimensions: Mapping[str, object] | None,
) -> dict[str, int]:
    """Validate and normalize runtime dimensions by lowercase name."""
    if dimensions is None:
        return {}
    normalized: dict[str, int] = {}
    for name, value in dimensions.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("runtime dimension names must be non-empty strings")
        validate_user_fortran_identifier(name, label=f"runtime dimension '{name}'")
        canonical_name = name.lower()
        if canonical_name in normalized:
            raise ValueError(f"runtime dimension '{name}' duplicates another dimension name")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"runtime dimension '{name}' must be an integer")
        if value <= 0:
            raise ValueError(f"runtime dimension '{name}' must be positive")
        normalized[canonical_name] = value
    return normalized


def constant_dimension_overlap(
    constants: Mapping[str, object],
    dimensions: Mapping[str, object],
) -> list[str]:
    """Return lowercase names present in both constants and dimensions."""
    return sorted({name.lower() for name in constants} & {name.lower() for name in dimensions})


def reject_constant_dimension_overlap(
    constants: Mapping[str, object],
    dimensions: Mapping[str, object],
) -> None:
    """Raise when constants and runtime dimensions share names."""
    overlap = constant_dimension_overlap(constants, dimensions)
    if overlap:
        raise ValueError("constants and dimensions must not share names: " + ", ".join(overlap))
