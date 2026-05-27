"""Schema loading and local JSON Schema reference resolution utilities."""

from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit

import yaml

from ._utils import FORTRAN_IDENTIFIER

_DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
_DOCUMENT_SUFFIXES = {".json", ".yml", ".yaml"}
_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_MAPPING_IDENTITY_COUNTER = count(1)
DERIVED_REF_ORIGIN_KEY = "_nml_tools_ref_origin"
_REPRESENTATION_KEYS = {
    "type",
    "x-fortran-kind",
    "x-fortran-len",
    "x-fortran-shape",
    "x-fortran-flex-tail-dims",
    "x-fortran-type",
    "x-fortran-module",
}
_ANNOTATION_KEYS = {"title", "description", "examples", "$comment"}
_DEFAULT_CONTROL_KEYS = {
    "x-fortran-default-order",
    "x-fortran-default-repeat",
    "x-fortran-default-pad",
}
_BOUND_KEYS = {"minimum", "exclusiveMinimum", "maximum", "exclusiveMaximum"}
_COMPOSITION_KEYS = {
    "$ref",
    "$defs",
    "properties",
    "required",
    "items",
    "enum",
    "default",
    *_REPRESENTATION_KEYS,
    *_ANNOTATION_KEYS,
    *_DEFAULT_CONTROL_KEYS,
    *_BOUND_KEYS,
}
_REJECTED_REFERENCE_KEYS = {
    "$def",
    "definitions",
    "$dynamicRef",
    "$dynamicAnchor",
    "$anchor",
    "$id",
    "allOf",
    "anyOf",
    "oneOf",
    "not",
    "if",
    "then",
    "else",
}


@dataclass(frozen=True)
class _Document:
    """A raw schema document and its reference base."""

    data: dict[str, Any]
    path: Path | None
    mapping_identity: str | None = None

    @property
    def label(self) -> str:
        if self.path is None:
            return "<mapping>"
        return str(self.path)

    @property
    def identity(self) -> str:
        if self.path is None:
            if self.mapping_identity is None:
                raise ValueError("source-less mapping document has no private identity")
            return self.mapping_identity
        return str(self.path)


