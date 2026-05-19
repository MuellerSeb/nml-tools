"""Internal shared helpers."""

from __future__ import annotations


def strip_trailing_whitespace(text: str) -> str:
    """Strip trailing horizontal whitespace from each line while preserving final newline."""
    cleaned = "\n".join(line.rstrip() for line in text.splitlines())
    if text.endswith("\n"):
        cleaned += "\n"
    return cleaned
