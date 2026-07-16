"""Schema-aware evaluation of the private namelist parser IR."""

from __future__ import annotations

import itertools
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, NoReturn

from ._namelist_parser import (
    Assignment,
    DecimalMode,
    Designator,
    NamelistError,
    NullValue,
    ParsedFile,
    ParsedGroup,
    RawValue,
    RepeatedValue,
    ScalarSelector,
    SourceSpan,
)
from ._utils import (
    normalize_constant_values,
    normalize_runtime_dimensions,
    reject_constant_dimension_overlap,
    validate_user_fortran_identifier,
)
from .validate import (
    _normalize_properties,
    _parse_flex_tail_dims,
    _parse_required,
    _parse_shape,
    _scalar_constraints,
    _validate_scalar_value,
    validate_schema_defaults,
)


class NamelistEvaluationError(NamelistError):
    category = "evaluation"


class NamelistCapabilityError(NamelistEvaluationError):
    category = "unsupported capability"


class NamelistBoundsError(NamelistEvaluationError):
    category = "bounds"


class NamelistConversionError(NamelistEvaluationError):
    category = "conversion"


class NamelistConstraintError(NamelistEvaluationError):
    category = "constraint"


@dataclass(frozen=True)
class LeafState:
    """Final state of one scalar effective item."""

    path: str
    coordinates: tuple[int, ...]
    value: Any
    has_value: bool
    initialized_by_default: bool
    explicitly_assigned: bool
    null_consumed: bool
    source_span: SourceSpan | None


@dataclass(frozen=True)
class EvaluatedGroup:
    name: str
    states: Mapping[tuple[str, tuple[int, ...], str | None], LeafState]


@dataclass(frozen=True)
class _Property:
    name: str
    key: str
    schema: Mapping[str, Any]
    value_schema: Mapping[str, Any]
    shape: tuple[int | None, ...]
    flex_tail_dims: int
    components: Mapping[str, tuple[str, Mapping[str, Any]]]
    required_components: frozenset[str]

    @property
    def rank(self) -> int:
        return len(self.shape)

    @property
    def derived(self) -> bool:
        return self.value_schema.get("type") == "object"


@dataclass(frozen=True)
class _Target:
    root: _Property
    coordinates: tuple[int, ...]
    component_key: str | None
    component_name: str | None
    schema: Mapping[str, Any]
    path: str
    default: Any
    has_default: bool

    @property
    def state_key(self) -> tuple[str, tuple[int, ...], str | None]:
        return (self.root.key, self.coordinates, self.component_key)


@dataclass
class _MutableState:
    target: _Target
    value: Any
    has_value: bool
    initialized_by_default: bool
    explicitly_assigned: bool = False
    null_consumed: bool = False
    source_span: SourceSpan | None = None


@dataclass(frozen=True)
class _CompiledSchema:
    name: str
    properties: Mapping[str, _Property]
    required: frozenset[str]


def evaluate_file(
    parsed: ParsedFile,
    schemas: Iterable[Mapping[str, Any]],
    *,
    constants: dict[str, int] | None = None,
    dimensions: dict[str, int] | None = None,
    decimal_mode: DecimalMode = DecimalMode.POINT,
) -> tuple[EvaluatedGroup, ...]:
    """Evaluate every parsed group against a unique matching schema."""
    compiled: dict[str, _CompiledSchema] = {}
    for schema in schemas:
        model = _compile_schema(schema, constants=constants, dimensions=dimensions)
        key = model.name.lower()
        if key in compiled:
            raise ValueError(f"duplicate schema for namelist '{model.name}'")
        compiled[key] = model

    seen: set[str] = set()
    results: list[EvaluatedGroup] = []
    for group in parsed.groups:
        key = group.name.lower()
        if key in seen:
            _raise(
                NamelistEvaluationError,
                f"namelist group '{group.name}' appears multiple times",
                parsed.source,
                group.span,
            )
        seen.add(key)
        matched = compiled.get(key)
        if matched is None:
            _raise(
                NamelistEvaluationError,
                f"input contains unknown namelist '{group.name}'",
                parsed.source,
                group.span,
            )
        results.append(
            _evaluate_group_model(
                group,
                matched,
                source=parsed.source,
                constants=normalize_constant_values(constants),
                dimensions=normalize_runtime_dimensions(dimensions),
                decimal_mode=decimal_mode,
            )
        )
    return tuple(results)