class SchemaResolver:
    """Resolve the local `$defs`/`$ref` subset supported by nml-tools."""

    def __init__(self) -> None:
        self._documents: dict[Path, _Document] = {}
        self._active_refs: list[tuple[str, str]] = []

    def resolve_file(self, path: str | Path) -> dict[str, Any]:
        """Load and resolve a file-backed schema document."""
        document = self._load_document(Path(path))
        _reject_reserved_marker(document.data, document, "")
        if not _requires_normalization(document.data, position="root"):
            return copy.deepcopy(document.data)
        self._validate_document_metadata(document)
        return self._resolve_node(document.data, document, "", position="root")

    def resolve_mapping(
        self,
        schema: Mapping[str, Any],
        *,
        source_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """Resolve an in-memory schema, optionally supplying its filesystem base."""
        data = dict(schema)
        path = Path(source_path).resolve() if source_path is not None else None
        mapping_identity = f"<mapping:{next(_MAPPING_IDENTITY_COUNTER)}>" if path is None else None
        document = _Document(data, path, mapping_identity)
        if path is not None:
            self._documents[path] = document
        _reject_reserved_marker(data, document, "")
        if not _requires_normalization(data, position="root"):
            return copy.deepcopy(data)
        self._validate_document_metadata(document)
        return self._resolve_node(data, document, "", position="root")

    def _load_document(self, path: Path) -> _Document:
        canonical_path = path.resolve()
        cached = self._documents.get(canonical_path)
        if cached is not None:
            return cached
        if not canonical_path.exists():
            raise FileNotFoundError(canonical_path)
        suffix = canonical_path.suffix.lower()
        if suffix not in _DOCUMENT_SUFFIXES:
            raise ValueError(f"schema must be a .json, .yml, or .yaml file: {canonical_path}")
        if suffix == ".json":
            data = json.loads(canonical_path.read_text(encoding="utf-8"))
        else:
            data = yaml.safe_load(canonical_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"schema root must be an object: {canonical_path}")
        document = _Document(data, canonical_path)
        self._documents[canonical_path] = document
        return document

    def _validate_document_metadata(self, document: _Document) -> None:
        dialect = document.data.get("$schema")
        if dialect is not None:
            if not isinstance(dialect, str) or dialect.rstrip("#") != _DRAFT_2020_12:
                raise ValueError(
                    f"{document.label}: references require JSON Schema Draft 2020-12"
                )
        for keyword in ("$id", "$anchor", "$dynamicAnchor"):
            if keyword in document.data:
                raise ValueError(
                    f"{document.label}: keyword '{keyword}' is not supported with references"
                )

    def _resolve_node(
        self,
        raw: Mapping[str, Any],
        document: _Document,
        pointer: str,
        *,
        position: str,
        allow_derived_definition: bool = False,
    ) -> dict[str, Any]:
        _reject_unsupported_reference_keywords(raw, document, pointer)
        ref = raw.get("$ref")
        if ref is not None:
            if not isinstance(ref, str) or not ref:
                raise ValueError(f"{_location(document, pointer)}: '$ref' must be a string")
            target, target_document, target_pointer = self._dereference(ref, document, pointer)
            identity = (target_document.identity, target_pointer)
            if identity in self._active_refs:
                raise ValueError(
                    f"{_location(document, pointer)}: cyclic $ref '{ref}' "
                    f"targeting {_location(target_document, target_pointer)}"
                )
            self._active_refs.append(identity)
            try:
                resolved_target = self._resolve_node(
                    target,
                    target_document,
                    target_pointer,
                    position=position,
                    allow_derived_definition=position in {"property", "items"},
                )
            finally:
                self._active_refs.pop()
            local = {key: value for key, value in raw.items() if key not in {"$ref", "$defs"}}
            resolved_local = self._resolve_plain(local, document, pointer, position=position)
            try:
                result = _compose_nodes(resolved_target, resolved_local, position=position)
            except ValueError as exc:
                raise ValueError(
                    f"{_location(document, pointer)}: invalid $ref '{ref}': {exc}"
                ) from exc
            if position in {"property", "items"} and result.get("type") == "object":
                base_definition = copy.deepcopy(resolved_target)
                base_definition.pop(DERIVED_REF_ORIGIN_KEY, None)
                result[DERIVED_REF_ORIGIN_KEY] = {
                    "identity": [target_document.identity, target_pointer],
                    "definition": base_definition,
                }
        else:
            result = self._resolve_plain(raw, document, pointer, position=position)

        if (
            position in {"property", "items"}
            and result.get("type") == "object"
            and DERIVED_REF_ORIGIN_KEY not in result
            and not allow_derived_definition
            and "x-fortran-type" in result
        ):
            definition = copy.deepcopy(result)
            result[DERIVED_REF_ORIGIN_KEY] = {
                "identity": [document.identity, pointer],
                "definition": definition,
            }
        if (
            position != "root"
            and result.get("type") == "object"
            and DERIVED_REF_ORIGIN_KEY not in result
            and not allow_derived_definition
        ):
            raise ValueError(
                f"{_location(document, pointer)}: object-valued properties and items must "
                "define 'x-fortran-type' inline or use '$ref'"
            )
        _validate_effective_node(result, position=position)
        return result

    def _resolve_plain(
        self,
        raw: Mapping[str, Any],
        document: _Document,
        pointer: str,
        *,
        position: str,
    ) -> dict[str, Any]:
        resolved = {
            key: copy.deepcopy(value)
            for key, value in raw.items()
            if key not in {"$ref", "$defs"}
        }
        if "properties" in raw:
            properties = raw["properties"]
            if not isinstance(properties, Mapping):
                raise ValueError(f"{_location(document, pointer)}: 'properties' must be an object")
            resolved["properties"] = {
                name: self._resolve_property_value(value, document, pointer, name)
                for name, value in properties.items()
            }
        if "items" in raw:
            items = raw["items"]
            if not isinstance(items, Mapping):
                raise ValueError(f"{_location(document, pointer)}: 'items' must be an object")
            resolved["items"] = self._resolve_node(
                items,
                document,
                _child_pointer(pointer, "items"),
                position="items",
            )
        return resolved

    def _resolve_property_value(
        self,
        value: Any,
        document: _Document,
        pointer: str,
        name: Any,
    ) -> dict[str, Any]:
        if not isinstance(name, str):
            raise ValueError(f"{_location(document, pointer)}: property names must be strings")
        if not isinstance(value, Mapping):
            property_pointer = _child_pointer(_child_pointer(pointer, "properties"), name)
            raise ValueError(
                f"{_location(document, property_pointer)}: property schema must be an object"
            )
        return self._resolve_node(
            value,
            document,
            _child_pointer(_child_pointer(pointer, "properties"), name),
            position="property",
        )

    def _dereference(
        self,
        ref: str,
        document: _Document,
        pointer: str,
    ) -> tuple[dict[str, Any], _Document, str]:
        if _WINDOWS_ABSOLUTE_PATH.match(ref):
            ref_path, separator, ref_fragment = ref.partition("#")
            fragment = ref_fragment if separator else ""
        else:
            split = urlsplit(ref)
            if split.scheme or split.netloc or split.query:
                raise ValueError(
                    f"{_location(document, pointer)}: remote or URI $ref is not supported: '{ref}'"
                )
            ref_path = split.path
            fragment = split.fragment
        if ref_path:
            if document.path is None:
                raise ValueError(
                    f"{_location(document, pointer)}: external $ref '{ref}' "
                    "requires a source path"
                )
            external_path = Path(unquote(ref_path))
            if not external_path.is_absolute():
                external_path = document.path.parent / external_path
            try:
                target_document = self._load_document(external_path)
            except FileNotFoundError as exc:
                raise ValueError(
                    f"{_location(document, pointer)}: unresolved $ref '{ref}': "
                    f"referenced file not found '{external_path.resolve()}'"
                ) from exc
            self._validate_document_metadata(target_document)
        else:
            target_document = document
        target_pointer = _fragment_to_pointer(fragment, ref, document, pointer)
        target = _lookup_pointer(
            target_document.data,
            target_pointer,
            target_document,
            ref,
            document,
            pointer,
        )
        if not isinstance(target, dict):
            raise ValueError(
                f"{_location(document, pointer)}: $ref '{ref}' does not target a schema object"
            )
        return target, target_document, target_pointer


def load_schema(
    path: str | Path,
    *,
    resolver: SchemaResolver | None = None,
) -> dict[str, Any]:
    """Load and resolve a schema definition from *path*."""
    active_resolver = resolver or SchemaResolver()
    return active_resolver.resolve_file(path)


def resolve_schema(
    schema: Mapping[str, Any],
    *,
    source_path: str | Path | None = None,
    resolver: SchemaResolver | None = None,
) -> dict[str, Any]:
    """Resolve references in an in-memory schema mapping."""
    active_resolver = resolver or SchemaResolver()
    return active_resolver.resolve_mapping(schema, source_path=source_path)


def _contains_reachable_ref(raw: Mapping[str, Any], *, position: str) -> bool:
    if "$ref" in raw:
        return True
    if position == "root":
        properties = raw.get("properties")
        if isinstance(properties, Mapping):
            for prop in properties.values():
                if isinstance(prop, Mapping) and _contains_reachable_ref(prop, position="property"):
                    return True
    items = raw.get("items")
    return isinstance(items, Mapping) and _contains_reachable_ref(items, position="items")


def _requires_normalization(raw: Mapping[str, Any], *, position: str) -> bool:
    if _contains_reachable_ref(raw, position=position):
        return True
    if raw.get("type") == "object" and position != "root":
        return True
    properties = raw.get("properties")
    if isinstance(properties, Mapping):
        for prop in properties.values():
            if isinstance(prop, Mapping) and _requires_normalization(prop, position="property"):
                return True
    items = raw.get("items")
    return isinstance(items, Mapping) and _requires_normalization(items, position="items")


def _reject_unsupported_reference_keywords(
    raw: Mapping[str, Any],
    document: _Document,
    pointer: str,
) -> None:
    if DERIVED_REF_ORIGIN_KEY in raw:
        raise ValueError(
            f"{_location(document, pointer)}: keyword '{DERIVED_REF_ORIGIN_KEY}' is reserved"
        )
    for keyword in _REJECTED_REFERENCE_KEYS:
        if keyword in raw:
            raise ValueError(
                f"{_location(document, pointer)}: keyword '{keyword}' is not supported "
                "with references"
            )


def _reject_reserved_marker(raw: Any, document: _Document, pointer: str) -> None:
    if isinstance(raw, Mapping):
        if DERIVED_REF_ORIGIN_KEY in raw:
            raise ValueError(
                f"{_location(document, pointer)}: keyword '{DERIVED_REF_ORIGIN_KEY}' is reserved"
            )
        for key, value in raw.items():
            if isinstance(key, str):
                _reject_reserved_marker(value, document, _child_pointer(pointer, key))
        return
    if isinstance(raw, list):
        for index, value in enumerate(raw):
            _reject_reserved_marker(value, document, _child_pointer(pointer, str(index)))


def _compose_nodes(
    referenced: dict[str, Any],
    local: dict[str, Any],
    *,
    position: str,
) -> dict[str, Any]:
    result = copy.deepcopy(referenced)
    for key, value in local.items():
        if key not in _COMPOSITION_KEYS:
            result[key] = copy.deepcopy(value)

    representation_keys = set(_REPRESENTATION_KEYS)
    if position == "root":
        representation_keys.add("x-fortran-namelist")
    for key in representation_keys:
        if key in local:
            if (
                key == "x-fortran-module"
                and position in {"property", "items"}
                and referenced.get("type") == "object"
                and key not in referenced
            ):
                raise ValueError(
                    "'x-fortran-module' must be declared on the referenced derived definition"
                )
            if key in referenced and referenced[key] != local[key]:
                raise ValueError(f"conflicting '{key}' in referenced and local schema")
            result[key] = copy.deepcopy(local[key])

    for key in _ANNOTATION_KEYS:
        if key in local:
            result[key] = copy.deepcopy(local[key])

    if "default" in local:
        result["default"] = copy.deepcopy(local["default"])
        if result.get("type") == "array":
            for key in _DEFAULT_CONTROL_KEYS:
                result.pop(key, None)
            for key in _DEFAULT_CONTROL_KEYS:
                if key in local:
                    result[key] = copy.deepcopy(local[key])
    else:
        present_controls = _DEFAULT_CONTROL_KEYS.intersection(local)
        if present_controls:
            control = sorted(present_controls)[0]
            raise ValueError(f"'{control}' requires a local array-level 'default'")

    _compose_bounds(result, referenced, local)
    _compose_enum(result, referenced, local)

    if "items" in referenced or "items" in local:
        if "items" not in referenced:
            result["items"] = copy.deepcopy(local["items"])
        elif "items" not in local:
            result["items"] = copy.deepcopy(referenced["items"])
        else:
            result["items"] = _compose_nodes(
                referenced["items"], local["items"], position="items"
            )

    if "properties" in referenced or "properties" in local:
        if position == "root":
            result["properties"] = _compose_properties(
                referenced.get("properties", {}),
                local.get("properties", {}),
            )
        elif result.get("type") == "object":
            result["properties"] = _compose_derived_properties(
                referenced.get("properties", {}),
                local.get("properties", {}),
            )
        else:
            raise ValueError("object property composition is not supported for scalar fields")
    if "required" in referenced or "required" in local:
        if position != "root" and result.get("type") != "object":
            raise ValueError("'required' composition is only supported for objects")
        result["required"] = _union_required(
            referenced.get("required", []),
            local.get("required", []),
        )
    _validate_effective_node(result, position=position)
    return result


def _compose_properties(
    referenced: Any,
    local: Any,
) -> dict[str, Any]:
    if not isinstance(referenced, dict) or not isinstance(local, dict):
        raise ValueError("'properties' must be objects")
    result = copy.deepcopy(referenced)
    for name, schema in local.items():
        if name in result:
            if not isinstance(result[name], dict) or not isinstance(schema, dict):
                raise ValueError(f"property '{name}' must be a schema object")
            result[name] = _compose_nodes(result[name], schema, position="property")
        else:
            result[name] = copy.deepcopy(schema)
    return result


def _compose_derived_properties(referenced: Any, local: Any) -> dict[str, Any]:
    if not isinstance(referenced, dict) or not isinstance(local, dict):
        raise ValueError("'properties' must be objects")
    result = copy.deepcopy(referenced)
    canonical = {name.lower(): name for name in referenced if isinstance(name, str)}
    for name, schema in local.items():
        if not isinstance(name, str):
            raise ValueError("derived-type component names must be strings")
        target_name = canonical.get(name.lower())
        if target_name is None:
            raise ValueError(f"derived-type use site must not add component '{name}'")
        if not isinstance(result[target_name], dict) or not isinstance(schema, dict):
            raise ValueError(f"component '{name}' must be a schema object")
        result[target_name] = _compose_nodes(result[target_name], schema, position="property")
    return result


def _union_required(referenced: Any, local: Any) -> list[Any]:
    if not isinstance(referenced, list) or not isinstance(local, list):
        raise ValueError("'required' must be a list")
    result = list(referenced)
    for value in local:
        if value not in result:
            result.append(value)
    return result


def _compose_bounds(
    result: dict[str, Any],
    referenced: Mapping[str, Any],
    local: Mapping[str, Any],
) -> None:
    lower = _select_bound(_read_bound(referenced, lower=True), _read_bound(local, lower=True), True)
    upper = _select_bound(
        _read_bound(referenced, lower=False), _read_bound(local, lower=False), False
    )
    for key in _BOUND_KEYS:
        result.pop(key, None)
    _write_bound(result, lower, lower=True)
    _write_bound(result, upper, lower=False)
    _validate_bound_interval(lower, upper, result.get("type"))


def _read_bound(raw: Mapping[str, Any], *, lower: bool) -> tuple[float | int, bool] | None:
    inclusive = "minimum" if lower else "maximum"
    exclusive = "exclusiveMinimum" if lower else "exclusiveMaximum"
    if inclusive in raw and exclusive in raw:
        raise ValueError(f"schema must not define both '{inclusive}' and '{exclusive}'")
    key = exclusive if exclusive in raw else inclusive
    if key not in raw:
        return None
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"'{key}' must be numeric")
    if not math.isfinite(float(value)):
        raise ValueError(f"'{key}' must be finite")
    return value, key == exclusive


