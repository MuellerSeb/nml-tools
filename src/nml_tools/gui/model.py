"""Qt-independent project and persistence model used by the GUI."""

from __future__ import annotations

import copy
import json
import math
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

import click

from .._namelist_eval import EvaluatedGroup, LeafState, evaluate_group
from .._namelist_parser import parse_namelist
from ..cli import (
    _iter_file_profiles,
    _load_config_checked,
    _load_constants,
    _load_dimensions,
    _load_namelist_registry,
    _namelist_registry_by_key,
)
from ..json2nml import json_to_namelist
from ..schema import SchemaResolver
from .arrays import flex_tail_dims, initial_array, resolve_shape, validate_array_shape

FORMAT_VERSION = 1
MISSING = object()


def suggestion(schema: Mapping[str, Any], sizes: Mapping[str, int]) -> Any:
    """Return the deterministic editable value used for an unset schema field."""
    examples = schema.get("examples")
    if isinstance(examples, list) and examples:
        candidate = copy.deepcopy(examples[0])
    elif "default" in schema:
        candidate = copy.deepcopy(schema["default"])
    else:
        candidate = MISSING

    kind = schema.get("type")
    if kind == "array":
        items = schema.get("items")
        if not isinstance(items, Mapping):
            raise ValueError("array field must define object 'items'")
        leaf = suggestion(items, sizes)
        return initial_array(schema, sizes, None if candidate is MISSING else candidate, leaf)
    if kind == "object":
        raw = candidate if isinstance(candidate, Mapping) else {}
        properties = schema.get("properties")
        if not isinstance(properties, Mapping):
            raise ValueError("derived field must define object 'properties'")
        return {
            name: copy.deepcopy(raw[name]) if name in raw else suggestion(child, sizes)
            for name, child in properties.items()
            if isinstance(name, str) and isinstance(child, Mapping)
        }
    if candidate is not MISSING:
        return candidate
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return copy.deepcopy(enum[0])
    if kind == "boolean":
        return False
    if kind == "integer":
        minimum = schema.get("minimum")
        return int(minimum) if isinstance(minimum, int) and not isinstance(minimum, bool) else 0
    if kind == "number":
        minimum = schema.get("minimum")
        return float(minimum) if isinstance(minimum, (int, float)) else 0.0
    if kind == "string":
        return ""
    raise ValueError(f"unsupported schema type '{kind}'")


@dataclass(frozen=True)
class NamelistPage:
    """A configured namelist and its resolved schema."""

    name: str
    key: str
    schema: dict[str, Any]


@dataclass(frozen=True)
class GuiProfile:
    """An ordered file profile presented by the GUI."""

    name: str
    key: str
    title: str
    description: str | None
    default_file: str
    pages: tuple[NamelistPage, ...]


@dataclass(frozen=True)
class GuiProject:
    """Resolved nml-tools project data needed by the GUI."""

    root: Path
    constants: dict[str, int]
    default_dimensions: dict[str, int]
    profiles: tuple[GuiProfile, ...]
    output_dir: Path | None = None
    namelists: tuple[NamelistPage, ...] = ()

    @property
    def output_root(self) -> Path:
        """Return the directory used for JSON and namelist output."""
        return self.output_dir or self.root

    def profile(self, key: str) -> GuiProfile:
        for profile in self.profiles:
            if profile.key == key.lower():
                return profile
        raise KeyError(key)