def evaluate_group(
    group: ParsedGroup,
    schema: Mapping[str, Any],
    *,
    source: str = "<input>",
    constants: dict[str, int] | None = None,
    dimensions: dict[str, int] | None = None,
    decimal_mode: DecimalMode = DecimalMode.POINT,
) -> EvaluatedGroup:
    """Evaluate one parsed group against one resolved schema."""
    model = _compile_schema(schema, constants=constants, dimensions=dimensions)
    if group.name.lower() != model.name.lower():
        _raise(
            NamelistEvaluationError,
            f"group '{group.name}' does not match schema namelist '{model.name}'",
            source,
            group.span,
        )
    return _evaluate_group_model(
        group,
        model,
        source=source,
        constants=normalize_constant_values(constants),
        dimensions=normalize_runtime_dimensions(dimensions),
        decimal_mode=decimal_mode,
    )


def _compile_schema(
    schema: Mapping[str, Any],
    *,
    constants: dict[str, int] | None,
    dimensions: dict[str, int] | None,
) -> _CompiledSchema:
    normalized_constants = normalize_constant_values(constants)
    normalized_dimensions = normalize_runtime_dimensions(dimensions)
    reject_constant_dimension_overlap(normalized_constants, normalized_dimensions)
    validate_schema_defaults(
        schema,
        constants=normalized_constants,
        dimensions=normalized_dimensions,
    )
    name = schema.get("x-fortran-namelist")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("schema must define non-empty 'x-fortran-namelist'")
    validate_user_fortran_identifier(name, label="'x-fortran-namelist'")
    if schema.get("type") != "object":
        raise ValueError(f"schema '{name}' must be of type 'object'")
    raw_properties = schema.get("properties")
    if not isinstance(raw_properties, dict) or not raw_properties:
        raise ValueError(f"schema '{name}' must define object 'properties'")
    normalized = _normalize_properties(raw_properties, name)
    required = frozenset(_parse_required(schema.get("required", []), normalized, name))
    shape_values = {**normalized_constants, **normalized_dimensions}
    properties: dict[str, _Property] = {}
    for key, (property_name, raw) in normalized.items():
        prop: Mapping[str, Any] = raw
        value_schema = prop
        shape: tuple[int | None, ...] = ()
        flex = 0
        if prop.get("type") == "array":
            items = prop.get("items")
            if not isinstance(items, Mapping):
                raise ValueError(f"array property '{property_name}' must define 'items'")
            value_schema = items
            parsed_shape = _parse_shape(prop.get("x-fortran-shape"), shape_values, property_name)
            flex = _parse_flex_tail_dims(prop, len(parsed_shape), property_name, parsed_shape)
            shape = tuple(parsed_shape)
        components: dict[str, tuple[str, Mapping[str, Any]]] = {}
        required_components: frozenset[str] = frozenset()
        if value_schema.get("type") == "object":
            raw_components = value_schema.get("properties")
            if not isinstance(raw_components, Mapping) or not raw_components:
                raise ValueError(
                    f"derived property '{property_name}' must define object 'properties'"
                )
            for component_name, component_schema in raw_components.items():
                if not isinstance(component_name, str) or not isinstance(component_schema, Mapping):
                    raise ValueError(
                        f"derived property '{property_name}' has invalid component declaration"
                    )
                components[component_name.lower()] = (component_name, component_schema)
            required_components = _parse_derived_required(
                value_schema.get("required", []),
                components,
                property_name,
            )
        properties[key] = _Property(
            property_name,
            key,
            prop,
            value_schema,
            shape,
            flex,
            components,
            required_components,
        )
    return _CompiledSchema(name, properties, required)


