"""Array shape, label, and display-order helpers for the GUI."""

from __future__ import annotations

import copy
import math
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, cast


def resolve_shape(
    schema: Mapping[str, Any],
    sizes: Mapping[str, int],
    existing: Any = None,
) -> tuple[int, ...]:
    """Resolve ``x-fortran-shape`` using configured constants and dimensions."""
    raw = schema.get("x-fortran-shape")
    dimensions = raw if isinstance(raw, list) else [raw]
    existing_shape = _list_shape(existing)
    result: list[int] = []
    for axis, dimension in enumerate(dimensions):
        if isinstance(dimension, bool):
            raise ValueError("array shape must not contain booleans")
        if isinstance(dimension, int):
            value = dimension
        elif isinstance(dimension, str):
            token = dimension.strip()
            if token == ":":
                value = existing_shape[axis] if axis < len(existing_shape) else 1
            else:
                try:
                    value = int(token)
                except ValueError as exc:
                    value = sizes.get(token.lower(), 0)
                    if not value:
                        raise ValueError(f"unknown array dimension '{dimension}'") from exc
        else:
            raise ValueError("array property must define 'x-fortran-shape'")
        if value <= 0:
            raise ValueError("array dimensions must be positive")
        result.append(value)
    if not result:
        raise ValueError("array property must define 'x-fortran-shape'")
    return tuple(result)


def flex_tail_dims(schema: Mapping[str, Any], rank: int) -> int:
    """Return the validated number of flexible trailing dimensions."""
    raw = schema.get("x-fortran-flex-tail-dims", 0)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError("'x-fortran-flex-tail-dims' must be an integer")
    if not 0 <= raw <= rank:
        raise ValueError("'x-fortran-flex-tail-dims' must be between zero and the array rank")
    return raw


def array_shape(value: Any) -> tuple[int, ...]:
    """Return the non-empty rectangular shape of a JSON array value."""
    shape = _list_shape(value)
    if not shape:
        raise ValueError("array values must be non-empty and rectangular")
    return shape


def validate_array_shape(
    schema: Mapping[str, Any], sizes: Mapping[str, int], value: Any
) -> tuple[int, ...]:
    """Validate a saved JSON array shape and return its actual shape."""
    actual = array_shape(value)
    declared = resolve_shape(schema, sizes, value)
    if len(actual) != len(declared):
        raise ValueError(f"array rank {len(actual)} does not match declared rank {len(declared)}")
    flexible = flex_tail_dims(schema, len(declared))
    fixed = len(declared) - flexible
    if actual[:fixed] != declared[:fixed]:
        raise ValueError(f"array shape {actual} does not match declared shape {declared}")
    if flexible and any(actual[index] > declared[index] for index in range(fixed, len(declared))):
        raise ValueError(f"array shape {actual} exceeds declared shape {declared}")
    if not flexible and actual != declared:
        raise ValueError(f"array shape {actual} does not match declared shape {declared}")
    return actual


def axis_labels(schema: Mapping[str, Any], axis: int, extent: int) -> list[str] | None:
    """Return labels for a one-based array *axis*, validating their count."""
    metadata = schema.get("x-nml-tools-ui", {})
    if metadata is None:
        return None
    if not isinstance(metadata, Mapping):
        raise ValueError("'x-nml-tools-ui' must be an object")
    axes = metadata.get("axes", {})
    if not isinstance(axes, Mapping):
        raise ValueError("'x-nml-tools-ui.axes' must be an object")
    raw = axes.get(str(axis), axes.get(axis))
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError(f"array UI axis {axis} must be an object")
    title = raw.get("title")
    if title is not None and not isinstance(title, str):
        raise ValueError(f"array UI axis {axis} title must be a string")
    labels = raw.get("labels")
    template = raw.get("label-template")
    if labels is not None and template is not None:
        raise ValueError(f"array UI axis {axis} cannot define labels and label-template")
    if labels is not None:
        if not isinstance(labels, list) or not all(isinstance(item, str) for item in labels):
            raise ValueError(f"array UI axis {axis} labels must be a list of strings")
        if len(labels) != extent:
            raise ValueError(
                f"array UI axis {axis} defines {len(labels)} labels for extent {extent}"
            )
        return list(labels)
    if template is not None:
        if not isinstance(template, str) or not template:
            raise ValueError(f"array UI axis {axis} label-template must be a string")
        try:
            return [template.format(index=index) for index in range(1, extent + 1)]
        except (KeyError, ValueError) as exc:
            raise ValueError(
                f"array UI axis {axis} label-template must use '{{index}}'"
            ) from exc
    return None


