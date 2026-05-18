"""Small package demonstrating nml-tools f2py handle wrappers."""

from __future__ import annotations

from . import f2py_config as _f2py_config
from .config_wrappers import Config, NmlError, _check_status

__all__ = [
    "Config",
    "NmlError",
    "get_config",
    "get_enabled",
    "get_iterations",
    "get_tolerance",
    "get_weights",
    "print_config",
    "reset_config",
]


def get_config() -> Config:
    """Return a Python wrapper for the persistent Fortran config target."""
    return Config(_f2py_config.f2py_config_store.config_get_handle_wrapper())


def reset_config() -> None:
    """Reset the persistent Fortran config target to defaults and sentinels."""
    _check_status(_f2py_config.f2py_config_store.config_reset_wrapper())


def get_iterations() -> int:
    """Return the configured iteration count from Fortran."""
    return int(_f2py_config.f2py_config_store.config_get_iterations_wrapper())


def get_tolerance() -> float:
    """Return the configured tolerance from Fortran."""
    return float(_f2py_config.f2py_config_store.config_get_tolerance_wrapper())


def get_weights() -> tuple[float, float, float]:
    """Return the configured weights from Fortran."""
    return tuple(
        float(_f2py_config.f2py_config_store.config_get_weight_wrapper(idx))
        for idx in range(1, 4)
    )


def get_enabled() -> bool:
    """Return the configured enabled flag from Fortran."""
    return bool(_f2py_config.f2py_config_store.config_get_enabled_wrapper())


def print_config() -> None:
    """Print the persistent Fortran config target from Fortran."""
    _f2py_config.f2py_config_store.config_print_wrapper()
