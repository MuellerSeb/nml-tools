"""Namelist validation utilities."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from ._utils import (
    FORTRAN_IDENTIFIER,
    normalize_constant_values,
    normalize_runtime_dimensions,
    reject_constant_dimension_overlap,
    validate_user_fortran_identifier,
)
from .schema import _is_intrinsic_scalar_schema


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


@dataclass(frozen=True)
class PropertyRequirement:
    """Schema-time requiredness and operational-default coverage for a property."""

    declared_required: bool
    required_defaults_complete: bool
    fully_default_initialized: bool
    requires_input: bool
    uncovered_required_components: frozenset[str]


def validate_schema_defaults(
    schema: Mapping[str, Any],
    *,
    constants: dict[str, int] | None = None,
    dimensions: dict[str, int] | None = None,
) -> None:
    """Validate operational defaults against each property's constraints."""
    if _has_reachable_reference(schema, position="root"):
        raise ValueError(
            "schema contains unresolved '$ref'; use load_schema() or resolve_schema() "
            "before validation or generation"
        )
    constants = normalize_constant_values(constants)
    dimensions = normalize_runtime_dimensions(dimensions)
    reject_constant_dimension_overlap(constants, dimensions)
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return
    required_names = {
        name.lower()
        for name in schema.get("required", [])
        if isinstance(name, str)
    }
    for name, prop in properties.items():
        if not isinstance(name, str) or not isinstance(prop, Mapping):
            continue
        _validate_property_defaults(
            name,
            prop,
            constants=constants,
            dimensions=dimensions,
        )
        analyze_property_requirement(
            name,
            prop,
            declared_required=name.lower() in required_names,
        )


def _has_reachable_reference(raw: Mapping[str, Any], *, position: str) -> bool:
    if "$ref" in raw:
        return True
    if position == "root":
        properties = raw.get("properties")
        if isinstance(properties, Mapping):
            for prop in properties.values():
                if isinstance(prop, Mapping) and _has_reachable_reference(
                    prop, position="property"
                ):
                    return True
    items = raw.get("items")
    return isinstance(items, Mapping) and _has_reachable_reference(items, position="items")


def _validate_property_defaults(
    name: str,
    prop: Mapping[str, Any],
    *,
    constants: dict[str, int] | None,
    dimensions: dict[str, int] | None,
) -> None:
    if prop.get("type") == "object":
        _validate_derived_declaration(name, prop)
        properties = prop.get("properties")
        if not isinstance(properties, Mapping):
            raise ValueError(f"derived property '{name}' must define object 'properties'")
        for child_name, child in properties.items():
            if isinstance(child_name, str):
                validate_user_fortran_identifier(
                    child_name, label=f"derived property '{name}' component '{child_name}'"
                )
            if not isinstance(child_name, str) or not _is_intrinsic_scalar_schema(child):
                raise ValueError(
                    f"derived property '{name}' component '{child_name}' "
                    "must define an intrinsic scalar type"
                )
            _validate_property_defaults(
                f"{name}.{child_name}",
                child,
                constants=constants,
                dimensions=dimensions,
            )
        _validate_derived_object_default(
            name,
            prop,
            constants=constants,
            dimensions=dimensions,
        )
        return

    if prop.get("type") != "array":
        if "default" in prop:
            _validate_scalar_default(
                name,
                prop,
                prop["default"],
                constants=constants,
                dimensions=dimensions,
            )
        return

    controls = {
        "x-fortran-default-order",
        "x-fortran-default-repeat",
        "x-fortran-default-pad",
    }
    if controls.intersection(prop) and "default" not in prop:
        raise ValueError(f"array property '{name}' default options require an array default")
    items = prop.get("items")
    if not isinstance(items, Mapping):
        if "default" in prop:
            raise ValueError(f"array property '{name}' with a default must define object 'items'")
        return
    if items.get("type") == "object":
        if "default" in prop or controls.intersection(prop):
            raise ValueError(f"derived array property '{name}' must not define defaults")
        if "x-fortran-flex-tail-dims" in prop:
            raise ValueError(
                f"derived array property '{name}' must not define x-fortran-flex-tail-dims"
            )
        _validate_property_defaults(
            f"{name}[]",
            items,
            constants=constants,
            dimensions=dimensions,
        )
        return
    if "default" in prop and "default" in items:
        raise ValueError(
            f"array property '{name}' default must be defined on property or items, not both"
        )
    has_default = "default" in prop or "default" in items
    if has_default:
        shape_constants = {**(constants or {}), **(dimensions or {})}
        shape = _parse_shape(prop.get("x-fortran-shape"), shape_constants, name)
        if _parse_flex_tail_dims(prop, len(shape), name, shape) > 0:
            raise ValueError(f"array property '{name}' flex arrays cannot define defaults")

    if "default" in prop:
        default = prop["default"]
        if not isinstance(default, list):
            raise ValueError(f"array default must be a list for property '{name}'")
        _validate_array_default_layout(name, prop, default, constants, dimensions)
        for value in _iter_scalars(default):
            _validate_scalar_default(
                name,
                items,
                value,
                constants=constants,
                dimensions=dimensions,
            )
    elif "default" in items:
        _validate_scalar_default(
            name,
            items,
            items["default"],
            constants=constants,
            dimensions=dimensions,
        )

    if "x-fortran-default-pad" in prop:
        pad = prop["x-fortran-default-pad"]
        pad_values = pad if isinstance(pad, list) else [pad]
        for value in _iter_scalars(pad_values):
            _validate_scalar_default(
                name,
                items,
                value,
                constants=constants,
                dimensions=dimensions,
            )


