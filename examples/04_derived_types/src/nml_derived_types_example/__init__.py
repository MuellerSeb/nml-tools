"""Buildable demonstration of nml-tools derived-type wrappers."""

from __future__ import annotations

from . import f2py_config as _f2py_config
from .config_wrappers import NmlError, Run, _check_status

__all__ = [
    "NmlError",
    "Run",
    "get_config",
    "get_period_item_starts",
    "get_period_start",
    "get_station_code",
    "get_station_label",
    "reset_config",
]


def get_config() -> Run:
    """Return a wrapper for the persistent derived-type configuration."""
    return Run(_f2py_config.f2py_config_store.run_get_handle_wrapper())


def reset_config() -> None:
    """Reset the persistent target to generated defaults and sentinels."""
    _check_status(_f2py_config.f2py_config_store.run_reset_wrapper())


def get_period_start() -> int:
    """Return the top-level period start year."""
    return int(_f2py_config.f2py_config_store.run_get_period_start_wrapper())


def get_period_item_starts() -> tuple[int, int]:
    """Return the two configured period-array start years."""
    return tuple(
        int(_f2py_config.f2py_config_store.run_get_period_item_start_wrapper(index))
        for index in (1, 2)
    )  # type: ignore[return-value]


def get_station_code() -> int:
    """Return the imported station type's code component."""
    return int(_f2py_config.f2py_config_store.run_get_station_code_wrapper())


def get_station_label() -> str:
    """Return the canonical mapped portion of the imported label."""
    value = _f2py_config.f2py_config_store.run_get_station_label_wrapper()
    if isinstance(value, bytes):
        return value.decode("utf-8").rstrip()
    return str(value).rstrip()
