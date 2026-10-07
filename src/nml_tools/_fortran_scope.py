"""Small declaration inventories for the Fortran scopes emitted by the generators.

This is not a Fortran name resolver: callers register declarations and the host
dependencies that their generated procedures actually need to leave unshadowed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class _Symbol:
    category: str
    identity: tuple[str, ...]
    source: str


class FortranScope:
    """Reject conflicting entities under the same case-insensitive local name."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._symbols: dict[str, _Symbol] = {}

    @property
    def names(self) -> set[str]:
        """Return an independent reservation set for generated-name allocation."""
        return set(self._symbols)

    def declare(self, name: str, *, category: str, identity: tuple[str, ...], source: str) -> None:
        symbol = _Symbol(category, identity, source)
        key = name.lower()
        previous = self._symbols.get(key)
        if previous is not None and (
            previous.category != category or previous.identity != identity
        ):
            raise ValueError(
                f"{source} conflicts with {previous.source} "
                f"in Fortran scope '{self.name}' (local name '{name}')"
            )
        self._symbols[key] = symbol

    def import_symbol(self, symbol: str, module: str, *, category: str = "import") -> None:
        """Register a USE name, optionally written as local => remote."""
        parts = symbol.split("=>", maxsplit=1)
        local = parts[0].strip()
        remote = parts[-1].strip()
        self.declare(
            local,
            category=category,
            identity=("import", module.lower(), remote.lower()),
            source=f"imported symbol '{local}' from '{module}' ({remote})",
        )

    def child(self, name: str, *, names: set[str] | None = None) -> FortranScope:
        """Copy dependencies to a procedure inventory without changing its host."""
        scope = FortranScope(name)
        scope._symbols = {
            key: symbol for key, symbol in self._symbols.items() if names is None or key in names
        }
        return scope
