"""Internal shared helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping

FORTRAN_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
RESERVED_IDENTIFIER_SEPARATOR = "__"
RESERVED_NAMELIST_IDENTIFIERS = frozenset({"errmsg"})
GENERATED_INTRINSIC_IDENTIFIERS = frozenset(
    {
        "achar",
        "all",
        "allocated",
        "any",
        "associated",
        "char",
        "huge",
        "iachar",
        "ichar",
        "index",
        "len",
        "len_trim",
        "minval",
        "present",
        "reshape",
        "shape",
        "size",
        "trim",
    }
)
GENERATED_HELPER_IDENTIFIERS = frozenset(
    {
        "nml_close",
        "nml_file_t",
        "nml_find",
        "nml_line_buffer",
        "nml_open",
        "nml_ok",
        "nml_err_file_not_found",
        "nml_err_open",
        "nml_err_not_open",
        "nml_err_nml_not_found",
        "nml_err_read",
        "nml_err_close",
        "nml_err_required",
        "nml_err_enum",
        "nml_err_not_set",
        "nml_err_partly_set",
        "nml_err_bounds",
        "nml_err_invalid_name",
        "nml_err_invalid_index",
        "nml_err_invalid_handle",
    }
)


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


def validate_namelist_identifier(name: str, *, label: str) -> None:
    """Validate an identifier used for a namelist property or runtime dimension."""
    validate_user_fortran_identifier(name, label=label)
    validate_generated_fortran_identifier(name, label=label)


def validate_derived_component_identifier(name: str, *, label: str) -> None:
    """Validate a qualified component identifier without reserving direct intrinsics."""
    validate_user_fortran_identifier(name, label=label)
    if name.lower() in RESERVED_NAMELIST_IDENTIFIERS:
        raise ValueError(f"{label} is reserved for the generated Fortran API")


def validate_generated_fortran_identifier(name: str, *, label: str) -> None:
    """Reject names that shadow generated Fortran dependencies."""
    canonical_name = name.lower()
    if canonical_name in RESERVED_NAMELIST_IDENTIFIERS:
        raise ValueError(f"{label} is reserved for the generated Fortran API")
    if canonical_name in GENERATED_INTRINSIC_IDENTIFIERS:
        raise ValueError(f"{label} is reserved as a Fortran intrinsic used by generated code")
    if canonical_name in GENERATED_HELPER_IDENTIFIERS:
        raise ValueError(f"{label} is reserved by the generated helper API")


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
        validate_generated_fortran_identifier(name, label=f"constant '{name}'")
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
        validate_namelist_identifier(name, label=f"runtime dimension '{name}'")
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
