"""Namelist validation utilities."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, cast

_FORTRAN_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class ScalarConstraints:
    category: str
    length: int | None
    enum_values: tuple[int | str, ...] | None
    enum_trimmed: tuple[str, ...] | None
    min_value: int | float | None
    max_value: int | float | None
    min_exclusive: bool
    max_exclusive: bool


def validate_namelist(
    schema: dict[str, Any],
    namelist: dict[str, Any],
    *,
    constants: dict[str, int | float] | None = None,
) -> None:
    """Validate *namelist* against *schema*."""
    namelist_name = schema.get("x-fortran-namelist")
    if not isinstance(namelist_name, str) or not namelist_name.strip():
        raise ValueError("schema must define non-empty 'x-fortran-namelist'")
    if schema.get("type") != "object":
        raise ValueError(f"schema '{namelist_name}' must be of type 'object'")
    properties_raw = schema.get("properties")
    if not isinstance(properties_raw, dict) or not properties_raw:
        raise ValueError(f"schema '{namelist_name}' must define object 'properties'")

    properties = _normalize_properties(properties_raw, namelist_name)
    required = _parse_required(schema.get("required", []), properties, namelist_name)
    values = _normalize_namelist(namelist, namelist_name)

    for key in values:
        if key not in properties:
            raise ValueError(
                f"namelist '{namelist_name}' has unknown property '{values[key][0]}'"
            )

    for key, (prop_name, prop) in properties.items():
        if key in values:
            _validate_property(
                prop_name,
                prop,
                values[key][1],
                constants=constants,
            )
        elif key in required:
            raise ValueError(f"namelist '{namelist_name}' is missing required '{prop_name}'")


def _normalize_properties(
    properties: Mapping[str, Any],
    namelist_name: str,
) -> dict[str, tuple[str, dict[str, Any]]]:
    normalized: dict[str, tuple[str, dict[str, Any]]] = {}
    for name, prop in properties.items():
        if not isinstance(name, str):
            raise ValueError(f"schema '{namelist_name}' property names must be strings")
        if not isinstance(prop, dict):
            raise ValueError(f"schema '{namelist_name}' property '{name}' must be an object")
        key = name.lower()
        if key in normalized:
            raise ValueError(
                f"schema '{namelist_name}' defines duplicate property '{name}'"
            )
        normalized[key] = (name, prop)
    return normalized


def _parse_required(
    raw: Any,
    properties: Mapping[str, tuple[str, dict[str, Any]]],
    namelist_name: str,
) -> set[str]:
    if raw is None:
        return set()
    if not isinstance(raw, list):
        raise ValueError(f"schema '{namelist_name}' required must be a list")
    required: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            raise ValueError(f"schema '{namelist_name}' required entries must be strings")
        key = item.lower()
        if key not in properties:
            raise ValueError(
                f"schema '{namelist_name}' required entry '{item}' is not a property"
            )
        required.add(key)
    return required


def _normalize_namelist(
    namelist: Mapping[str, Any],
    namelist_name: str,
) -> dict[str, tuple[str, Any]]:
    normalized: dict[str, tuple[str, Any]] = {}
    for name, value in namelist.items():
        if not isinstance(name, str):
            raise ValueError(f"namelist '{namelist_name}' keys must be strings")
        key = name.lower()
        if key in normalized:
            raise ValueError(
                f"namelist '{namelist_name}' defines duplicate key '{name}'"
            )
        normalized[key] = (name, value)
    return normalized


def _validate_property(
    name: str,
    prop: Mapping[str, Any],
    value: Any,
    *,
    constants: dict[str, int | float] | None,
) -> None:
    prop_type = prop.get("type")
    if prop_type == "array":
        _validate_array(name, prop, value, constants)
        return
    if prop_type in {"integer", "number", "boolean", "string"}:
        constraints = _scalar_constraints(name, prop, prop_type, constants)
        _validate_scalar_value(name, value, constraints)
        return
    raise ValueError(f"property '{name}' has unsupported type '{prop_type}'")


def _validate_array(
    name: str,
    prop: Mapping[str, Any],
    value: Any,
    constants: dict[str, int | float] | None,
) -> None:
    items = prop.get("items")
    if not isinstance(items, dict):
        raise ValueError(f"array property '{name}' must define 'items'")
    items_type = items.get("type")
    if items_type == "array":
        raise ValueError(f"array property '{name}' must not nest arrays")
    if items_type not in {"integer", "number", "boolean", "string"}:
        raise ValueError(f"array property '{name}' items must define a scalar type")

    dimensions = _parse_shape(prop.get("x-fortran-shape"), constants, name)
    flex_tail_dims = _parse_flex_tail_dims(prop, len(dimensions), name, dimensions)

    array_value = _coerce_array_value(value, name)
    shape = _nested_shape(array_value, name)
    if len(shape) != len(dimensions):
        raise ValueError(
            f"array '{name}' rank mismatch: expected {len(dimensions)} got {len(shape)}"
        )
    shape_fortran = list(reversed(shape))
    for idx, (provided, expected) in enumerate(zip(shape_fortran, dimensions), start=1):
        if provided <= 0:
            raise ValueError(f"array '{name}' has empty dimension {idx}")
        if expected is None:
            continue
        if flex_tail_dims > 0 and idx <= len(dimensions) - flex_tail_dims:
            if provided != expected:
                raise ValueError(
                    f"array '{name}' dimension {idx} must be {expected}, got {provided}"
                )
        else:
            if provided > expected:
                raise ValueError(
                    f"array '{name}' dimension {idx} must be <= {expected}, got {provided}"
                )

    constraints = _scalar_constraints(name, items, items_type, constants)
    for element in _iter_scalars(array_value):
        _validate_scalar_value(name, element, constraints)


def _scalar_constraints(
    name: str,
    prop: Mapping[str, Any],
    category: str,
    constants: dict[str, int | float] | None,
) -> ScalarConstraints:
    length = None
    if category == "string":
        length = _parse_length(prop, constants, name)
    enum_values, enum_trimmed = _parse_enum(prop, category, length, name)
    min_value, min_exclusive = _extract_bound(prop, "minimum", "exclusiveMinimum", name)
    max_value, max_exclusive = _extract_bound(prop, "maximum", "exclusiveMaximum", name)
    if min_value is not None or max_value is not None:
        if category not in {"integer", "number"}:
            raise ValueError(f"property '{name}' bounds require integer or number")
        _validate_bound_scalar(min_value, category, name, "minimum")
        _validate_bound_scalar(max_value, category, name, "maximum")
        _validate_bound_range(min_value, max_value, min_exclusive, max_exclusive, name)
    return ScalarConstraints(
        category=category,
        length=length,
        enum_values=enum_values,
        enum_trimmed=enum_trimmed,
        min_value=min_value,
        max_value=max_value,
        min_exclusive=min_exclusive,
        max_exclusive=max_exclusive,
    )


def _parse_length(
    prop: Mapping[str, Any],
    constants: dict[str, int | float] | None,
    name: str,
) -> int:
    raw = prop.get("x-fortran-len")
    if isinstance(raw, bool) or raw is None:
        raise ValueError(f"string property '{name}' must define 'x-fortran-len'")
    if isinstance(raw, int):
        if raw <= 0:
            raise ValueError(f"string property '{name}' length must be positive")
        return raw
    if isinstance(raw, str):
        token = raw.strip()
        if not token:
            raise ValueError(f"string property '{name}' length must be non-empty")
        if _is_int_literal(token):
            length = int(token)
            if length <= 0:
                raise ValueError(f"string property '{name}' length must be positive")
            return length
        if not _FORTRAN_IDENTIFIER.match(token):
            raise ValueError(f"string property '{name}' length must be literal or identifier")
        if constants is None or token not in constants:
            raise ValueError(f"string property '{name}' length constant '{token}' not defined")
        value = constants[token]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"string property '{name}' length constant '{token}' must be int")
        if value <= 0:
            raise ValueError(f"string property '{name}' length constant '{token}' must be positive")
        return value
    raise ValueError(f"string property '{name}' must define 'x-fortran-len'")


def _parse_enum(
    prop: Mapping[str, Any],
    category: str,
    length: int | None,
    name: str,
) -> tuple[tuple[int | str, ...] | None, tuple[str, ...] | None]:
    if "enum" not in prop:
        return None, None
    enum_raw = prop.get("enum")
    if not isinstance(enum_raw, list) or not enum_raw:
        raise ValueError(f"property '{name}' enum must be a non-empty list")
    if category == "integer":
        values: list[int] = []
        for item in enum_raw:
            if isinstance(item, bool) or not isinstance(item, int):
                raise ValueError(f"property '{name}' enum values must be integers")
            values.append(item)
        return tuple(values), None
    if category == "string":
        values_str: list[str] = []
        trimmed: list[str] = []
        for item in enum_raw:
            if not isinstance(item, str):
                raise ValueError(f"property '{name}' enum values must be strings")
            if length is not None and len(item) > length:
                raise ValueError(f"property '{name}' enum value '{item}' exceeds length")
            values_str.append(item)
            trimmed.append(item.rstrip())
        return tuple(values_str), tuple(trimmed)
    raise ValueError(f"property '{name}' enum only supports strings or integers")


def _extract_bound(
    prop: Mapping[str, Any],
    inclusive_key: str,
    exclusive_key: str,
    name: str,
) -> tuple[int | float | None, bool]:
    has_inclusive = inclusive_key in prop
    has_exclusive = exclusive_key in prop
    if has_inclusive and has_exclusive:
        raise ValueError(
            f"property '{name}' must not define both '{inclusive_key}' and '{exclusive_key}'"
        )
    if has_exclusive:
        value = prop.get(exclusive_key)
        if value is None:
            raise ValueError(f"property '{name}' {exclusive_key} must be a number")
        return _ensure_number(value, name, exclusive_key), True
    if has_inclusive:
        value = prop.get(inclusive_key)
        if value is None:
            raise ValueError(f"property '{name}' {inclusive_key} must be a number")
        return _ensure_number(value, name, inclusive_key), False
    return None, False


def _ensure_number(value: Any, name: str, label: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"property '{name}' {label} must be a number")
    return cast(int | float, value)


def _validate_bound_scalar(
    value: int | float | None,
    category: str,
    name: str,
    label: str,
) -> None:
    if value is None:
        return
    if category == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"property '{name}' {label} must be an integer")
        return
    if category == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"property '{name}' {label} must be a number")
        if math.isinf(float(value)):
            raise ValueError(f"property '{name}' {label} must not be infinite")
        if math.isnan(float(value)):
            raise ValueError(f"property '{name}' {label} must not be NaN")
        return
    raise ValueError(f"property '{name}' bounds only support integers or numbers")


def _validate_bound_range(
    min_value: int | float | None,
    max_value: int | float | None,
    min_exclusive: bool,
    max_exclusive: bool,
    name: str,
) -> None:
    if min_value is None or max_value is None:
        return
    min_comp = float(min_value)
    max_comp = float(max_value)
    if min_exclusive or max_exclusive:
        if min_comp >= max_comp:
            raise ValueError(f"property '{name}' minimum must be < maximum for exclusive bounds")
    else:
        if min_comp > max_comp:
            raise ValueError(f"property '{name}' minimum must be <= maximum")


def _validate_scalar_value(
    name: str,
    value: Any,
    constraints: ScalarConstraints,
) -> None:
    category = constraints.category
    if category == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"property '{name}' must be an integer")
        if constraints.enum_values is not None and value not in constraints.enum_values:
            raise ValueError(f"property '{name}' has value outside enum")
        _validate_value_bounds(value, constraints, name)
        return
    if category == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"property '{name}' must be a number")
        if math.isnan(float(value)):
            raise ValueError(f"property '{name}' must not be NaN")
        if math.isinf(float(value)):
            raise ValueError(f"property '{name}' must not be infinite")
        _validate_value_bounds(float(value), constraints, name)
        return
    if category == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"property '{name}' must be boolean")
        return
    if category == "string":
        if not isinstance(value, str):
            raise ValueError(f"property '{name}' must be a string")
        if constraints.length is not None and len(value) > constraints.length:
            raise ValueError(f"property '{name}' exceeds length {constraints.length}")
        if constraints.enum_trimmed is not None:
            if value.rstrip() not in constraints.enum_trimmed:
                raise ValueError(f"property '{name}' has value outside enum")
        return
    raise ValueError(f"property '{name}' has unsupported type '{category}'")


def _validate_value_bounds(
    value: int | float,
    constraints: ScalarConstraints,
    name: str,
) -> None:
    if constraints.min_value is not None:
        if constraints.min_exclusive:
            if value <= constraints.min_value:
                raise ValueError(f"property '{name}' must be > {constraints.min_value}")
        else:
            if value < constraints.min_value:
                raise ValueError(f"property '{name}' must be >= {constraints.min_value}")
    if constraints.max_value is not None:
        if constraints.max_exclusive:
            if value >= constraints.max_value:
                raise ValueError(f"property '{name}' must be < {constraints.max_value}")
        else:
            if value > constraints.max_value:
                raise ValueError(f"property '{name}' must be <= {constraints.max_value}")


def _parse_shape(
    raw: Any,
    constants: dict[str, int | float] | None,
    name: str,
) -> list[int | None]:
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"array property '{name}' must define non-empty x-fortran-shape")
    parsed: list[int | None] = []
    for dim in raw:
        if isinstance(dim, bool):
            raise ValueError(f"array property '{name}' shape entries must be int or str")
        if isinstance(dim, int):
            if dim <= 0:
                raise ValueError(f"array property '{name}' shape values must be positive")
            parsed.append(dim)
            continue
        if isinstance(dim, str):
            token = dim.strip()
            if not token:
                raise ValueError(f"array property '{name}' shape entries must be non-empty")
            if token == ":":
                parsed.append(None)
                continue
            if _is_int_literal(token):
                size = int(token)
                if size <= 0:
                    raise ValueError(f"array property '{name}' shape values must be positive")
                parsed.append(size)
                continue
            if not _FORTRAN_IDENTIFIER.match(token):
                raise ValueError(
                    f"array property '{name}' shape entries must be ints or identifiers"
                )
            if constants is None or token not in constants:
                raise ValueError(f"array property '{name}' constant '{token}' not defined")
            value = constants[token]
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"array property '{name}' constant '{token}' must be int")
            if value <= 0:
                raise ValueError(f"array property '{name}' constant '{token}' must be positive")
            parsed.append(value)
            continue
        raise ValueError(f"array property '{name}' shape entries must be int or str")
    return parsed


def _parse_flex_tail_dims(
    prop: Mapping[str, Any],
    rank: int,
    name: str,
    dimensions: Iterable[int | None],
) -> int:
    raw = prop.get("x-fortran-flex-tail-dims")
    if raw is None:
        flex = 0
    else:
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ValueError(f"array property '{name}' flex tail dims must be an integer")
        flex = raw
    if flex < 0:
        raise ValueError(f"array property '{name}' flex tail dims must be >= 0")
    if flex == 0:
        return 0
    if flex > rank:
        raise ValueError(f"array property '{name}' flex tail dims must not exceed rank")
    if any(dim is None for dim in dimensions):
        raise ValueError(f"array property '{name}' flex tail dims require concrete shape")
    return flex


def _coerce_array_value(value: Any, name: str) -> Any:
    if isinstance(value, (list, tuple)):
        return value
    if hasattr(value, "tolist"):
        return value.tolist()
    raise ValueError(f"array property '{name}' must be a list")


def _nested_shape(value: Any, name: str) -> list[int]:
    if isinstance(value, (list, tuple)):
        if not value:
            raise ValueError(f"array property '{name}' must not be empty")
        first_shape: list[int] | None = None
        for item in value:
            item_shape = _nested_shape(item, name)
            if first_shape is None:
                first_shape = item_shape
            elif item_shape != first_shape:
                raise ValueError(f"array property '{name}' must be rectangular")
        return [len(value)] + (first_shape or [])
    return []


def _iter_scalars(value: Any) -> Iterable[Any]:
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_scalars(item)
        return
    yield value


def _is_int_literal(value: str) -> bool:
    try:
        int(value)
    except ValueError:
        return False
    return True