def load_project(
    schemas_dir: Path | str | None = None,
    output_dir: Path | str | None = None,
) -> GuiProject:
    """Load schemas and profiles, using a separate output directory if given."""
    root = Path.cwd() if schemas_dir is None else Path(schemas_dir)
    root = root.resolve()
    output_root = root if output_dir is None else Path(output_dir).resolve()
    config_path = root / "nml-config.toml"
    if not config_path.is_file():
        raise RuntimeError(f"nml-config.toml was not found in {root}")

    try:
        config, resolved_path = _load_config_checked(config_path)
        constants, _ = _load_constants(config)
        dimensions, _ = _load_dimensions(config, constants)
        loaded = _load_namelist_registry(config, resolved_path.parent, SchemaResolver())
        registry = _namelist_registry_by_key(loaded)
        configured_profiles = _iter_file_profiles(config, registry)
    except click.ClickException as exc:
        raise RuntimeError(exc.format_message()) from exc
    except (OSError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc

    namelists = tuple(NamelistPage(item.name, item.key, item.schema) for item in loaded)
    pages_by_key = {page.key: page for page in namelists}
    profiles: list[GuiProfile] = []
    output_paths: dict[Path, str] = {}
    for configured in configured_profiles.values():
        target = (output_root / configured.default_file).resolve()
        try:
            target.relative_to(output_root)
        except ValueError as exc:
            raise RuntimeError(
                f"file profile '{configured.name}' writes outside the output directory"
            ) from exc
        if target == output_root / "nml.json":
            raise RuntimeError(
                f"file profile '{configured.name}' must not use the reserved output nml.json"
            )
        previous = output_paths.get(target)
        if previous is not None:
            raise RuntimeError(
                f"file profiles '{previous}' and '{configured.name}' both write {target}"
            )
        output_paths[target] = configured.name
        pages = tuple(pages_by_key[key] for key in configured.namelists)
        profiles.append(
            GuiProfile(
                name=configured.name,
                key=configured.key,
                title=configured.title or configured.name,
                description=configured.description,
                default_file=configured.default_file,
                pages=pages,
            )
        )

    return GuiProject(
        root,
        constants,
        dimensions,
        tuple(profiles),
        output_root,
        namelists,
    )


def create_virtual_project(
    project: GuiProject,
    name: str,
    default_file: str,
    namelist_keys: Iterable[str],
) -> GuiProject:
    """Return *project* with one virtual profile using selected namelists."""
    profile = _virtual_profile(project, name, default_file, namelist_keys, ())
    return replace(project, profiles=(profile,))


def append_virtual_profile(
    project: GuiProject,
    name: str,
    default_file: str,
    namelist_keys: Iterable[str],
    *,
    reserved_profiles: Iterable[GuiProfile] = (),
) -> GuiProject:
    """Append one user-defined profile to *project*."""
    profile = _virtual_profile(
        project,
        name,
        default_file,
        namelist_keys,
        (*project.profiles, *reserved_profiles),
    )
    return replace(project, profiles=(*project.profiles, profile))


def _virtual_profile(
    project: GuiProject,
    name: str,
    default_file: str,
    namelist_keys: Iterable[str],
    existing: Iterable[GuiProfile],
) -> GuiProfile:
    if not isinstance(name, str):
        raise ValueError("file profile name must be a string")
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("file profile name must not be empty")
    if not isinstance(default_file, str):
        raise ValueError("default file name must be a string")
    clean_default = default_file.strip()
    if not clean_default:
        raise ValueError("default file name must not be empty")

    target = (project.output_root / clean_default).resolve()
    try:
        relative = target.relative_to(project.output_root)
    except ValueError as exc:
        raise ValueError("default file must be inside the output directory") from exc
    if target == project.output_root or target == (project.output_root / "nml.json").resolve():
        raise ValueError("default file must not be the reserved nml.json")

    existing_profiles = tuple(existing)
    for profile in existing_profiles:
        if profile.key == clean_name.lower():
            raise ValueError(f"file profile '{clean_name}' already exists")
        previous_target = (project.output_root / profile.default_file).resolve()
        if (
            previous_target == target
            or profile.default_file.casefold() == clean_default.casefold()
        ):
            raise ValueError(
                f"default file '{clean_default}' is already used by profile '{profile.name}'"
            )

    available = {page.key: page for page in project.namelists}
    selected: list[NamelistPage] = []
    seen: set[str] = set()
    for raw_key in namelist_keys:
        if not isinstance(raw_key, str) or not raw_key.strip():
            raise ValueError("selected namelist names must be non-empty strings")
        key = raw_key.lower()
        if key in seen:
            raise ValueError(f"selected namelist '{raw_key}' is duplicated")
        seen.add(key)
        page = available.get(key)
        if page is None:
            raise ValueError(f"selected namelist '{raw_key}' is unknown")
        selected.append(page)
    if not selected:
        raise ValueError("at least one namelist schema must be selected")

    return GuiProfile(
        name=clean_name,
        key=clean_name.lower(),
        title=clean_name,
        description=None,
        default_file=str(relative),
        pages=tuple(selected),
    )


def empty_document(project: GuiProject) -> dict[str, Any]:
    """Return an empty canonical GUI document."""
    return {
        "format_version": FORMAT_VERSION,
        "dimensions": dict(project.default_dimensions),
        "file_profiles": {},
    }


def discover_json_files(project: GuiProject) -> list[Path]:
    """Return output-directory JSON files, preferring the canonical ``nml.json``."""
    paths = sorted(project.output_root.glob("*.json"), key=lambda path: path.name.casefold())
    canonical = project.output_root / "nml.json"
    if canonical in paths:
        paths.remove(canonical)
        paths.insert(0, canonical)
    return paths


def discover_configuration_files(project: GuiProject) -> list[Path]:
    """Return JSON and namelist inputs, preferring the canonical ``nml.json``."""
    paths = [
        *project.output_root.glob("*.json"),
        *project.output_root.glob("*.nml"),
    ]
    paths.sort(key=lambda path: path.name.casefold())
    canonical = project.output_root / "nml.json"
    if canonical in paths:
        paths.remove(canonical)
        paths.insert(0, canonical)
    return paths


def project_for_document(project: GuiProject, document: Mapping[str, Any]) -> GuiProject:
    """Resolve configured and user-defined profiles referenced by *document*."""
    profiles_raw = document.get("file_profiles", {})
    if not isinstance(profiles_raw, Mapping):
        raise ValueError("JSON 'file_profiles' must be an object")
    if not profiles_raw:
        return project

    entries: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for raw_key, entry in profiles_raw.items():
        if not isinstance(raw_key, str) or not isinstance(entry, Mapping):
            raise ValueError("file profile entries must be named objects")
        key = raw_key.lower()
        if key in entries:
            raise ValueError(
                f"JSON repeats file profile '{raw_key}' case-insensitively"
            )
        entries[key] = (raw_key, entry)

    configured = {profile.key: profile for profile in project.profiles}
    selected = [profile for profile in project.profiles if profile.key in entries]
    active = replace(project, profiles=tuple(selected))
    for key, (raw_key, entry) in entries.items():
        if key in configured:
            continue
        declared = entry.get("profile", raw_key)
        if not isinstance(declared, str) or declared.lower() != key:
            raise ValueError(
                f"file profile '{raw_key}' has mismatched 'profile' metadata"
            )
        default_file = entry.get("default_filename", f"{declared}.nml")
        if not isinstance(default_file, str):
            raise ValueError(
                f"file profile '{raw_key}' default_filename must be a string"
            )
        values = entry.get("values", {})
        if not isinstance(values, Mapping):
            raise ValueError(f"file profile '{raw_key}' values must be an object")
        active = append_virtual_profile(
            active,
            declared,
            default_file,
            values.keys(),
            reserved_profiles=project.profiles,
        )
    return active


def load_document(path: Path, project: GuiProject) -> dict[str, Any]:
    """Load and normalize a canonical aggregate or a single-profile wrapper."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"failed to read {path.name}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"failed to parse {path.name}: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise ValueError("JSON root must be an object")
    version = raw.get("format_version", FORMAT_VERSION)
    if isinstance(version, bool) or not isinstance(version, int) or version != FORMAT_VERSION:
        raise ValueError(f"unsupported JSON format_version '{version}'")

    document = empty_document(project)
    dimensions = raw.get("dimensions", {})
    if not isinstance(dimensions, Mapping):
        raise ValueError("JSON 'dimensions' must be an object")
    seen_dimensions: set[str] = set()
    for raw_name, value in dimensions.items():
        if not isinstance(raw_name, str):
            raise ValueError("dimension names must be strings")
        key = raw_name.lower()
        if key not in project.default_dimensions:
            raise ValueError(f"JSON contains unknown dimension '{raw_name}'")
        if key in seen_dimensions:
            raise ValueError(f"JSON repeats dimension '{raw_name}' case-insensitively")
        seen_dimensions.add(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"dimension '{raw_name}' must be a positive integer")
        document["dimensions"][key] = value

    profiles_raw = raw.get("file_profiles")
    if profiles_raw is None and "values" in raw:
        profile_name = raw.get("profile")
        if not isinstance(profile_name, str):
            raise ValueError("single-profile JSON must define string 'profile'")
        profiles_raw = {profile_name: raw}
    if profiles_raw is None:
        profiles_raw = {}
    if not isinstance(profiles_raw, Mapping):
        raise ValueError("JSON 'file_profiles' must be an object")

    active_project = project_for_document(
        project, {"file_profiles": profiles_raw}
    )

    known_profiles = {profile.key: profile for profile in active_project.profiles}
    configured_profiles = {profile.key: profile for profile in project.profiles}
    sizes = {**project.constants, **document["dimensions"]}
    normalized_profiles: dict[str, dict[str, Any]] = {}
    seen_profiles: set[str] = set()
    for raw_key, entry in profiles_raw.items():
        if not isinstance(raw_key, str) or not isinstance(entry, Mapping):
            raise ValueError("file profile entries must be named objects")
        key = raw_key.lower()
        profile = known_profiles.get(key)
        if profile is None:
            raise ValueError(f"JSON contains unknown file profile '{raw_key}'")
        if key in seen_profiles:
            raise ValueError(f"JSON repeats file profile '{raw_key}' case-insensitively")
        seen_profiles.add(key)
        declared = entry.get("profile", profile.name)
        if not isinstance(declared, str) or declared.lower() != key:
            raise ValueError(f"file profile '{raw_key}' has mismatched 'profile' metadata")
        default_file = entry.get("default_filename", profile.default_file)
        if not isinstance(default_file, str):
            raise ValueError(
                f"file profile '{raw_key}' default_filename must be a string"
            )
        if key in configured_profiles and default_file != profile.default_file:
            raise ValueError(
                f"file profile '{raw_key}' has mismatched 'default_filename' metadata"
            )
        values = _normalize_profile_values(entry.get("values", {}), profile, sizes)
        normalized_profiles[key] = {
            "profile": profile.name,
            "default_filename": profile.default_file,
            "values": values,
        }
    document["file_profiles"] = {
        profile.key: normalized_profiles[profile.key]
        for profile in active_project.profiles
        if profile.key in normalized_profiles
    }
    return document


def load_namelist_document(
    path: Path,
    project: GuiProject,
    dimensions: Mapping[str, int],
) -> tuple[GuiProject, dict[str, Any]]:
    """Load one namelist file as a single editable profile."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"failed to read {path.name}: {exc}") from exc
    parsed = parse_namelist(text, source=str(path))
    if not parsed.groups:
        raise ValueError(f"namelist file '{path.name}' does not contain any groups")

    pages = {page.key: page for page in project.namelists}
    selected: list[NamelistPage] = []
    seen: set[str] = set()
    for group in parsed.groups:
        key = group.name.lower()
        if key in seen:
            raise ValueError(f"namelist '{group.name}' appears multiple times")
        seen.add(key)
        page = pages.get(key)
        if page is None:
            raise ValueError(
                f"Namelist '{group.name}' is not part of this nml-config.toml project"
            )
        selected.append(page)

    clean_dimensions = _normalize_dimensions(dimensions, project)
    selected_keys = tuple(page.key for page in selected)
    selected_key_set = set(selected_keys)
    matches = [
        profile
        for profile in project.profiles
        if Path(profile.default_file).name.casefold() == path.name.casefold()
        and selected_key_set <= {page.key for page in profile.pages}
    ]
    if len(matches) == 1:
        profile = matches[0]
        active_project = replace(project, profiles=(profile,))
    else:
        profile_name = path.stem or path.name
        active_project = create_virtual_project(
            project,
            profile_name,
            path.name,
            selected_keys,
        )
        profile = active_project.profiles[0]
    sizes = {**project.constants, **clean_dimensions}
    values: dict[str, dict[str, Any]] = {}
    for group, page in zip(parsed.groups, selected):
        evaluated = evaluate_group(
            group,
            page.schema,
            source=str(path),
            constants=project.constants,
            dimensions=clean_dimensions,
        )
        values[page.name] = _evaluated_group_values(evaluated, page.schema, sizes)

    normalized = _normalize_profile_values(values, profile, sizes)
    document = {
        "format_version": FORMAT_VERSION,
        "dimensions": clean_dimensions,
        "file_profiles": {
            profile.key: {
                "profile": profile.name,
                "default_filename": profile.default_file,
                "values": normalized,
            }
        },
    }
    return active_project, document


def _evaluated_group_values(
    evaluated: EvaluatedGroup,
    schema: Mapping[str, Any],
    sizes: Mapping[str, int],
) -> dict[str, Any]:
    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        raise ValueError(f"schema for namelist '{evaluated.name}' has invalid properties")
    result: dict[str, Any] = {}
    for name, prop in properties.items():
        if not isinstance(name, str) or not isinstance(prop, Mapping):
            continue
        states = [
            (coordinates, component, state)
            for (root, coordinates, component), state in evaluated.states.items()
            if root == name.lower() and state.explicitly_assigned
        ]
        if not states:
            continue
        if prop.get("type") == "array":
            result[name] = _evaluated_array(prop, states, sizes)
        elif prop.get("type") == "object":
            components = _component_names(prop)
            result[name] = {
                components[component]: _imported_scalar(state.value)
                for _, component, state in states
                if component in components
            }
        else:
            result[name] = _imported_scalar(states[-1][2].value)
    return result


def _evaluated_array(
    schema: Mapping[str, Any],
    states: list[tuple[tuple[int, ...], str | None, LeafState]],
    sizes: Mapping[str, int],
) -> list[Any]:
    items = schema.get("items")
    if not isinstance(items, Mapping):
        raise ValueError("array field must define object 'items'")
    shape = list(resolve_shape(schema, sizes))
    flexible = flex_tail_dims(schema, len(shape))
    for axis in range(len(shape) - flexible, len(shape)):
        used = [coordinates[axis] for coordinates, _, _ in states if coordinates]
        if used:
            shape[axis] = max(used)
    result = _filled(tuple(shape), suggestion(items, sizes))
    components = _component_names(items) if items.get("type") == "object" else {}
    for coordinates, component, state in states:
        target = result
        for coordinate in coordinates[:-1]:
            target = target[coordinate - 1]
        index = coordinates[-1] - 1
        value = _imported_scalar(state.value)
        if component is None:
            target[index] = value
        elif component in components:
            target[index][components[component]] = value
    return result


def _component_names(schema: Mapping[str, Any]) -> dict[str, str]:
    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        return {}
    return {
        name.lower(): name
        for name in properties
        if isinstance(name, str)
    }


def _filled(shape: tuple[int, ...], value: Any) -> Any:
    if not shape:
        return copy.deepcopy(value)
    return [_filled(shape[1:], value) for _ in range(shape[0])]


def _imported_scalar(value: Any) -> Any:
    return value.rstrip() if isinstance(value, str) else copy.deepcopy(value)


def _normalize_profile_values(
    raw: Any,
    profile: GuiProfile,
    sizes: Mapping[str, int],
) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"file profile '{profile.name}' values must be an object")
    pages = {page.key: page for page in profile.pages}
    values: dict[str, dict[str, Any]] = {}
    seen_pages: set[str] = set()
    for raw_name, fields in raw.items():
        if not isinstance(raw_name, str) or not isinstance(fields, Mapping):
            raise ValueError(f"profile '{profile.name}' namelists must be named objects")
        page = pages.get(raw_name.lower())
        if page is None:
            raise ValueError(
                f"profile '{profile.name}' contains unknown namelist '{raw_name}'"
            )
        if page.key in seen_pages:
            raise ValueError(
                f"profile '{profile.name}' repeats namelist '{raw_name}' case-insensitively"
            )
        seen_pages.add(page.key)
        properties = page.schema.get("properties", {})
        if not isinstance(properties, Mapping):
            raise ValueError(f"schema for namelist '{page.name}' has invalid properties")
        canonical = {
            str(name).lower(): (str(name), schema)
            for name, schema in properties.items()
            if isinstance(schema, Mapping)
        }
        normalized_fields: dict[str, Any] = {}
        seen_fields: set[str] = set()
        for raw_field, value in fields.items():
            if not isinstance(raw_field, str):
                raise ValueError(f"namelist '{page.name}' field names must be strings")
            field = canonical.get(raw_field.lower())
            if field is None:
                raise ValueError(f"namelist '{page.name}' contains unknown field '{raw_field}'")
            field_name, field_schema = field
            field_key = field_name.lower()
            if field_key in seen_fields:
                raise ValueError(
                    f"namelist '{page.name}' repeats field '{raw_field}' case-insensitively"
                )
            seen_fields.add(field_key)
            normalized_fields[field_name] = _normalize_value(
                value,
                field_schema,
                sizes,
                f"{page.name}.{field_name}",
            )
        values[page.name] = normalized_fields
    return values


