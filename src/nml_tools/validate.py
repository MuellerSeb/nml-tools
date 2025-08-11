"""Namelist validation utilities."""

from __future__ import annotations

from typing import Any


def validate_namelist(schema: dict[str, Any], namelist: dict[str, Any]) -> None:
    """Validate *namelist* against *schema*."""
    raise NotImplementedError