def _evaluate_group_model(
    group: ParsedGroup,
    model: _CompiledSchema,
    *,
    source: str,
    constants: dict[str, int],
    dimensions: dict[str, int],
    decimal_mode: DecimalMode,
) -> EvaluatedGroup:
    states: dict[tuple[str, tuple[int, ...], str | None], _MutableState] = {}
    explicit_roots: set[str] = set()
    explicit_components: dict[tuple[str, tuple[int, ...]], set[str]] = {}
    instance_spans: dict[tuple[str, tuple[int, ...]], SourceSpan] = {}

    for assignment in group.assignments:
        value_count = _value_count(assignment)
        targets = _resolve_targets(
            assignment.designator,
            model,
            value_count=value_count,
            source=source,
            assignment_span=assignment.span,
        )
        if value_count > len(targets):
            _raise(
                NamelistEvaluationError,
                f"assignment to '{assignment.designator.source_text}' supplies "
                f"{value_count} values for {len(targets)} effective items",
                source,
                assignment.span,
            )
        for parsed_value, target in zip(_expand_values(assignment), targets):
            state = states.get(target.state_key)
            if state is None:
                initial_value = _initialized_default_value(
                    target,
                    constants=constants,
                    dimensions=dimensions,
                )
                state = _MutableState(
                    target,
                    initial_value,
                    target.has_default,
                    target.has_default,
                )
                states[target.state_key] = state
            if isinstance(parsed_value, NullValue):
                state.null_consumed = True
                state.source_span = parsed_value.span
                continue
            value = _convert_value(
                parsed_value,
                target,
                source=source,
                constants=constants,
                dimensions=dimensions,
                decimal_mode=decimal_mode,
            )
            state.value = value
            state.has_value = True
            state.explicitly_assigned = True
            state.source_span = parsed_value.span
            explicit_roots.add(target.root.key)
            if target.root.derived and target.component_key is not None:
                instance = (target.root.key, target.coordinates)
                explicit_components.setdefault(instance, set()).add(target.component_key)
                instance_spans[instance] = assignment.span

    for key in model.required:
        if key not in explicit_roots:
            prop = model.properties[key]
            _raise(
                NamelistConstraintError,
                f"namelist '{model.name}' is missing required '{prop.name}'",
                source,
                group.span,
            )

    for (root_key, coordinates), supplied in explicit_components.items():
        prop = model.properties[root_key]
        for missing in prop.required_components - supplied:
            component_name = prop.components[missing][0]
            path = _format_path(prop.name, coordinates, component_name)
            _raise(
                NamelistConstraintError,
                f"derived property '{_format_path(prop.name, coordinates)}' "
                f"is missing required '{path}'",
                source,
                instance_spans[(root_key, coordinates)],
            )

    frozen = {
        key: LeafState(
            state.target.path,
            state.target.coordinates,
            state.value,
            state.has_value,
            state.initialized_by_default,
            state.explicitly_assigned,
            state.null_consumed,
            state.source_span,
        )
        for key, state in states.items()
    }
    return EvaluatedGroup(group.name, frozen)


def _expand_values(assignment: Assignment) -> Iterable[RawValue | NullValue]:
    for value in assignment.values:
        if isinstance(value, RepeatedValue):
            for _ in range(value.count):
                yield value.value
        else:
            yield value


def _value_count(assignment: Assignment) -> int:
    return sum(
        value.count if isinstance(value, RepeatedValue) else 1
        for value in assignment.values
    )


def _parse_derived_required(
    raw: Any,
    components: Mapping[str, tuple[str, Mapping[str, Any]]],
    property_name: str,
) -> frozenset[str]:
    if raw is None:
        return frozenset()
    if not isinstance(raw, list):
        raise ValueError(f"derived property '{property_name}' required must be a list")
    required: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            raise ValueError(
                f"derived property '{property_name}' required entries must be strings"
            )
        key = item.lower()
        if key not in components:
            raise ValueError(
                f"derived property '{property_name}' required component '{item}' "
                "is not declared in properties"
            )
        required.add(key)
    return frozenset(required)