def _select_bound(
    referenced: tuple[float | int, bool] | None,
    local: tuple[float | int, bool] | None,
    lower: bool,
) -> tuple[float | int, bool] | None:
    if referenced is None:
        return local
    if local is None:
        return referenced
    reference_value, reference_exclusive = referenced
    local_value, local_exclusive = local
    if local_value == reference_value:
        return local_value, local_exclusive or reference_exclusive
    if lower:
        return local if local_value > reference_value else referenced
    return local if local_value < reference_value else referenced


def _write_bound(
    result: dict[str, Any],
    bound: tuple[float | int, bool] | None,
    *,
    lower: bool,
) -> None:
    if bound is None:
        return
    value, exclusive = bound
    if lower:
        key = "exclusiveMinimum" if exclusive else "minimum"
    else:
        key = "exclusiveMaximum" if exclusive else "maximum"
    result[key] = value


def _validate_bound_interval(
    lower: tuple[float | int, bool] | None,
    upper: tuple[float | int, bool] | None,
    schema_type: Any,
) -> None:
    if lower is None or upper is None:
        return
    low, low_exclusive = lower
    high, high_exclusive = upper
    if low > high or (low == high and (low_exclusive or high_exclusive)):
        raise ValueError("combined numeric bounds define an empty interval")
    if schema_type == "integer":
        minimum = math.floor(low) + 1 if low_exclusive else math.ceil(low)
        maximum = math.ceil(high) - 1 if high_exclusive else math.floor(high)
        if minimum > maximum:
            raise ValueError("combined numeric bounds define an empty integer interval")