def _normalize_value(
    value: Any,
    schema: Mapping[str, Any],
    sizes: Mapping[str, int],
    path: str,
) -> Any:
    kind = schema.get("type")
    if kind == "array":
        if not isinstance(value, list):
            raise ValueError(f"'{path}' must be an array")
        validate_array_shape(schema, sizes, value)
        items = schema.get("items")
        if not isinstance(items, Mapping):
            raise ValueError(f"array '{path}' must define object items")

        def normalize_items(node: Any, indices: tuple[int, ...] = ()) -> Any:
            if isinstance(node, list):
                return [
                    normalize_items(item, (*indices, index))
                    for index, item in enumerate(node, start=1)
                ]
            suffix = "".join(f"[{index}]" for index in indices)
            return _normalize_value(node, items, sizes, f"{path}{suffix}")

        return normalize_items(value)
    if kind == "object":
        if not isinstance(value, Mapping):
            raise ValueError(f"'{path}' must be an object")
        properties = schema.get("properties")
        if not isinstance(properties, Mapping):
            raise ValueError(f"derived value '{path}' must define properties")
        canonical = {
            str(name).lower(): (str(name), child)
            for name, child in properties.items()
            if isinstance(child, Mapping)
        }
        result: dict[str, Any] = {}
        seen: set[str] = set()
        for raw_name, child_value in value.items():
            if not isinstance(raw_name, str):
                raise ValueError(f"derived value '{path}' component names must be strings")
            child = canonical.get(raw_name.lower())
            if child is None:
                raise ValueError(f"derived value '{path}' contains unknown component '{raw_name}'")
            child_name, child_schema = child
            child_key = child_name.lower()
            if child_key in seen:
                raise ValueError(
                    f"derived value '{path}' repeats component '{raw_name}' case-insensitively"
                )
            seen.add(child_key)
            result[child_name] = _normalize_value(
                child_value,
                child_schema,
                sizes,
                f"{path}.{child_name}",
            )
        return result
    if kind == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"'{path}' must be a boolean")
    elif kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"'{path}' must be an integer")
    elif kind == "number":
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError(f"'{path}' must be a finite number")
    elif kind == "string":
        if not isinstance(value, str):
            raise ValueError(f"'{path}' must be a string")
    else:
        raise ValueError(f"'{path}' has unsupported schema type '{kind}'")
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        raise ValueError(f"'{path}' must be one of the configured enum values")
    return copy.deepcopy(value)


