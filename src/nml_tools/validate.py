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
        _validate_derived_presence_policy(name, prop, name.lower() in required_names)
        _validate_property_defaults(
            name,
            prop,
            constants=constants,
            dimensions=dimensions,
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


def validate_namelist(
    schema: dict[str, Any],
    namelist: dict[str, Any],
    *,
    constants: dict[str, int] | None = None,
    dimensions: dict[str, int] | None = None,
) -> None:
    """Validate *namelist* against *schema*."""
    constants = normalize_constant_values(constants)
    dimensions = normalize_runtime_dimensions(dimensions)
    reject_constant_dimension_overlap(constants, dimensions)
    validate_schema_defaults(schema, constants=constants, dimensions=dimensions)

    namelist_name = schema.get("x-fortran-namelist")
    if not isinstance(namelist_name, str) or not namelist_name.strip():
        raise ValueError("schema must define non-empty 'x-fortran-namelist'")
    validate_user_fortran_identifier(namelist_name, label="'x-fortran-namelist'")
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
                dimensions=dimensions,
            )
        elif key in required:
            raise ValueError(f"namelist '{namelist_name}' is missing required '{prop_name}'")


def _validate_property_defaults(
    name: str,
    prop: Mapping[str, Any],
    *,
    constants: dict[str, int] | None,
    dimensions: dict[str, int] | None,
) -> None:
    if prop.get("type") == "object":
        _validate_derived_declaration(name, prop)
        if "default" in prop:
            raise ValueError(f"derived property '{name}' must not define an object default")
        properties = prop.get("properties")
        if not isinstance(properties, Mapping):
            raise ValueError(f"derived property '{name}' must define object 'properties'")
        for child_name, child in properties.items():
            if isinstance(child_name, str):
                validate_user_fortran_identifier(
                    child_name, label=f"derived property '{name}' component '{child_name}'"
                )
            if not isinstance(child_name, str) or not isinstance(child, Mapping) or child.get(
                "type"
            ) not in {"integer", "number", "boolean", "string"}:
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
        return

    if prop.get("type") != "array":
        if "default" in prop:
            _validate_property(
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
            _validate_property(
                name,
                items,
                value,
                constants=constants,
                dimensions=dimensions,
            )
    elif "default" in items:
        _validate_property(
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
            _validate_property(
                name,
                items,
                value,
                constants=constants,
                dimensions=dimensions,
            )


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
    constants: dict[str, int] | None,
    dimensions: dict[str, int] | None,
) -> None:
    prop_type = prop.get("type")
    if prop_type == "array":
        _validate_array(name, prop, value, constants, dimensions)
        return
    if prop_type == "object":
        _validate_derived_value(name, prop, value, constants, dimensions)
        return
    if prop_type in {"integer", "number", "boolean", "string"}:
        constraints = _scalar_constraints(name, prop, prop_type, constants, dimensions)
        _validate_scalar_value(name, value, constraints)
        return
    raise ValueError(f"property '{name}' has unsupported type '{prop_type}'")


def _validate_array(
    name: str,
    prop: Mapping[str, Any],
    value: Any,
    constants: dict[str, int] | None,
    dimensions: dict[str, int] | None,
) -> None:
    items = prop.get("items")
    if not isinstance(items, dict):
        raise ValueError(f"array property '{name}' must define 'items'")
    items_type = items.get("type")
    if items_type == "array":
        raise ValueError(f"array property '{name}' must not nest arrays")
    if items_type not in {"integer", "number", "boolean", "string", "object"}:
        raise ValueError(f"array property '{name}' items must define a scalar type")

    shape_constants = {**(constants or {}), **(dimensions or {})}
    shape = _parse_shape(prop.get("x-fortran-shape"), shape_constants, name)
    flex_tail_dims = _parse_flex_tail_dims(prop, len(shape), name, shape)
    if items_type == "object" and flex_tail_dims:
        raise ValueError(
            f"derived array property '{name}' must not define x-fortran-flex-tail-dims"
        )

    if items_type == "object" and _is_derived_array_buffer(value):
        _validate_derived_array_buffer(name, items, value, shape, constants, dimensions)
        return

    if items_type != "object" and _is_bare_array_buffer(value, len(shape)):
        constraints = _scalar_constraints(name, items, items_type, constants, dimensions)
        _validate_bare_array_buffer(name, value, shape, constraints)
        return

    array_value = _coerce_array_value(value, name)
    provided_shape = _nested_shape(array_value, name)
    if len(provided_shape) != len(shape):
        raise ValueError(
            f"array '{name}' rank mismatch: expected {len(shape)} got {len(provided_shape)}"
        )
    shape_fortran = list(reversed(provided_shape))
    for idx, (provided, expected) in enumerate(zip(shape_fortran, shape), start=1):
        if provided <= 0:
            raise ValueError(f"array '{name}' has empty dimension {idx}")
        if expected is None:
            continue
        if flex_tail_dims > 0 and idx <= len(shape) - flex_tail_dims:
            if provided != expected:
                raise ValueError(
                    f"array '{name}' dimension {idx} must be {expected}, got {provided}"
                )
        else:
            if provided > expected:
                raise ValueError(
                    f"array '{name}' dimension {idx} must be <= {expected}, got {provided}"
                )

    if items_type == "object":
        for path, element in _iter_object_elements(array_value, name):
            _validate_derived_value(path, items, element, constants, dimensions)
        return

    constraints = _scalar_constraints(name, items, items_type, constants, dimensions)
    for element in _iter_scalars(array_value):
        _validate_scalar_value(name, element, constraints)


def _is_bare_array_buffer(value: Any, rank: int) -> bool:
    if isinstance(value, (list, tuple)):
        return rank > 1 and all(not isinstance(item, (list, tuple)) for item in value)
    if hasattr(value, "tolist"):
        coerced = value.tolist()
        return _is_bare_array_buffer(coerced, rank)
    return True


def _validate_bare_array_buffer(
    name: str,
    value: Any,
    shape: list[int | None],
    constraints: ScalarConstraints,
) -> None:
    if isinstance(value, (list, tuple)):
        buffer_values = list(value)
    elif hasattr(value, "tolist"):
        coerced = value.tolist()
        buffer_values = coerced if isinstance(coerced, list) else [coerced]
    else:
        buffer_values = [value]

    if not buffer_values:
        raise ValueError(f"array property '{name}' must not be empty")
    if len(shape) > 1 and any(dimension is None for dimension in shape):
        raise ValueError(
            f"array '{name}' bare buffer assignment requires concrete shape"
        )
    concrete_shape = [dimension for dimension in shape if dimension is not None]
    if len(concrete_shape) == len(shape):
        total_size = math.prod(concrete_shape)
        if len(buffer_values) > total_size:
            raise ValueError(
                f"array '{name}' buffer is longer than shape: "
                f"{len(buffer_values)} > {total_size}"
            )

    for element in buffer_values:
        _validate_scalar_value(name, element, constraints)


def _validate_derived_presence_policy(
    name: str,
    prop: Mapping[str, Any],
    is_required: bool,
) -> None:
    derived = _derived_object_schema(prop)
    if derived is None or is_required:
        return
    inner_required = derived.get("required", [])
    if isinstance(inner_required, list) and inner_required:
        raise ValueError(
            f"optional derived property '{name}' must not define required inner components"
        )


def _derived_object_schema(prop: Mapping[str, Any]) -> Mapping[str, Any] | None:
    if prop.get("type") == "object":
        return prop
    if prop.get("type") == "array":
        items = prop.get("items")
        if isinstance(items, Mapping) and items.get("type") == "object":
            return items
    return None


def _validate_derived_value(
    name: str,
    prop: Mapping[str, Any],
    value: Any,
    constants: dict[str, int] | None,
    dimensions: dict[str, int] | None,
) -> None:
    properties_raw = prop.get("properties")
    if not isinstance(properties_raw, Mapping) or not properties_raw:
        raise ValueError(f"derived property '{name}' must define object 'properties'")
    properties = _normalize_properties(properties_raw, name)
    required = _parse_required(prop.get("required", []), properties, name)
    if isinstance(value, Mapping):
        supplied = _normalize_namelist(value, name)
        for key, (child_name, _) in supplied.items():
            if key not in properties:
                raise ValueError(f"property '{name}.{child_name}' is unknown")
    else:
        supplied = _normalize_derived_buffer(name, properties, value)

    _validate_derived_supplied(
        name,
        properties,
        required,
        supplied,
        constants=constants,
        dimensions=dimensions,
    )


def _validate_derived_supplied(
    name: str,
    properties: Mapping[str, tuple[str, dict[str, Any]]],
    required: set[str],
    supplied: Mapping[str, tuple[str, Any]],
    *,
    constants: dict[str, int] | None,
    dimensions: dict[str, int] | None,
) -> None:
    for key, (child_name, child) in properties.items():
        child_path = f"{name}.{child_name}"
        if key in supplied:
            _validate_property(
                child_path,
                child,
                supplied[key][1],
                constants=constants,
                dimensions=dimensions,
            )
        elif key in required:
            raise ValueError(f"derived property '{name}' is missing required '{child_path}'")


def _normalize_derived_buffer(
    name: str,
    properties: Mapping[str, tuple[str, dict[str, Any]]],
    value: Any,
) -> dict[str, tuple[str, Any]]:
    values = _coerce_buffer_values(value)
    if not values:
        raise ValueError(f"derived property '{name}' buffer must not be empty")
    if len(values) > len(properties):
        raise ValueError(
            f"derived property '{name}' buffer has too many values: "
            f"{len(values)} > {len(properties)}"
        )
    supplied: dict[str, tuple[str, Any]] = {}
    for (key, (child_name, _)), item in zip(properties.items(), values):
        if item is None:
            continue
        supplied[key] = (child_name, item)
    return supplied


def _is_derived_array_buffer(value: Any) -> bool:
    if isinstance(value, Mapping):
        return False
    if isinstance(value, (list, tuple)):
        return all(not isinstance(item, (Mapping, list, tuple)) for item in value)
    if hasattr(value, "tolist"):
        return _is_derived_array_buffer(value.tolist())
    return True


def _validate_derived_array_buffer(
    name: str,
    items: Mapping[str, Any],
    value: Any,
    shape: list[int | None],
    constants: dict[str, int] | None,
    dimensions: dict[str, int] | None,
) -> None:
    buffer_values = _coerce_buffer_values(value)
    if not buffer_values:
        raise ValueError(f"array property '{name}' must not be empty")
    if len(shape) > 1 and any(dimension is None for dimension in shape):
        raise ValueError(
            f"derived array '{name}' flat buffer assignment requires concrete shape"
        )
    properties_raw = items.get("properties")
    if not isinstance(properties_raw, Mapping) or not properties_raw:
        raise ValueError(
            f"derived array '{name}' items must define non-empty object 'properties'"
        )
    properties = _normalize_properties(properties_raw, name)
    component_count = len(properties)
    concrete_shape = [dimension for dimension in shape if dimension is not None]
    if len(concrete_shape) == len(shape):
        total_size = math.prod(concrete_shape)
        max_values = total_size * component_count
        if len(buffer_values) > max_values:
            raise ValueError(
                f"array '{name}' buffer is longer than shape: "
                f"{len(buffer_values)} > {max_values}"
            )
    required = _parse_required(items.get("required", []), properties, name)
    for offset in range(0, len(buffer_values), component_count):
        element_values = buffer_values[offset : offset + component_count]
        element_index = offset // component_count
        path = _derived_array_element_path(name, element_index, shape)
        supplied = _normalize_derived_buffer(path, properties, element_values)
        _validate_derived_supplied(
            path,
            properties,
            required,
            supplied,
            constants=constants,
            dimensions=dimensions,
        )


def _derived_array_element_path(
    name: str,
    zero_based_index: int,
    shape: list[int | None],
) -> str:
    if len(shape) == 1:
        return f"{name}[{zero_based_index + 1}]"
    remaining = zero_based_index
    indexes: list[int] = []
    for dimension in shape:
        if dimension is None:
            return f"{name}[{zero_based_index + 1}]"
        indexes.append(remaining % dimension + 1)
        remaining //= dimension
    return f"{name}[{','.join(str(index) for index in indexes)}]"


def _coerce_buffer_values(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple)):
        return list(value)
    if hasattr(value, "tolist"):
        coerced = value.tolist()
        return _coerce_buffer_values(coerced)
    return [value]


def _iter_object_elements(
    value: Any,
    name: str,
    indexes: tuple[int, ...] = (),
) -> Iterable[tuple[str, Any]]:
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value, start=1):
            yield from _iter_object_elements(item, name, indexes + (index,))
        return
    suffix = ",".join(str(index) for index in indexes)
    yield f"{name}[{suffix}]", value


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