def _resolve_targets(
    designator: Designator,
    model: _CompiledSchema,
    *,
    value_count: int,
    source: str,
    assignment_span: SourceSpan,
) -> list[_Target]:
    parts = designator.parts
    root_part = parts[0]
    root = model.properties.get(root_part.name.lower())
    if root is None:
        _raise(
            NamelistEvaluationError,
            f"namelist '{model.name}' has unknown property '{root_part.name}' "
            f"in designator '{designator.source_text}'",
            source,
            root_part.span,
        )
    if len(parts) > 2:
        _raise(
            NamelistCapabilityError,
            f"nested derived designator '{designator.source_text}' is not supported",
            source,
            designator.span,
        )

    component_key: str | None = None
    component_name: str | None = None
    leaf_schema = root.value_schema
    if len(parts) == 2:
        if not root.derived:
            if root.value_schema.get("type") == "complex" and parts[1].name.lower() in {"re", "im"}:
                _raise(
                    NamelistCapabilityError,
                    "complex part designators require first-class complex schema support",
                    source,
                    parts[1].span,
                )
            _raise(
                NamelistEvaluationError,
                f"property '{root.name}' has no component '{parts[1].name}'",
                source,
                parts[1].span,
            )
        component_key = parts[1].name.lower()
        component = root.components.get(component_key)
        if component is None:
            _raise(
                NamelistEvaluationError,
                f"derived property '{root.name}' has unknown component '{parts[1].name}'",
                source,
                parts[1].span,
            )
        component_name, leaf_schema = component

    root_groups = root_part.selectors
    component_groups = parts[1].selectors if len(parts) == 2 else ()
    if root.rank == 0:
        if root_groups:
            if not root.derived and root.value_schema.get("type") == "string":
                _substring_error(designator, source, root_groups[0].span)
            _raise(
                NamelistBoundsError,
                f"scalar property '{root.name}' must not have array subscripts",
                source,
                root_groups[0].span,
            )
        coordinates: list[tuple[int, ...]] = [()]
    else:
        if len(root_groups) > 1:
            if root.value_schema.get("type") == "string" and len(root_groups) == 2:
                _substring_error(designator, source, root_groups[1].span)
            _raise(
                NamelistBoundsError,
                f"array property '{root.name}' has too many selector groups",
                source,
                root_groups[1].span,
            )
        component_count = len(root.components) if root.derived and component_key is None else 1
        needed_elements = math.ceil(value_count / component_count) if value_count else 0
        coordinates = _select_coordinates(
            root,
            root_groups[0] if root_groups else None,
            dynamic_count=needed_elements,
            source=source,
            span=root_part.span,
        )

    if component_groups:
        if leaf_schema.get("type") == "string" and len(component_groups) == 1:
            _substring_error(designator, source, component_groups[0].span)
        _raise(
            NamelistCapabilityError,
            f"array-valued component selection in '{designator.source_text}' is not supported",
            source,
            component_groups[0].span,
        )

    targets: list[_Target] = []
    if root.derived and component_key is None:
        for coordinate in coordinates:
            for key, (name, schema) in root.components.items():
                targets.append(_make_target(root, coordinate, key, name, schema))
    else:
        for coordinate in coordinates:
            targets.append(
                _make_target(root, coordinate, component_key, component_name, leaf_schema)
            )
    if not targets and value_count:
        _raise(
            NamelistBoundsError,
            f"designator '{designator.source_text}' selects no effective items",
            source,
            assignment_span,
        )
    return targets


def _select_coordinates(
    prop: _Property,
    group: Any,
    *,
    dynamic_count: int,
    source: str,
    span: SourceSpan,
) -> list[tuple[int, ...]]:
    if group is None:
        if all(extent is not None for extent in prop.shape):
            full_selections = [
                list(range(1, int(extent) + 1))
                for extent in prop.shape
                if extent is not None
            ]
            return _fortran_product(full_selections)
        if prop.rank == 1:
            return [(index,) for index in range(1, dynamic_count + 1)]
        _raise(
            NamelistCapabilityError,
            f"whole-array assignment to deferred-shape '{prop.name}' requires a concrete shape",
            source,
            span,
        )
    if len(group.selectors) != prop.rank:
        _raise(
            NamelistBoundsError,
            f"array '{prop.name}' rank mismatch: expected {prop.rank} subscripts, "
            f"got {len(group.selectors)}",
            source,
            group.span,
        )
    selections: list[list[int]] = []
    for dimension, (selector, extent) in enumerate(zip(group.selectors, prop.shape), start=1):
        if isinstance(selector, ScalarSelector):
            _check_index(prop, dimension, selector.value, extent, source, selector.span)
            selections.append([selector.value])
            continue
        stride = selector.stride if selector.stride is not None else 1
        if extent is None and (selector.lower is None or selector.upper is None):
            _raise(
                NamelistCapabilityError,
                f"omitted section bounds for deferred dimension {dimension} of '{prop.name}' "
                "require a concrete shape",
                source,
                selector.span,
            )
        lower = selector.lower
        upper = selector.upper
        if lower is None:
            assert extent is not None
            lower = 1 if stride > 0 else int(extent)
        if upper is None:
            assert extent is not None
            upper = int(extent) if stride > 0 else 1
        stop = upper + (1 if stride > 0 else -1)
        indexes = list(range(lower, stop, stride))
        if not indexes:
            _raise(
                NamelistBoundsError,
                f"section for dimension {dimension} of '{prop.name}' must not be empty",
                source,
                selector.span,
            )
        for index in indexes:
            _check_index(prop, dimension, index, extent, source, selector.span)
        selections.append(indexes)
    return _fortran_product(selections)