def document_dimensions(document: Mapping[str, Any], project: GuiProject) -> dict[str, int]:
    """Return project defaults updated with the document's runtime dimensions."""
    result = dict(project.default_dimensions)
    raw = document.get("dimensions", {})
    if isinstance(raw, Mapping):
        for name, value in raw.items():
            if name in result and isinstance(value, int) and not isinstance(value, bool):
                result[name] = value
    return result


def profile_values(document: Mapping[str, Any], profile: GuiProfile) -> dict[str, Any]:
    """Return a detached values mapping for *profile*."""
    raw_profiles = document.get("file_profiles", {})
    if not isinstance(raw_profiles, Mapping):
        return {}
    entry = raw_profiles.get(profile.key)
    if not isinstance(entry, Mapping):
        return {}
    values = entry.get("values", {})
    return copy.deepcopy(dict(values)) if isinstance(values, Mapping) else {}


def merge_initial_dimensions(
    document: Mapping[str, Any],
    initial_dimensions: Mapping[str, int],
    project: GuiProject,
) -> dict[str, Any]:
    """Overlay runtime dimensions on a canonical GUI document."""
    if not isinstance(initial_dimensions, Mapping):
        raise ValueError("initial dimensions must be an object")
    updated = copy.deepcopy(dict(document))
    dimensions = document_dimensions(updated, project)
    seen: set[str] = set()
    for raw_name, value in initial_dimensions.items():
        if not isinstance(raw_name, str):
            raise ValueError("initial dimension names must be strings")
        key = raw_name.lower()
        if key not in project.default_dimensions:
            raise ValueError(f"initial dimensions contain unknown dimension '{raw_name}'")
        if key in seen:
            raise ValueError(
                f"initial dimensions repeat dimension '{raw_name}' case-insensitively"
            )
        seen.add(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"dimension '{raw_name}' must be a positive integer")
        dimensions[key] = value
    updated["dimensions"] = dimensions
    return updated


