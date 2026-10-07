"""Case-insensitive ownership, rather than growing ad-hoc reserved lists."""

import pytest

from nml_tools._fortran_scope import FortranScope


def test_repeated_import_is_the_same_entity() -> None:
    scope = FortranScope("helper")
    scope.import_symbol("I4 => int32", "iso_fortran_env")
    scope.import_symbol("i4 => INT32", "ISO_FORTRAN_ENV")
    assert scope.names == {"i4"}
    reservation = scope.names
    reservation.add("other")
    assert scope.names == {"i4"}


@pytest.mark.parametrize("module, remote", [("other", "int32"), ("kinds", "int64")])
def test_same_local_name_requires_same_module_and_remote(module: str, remote: str) -> None:
    scope = FortranScope("native")
    scope.import_symbol("i4 => int32", "kinds")
    with pytest.raises(ValueError, match="conflicts.*kinds.*scope 'native'"):
        scope.import_symbol(f"I4 => {remote}", module)


def test_local_categories_and_child_scopes() -> None:
    scope = FortranScope("helper")
    scope.declare("period", category="type", identity=("schema", "period"), source="schema type")
    scope.declare("PERIOD", category="type", identity=("schema", "period"), source="reused type")
    child = scope.child("setter")
    with pytest.raises(ValueError, match="dummy conflicts with reused type.*scope 'setter'"):
        child.declare("period", category="dummy", identity=("dummy",), source="dummy")
    assert scope.names == {"period"}
    assert scope.child("unrelated", names=set()).names == set()