def _validate_scalar_default(
    name: str,
    prop: Mapping[str, Any],
    value: Any,
    *,
    constants: dict[str, int] | None,
    dimensions: dict[str, int] | None,
) -> None:
    category = prop.get("type")
    if category not in {"integer", "number", "boolean", "string"}:
        raise ValueError(f"property '{name}' has unsupported type '{category}'")
    constraints = _scalar_constraints(name, prop, category, constants, dimensions)
    _validate_scalar_value(name, value, constraints)


def _validate_derived_declaration(name: str, prop: Mapping[str, Any]) -> None:
    type_name = prop.get("x-fortran-type")
    if not isinstance(type_name, str) or not type_name.strip():
        raise ValueError(f"derived property '{name}' must define non-empty 'x-fortran-type'")
    try:
        validate_user_fortran_identifier(
            type_name.strip(), label=f"derived property '{name}' x-fortran-type"
        )
    except ValueError as exc:
        raise ValueError(str(exc).replace("Fortran identifier", "identifier")) from exc
    module_name = prop.get("x-fortran-module")
    if module_name is not None and (
        not isinstance(module_name, str) or not module_name.strip()
    ):
        raise ValueError(
            f"derived property '{name}' x-fortran-module must be a valid identifier"
        )
    if isinstance(module_name, str):
        try:
            validate_user_fortran_identifier(
                module_name.strip(), label=f"derived property '{name}' x-fortran-module"
            )
        except ValueError as exc:
            raise ValueError(str(exc).replace("Fortran identifier", "identifier")) from exc


def _validate_array_default_layout(
    name: str,
    prop: Mapping[str, Any],
    default: list[Any],
    constants: dict[str, int] | None,
    dimensions: dict[str, int] | None,
) -> None:
    if any(isinstance(value, list) for value in default):
        raise ValueError(f"array property '{name}' default must be a flat list")
    if not default:
        raise ValueError(f"array property '{name}' default must contain at least one value")
    shape_constants = {**(constants or {}), **(dimensions or {})}
    shape = _parse_shape(prop.get("x-fortran-shape"), shape_constants, name)
    if any(dimension is None for dimension in shape):
        raise ValueError(
            f"array property '{name}' defaults do not support deferred-size dimensions"
        )
    total_size = math.prod(dimension for dimension in shape if dimension is not None)
    if len(default) > total_size:
        raise ValueError(f"array property '{name}' default is longer than its shape")
    order = prop.get("x-fortran-default-order", "F")
    if not isinstance(order, str) or order.upper() not in {"F", "C"}:
        raise ValueError(f"array property '{name}' default order must be 'F' or 'C'")
    repeat = prop.get("x-fortran-default-repeat", False)
    if not isinstance(repeat, bool):
        raise ValueError(f"array property '{name}' default repeat must be boolean")
    pad = prop.get("x-fortran-default-pad")
    if pad is not None and repeat:
        raise ValueError(f"array property '{name}' default cannot set both pad and repeat")
    if isinstance(pad, list) and not pad:
        raise ValueError(f"array property '{name}' default pad must not be empty")
    if len(default) < total_size and pad is None and not repeat:
        raise ValueError(
            "array default shorter than declared x-fortran-shape without pad or repeat"
        )


