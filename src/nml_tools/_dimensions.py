"""Private, UI-independent runtime dimension source resolution and inference."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from ._namelist_eval import NamelistConstraintError, NamelistEvaluationError, evaluate_group
from ._namelist_parser import DecimalMode, ParsedFile, ParsedGroup
from ._utils import (
    normalize_constant_values,
    normalize_runtime_dimensions,
    reject_constant_dimension_overlap,
    validate_user_fortran_identifier,
)
from .validate import _has_reachable_reference, _normalize_properties


@dataclass(frozen=True)
class DimensionSource:
    """One top-level integer property supplying a runtime dimension."""

    namelist: str
    property: str


def resolve_dimension_source(
    source: DimensionSource,
    schemas: Mapping[str, Mapping[str, Any]],
) -> DimensionSource:
    """Check a source against resolved schemas without evaluating array shapes."""
    validate_user_fortran_identifier(source.namelist, label="dimension source namelist")
    validate_user_fortran_identifier(source.property, label="dimension source property")
    schema = schemas.get(source.namelist.lower())
    if schema is None:
        raise ValueError(f"dimension source references unknown namelist '{source.namelist}'")
    if _has_reachable_reference(schema, position="root"):
        raise ValueError(
            "schema contains unresolved '$ref'; use load_schema() or resolve_schema() "
            "before dimension source resolution"
        )
    raw_properties = schema.get("properties")
    if not isinstance(raw_properties, Mapping):
        raise ValueError(f"dimension source namelist '{source.namelist}' must define properties")
    properties = _normalize_properties(raw_properties, source.namelist)
    matched = properties.get(source.property.lower())
    if matched is None:
        raise ValueError(
            f"dimension source namelist '{source.namelist}' references "
            f"unknown property '{source.property}'"
        )
    name, prop = matched
    if prop.get("type") != "integer":
        raise ValueError(
            f"dimension source '{source.namelist}%{name}' must be an intrinsic integer scalar"
        )
    return DimensionSource(source.namelist.lower(), name)


def infer_runtime_dimensions(
    files: Iterable[ParsedFile],
    *,
    sources: Mapping[str, DimensionSource],
    schemas: Mapping[str, Mapping[str, Any]],
    defaults: Mapping[str, object],
    overrides: Mapping[str, object] | None = None,
    constants: Mapping[str, object] | None = None,
    decimal_mode: DecimalMode = DecimalMode.POINT,
) -> dict[str, int]:
    """Infer explicit source values before callers evaluate complete schemas.

    Explicit overrides bypass source extraction. Null input and schema defaults
    do not supply dimensions. Source namelists must be unique across the parsed
    inputs for each dimension being inferred.
    """
    dimensions = normalize_runtime_dimensions(defaults)
    normalized_overrides = normalize_runtime_dimensions(overrides)
    dimensions.update(normalized_overrides)
    normalized_constants = normalize_constant_values(constants)
    reject_constant_dimension_overlap(normalized_constants, dimensions)
    groups: dict[str, list[tuple[ParsedFile, ParsedGroup]]] = {}
    for parsed in files:
        for group in parsed.groups:
            groups.setdefault(group.name.lower(), []).append((parsed, group))

    seen: set[str] = set()
    for raw_name, source in sources.items():
        validate_user_fortran_identifier(raw_name, label="runtime dimension")
        name = raw_name.lower()
        if name in seen:
            raise ValueError(f"runtime dimension '{raw_name}' duplicates another source name")
        seen.add(name)
        if name not in dimensions:
            raise ValueError(f"dimension source '{raw_name}' has no configured default")
        resolved = resolve_dimension_source(source, schemas)
        if name in normalized_overrides:
            continue
        matches = groups.get(resolved.namelist, [])
        if len(matches) > 1:
            parsed, group = matches[1]
            first_file, first_group = matches[0]
            raise NamelistEvaluationError(
                f"dimension '{name}' has ambiguous source namelist '{resolved.namelist}'; "
                f"also present in {first_file.source}:{first_group.span.start.line}",
                source=parsed.source,
                span=group.span,
            )
        if not matches:
            continue
        parsed, group = matches[0]
        prop = schemas[resolved.namelist]["properties"][resolved.property]
        scalar_schema = {
            "type": "object",
            "x-fortran-namelist": resolved.namelist,
            "properties": {resolved.property: prop},
        }
        scalar_group = ParsedGroup(
            group.name,
            tuple(
                assignment
                for assignment in group.assignments
                if assignment.designator.parts[0].name.lower() == resolved.property.lower()
            ),
            group.span,
        )
        evaluated = evaluate_group(
            scalar_group,
            scalar_schema,
            source=parsed.source,
            constants=normalized_constants,
            dimensions=dimensions,
            decimal_mode=decimal_mode,
        )
        state = evaluated.states.get((resolved.property.lower(), (), None))
        if state is None or not state.explicitly_assigned:
            continue
        if state.value <= 0:
            raise NamelistConstraintError(
                f"dimension '{name}' source '{resolved.namelist}%{resolved.property}' "
                "must be positive",
                source=parsed.source,
                span=state.source_span or group.span,
            )
        dimensions[name] = state.value
    return dimensions
