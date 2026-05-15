"""Python wrappers for f2py generated namelist modules."""

from __future__ import annotations

from typing import Any

import numpy as np

from . import f2py_config

NML_OK = 0
NML_ERR_NOT_SET = 12


class NmlError(RuntimeError):
    """Error returned by a generated namelist wrapper."""

    def __init__(self, status: int, errmsg: Any = "") -> None:
        self.status = int(status)
        self.errmsg = _clean_errmsg(errmsg)
        super().__init__(f"nml-tools status {self.status}: {self.errmsg}")


def _clean_errmsg(errmsg: Any) -> str:
    if errmsg is None:
        return ""
    if isinstance(errmsg, bytes):
        return errmsg.decode(errors="replace").replace("\x00", "").strip()
    if hasattr(errmsg, "tobytes"):
        try:
            raw = errmsg.tobytes()
        except Exception:
            raw = None
        if isinstance(raw, bytes):
            return raw.decode(errors="replace").replace("\x00", "").strip()
    return str(errmsg).replace("\x00", "").strip()


def _split_result(result: Any) -> tuple[int, str]:
    if isinstance(result, tuple):
        if len(result) < 2:
            raise RuntimeError("f2py wrapper did not return status and errmsg")
        status = result[-2]
        errmsg = result[-1]
    else:
        status = result
        errmsg = ""
    return int(status), _clean_errmsg(errmsg)


def _check_status(result: Any) -> None:
    status, errmsg = _split_result(result)
    if status != NML_OK:
        raise NmlError(status, errmsg)


def _normalize_array(value: Any, rank: int, name: str, dtype: Any = None) -> np.ndarray:
    array = np.asarray(value, dtype=dtype)
    if array.ndim == 0:
        target_shape = (1,) * rank
    elif array.ndim <= rank:
        target_shape = array.shape + (1,) * (rank - array.ndim)
    else:
        raise ValueError(f"array '{name}' has rank {array.ndim}, expected at most {rank}")
    return np.asfortranarray(array.reshape(target_shape, order="F"))


def _dummy_array(rank: int, dtype: Any = None) -> np.ndarray:
    target_shape = (1,) * rank
    return np.asfortranarray(np.zeros(target_shape, dtype=dtype))


class Config:
    """Python handle for the config namelist."""

    _f2py = f2py_config.f2py_config

    def __init__(self, handle: int) -> None:
        self.handle = int(handle)

    def from_file(self, file: str) -> None:
        result = self._f2py.config_from_file_wrapper(
            self.handle,
            str(file),
        )
        _check_status(result)

    def set(
        self,
        iterations: Any,
        tolerance: Any,
        name: Any = None,
        enabled: Any = None,
        weights: Any = None,
    ) -> None:
        if iterations is None:
            raise ValueError("required argument 'iterations' must not be None")
        if tolerance is None:
            raise ValueError("required argument 'tolerance' must not be None")
        kwargs: dict[str, Any] = {}
        if iterations is not None:
            kwargs["iterations"] = iterations
        else:
            kwargs["iterations"] = 0
        if tolerance is not None:
            kwargs["tolerance"] = tolerance
        else:
            kwargs["tolerance"] = 0.0
        if name is not None:
            kwargs["name"] = name
        else:
            kwargs["name"] = ""
        kwargs["has_name"] = name is not None
        if enabled is not None:
            kwargs["enabled"] = enabled
        else:
            kwargs["enabled"] = False
        kwargs["has_enabled"] = enabled is not None
        if weights is not None:
            kwargs["weights"] = _normalize_array(
                weights,
                1,
                "weights",
                dtype="float",
            )
        else:
            kwargs["weights"] = _dummy_array(
                1,
                dtype="float",
            )
        kwargs["has_weights"] = weights is not None
        result = self._f2py.config_set_wrapper(
            self.handle,
            **kwargs,
        )
        _check_status(result)

    def is_set(self, name: str, idx: Any = None) -> bool:
        kwargs: dict[str, Any] = {}
        if idx is not None:
            idx_array = np.asarray(idx, dtype=int)
            if idx_array.ndim == 0:
                idx_array = idx_array.reshape((1,))
            elif idx_array.ndim != 1:
                raise ValueError("idx must be a scalar or rank-1 array")
            kwargs["idx"] = np.asfortranarray(idx_array)
            kwargs["has_idx"] = True
        else:
            kwargs["idx"] = np.asfortranarray(np.zeros((1,), dtype=int))
            kwargs["has_idx"] = False
        result = self._f2py.config_is_set_wrapper(
            self.handle,
            name,
            **kwargs,
        )
        status, errmsg = _split_result(result)
        if status == NML_OK:
            return True
        if status == NML_ERR_NOT_SET:
            return False
        raise NmlError(status, errmsg)

    def is_valid(self) -> None:
        result = self._f2py.config_is_valid_wrapper(
            self.handle,
        )
        _check_status(result)