def merge_initial_values(
    document: Mapping[str, Any],
    initial_values: Mapping[str, Any],
    project: GuiProject,
) -> dict[str, Any]:
    """Overlay profile/namelist/field values on a canonical GUI document."""
    if not isinstance(initial_values, Mapping):
        raise ValueError("initial values must be an object")
    updated = copy.deepcopy(dict(document))
    raw_profiles = updated.get("file_profiles", {})
    if not isinstance(raw_profiles, Mapping):
        raise ValueError("JSON 'file_profiles' must be an object")

    profiles: dict[str, dict[str, Any]] = {}
    for profile in project.profiles:
        entry = raw_profiles.get(profile.key)
        if isinstance(entry, Mapping):
            values = entry.get("values", {})
            if not isinstance(values, Mapping):
                raise ValueError(f"file profile '{profile.name}' values must be an object")
            profiles[profile.key] = {
                "profile": profile.name,
                "default_filename": profile.default_file,
                "values": copy.deepcopy(dict(values)),
            }

    known = {profile.key: profile for profile in project.profiles}
    sizes = {**project.constants, **document_dimensions(updated, project)}
    seen: set[str] = set()
    for raw_name, raw_values in initial_values.items():
        if not isinstance(raw_name, str):
            raise ValueError("initial value profile names must be strings")
        key = raw_name.lower()
        selected = known.get(key)
        if selected is None:
            raise ValueError(f"initial values contain unknown file profile '{raw_name}'")
        if key in seen:
            raise ValueError(
                f"initial values repeat file profile '{raw_name}' case-insensitively"
            )
        seen.add(key)
        overlay = _normalize_profile_values(raw_values, selected, sizes)
        entry = profiles.setdefault(
            key,
            {
                "profile": selected.name,
                "default_filename": selected.default_file,
                "values": {},
            },
        )
        combined = entry["values"]
        for namelist, fields in overlay.items():
            combined.setdefault(namelist, {}).update(fields)
        entry["values"] = _normalize_profile_values(combined, selected, sizes)

    updated["file_profiles"] = {
        profile.key: profiles[profile.key]
        for profile in project.profiles
        if profile.key in profiles
    }
    return updated