def _compose_enum(
    result: dict[str, Any],
    referenced: Mapping[str, Any],
    local: Mapping[str, Any],
) -> None:
    if "enum" not in referenced and "enum" not in local:
        return
    if "enum" in referenced and not isinstance(referenced["enum"], list):
        raise ValueError("'enum' must be a list")
    if "enum" in local and not isinstance(local["enum"], list):
        raise ValueError("'enum' must be a list")
    if "enum" not in referenced:
        result["enum"] = copy.deepcopy(local["enum"])
        return
    if "enum" not in local:
        result["enum"] = copy.deepcopy(referenced["enum"])
        return
    values = [value for value in referenced["enum"] if value in local["enum"]]
    if not values:
        raise ValueError("combined enum restrictions have no common values")
    result["enum"] = values


def _validate_effective_node(schema: dict[str, Any], *, position: str) -> None:
    if schema.get("type") == "array":
        if _DEFAULT_CONTROL_KEYS.intersection(schema) and "default" not in schema:
            raise ValueError("array x-fortran-default-* options require an array-level default")
        items = schema.get("items")
        if isinstance(items, Mapping) and items.get("type") == "object":
            if "x-fortran-flex-tail-dims" in schema:
                raise ValueError(
                    "derived-type arrays must not define 'x-fortran-flex-tail-dims'"
                )
            if "default" in schema or _DEFAULT_CONTROL_KEYS.intersection(schema):
                raise ValueError("derived-type arrays must not define defaults")
        return
    if schema.get("type") == "object" and position != "root":
        _validate_derived_object(schema)
        return
    enum = schema.get("enum")
    if enum is None:
        return
    if not isinstance(enum, list) or not enum:
        raise ValueError("'enum' must be a non-empty list")
    effective_values = [
        value for value in enum if _scalar_satisfies_static_constraints(value, schema)
    ]
    if len(effective_values) != len(enum):
        if not effective_values:
            raise ValueError("enum values are eliminated by effective constraints")
        raise ValueError("enum contains values outside effective constraints")