def _check_index(
    prop: _Property,
    dimension: int,
    index: int,
    extent: int | None,
    source: str,
    span: SourceSpan,
) -> None:
    if index < 1 or (extent is not None and index > extent):
        upper = "unbounded" if extent is None else str(extent)
        _raise(
            NamelistBoundsError,
            f"subscript {index} for dimension {dimension} of '{prop.name}' "
            f"is outside 1:{upper}",
            source,
            span,
        )


def _fortran_product(selections: list[list[int]]) -> list[tuple[int, ...]]:
    return [tuple(reversed(item)) for item in itertools.product(*reversed(selections))]


def _make_target(
    root: _Property,
    coordinates: tuple[int, ...],
    component_key: str | None,
    component_name: str | None,
    schema: Mapping[str, Any],
) -> _Target:
    has_default, default = _target_default(root, coordinates, schema)
    return _Target(
        root,
        coordinates,
        component_key,
        component_name,
        schema,
        _format_path(root.name, coordinates, component_name),
        default,
        has_default,
    )


def _target_default(
    root: _Property,
    coordinates: tuple[int, ...],
    leaf_schema: Mapping[str, Any],
) -> tuple[bool, Any]:
    if root.rank == 0:
        if "default" in leaf_schema:
            return True, leaf_schema["default"]
        return False, None
    if "default" in leaf_schema:
        return True, leaf_schema["default"]
    raw_default = root.schema.get("default")
    if not isinstance(raw_default, list) or any(extent is None for extent in root.shape):
        return False, None
    shape = tuple(int(extent) for extent in root.shape if extent is not None)
    total = math.prod(shape)
    values = list(raw_default)
    repeat = root.schema.get("x-fortran-default-repeat", False)
    pad = root.schema.get("x-fortran-default-pad")
    if repeat and values:
        values = [values[index % len(values)] for index in range(total)]
    elif pad is not None and len(values) < total:
        pad_values = list(pad) if isinstance(pad, list) else [pad]
        values.extend(pad_values[index % len(pad_values)] for index in range(total - len(values)))
    order = str(root.schema.get("x-fortran-default-order", "F")).upper()
    if order == "F":
        flat_index = _fortran_flat_index(coordinates, shape)
    else:
        flat_index = _c_flat_index(coordinates, shape)
    if flat_index < len(values):
        return True, values[flat_index]
    return False, None


def _initialized_default_value(
    target: _Target,
    *,
    constants: dict[str, int],
    dimensions: dict[str, int],
) -> Any:
    value = target.default
    if not target.has_default or target.schema.get("type") != "string":
        return value
    constraints = _scalar_constraints(
        target.path,
        target.schema,
        "string",
        constants,
        dimensions,
    )
    if constraints.length is None:
        return value
    return str(value).ljust(constraints.length)


def _fortran_flat_index(coordinates: tuple[int, ...], shape: tuple[int, ...]) -> int:
    multiplier = 1
    result = 0
    for coordinate, extent in zip(coordinates, shape):
        result += (coordinate - 1) * multiplier
        multiplier *= extent
    return result


def _c_flat_index(coordinates: tuple[int, ...], shape: tuple[int, ...]) -> int:
    result = 0
    for coordinate, extent in zip(coordinates, shape):
        result = result * extent + coordinate - 1
    return result