def render_profile(
    project: GuiProject,
    profile: GuiProfile,
    values: Mapping[str, Any],
    dimensions: Mapping[str, int],
) -> str:
    """Render and validate one profile without writing files."""
    sizes = {**project.constants, **dimensions}
    normalized = _normalize_profile_values(values, profile, sizes)
    ordered_values = {
        page.name: normalized.get(page.name, {})
        for page in profile.pages
    }
    payload = {
        "format_version": FORMAT_VERSION,
        "profile": profile.name,
        "dimensions": dict(dimensions),
        "values": ordered_values,
    }
    rendered = json_to_namelist(payload)
    parsed = parse_namelist(rendered, source=f"profile '{profile.name}'")
    groups = {group.name.lower(): group for group in parsed.groups}
    for page in profile.pages:
        evaluate_group(
            groups[page.key],
            page.schema,
            source=f"profile '{profile.name}'",
            constants=project.constants,
            dimensions=dict(dimensions),
        )
    return rendered


def save_profile(
    project: GuiProject,
    document: Mapping[str, Any],
    profile: GuiProfile,
    values: Mapping[str, Any],
    dimensions: Mapping[str, int],
    json_path: Path | None = None,
) -> dict[str, Any]:
    """Update one profile namelist and its JSON document."""
    return save_profiles(
        project,
        document,
        {profile.key: values},
        dimensions,
        json_path,
    )