def _validate_derived_object(schema: Mapping[str, Any]) -> None:
    type_name = schema.get("x-fortran-type")
    if not isinstance(type_name, str) or not type_name.strip():
        raise ValueError("derived-type object must define non-empty 'x-fortran-type'")
    if FORTRAN_IDENTIFIER.match(type_name.strip()) is None:
        raise ValueError("'x-fortran-type' must be a valid Fortran identifier")
    module_name = schema.get("x-fortran-module")
    if module_name is not None:
        if (
            not isinstance(module_name, str)
            or FORTRAN_IDENTIFIER.match(module_name.strip()) is None
        ):
            raise ValueError("'x-fortran-module' must be a valid Fortran identifier")
    if "default" in schema:
        raise ValueError("derived-type object must not define a default")
    properties = schema.get("properties")
    if not isinstance(properties, Mapping) or not properties:
        raise ValueError("derived-type object must define non-empty 'properties'")
    canonical: set[str] = set()
    for name, prop in properties.items():
        if not isinstance(name, str):
            raise ValueError("derived-type component names must be strings")
        if FORTRAN_IDENTIFIER.match(name) is None:
            raise ValueError(
                f"derived-type component '{name}' must be a valid Fortran identifier"
            )
        key = name.lower()
        if key in canonical:
            raise ValueError(f"derived-type object defines duplicate component '{name}'")
        canonical.add(key)
        if not isinstance(prop, Mapping) or prop.get("type") not in {
            "integer",
            "number",
            "boolean",
            "string",
        }:
            raise ValueError(
                f"derived-type component '{name}' must define an intrinsic scalar type"
            )
    required = schema.get("required", [])
    if not isinstance(required, list):
        raise ValueError("derived-type 'required' must be a list")
    for name in required:
        if not isinstance(name, str) or name.lower() not in canonical:
            raise ValueError(f"derived-type required component '{name}' is not a property")


