"""Python wrappers for f2py generated namelist modules."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from . import f2py_config

NML_OK = 0
NML_ERR_NOT_SET = 12


class NmlError(RuntimeError):
    """Error returned by a generated namelist wrapper.

    Parameters
    ----------
    status : int
        nml-tools status code.
    errmsg : str, optional
        Error message returned by the wrapper.
    """

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


def _normalize_array(
    value: Any,
    rank: int,
    name: str,
    dtype: Any = None,
    expected_shape: tuple[int, ...] | None = None,
) -> np.ndarray:
    array = np.asarray(value, dtype=dtype)
    if expected_shape is not None:
        if len(expected_shape) != rank:
            raise ValueError(
                f"array '{name}' has invalid wrapper metadata: "
                f"shape rank {len(expected_shape)}, expected {rank}"
            )
        if array.ndim == 0:
            return np.asfortranarray(
                np.full(expected_shape, array.item(), dtype=dtype)
            )
        if array.ndim > rank:
            raise ValueError(f"array '{name}' has rank {array.ndim}, expected {rank}")
        if array.shape != expected_shape:
            raise ValueError(
                f"array '{name}' has shape {array.shape}, expected {expected_shape}"
            )
        return np.asfortranarray(array)
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


def _validate_derived_members(
    value: Mapping[Any, Any],
    path: str,
    members: set[str],
) -> None:
    if any(not isinstance(member, str) for member in value):
        raise ValueError(f"{path} has non-string member names")
    unknown = set(value) - members
    if unknown:
        raise ValueError(f"{path} has unknown members: " + ", ".join(sorted(unknown)))


def _derived_array(
    value: Any,
    name: str,
    rank: int,
    members: set[str],
) -> np.ndarray:
    array = np.asarray(value, dtype=object)
    if array.ndim == 0:
        raise ValueError(f"derived array argument '{name}' must be a sequence of mappings")
    if array.ndim > rank:
        raise ValueError(
            f"derived array argument '{name}' has rank {array.ndim}, expected at most {rank}"
        )
    for index in np.ndindex(array.shape):
        item = array[index]
        path = "".join(f"[{part + 1}]" for part in index)
        if not isinstance(item, Mapping):
            raise ValueError(f"derived array argument '{name}'{path} must be a mapping")
        _validate_derived_members(item, f"derived array argument '{name}'{path}", members)
    return array


def _derived_member_array(
    array: np.ndarray,
    member: str,
    dummy: Any,
) -> tuple[np.ndarray, np.ndarray]:
    values = np.empty(array.shape, dtype=object)
    present = np.empty(array.shape, dtype=bool)
    for index in np.ndindex(array.shape):
        item = array[index]
        values[index] = item.get(member, dummy)
        present[index] = member in item
    return values, present


class Run:
    """Python handle for the run namelist.

    Derived-type configuration

    Parameters
    ----------
    handle : int
        Opaque handle to a Fortran namelist instance.
    """

    _f2py = f2py_config.f2py_run

    def __init__(self, handle: int) -> None:
        self.handle = int(handle)

    def invalidate(self) -> None:
        """Clear this wrapper's stored Fortran handle.

        This does not deallocate or notify the Fortran owner. It only prevents
        this Python wrapper from accidentally reusing a handle that the owning
        Fortran library has made invalid.
        """
        self.handle = 0

    def from_file(self, file: str) -> None:
        """Read the run namelist from a file.

        Parameters
        ----------
        file : str
            Namelist file path.

        Raises
        ------
        NmlError
            If reading the file fails.
        """
        result = self._f2py.run_from_file_wrapper(
            self.handle,
            str(file),
        )
        _check_status(result)

    def set_dims(
        self,
        n_periods: Any = None,
    ) -> None:
        """Set runtime dimensions for the handled run instance.

        Omitted or None values reset the corresponding dimension to the configured
        helper-module default. Applying dimensions deallocates affected arrays
        and clears previously configured namelist values.

        Parameters
        ----------
        n_periods : int, optional
            Runtime dimension override for n_periods.

        Raises
        ------
        NmlError
            If the Fortran setter returns a non-OK status.
        """
        kwargs: dict[str, Any] = {}
        if n_periods is not None:
            kwargs["n_periods"] = n_periods
        else:
            kwargs["n_periods"] = 0
        kwargs["has__n_periods"] = n_periods is not None
        result = self._f2py.run_set_dims_wrapper(
            self.handle,
            **kwargs,
        )
        _check_status(result)

    def set(
        self,
        period: Any,
        periods: Any,
        station: Any,
    ) -> None:
        """Set run values.

        Parameters
        ----------
        period : mapping
            Main simulation period.
        periods : sequence of mappings
            Comparison periods.
        station : mapping
            Selected station.

        Raises
        ------
        ValueError
            If a required argument is None or an array shape/rank is invalid.
        NmlError
            If the Fortran setter returns a non-OK status.
        """
        if period is None:
            raise ValueError("required argument 'period' must not be None")
        if periods is None:
            raise ValueError("required argument 'periods' must not be None")
        if station is None:
            raise ValueError("required argument 'station' must not be None")
        kwargs: dict[str, Any] = {}
        if period is not None:
            if not isinstance(period, Mapping):
                raise ValueError("derived argument 'period' must be a mapping")
            _validate_derived_members(period, "derived argument 'period'", {
                "start_year",
                "end_year",
                "label",
            })
            kwargs["period__start_year"] = period.get("start_year", 0)
            kwargs["has__period__start_year"] = "start_year" in period
            kwargs["period__end_year"] = period.get("end_year", 0)
            kwargs["has__period__end_year"] = "end_year" in period
            kwargs["period__label"] = period.get("label", "")
            kwargs["has__period__label"] = "label" in period
        else:
            kwargs["period__start_year"] = 0
            kwargs["has__period__start_year"] = False
            kwargs["period__end_year"] = 0
            kwargs["has__period__end_year"] = False
            kwargs["period__label"] = ""
            kwargs["has__period__label"] = False
        if periods is not None:
            periods_array = _derived_array(
                periods,
                "periods",
                1,
                {
                    "start_year",
                    "end_year",
                    "label",
                },
            )
            periods__start_year_values, periods__start_year_present = _derived_member_array(
                periods_array,
                "start_year",
                0,
            )
            kwargs["periods__start_year"] = _normalize_array(
                periods__start_year_values,
                1,
                "periods.start_year",
                dtype="int",
            )
            kwargs["has__periods__start_year"] = _normalize_array(
                periods__start_year_present,
                1,
                "periods.start_year presence",
                dtype="bool",
            )
            periods__end_year_values, periods__end_year_present = _derived_member_array(
                periods_array,
                "end_year",
                0,
            )
            kwargs["periods__end_year"] = _normalize_array(
                periods__end_year_values,
                1,
                "periods.end_year",
                dtype="int",
            )
            kwargs["has__periods__end_year"] = _normalize_array(
                periods__end_year_present,
                1,
                "periods.end_year presence",
                dtype="bool",
            )
            periods__label_values, periods__label_present = _derived_member_array(
                periods_array,
                "label",
                "",
            )
            kwargs["periods__label"] = _normalize_array(
                periods__label_values,
                1,
                "periods.label",
                dtype="str",
            )
            kwargs["has__periods__label"] = _normalize_array(
                periods__label_present,
                1,
                "periods.label presence",
                dtype="bool",
            )
        else:
            kwargs["periods__start_year"] = _dummy_array(
                1,
                dtype="int",
            )
            kwargs["has__periods__start_year"] = _dummy_array(1, dtype="bool")
            kwargs["periods__end_year"] = _dummy_array(
                1,
                dtype="int",
            )
            kwargs["has__periods__end_year"] = _dummy_array(1, dtype="bool")
            kwargs["periods__label"] = _dummy_array(
                1,
                dtype="str",
            )
            kwargs["has__periods__label"] = _dummy_array(1, dtype="bool")
        if station is not None:
            if not isinstance(station, Mapping):
                raise ValueError("derived argument 'station' must be a mapping")
            _validate_derived_members(station, "derived argument 'station'", {
                "code",
                "label",
            })
            kwargs["station__code"] = station.get("code", 0)
            kwargs["has__station__code"] = "code" in station
            kwargs["station__label"] = station.get("label", "")
            kwargs["has__station__label"] = "label" in station
        else:
            kwargs["station__code"] = 0
            kwargs["has__station__code"] = False
            kwargs["station__label"] = ""
            kwargs["has__station__label"] = False
        result = self._f2py.run_set_wrapper(
            self.handle,
            **kwargs,
        )
        _check_status(result)

    def is_set(self, name: str, idx: Any = None) -> bool:
        """Check whether a field is set.

        Parameters
        ----------
        name : str
            Field name.
        idx : int or array_like, optional
            Optional field index.

        Returns
        -------
        bool
            True if the field is set, otherwise False.

        Raises
        ------
        ValueError
            If idx is not scalar or rank-1.
        NmlError
            If the field name or index is invalid.
        """
        kwargs: dict[str, Any] = {}
        if idx is not None:
            idx_array = np.asarray(idx, dtype=int)
            if idx_array.ndim == 0:
                idx_array = idx_array.reshape((1,))
            elif idx_array.ndim != 1:
                raise ValueError("idx must be a scalar or rank-1 array")
            kwargs["idx"] = np.asfortranarray(idx_array)
            kwargs["has__idx"] = True
        else:
            kwargs["idx"] = np.asfortranarray(np.zeros((1,), dtype=int))
            kwargs["has__idx"] = False
        result = self._f2py.run_is_set_wrapper(
            self.handle,
            name.replace(".", "%"),
            **kwargs,
        )
        status, errmsg = _split_result(result)
        if status == NML_OK:
            return True
        if status == NML_ERR_NOT_SET:
            return False
        raise NmlError(status, errmsg)

    def is_valid(self) -> None:
        """Validate the handled run instance.

        Raises
        ------
        NmlError
            If validation fails.
        """
        result = self._f2py.run_is_valid_wrapper(
            self.handle,
        )
        _check_status(result)