def save_profiles(
    project: GuiProject,
    document: Mapping[str, Any],
    values_by_profile: Mapping[str, Mapping[str, Any]],
    dimensions: Mapping[str, int],
    json_path: Path | None = None,
) -> dict[str, Any]:
    """Render requested profiles before writing their namelists and JSON document."""
    clean_dimensions = _normalize_dimensions(dimensions, project)
    sizes = {**project.constants, **clean_dimensions}
    known = {profile.key: profile for profile in project.profiles}
    updates: dict[str, tuple[dict[str, dict[str, Any]], str]] = {}
    for raw_name, values in values_by_profile.items():
        if not isinstance(raw_name, str):
            raise ValueError("file profile names must be strings")
        key = raw_name.lower()
        if key in updates:
            raise ValueError(
                f"file profile '{raw_name}' duplicates another profile case-insensitively"
            )
        profile = known.get(key)
        if profile is None:
            raise ValueError(f"unknown file profile '{raw_name}'")
        if not isinstance(values, Mapping):
            raise ValueError(f"file profile '{profile.name}' values must be an object")
        normalized = _normalize_profile_values(values, profile, sizes)
        rendered = render_profile(project, profile, normalized, clean_dimensions)
        updates[key] = (normalized, rendered)

    updated = copy.deepcopy(dict(document))
    updated["format_version"] = FORMAT_VERSION
    updated["dimensions"] = clean_dimensions
    raw_profiles = updated.get("file_profiles", {})
    if not isinstance(raw_profiles, Mapping):
        raw_profiles = {}
    profiles: dict[str, dict[str, Any]] = {}
    for profile in project.profiles:
        update = updates.get(profile.key)
        if update is not None:
            values = update[0]
        else:
            entry = raw_profiles.get(profile.key)
            if not isinstance(entry, Mapping):
                continue
            values = entry.get("values", {})
            if not isinstance(values, Mapping):
                raise ValueError(
                    f"file profile '{profile.name}' values must be an object"
                )
            values = copy.deepcopy(dict(values))
        profiles[profile.key] = {
            "profile": profile.name,
            "default_filename": profile.default_file,
            "values": values,
        }
    updated["file_profiles"] = profiles

    json_text = json.dumps(updated, indent=2, ensure_ascii=False) + "\n"
    for profile in project.profiles:
        update = updates.get(profile.key)
        if update is not None:
            _atomic_write(project.output_root / profile.default_file, update[1])
    _atomic_write(json_path or project.output_root / "nml.json", json_text)
    return updated


def _normalize_dimensions(
    dimensions: Mapping[str, int], project: GuiProject
) -> dict[str, int]:
    result = dict(project.default_dimensions)
    for name, value in dimensions.items():
        key = name.lower()
        if key not in result:
            raise ValueError(f"unknown dimension '{name}'")
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"dimension '{name}' must be a positive integer")
        result[key] = value
    return result


def profile_is_saved(
    project: GuiProject,
    document: Mapping[str, Any],
    profile: GuiProfile,
) -> bool:
    """Return whether the selected document profile matches its output file."""
    raw_profiles = document.get("file_profiles", {})
    if not isinstance(raw_profiles, Mapping) or profile.key not in raw_profiles:
        return False
    target = project.output_root / profile.default_file
    if not target.is_file():
        return False
    try:
        expected = render_profile(
            project,
            profile,
            profile_values(document, profile),
            document_dimensions(document, project),
        )
        return target.read_text(encoding="utf-8") == expected
    except (OSError, UnicodeError, ValueError, KeyError):
        return False


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