def _scalar_satisfies_static_constraints(value: Any, schema: Mapping[str, Any]) -> bool:
    schema_type = schema.get("type")
    if schema_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return False
    elif schema_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
    elif schema_type == "string":
        if not isinstance(value, str):
            return False
        length = schema.get("x-fortran-len")
        if isinstance(length, int) and not isinstance(length, bool) and len(value) > length:
            return False
    elif schema_type == "boolean":
        return isinstance(value, bool)
    else:
        return True
    lower = _read_bound(schema, lower=True)
    upper = _read_bound(schema, lower=False)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if lower is not None:
            bound, exclusive = lower
            if value < bound or (exclusive and value == bound):
                return False
        if upper is not None:
            bound, exclusive = upper
            if value > bound or (exclusive and value == bound):
                return False
    return True


def _fragment_to_pointer(
    fragment: str,
    ref: str,
    document: _Document,
    pointer: str,
) -> str:
    decoded = unquote(fragment)
    if not decoded:
        return ""
    if not decoded.startswith("/"):
        raise ValueError(
            f"{_location(document, pointer)}: only JSON Pointer fragments are supported "
            f"in $ref '{ref}'"
        )
    return decoded


def _lookup_pointer(
    data: Any,
    pointer: str,
    target_document: _Document,
    ref: str,
    referring_document: _Document,
    referring_pointer: str,
) -> Any:
    current = data
    if not pointer:
        return current
    for raw_token in pointer[1:].split("/"):
        if re.search(r"~(?![01])", raw_token):
            raise ValueError(
                f"{_location(referring_document, referring_pointer)}: "
                f"invalid JSON Pointer in $ref '{ref}'"
            )
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise ValueError(
                f"{_location(referring_document, referring_pointer)}: unresolved $ref '{ref}' "
                f"targeting {_location(target_document, pointer)}"
            )
    return current


def _child_pointer(pointer: str, token: str) -> str:
    escaped = token.replace("~", "~0").replace("/", "~1")
    return f"{pointer}/{escaped}"


def _location(document: _Document, pointer: str) -> str:
    return f"{document.label}#{pointer}"