def table_axes(schema: Mapping[str, Any], rank: int) -> tuple[int, int] | None:
    """Return zero-based ``(row, column)`` axes for a two-dimensional display."""
    metadata = schema.get("x-nml-tools-ui", {})
    if not isinstance(metadata, Mapping):
        raise ValueError("'x-nml-tools-ui' must be an object")
    table = metadata.get("table")
    if table is None:
        return (0, 1) if rank == 2 else None
    if not isinstance(table, Mapping):
        raise ValueError("'x-nml-tools-ui.table' must be an object")
    row = table.get("row-axis")
    column = table.get("column-axis")
    if isinstance(row, bool) or not isinstance(row, int):
        raise ValueError("array UI table row-axis must be an integer")
    if isinstance(column, bool) or not isinstance(column, int):
        raise ValueError("array UI table column-axis must be an integer")
    if row == column or not 1 <= row <= rank or not 1 <= column <= rank:
        raise ValueError("array UI table axes must be distinct valid one-based axes")
    if rank != 2:
        raise ValueError("array UI table orientation currently requires a rank-two array")
    return row - 1, column - 1


def display_array(value: Any, schema: Mapping[str, Any]) -> Any:
    """Return a NumPy array ordered for the configured table display."""
    import numpy as np

    data = np.asarray(value)
    if data.ndim == 1:
        return data.reshape((1, data.shape[0]))
    axes = table_axes(schema, data.ndim)
    if axes is not None and axes != (0, 1):
        return np.transpose(data, axes)
    return data


def canonical_array(value: Any, schema: Mapping[str, Any], rank: int) -> list[Any]:
    """Convert a displayed NumPy array back to canonical Fortran-axis JSON order."""
    import numpy as np

    data = np.asarray(value)
    if rank == 1:
        data = data.reshape((-1,))
    else:
        axes = table_axes(schema, rank)
        if axes is not None and axes != (0, 1):
            data = np.transpose(data, np.argsort(axes))
    return cast(list[Any], _json_value(data.tolist()))


def initial_array(
    schema: Mapping[str, Any],
    sizes: Mapping[str, int],
    value: Any,
    leaf_default: Any,
    *,
    strict: bool = False,
) -> list[Any]:
    """Fit a saved/default/example value to the resolved canonical shape."""
    shape = resolve_shape(schema, sizes, value)
    result = cast(list[Any], _filled(shape, leaf_default))
    if value is None:
        return result
    if not isinstance(value, list):
        if strict:
            raise ValueError("saved array values must be JSON arrays")
        return cast(list[Any], _filled(shape, value))
    current_shape = _list_shape(value)
    if strict:
        validate_array_shape(schema, sizes, value)
        return copy.deepcopy(value)
    if current_shape and flex_tail_dims(schema, len(shape)):
        try:
            validate_array_shape(schema, sizes, value)
        except ValueError:
            pass
        else:
            return copy.deepcopy(value)
    if current_shape == shape:
        return copy.deepcopy(value)

    flat = list(_flatten(value))
    if not flat:
        return result
    if len(shape) > 1 and len(flat) == shape[0]:
        return _broadcast_first_axis(flat, shape)
    if len(flat) == math.prod(shape):
        return _reshape(flat, shape)
    return _reshape([flat[index % len(flat)] for index in range(math.prod(shape))], shape)


def _broadcast_first_axis(values: list[Any], shape: tuple[int, ...]) -> list[Any]:
    tail = shape[1:]
    return [_filled(tail, value) for value in values]


def _filled(shape: Sequence[int], value: Any) -> Any:
    if not shape:
        return copy.deepcopy(value)
    return [_filled(shape[1:], value) for _ in range(shape[0])]


def _reshape(values: Sequence[Any], shape: tuple[int, ...]) -> list[Any]:
    iterator = iter(values)

    def build(remaining: tuple[int, ...]) -> Any:
        if len(remaining) == 1:
            return [copy.deepcopy(next(iterator)) for _ in range(remaining[0])]
        return [build(remaining[1:]) for _ in range(remaining[0])]

    return cast(list[Any], build(shape))


def _flatten(value: Any) -> Iterator[Any]:
    if isinstance(value, list):
        for child in value:
            yield from _flatten(child)
    else:
        yield value


def _list_shape(value: Any) -> tuple[int, ...]:
    if not isinstance(value, list) or not value:
        return ()
    first = _list_shape(value[0])
    if any(_list_shape(item) != first for item in value[1:]):
        return ()
    return (len(value), *first)


def _json_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value.item() if hasattr(value, "item") else value