def _convert_value(
    raw: RawValue,
    target: _Target,
    *,
    source: str,
    constants: dict[str, int],
    dimensions: dict[str, int],
    decimal_mode: DecimalMode,
) -> Any:
    category = target.schema.get("type")
    if category not in {"integer", "number", "boolean", "string"}:
        _raise(
            NamelistCapabilityError,
            f"schema type '{category}' at '{target.path}' is not supported by namelist evaluation",
            source,
            raw.span,
        )
    try:
        if category == "integer":
            if raw.quoted or not re.fullmatch(r"[+-]?\d+", raw.source_text):
                raise ValueError("expected a signed or unsigned integer")
            value: Any = int(raw.source_text)
        elif category == "number":
            if raw.quoted:
                raise ValueError("expected a real value")
            value = _parse_real(raw.source_text, decimal_mode)
        elif category == "boolean":
            if raw.quoted:
                raise ValueError("expected a logical value")
            logical = raw.source_text.strip().lower()
            if logical.startswith("."):
                logical = logical[1:]
            if not logical or logical[0] not in {"t", "f"}:
                raise ValueError("expected a standard logical value beginning with T or F")
            value = logical[0] == "t"
        else:
            if not raw.quoted:
                raise ValueError("character input must be apostrophe- or quote-delimited")
            value = _decode_character(raw.source_text)
            constraints = _scalar_constraints(
                target.path,
                target.schema,
                "string",
                constants,
                dimensions,
            )
            if constraints.length is not None:
                value = value[: constraints.length].ljust(constraints.length)
        constraints = _scalar_constraints(
            target.path,
            target.schema,
            str(category),
            constants,
            dimensions,
        )
        _validate_scalar_value(target.path, value, constraints)
        return value
    except NamelistError:
        raise
    except ValueError as exc:
        error_type = (
            NamelistConstraintError
            if str(exc).startswith("property '")
            else NamelistConversionError
        )
        _raise(error_type, f"{target.path}: {exc}", source, raw.span)


def _parse_real(text: str, decimal_mode: DecimalMode) -> float:
    token = text.strip()
    lower = token.lower()
    if lower in {"inf", "+inf", "infinity", "+infinity"}:
        return math.inf
    if lower in {"-inf", "-infinity"}:
        return -math.inf
    if lower in {"nan", "+nan", "-nan"} or re.fullmatch(
        r"[+-]?nan\([a-z0-9]*\)", lower
    ):
        return math.nan
    if decimal_mode is DecimalMode.COMMA:
        token = token.replace(",", ".")
    if re.fullmatch(
        r"[+-]?0[xX](?:[0-9A-Fa-f]+(?:\.[0-9A-Fa-f]*)?|\.[0-9A-Fa-f]+)"
        r"[pP][+-]?\d+",
        token,
    ):
        return float.fromhex(token)
    token = re.sub(r"[dD]", "e", token)
    if "e" not in token.lower():
        match = re.fullmatch(r"([+-]?(?:\d+\.\d*|\.\d+))([+-]\d+)", token)
        if match is not None:
            token = f"{match.group(1)}e{match.group(2)}"
    if not re.fullmatch(
        r"[+-]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|\d+[eE][+-]?\d+)",
        token,
    ):
        raise ValueError("expected a standard real input value")
    return float(token)


def _decode_character(text: str) -> str:
    delimiter = text[0]
    content = text[1:-1].replace(delimiter * 2, delimiter)
    return content.replace("\r\n", "").replace("\r", "").replace("\n", "")


def _format_path(
    root_name: str,
    coordinates: tuple[int, ...] = (),
    component_name: str | None = None,
) -> str:
    path = root_name
    if coordinates:
        path += f"({','.join(str(index) for index in coordinates)})"
    if component_name is not None:
        path += f"%{component_name}"
    return path


def _substring_error(designator: Designator, source: str, span: SourceSpan) -> None:
    _raise(
        NamelistCapabilityError,
        f"character substring assignment in '{designator.source_text}' is not yet supported",
        source,
        span,
    )


def _raise(
    error_type: type[NamelistError],
    message: str,
    source: str,
    span: SourceSpan,
) -> NoReturn:
    raise error_type(message, source=source, span=span)