def _normalize_properties(
    properties: Mapping[str, Any],
    namelist_name: str,
) -> dict[str, tuple[str, dict[str, Any]]]:
    normalized: dict[str, tuple[str, dict[str, Any]]] = {}
    for name, prop in properties.items():
        if not isinstance(name, str):
            raise ValueError(f"schema '{namelist_name}' property names must be strings")
        validate_user_fortran_identifier(
            name, label=f"schema '{namelist_name}' property '{name}'"
        )
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


def analyze_property_requirement(
    name: str,
    prop: Mapping[str, Any],
    *,
    declared_required: bool,
) -> PropertyRequirement:
    """Return operational-default coverage and effective input requiredness."""
    derived = _derived_object_schema(prop)
    if derived is None:
        has_default = _intrinsic_property_has_default(prop)
        return PropertyRequirement(
            declared_required=declared_required,
            required_defaults_complete=has_default,
            fully_default_initialized=has_default,
            requires_input=declared_required and not has_default,
            uncovered_required_components=frozenset(),
        )

    components = _normalized_derived_components(name, derived)
    required = _normalized_derived_required(name, derived, components)
    object_default = _normalized_derived_default_mapping(name, derived, components)
    defaulted = {
        key
        for key, (_, child) in components.items()
        if "default" in child or key in object_default
    }
    uncovered = frozenset(required - defaulted)
    required_defaults_complete = not uncovered
    if not declared_required and uncovered:
        missing = ", ".join(components[key][0] for key in sorted(uncovered))
        raise ValueError(
            f"optional derived property '{name}' has required components without defaults: "
            f"{missing}; declare the outer property required or provide effective defaults"
        )
    return PropertyRequirement(
        declared_required=declared_required,
        required_defaults_complete=required_defaults_complete,
        fully_default_initialized=len(defaulted) == len(components),
        requires_input=declared_required and not required_defaults_complete,
        uncovered_required_components=uncovered,
    )


def derived_component_defaults(name: str, prop: Mapping[str, Any]) -> dict[str, Any]:
    """Return effective derived component defaults keyed by lowercase component name."""
    derived = _derived_object_schema(prop)
    if derived is None:
        return {}
    components = _normalized_derived_components(name, derived)
    object_default = _normalized_derived_default_mapping(name, derived, components)
    defaults: dict[str, Any] = {}
    for key, (_, child) in components.items():
        if "default" in child:
            defaults[key] = child["default"]
        if key in object_default:
            defaults[key] = object_default[key]
    return defaults


def derived_object_default(name: str, prop: Mapping[str, Any]) -> dict[str, Any]:
    """Return the selected object/item default keyed by lowercase component name."""
    derived = _derived_object_schema(prop)
    if derived is None:
        return {}
    components = _normalized_derived_components(name, derived)
    return _normalized_derived_default_mapping(name, derived, components)


def _intrinsic_property_has_default(prop: Mapping[str, Any]) -> bool:
    if prop.get("type") != "array":
        return "default" in prop
    if "default" in prop:
        return True
    items = prop.get("items")
    return isinstance(items, Mapping) and "default" in items


def _normalized_derived_components(
    name: str,
    derived: Mapping[str, Any],
) -> dict[str, tuple[str, Mapping[str, Any]]]:
    raw = derived.get("properties")
    if not isinstance(raw, Mapping) or not raw:
        raise ValueError(f"derived property '{name}' must define object 'properties'")
    components: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for child_name, child in raw.items():
        if not isinstance(child_name, str) or not isinstance(child, Mapping):
            raise ValueError(f"derived property '{name}' has an invalid component declaration")
        key = child_name.lower()
        if key in components:
            previous = components[key][0]
            raise ValueError(
                f"derived property '{name}' defines duplicate component '{child_name}' "
                f"matching '{previous}' case-insensitively"
            )
        components[key] = (child_name, child)
    return components


