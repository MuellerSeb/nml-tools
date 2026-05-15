from __future__ import annotations

import pytest

example = pytest.importorskip("nml_pybind_example")


def test_python_set_updates_persistent_fortran_target() -> None:
    example.reset_config()
    cfg = example.get_config()

    cfg.set(iterations=20, tolerance=1.0e-4, weights=2.0, enabled=True)
    cfg.is_valid()

    assert example.get_iterations() == 20
    assert example.get_tolerance() == pytest.approx(1.0e-4)
    assert example.get_weights() == pytest.approx((2.0, 1.0, 1.0))
    assert example.get_enabled() is True


def test_python_set_accepts_lower_rank_arrays_and_none_optionals() -> None:
    example.reset_config()
    cfg = example.get_config()

    cfg.set(iterations=5, tolerance=0.25, weights=[3.0, 4.0], enabled=None)
    cfg.is_valid()

    assert example.get_iterations() == 5
    assert example.get_weights() == pytest.approx((3.0, 4.0, 1.0))
    assert example.get_enabled() is False


def test_invalid_configuration_raises_nml_error() -> None:
    example.reset_config()
    cfg = example.get_config()

    cfg.set(iterations=1, tolerance=-1.0)
    with pytest.raises(example.NmlError):
        cfg.is_valid()


def test_required_python_arguments_reject_none() -> None:
    cfg = example.get_config()

    with pytest.raises(ValueError, match="required argument 'iterations'"):
        cfg.set(iterations=None, tolerance=1.0)