def _normalized_derived_required(
    name: str,
    derived: Mapping[str, Any],
    components: Mapping[str, tuple[str, Mapping[str, Any]]],
) -> set[str]:
    raw = derived.get("required", [])
    if raw is None:
        return set()
    if not isinstance(raw, list):
        raise ValueError(f"derived property '{name}' required must be a list")
    required: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            raise ValueError(f"derived property '{name}' required entries must be strings")
        key = item.lower()
        if key not in components:
            raise ValueError(
                f"derived property '{name}' required component '{item}' is not declared"
            )
        required.add(key)
    return required


def _normalized_derived_default_mapping(
    name: str,
    derived: Mapping[str, Any],
    components: Mapping[str, tuple[str, Mapping[str, Any]]],
) -> dict[str, Any]:
    if "default" not in derived:
        return {}
    raw = derived["default"]
    if not isinstance(raw, Mapping):
        raise ValueError(f"derived property '{name}' object default must be a mapping")
    normalized: dict[str, Any] = {}
    spelling: dict[str, str] = {}
    for child_name, value in raw.items():
        if not isinstance(child_name, str):
            raise ValueError(f"derived property '{name}' object default keys must be strings")
        key = child_name.lower()
        if key in normalized:
            raise ValueError(
                f"derived property '{name}' object default defines duplicate component "
                f"'{child_name}' matching '{spelling[key]}' case-insensitively"
            )
        if key not in components:
            raise ValueError(
                f"derived property '{name}' object default has unknown component '{child_name}'"
            )
        normalized[key] = value
        spelling[key] = child_name
    return normalized


def _validate_derived_object_default(
    name: str,
    derived: Mapping[str, Any],
    *,
    constants: dict[str, int] | None,
    dimensions: dict[str, int] | None,
) -> dict[str, Any]:
    components = _normalized_derived_components(name, derived)
    normalized = _normalized_derived_default_mapping(name, derived, components)
    for key, value in normalized.items():
        child_name, child = components[key]
        _validate_scalar_default(
            f"{name}.{child_name}",
            child,
            value,
            constants=constants,
            dimensions=dimensions,
        )
    return normalized


def _derived_object_schema(prop: Mapping[str, Any]) -> Mapping[str, Any] | None:
    if prop.get("type") == "object":
        return prop
    if prop.get("type") == "array":
        items = prop.get("items")
        if isinstance(items, Mapping) and items.get("type") == "object":
            return items
    return None


def _scalar_constraints(
    name: str,
    prop: Mapping[str, Any],
    category: str,
    constants: dict[str, int] | None,
    dimensions: dict[str, int] | None,
) -> ScalarConstraints:
    length = None
    if category == "string":
        length = _parse_length(prop, constants, dimensions, name)
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
    constants: dict[str, int] | None,
    dimensions: dict[str, int] | None,
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
        if not FORTRAN_IDENTIFIER.match(token):
            raise ValueError(f"string property '{name}' length must be literal or identifier")
        token_key = token.lower()
        if dimensions is not None and token_key in dimensions:
            raise ValueError(
                f"string property '{name}' length must not use runtime dimension '{token}'"
            )
        if constants is None or token_key not in constants:
            raise ValueError(f"string property '{name}' length constant '{token}' not defined")
        value = constants[token_key]
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


def _ensure_number(value: object, name: str, label: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"property '{name}' {label} must be a number")
    return value


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
    constants: dict[str, int] | None,
    name: str,
) -> list[int | None]:
    shape_entries: list[Any]
    if isinstance(raw, bool) or raw is None:
        raise ValueError(f"array property '{name}' must define non-empty x-fortran-shape")
    if isinstance(raw, (int, str)):
        shape_entries = [raw]
    elif isinstance(raw, list) and raw:
        shape_entries = raw
    else:
        raise ValueError(f"array property '{name}' must define non-empty x-fortran-shape")

    parsed: list[int | None] = []
    for dim in shape_entries:
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
            if not FORTRAN_IDENTIFIER.match(token):
                raise ValueError(
                    f"array property '{name}' shape entries must be ints or identifiers"
                )
            token_key = token.lower()
            if constants is None or token_key not in constants:
                raise ValueError(f"array property '{name}' constant '{token}' not defined")
            value = constants[token_key]
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
