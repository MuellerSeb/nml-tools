"""Qt-independent project loading and direct namelist persistence."""

from __future__ import annotations

import copy
import math
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from itertools import product
from pathlib import Path
from typing import Any, Mapping, cast

import click
import yaml

from .._dimensions import DimensionSource, infer_runtime_dimensions
from .._namelist_eval import EvaluatedGroup, LeafState, _expand_values, _value_count, evaluate_group
from .._namelist_parser import RawValue, ScalarSelector, parse_namelist
from ..cli import (
    _load_config_checked,
    _load_config_metadata,
    _load_constants,
    _load_dimensions,
    _load_namelist_registry,
    _load_toml,
    _namelist_registry_by_key,
)
from ..codegen_fortran import _format_scalar_default
from ..schema import SchemaResolver
from ..validate import _scalar_constraints, _validate_scalar_value, validate_schema_defaults
from .arrays import initial_array, resolve_shape

MISSING = object()
GUI_REF_ORIGIN_KEY = "_nml_tools_gui_ref_origin"


def _mark_referenced_arrays(loaded: Iterable[Any]) -> None:
    """Keep array-reference identity needed only by the GUI table layout."""
    for namelist in loaded:
        path = namelist.entry["schema"]
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        raw_properties = raw.get("properties", {}) if isinstance(raw, Mapping) else {}
        for name, child in namelist.schema.get("properties", {}).items():
            source = raw_properties.get(name, {})
            if child.get("type") == "array" and isinstance(source.get("$ref"), str):
                child[GUI_REF_ORIGIN_KEY] = source["$ref"]


class InputArray(list[Any]):
    """Dense editor values with the indices selected for namelist output."""

    def __init__(self, values: list[Any], assigned: set[tuple[int, ...]]):
        super().__init__(values)
        self.assigned = assigned


def suggestion(schema: Mapping[str, Any], sizes: Mapping[str, int]) -> Any:
    """Return the deterministic editable value used for an unset schema field."""
    examples = schema.get("examples")
    if "default" in schema:
        candidate = copy.deepcopy(schema["default"])
    elif isinstance(examples, list) and examples:
        candidate = copy.deepcopy(examples[0])
    else:
        candidate = MISSING

    kind = schema.get("type")
    if kind == "array":
        items = schema.get("items")
        if not isinstance(items, Mapping):
            raise ValueError("array field must define object 'items'")
        leaf = suggestion(items, sizes)
        if "default" in schema and isinstance(candidate, list):
            shape = resolve_shape(schema, sizes)
            count = math.prod(shape)
            if schema.get("x-fortran-default-repeat"):
                candidate = [candidate[index % len(candidate)] for index in range(count)]
            elif "x-fortran-default-pad" in schema:
                pad = schema["x-fortran-default-pad"]
                pad = pad if isinstance(pad, list) else [pad]
                candidate += [pad[index % len(pad)] for index in range(count - len(candidate))]
            if len(candidate) != count:
                raise ValueError("array default does not match its configured dimensions")
            result = _filled(shape, leaf)
            for index, coordinates in enumerate(product(*(range(size) for size in shape))):
                if schema.get("x-fortran-default-order", "F").upper() == "F":
                    index = sum(c * math.prod(shape[:axis]) for axis, c in enumerate(coordinates))
                target = result
                for coordinate in coordinates[:-1]:
                    target = target[coordinate]
                target[coordinates[-1]] = copy.deepcopy(candidate[index])
            return result
        if "default" in items:
            candidate = MISSING
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
    required: tuple[str, ...] = ()


@dataclass(frozen=True)
class GuiProjectProfile:
    """An ordered set of namelist files edited as one project."""

    name: str
    key: str
    title: str
    description: str | None
    profiles: tuple[GuiProfile, ...]
    source: Path | None = None
    custom: bool = False


@dataclass(frozen=True)
class GuiProject:
    """Resolved nml-tools project data needed by the GUI."""

    root: Path
    constants: dict[str, int]
    default_dimensions: dict[str, int]
    profiles: tuple[GuiProfile, ...]
    output_dir: Path | None = None
    namelists: tuple[NamelistPage, ...] = ()
    project_profiles: tuple[GuiProjectProfile, ...] = ()
    dimension_sources: dict[str, DimensionSource] = field(default_factory=dict)

    @property
    def output_root(self) -> Path:
        """Return the directory used for namelist output."""
        return self.output_dir or self.root

    def profile(self, key: str) -> GuiProfile:
        """Find a configured profile by its case-insensitive key."""
        for profile in self.profiles:
            if profile.key == key.lower():
                return profile
        raise KeyError(key)

    def project_profile(self, key: str) -> GuiProjectProfile:
        """Find a project profile by its case-insensitive name."""
        for profile in self.project_profiles:
            if profile.key == key.lower():
                return profile
        raise KeyError(key)


def load_project(
    schemas_dir: Path | str | None = None,
    output_dir: Path | str | None = None,
    project_profiles: str
    | Mapping[str, Mapping[str, list[str]]]
    | Mapping[str, list[str]]
    | None = None,
    *,
    file_profiles: Mapping[str, list[str]] | None = None,
) -> GuiProject:
    """Load schemas and selected project profiles from the project config."""
    if file_profiles is not None:
        if project_profiles is not None:
            raise ValueError("pass project_profiles or file_profiles, not both")
        project_profiles = file_profiles
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
        _mark_referenced_arrays(loaded)
        registry = _namelist_registry_by_key(loaded)
        metadata = _load_config_metadata(config, registry)
        configured_profiles = metadata.file_profiles
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
                required=tuple(configured.required),
            )
        )

    by_key = {profile.key: profile for profile in profiles}
    configured_projects = tuple(
        GuiProjectProfile(
            configured.name,
            configured.key,
            configured.title or configured.name,
            configured.description,
            tuple(by_key[key] for key in configured.file_profiles),
            config_path,
        )
        for configured in metadata.project_profiles.values()
    )
    if not configured_projects:
        configured_projects = (
            GuiProjectProfile("default", "default", "Default", None, tuple(profiles), config_path),
        )
    project = GuiProject(
        root,
        constants,
        dimensions,
        tuple(profiles),
        output_root,
        namelists,
        configured_projects,
        metadata.dimension_sources,
    )
    if project_profiles is None or project_profiles == {}:
        return project
    if isinstance(project_profiles, str):
        try:
            selected_project = project.project_profile(project_profiles)
        except KeyError as exc:
            raise ValueError(f"unknown project profile '{project_profiles}'") from exc
        return replace(
            project,
            profiles=selected_project.profiles,
            project_profiles=(selected_project,),
        )
    if not isinstance(project_profiles, Mapping):
        raise ValueError("project_profiles must be a name or mapping")
    if project_profiles and all(isinstance(value, list) for value in project_profiles.values()):
        selected_profiles = _select_profiles(
            project, cast(Mapping[str, list[str]], project_profiles)
        )
        implicit = GuiProjectProfile(
            "default", "default", "Default", None, selected_profiles, custom=True
        )
        return replace(project, profiles=selected_profiles, project_profiles=(implicit,))
    if not all(isinstance(value, Mapping) for value in project_profiles.values()):
        raise ValueError("project_profiles must map project names to file-profile mappings")
    selected_projects: list[GuiProjectProfile] = []
    union: dict[str, GuiProfile] = {}
    for project_name, selection in project_profiles.items():
        if not isinstance(project_name, str):
            raise ValueError("project profile names must be strings")
        configured_project = next(
            (item for item in project.project_profiles if item.key == project_name.lower()), None
        )
        available = configured_project.profiles if configured_project else project.profiles
        base = replace(project, profiles=available)
        chosen = (
            available
            if not selection
            else _select_profiles(base, cast(Mapping[str, list[str]], selection))
        )
        item = GuiProjectProfile(
            configured_project.name if configured_project else project_name,
            project_name.lower(),
            configured_project.title if configured_project else project_name,
            configured_project.description if configured_project else None,
            chosen,
            configured_project.source if configured_project else None,
            configured_project is None,
        )
        selected_projects.append(item)
        union.update((profile.key, profile) for profile in chosen)
    return replace(
        project, profiles=tuple(union.values()), project_profiles=tuple(selected_projects)
    )


def _select_profiles(
    project: GuiProject, file_profiles: Mapping[str, list[str]]
) -> tuple[GuiProfile, ...]:
    """Apply the legacy file-profile selection shape."""
    selected: dict[str, GuiProfile] = {}
    for name, names in file_profiles.items():
        if not isinstance(name, str) or not isinstance(names, list):
            raise ValueError("file_profiles must map profile names to lists of namelist names")
        try:
            profile = project.profile(name)
        except KeyError as exc:
            raise ValueError(f"unknown file profile '{name}'") from exc
        if profile.key in selected:
            raise ValueError(f"duplicate file profile '{name}'")
        if not all(isinstance(item, str) for item in names):
            raise ValueError(f"namelist names for '{name}' must be strings")
        keys = {item.lower() for item in names}
        unknown = keys - {page.key for page in profile.pages}
        if unknown:
            raise ValueError(f"profile '{name}' has no namelists: {', '.join(sorted(unknown))}")
        selected[profile.key] = replace(
            profile, pages=tuple(page for page in profile.pages if not keys or page.key in keys)
        )
    return tuple(selected[p.key] for p in project.profiles if p.key in selected)


def create_virtual_project(
    project: GuiProject,
    name: str,
    default_file: str,
    namelist_keys: Iterable[str],
) -> GuiProject:
    """Return one user-defined file profile using registered namelists."""
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
    if target == project.output_root:
        raise ValueError("default file must name a file")

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

    profile = GuiProfile(
        name=clean_name,
        key=clean_name.lower(),
        title=clean_name,
        description=None,
        default_file=str(relative),
        pages=tuple(selected),
    )
    return replace(project, profiles=(profile,))


def discover_project_files(project: GuiProject) -> tuple[Path, ...]:
    """Find additional project-profile TOML files in input and output roots."""
    config = (project.root / "nml-config.toml").resolve()
    paths = {
        path.resolve()
        for root in {project.root, project.output_root}
        for path in root.glob("*.toml")
        if path.name != "nml-config.toml" and path.resolve() != config
    }
    return tuple(sorted(paths))


def load_project_profile_file(project: GuiProject, path: Path) -> GuiProjectProfile:
    """Load one custom project profile against the configured schema registry."""
    data = _load_toml(path)
    available = {profile.key: profile for profile in project.profiles}
    pages = {page.key: page for page in project.namelists}
    raw_files = data.get("file_profiles", [])
    if not isinstance(raw_files, list):
        raise ValueError("'file_profiles' must be a list")
    custom_keys: set[str] = set()
    for entry in raw_files:
        if not isinstance(entry, Mapping):
            raise ValueError("each file profile must be a table")
        name = entry.get("name")
        default_file = entry.get("default_file")
        members = entry.get("namelists")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("file profile must define a non-empty name")
        if not isinstance(default_file, str) or not default_file.strip():
            raise ValueError(f"file profile '{name}' must define default_file")
        if (
            not isinstance(members, list)
            or not members
            or not all(isinstance(item, str) for item in members)
        ):
            raise ValueError(f"file profile '{name}' must define namelist names")
        unknown = [item for item in members if item.lower() not in pages]
        if unknown:
            raise ValueError(f"file profile '{name}' has unknown namelists: {', '.join(unknown)}")
        key = name.lower()
        if key in custom_keys:
            raise ValueError(f"file profile '{name}' is defined more than once")
        custom_keys.add(key)
        member_keys = [item.lower() for item in members]
        if len(member_keys) != len(set(member_keys)):
            raise ValueError(f"file profile '{name}' repeats a namelist")
        required = entry.get("required", [])
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            raise ValueError(f"file profile '{name}' required members must be strings")
        required_keys = [item.lower() for item in required]
        if len(required_keys) != len(set(required_keys)) or not set(required_keys) <= set(
            member_keys
        ):
            raise ValueError(f"file profile '{name}' has invalid required namelists")
        title = _optional_toml_text(entry, "title", f"file profile '{name}'")
        description = _optional_toml_text(entry, "description", f"file profile '{name}'")
        profile = GuiProfile(
            name.strip(),
            key,
            title or name,
            description,
            default_file.strip(),
            tuple(pages[item] for item in member_keys),
            tuple(required_keys),
        )
        _profile_path(project, profile)
        available[key] = profile
    raw_projects = data.get("project_profiles")
    if not isinstance(raw_projects, list) or len(raw_projects) != 1:
        raise ValueError("additional TOML must define exactly one project profile")
    entry = raw_projects[0]
    if not isinstance(entry, Mapping):
        raise ValueError("project profile must be a table")
    name = entry.get("name")
    members = entry.get("file_profiles")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("project profile must define a non-empty name")
    if (
        not isinstance(members, list)
        or not members
        or not all(isinstance(item, str) for item in members)
    ):
        raise ValueError(f"project profile '{name}' must define file profile names")
    member_keys = [item.lower() for item in members]
    if len(member_keys) != len(set(member_keys)):
        raise ValueError(f"project profile '{name}' repeats a file profile")
    unknown = [item for item in members if item.lower() not in available]
    if unknown:
        raise ValueError(f"project profile '{name}' has unknown files: {', '.join(unknown)}")
    title = _optional_toml_text(entry, "title", f"project profile '{name}'")
    description = _optional_toml_text(entry, "description", f"project profile '{name}'")
    return GuiProjectProfile(
        name.strip(),
        name.lower(),
        title or name,
        description,
        tuple(available[item] for item in member_keys),
        path.resolve(),
        True,
    )


def _optional_toml_text(entry: Mapping[str, Any], key: str, label: str) -> str | None:
    """Read one optional non-empty string from a custom project file."""
    value = entry.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} '{key}' must be a string")
    return value.strip() or None


def save_project_profile(project: GuiProject, profile: GuiProjectProfile) -> Path:
    """Persist one custom project profile in the schema directory."""
    if not profile.custom:
        raise ValueError("configured project profiles are read-only")
    if not profile.key.replace("-", "_").isalnum():
        raise ValueError("project name may contain only letters, numbers, '-' and '_'")
    path = (project.root / f"{profile.key}.toml").resolve()
    if project.root not in path.parents:
        raise ValueError("custom project file must remain inside the schema directory")
    if path.exists() and (profile.source is None or path != profile.source.resolve()):
        existing = load_project_profile_file(project, path)
        if existing.key != profile.key:
            raise ValueError(f"refusing to overwrite unrelated TOML file '{path.name}'")
    lines: list[str] = []
    for item in profile.profiles:
        lines.extend(
            [
                "[[file_profiles]]",
                f'name = "{_toml_escape(item.name)}"',
                f'default_file = "{_toml_escape(item.default_file)}"',
                "namelists = ["
                + ", ".join(f'"{_toml_escape(page.name)}"' for page in item.pages)
                + "]",
            ]
        )
        if item.title != item.name:
            lines.append(f'title = "{_toml_escape(item.title)}"')
        if item.description:
            lines.append(f'description = "{_toml_escape(item.description)}"')
        if item.required:
            lines.append(
                "required = ["
                + ", ".join(f'"{_toml_escape(name)}"' for name in item.required)
                + "]"
            )
        lines.append("")
    lines.extend(
        [
            "[[project_profiles]]",
            f'name = "{_toml_escape(profile.name)}"',
            "file_profiles = ["
            + ", ".join(f'"{_toml_escape(item.name)}"' for item in profile.profiles)
            + "]",
            "",
        ]
    )
    if profile.title != profile.name:
        lines.insert(-1, f'title = "{_toml_escape(profile.title)}"')
    if profile.description:
        lines.insert(-1, f'description = "{_toml_escape(profile.description)}"')
    _atomic_write(path, "\n".join(lines))
    return path


def _toml_escape(value: str) -> str:
    """Escape a string for the small TOML subset written by the GUI."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _evaluated_group_values(
    evaluated: EvaluatedGroup,
    schema: Mapping[str, Any],
    sizes: Mapping[str, int],
) -> dict[str, Any]:
    """Convert evaluated namelist leaves into schema-shaped GUI values."""
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
    """Rebuild a dense editable array while retaining assigned indices."""
    items = schema.get("items")
    if not isinstance(items, Mapping):
        raise ValueError("array field must define object 'items'")
    shape = list(resolve_shape(schema, sizes))
    raw = schema["x-fortran-shape"]
    raw = raw if isinstance(raw, list) else [raw]
    for axis in range(len(shape)):
        if raw[axis] != ":":
            continue
        used = [coordinates[axis] for coordinates, _, _ in states if coordinates]
        if used:
            shape[axis] = max(used)
    result = cast(list[Any], suggestion({**schema, "x-fortran-shape": shape}, sizes))
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
    return InputArray(result, {coordinates for coordinates, _, _ in states})


def _component_names(schema: Mapping[str, Any]) -> dict[str, str]:
    """Map lower-case derived component names to schema spelling."""
    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        return {}
    return {name.lower(): name for name in properties if isinstance(name, str)}


def _filled(shape: tuple[int, ...], value: Any) -> Any:
    """Build a nested array of copied values for an evaluated shape."""
    if not shape:
        return copy.deepcopy(value)
    return [_filled(shape[1:], value) for _ in range(shape[0])]


def _imported_scalar(value: Any) -> Any:
    """Copy an imported scalar and trim Fortran string padding."""
    return value.rstrip() if isinstance(value, str) else copy.deepcopy(value)


def _normalize_profile_values(
    raw: Any,
    profile: GuiProfile,
    sizes: Mapping[str, int],
) -> dict[str, dict[str, Any]]:
    """Validate profile names and normalize fields to schema spelling."""
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
            raise ValueError(f"profile '{profile.name}' contains unknown namelist '{raw_name}'")
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
    """Validate and normalize one scalar, array, or derived value."""
    kind = schema.get("type")
    if kind == "array":
        if not isinstance(value, list):
            raise ValueError(f"'{path}' must be an array")
        items = schema.get("items")
        if not isinstance(items, Mapping):
            raise ValueError(f"array '{path}' must define object items")
        assigned = value.assigned if isinstance(value, InputArray) else None
        value = initial_array(schema, sizes, value, suggestion(items, sizes), strict=True)

        def normalize_items(node: Any, indices: tuple[int, ...] = ()) -> Any:
            if isinstance(node, list):
                return [
                    normalize_items(item, (*indices, index))
                    for index, item in enumerate(node, start=1)
                ]
            if assigned is not None and indices not in assigned:
                return node
            suffix = "".join(f"[{index}]" for index in indices)
            return _normalize_value(node, items, sizes, f"{path}{suffix}")

        normalized = normalize_items(value)
        return InputArray(normalized, assigned) if assigned is not None else normalized
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
    constraints = _scalar_constraints(path, schema, str(kind), dict(sizes), None)
    _validate_scalar_value(path, value, constraints)
    return copy.deepcopy(value)


def _normalize_dimensions(dimensions: Mapping[str, int], project: GuiProject) -> dict[str, int]:
    """Merge dimension overrides with project defaults and validate them."""
    if not isinstance(dimensions, Mapping):
        raise ValueError("dimensions must map names to positive integers")
    result = dict(project.default_dimensions)
    for name, value in dimensions.items():
        if not isinstance(name, str):
            raise ValueError("dimension names must be strings")
        key = name.lower()
        if key not in result:
            raise ValueError(f"unknown dimension '{name}'")
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"dimension '{name}' must be a positive integer")
        result[key] = value
    return result


def overlay_values(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Overlay supplied fields/components without discarding sibling values."""
    result = copy.deepcopy(dict(base))
    for name, value in override.items():
        if isinstance(value, Mapping) and isinstance(result.get(name), Mapping):
            result[name] = overlay_values(result[name], value)
        else:
            result[name] = copy.deepcopy(value)
    return result


def _profile_path(project: GuiProject, profile: GuiProfile) -> Path:
    """Resolve and confine a profile's file beneath the output directory."""
    path = (project.output_root / profile.default_file).resolve()
    if path == project.output_root or project.output_root not in path.parents:
        raise ValueError("profile output must be a file inside the output directory")
    return path


def _parsed_groups(path: Path) -> tuple[str, dict[str, Any]]:
    """Read a namelist file and index its unique groups by lower-case name."""
    text = path.read_text(encoding="utf-8")
    parsed = parse_namelist(text, source=str(path))
    groups = {}
    for group in parsed.groups:
        key = group.name.lower()
        if key in groups:
            raise ValueError(f"namelist '{group.name}' appears multiple times in {path}")
        groups[key] = group
    if not groups:
        raise ValueError(f"namelist file '{path}' contains no namelist groups")
    return text, groups


def recover_dimensions(
    project: GuiProject,
    paths: Iterable[Path] | None = None,
    overrides: Mapping[str, int] | None = None,
) -> dict[str, int]:
    """Infer editable sizes from saved indices before evaluating the namelists."""
    if paths is None:
        paths = (_profile_path(project, profile) for profile in project.profiles)
    pages = project.namelists or tuple(page for p in project.profiles for page in p.pages)
    schemas = {page.key: page.schema for page in pages}
    unique_paths = tuple(dict.fromkeys(paths))
    if project.dimension_sources:
        parsed = [
            parse_namelist(path.read_text(encoding="utf-8"), source=str(path))
            for path in unique_paths
            if path.exists()
        ]
        return infer_runtime_dimensions(
            parsed,
            sources=project.dimension_sources,
            schemas=schemas,
            defaults=project.default_dimensions,
            overrides=overrides,
            constants=project.constants,
        )
    extents: dict[str, int] = {}
    explicit: dict[str, int] = {}
    # Compatibility for older configs which predate explicit dimension sources.
    for path in unique_paths:
        if not path.exists():
            continue
        _, groups = _parsed_groups(path)
        saved: dict[str, int] = {}
        for key, group in groups.items():
            properties = {
                name.lower(): prop
                for name, prop in schemas.get(key, {}).get("properties", {}).items()
            }
            for assignment in group.assignments:
                part = assignment.designator.parts[0]
                name = part.name.lower()
                prop = properties.get(name, {})
                if (
                    name in project.default_dimensions
                    and prop.get("type") == "integer"
                    and len(assignment.designator.parts) == 1
                    and not part.selectors
                ):
                    for value in _expand_values(assignment):
                        if isinstance(value, RawValue) and not value.quoted:
                            saved[name] = int(value.source_text.split("_")[0])
                if prop.get("type") != "array":
                    continue
                raw = prop["x-fortran-shape"]
                shape = raw if isinstance(raw, list) else [raw]
                selectors = part.selectors[0].selectors if part.selectors else ()
                count = _value_count(assignment)
                items = prop["items"]
                if items.get("type") == "object" and len(assignment.designator.parts) == 1:
                    count = (count + len(items["properties"]) - 1) // len(items["properties"])
                for axis, token in enumerate(shape):
                    dimension = str(token).lower()
                    if dimension not in project.default_dimensions:
                        continue
                    selector = selectors[axis] if axis < len(selectors) else None
                    extent = 0
                    if isinstance(selector, ScalarSelector):
                        extent = selector.value + (max(0, count - 1) if len(shape) == 1 else 0)
                    elif selector is not None and selector.upper is not None:
                        stride = selector.stride or 1
                        indices = range(
                            selector.lower or 1, selector.upper + (1 if stride > 0 else -1), stride
                        )
                        extent = max(indices[0], indices[-1]) if indices else 0
                    elif len(shape) == 1:
                        lower = (selector.lower or 1) if selector is not None else 1
                        stride = (selector.stride or 1) if selector is not None else 1
                        extent = max(lower, lower + (count - 1) * stride) if count else 0
                    if extent > 0:
                        extents[dimension] = max(extents.get(dimension, 0), extent)
        for name, size in saved.items():
            if name in explicit and explicit[name] != size:
                raise ValueError(f"conflicting saved dimension '{name}'")
            explicit[name] = size
    _normalize_dimensions(overrides or {}, project)
    # ponytail: sparse external files give lower bounds, not declared capacities.
    dimensions = _normalize_dimensions(
        {**extents, **explicit, **{name.lower(): size for name, size in (overrides or {}).items()}},
        project,
    )
    for name, extent in extents.items():
        if dimensions[name] < extent:
            raise ValueError(f"dimension '{name}' is smaller than saved extent {extent}")
    return dimensions


def ensure_dimension_sources(
    project: GuiProject, profiles: Iterable[GuiProfile]
) -> tuple[GuiProfile, ...]:
    """Ensure every configured dimension source occurs in exactly one file."""
    result = list(profiles)
    pages = {page.key: page for page in project.namelists}
    used = set().union(*(_schema_dimensions(page.schema) for item in result for page in item.pages))
    for dimension, source in project.dimension_sources.items():
        if dimension not in used:
            continue
        occurrences = [
            index
            for index, profile in enumerate(result)
            if any(page.key == source.namelist for page in profile.pages)
        ]
        if len(occurrences) > 1:
            raise ValueError(
                f"dimension '{dimension}' source namelist '{source.namelist}' "
                "must occur in exactly one file profile"
            )
        if occurrences:
            continue
        source_page = pages.get(source.namelist)
        if source_page is None:
            raise ValueError(
                f"dimension '{dimension}' source namelist '{source.namelist}' is unavailable"
            )
        if not result:
            raise ValueError(
                f"add a file profile for dimension source namelist '{source.namelist}'"
            )
        result[0] = replace(result[0], pages=(*result[0].pages, source_page))
    return tuple(result)


def _schema_dimensions(schema: Mapping[str, Any]) -> set[str]:
    """Collect symbolic array dimensions used by a resolved schema."""
    result: set[str] = set()
    shape = schema.get("x-fortran-shape")
    for token in shape if isinstance(shape, list) else [shape]:
        if isinstance(token, str) and token != ":":
            result.add(token.lower())
    properties = schema.get("properties", {})
    if isinstance(properties, Mapping):
        for child in properties.values():
            if isinstance(child, Mapping):
                result.update(_schema_dimensions(child))
    items = schema.get("items")
    if isinstance(items, Mapping):
        result.update(_schema_dimensions(items))
    return result


def dimension_source_values(
    project: GuiProject,
    profiles: Iterable[GuiProfile],
    dimensions: Mapping[str, int],
) -> dict[str, dict[str, dict[str, int]]]:
    """Return project dimensions expressed as their source namelist fields."""
    result: dict[str, dict[str, dict[str, int]]] = {}
    profile_items = tuple(profiles)
    used = set().union(
        *(_schema_dimensions(page.schema) for item in profile_items for page in item.pages)
    )
    for dimension, source in project.dimension_sources.items():
        if dimension not in used:
            continue
        matches = [
            profile
            for profile in profile_items
            if any(page.key == source.namelist for page in profile.pages)
        ]
        if len(matches) != 1:
            raise ValueError(
                f"dimension '{dimension}' source namelist '{source.namelist}' "
                "must occur in exactly one file profile"
            )
        profile = matches[0]
        page = next(page for page in profile.pages if page.key == source.namelist)
        result.setdefault(profile.key, {}).setdefault(page.name, {})[source.property] = dimensions[
            dimension
        ]
    return result


def load_profile(
    project: GuiProject,
    profile: GuiProfile,
    dimensions: Mapping[str, int],
    path: Path | None = None,
) -> dict[str, Any]:
    """Read selected groups; absent fields are supplied by the form's defaults."""
    dimensions = _normalize_dimensions(dimensions, project)
    for page in profile.pages:
        validate_schema_defaults(page.schema, constants=project.constants, dimensions=dimensions)
    path = _profile_path(project, profile) if path is None else path
    if not path.exists():
        return {}
    _, groups = _parsed_groups(path)
    sizes = {**project.constants, **dimensions}
    result = {}
    for page in profile.pages:
        group = groups.get(page.key)
        if group is not None:
            evaluated = evaluate_group(
                group,
                page.schema,
                source=str(path),
                constants=project.constants,
                dimensions=dimensions,
            )
            result[page.name] = _evaluated_group_values(evaluated, page.schema, sizes)
    return result


def _assignments(name: str, value: Any, schema: Mapping[str, Any]) -> Iterable[str]:
    """Yield indexed Fortran assignments recursively for one schema value."""
    if schema["type"] == "array":
        assigned = value.assigned if isinstance(value, InputArray) else None

        def elements(node: Any, indices: tuple[int, ...] = ()) -> Iterable[str]:
            if isinstance(node, list):
                for index, child in enumerate(node, 1):
                    yield from elements(child, (*indices, index))
            else:
                if assigned is not None and indices not in assigned:
                    return
                suffix = ",".join(map(str, indices))
                yield from _assignments(f"{name}({suffix})", node, schema["items"])

        yield from elements(value)
    elif schema["type"] == "object":
        for component, child in value.items():
            yield from _assignments(f"{name}%{component}", child, schema["properties"][component])
    else:
        if schema["type"] == "string" and schema.get("format") == "file-path" and value == "":
            return
        category = "real" if schema["type"] == "number" else schema["type"]
        yield f"  {name} = {_format_scalar_default(value, None, category)}"


def render_profile(
    project: GuiProject,
    profile: GuiProfile,
    values: Mapping[str, Any],
    dimensions: Mapping[str, int],
) -> dict[str, str]:
    """Render and validate individual groups, retaining explicit Fortran indices."""
    dimensions = _normalize_dimensions(dimensions, project)
    normalized = _normalize_profile_values(values, profile, {**project.constants, **dimensions})
    rendered = {}
    for page in profile.pages:
        if page.name not in normalized:
            continue
        lines = [f"&{page.name}"]
        for name, value in normalized[page.name].items():
            lines.extend(_assignments(name, value, page.schema["properties"][name]))
        text = "\n".join([*lines, "/", ""])
        evaluate_group(
            parse_namelist(text).groups[0],
            page.schema,
            constants=project.constants,
            dimensions=dimensions,
        )
        rendered[page.key] = text
    return rendered


def save_profiles(
    project: GuiProject,
    updates: Iterable[tuple[GuiProfile, Mapping[str, Any], Mapping[str, int]]],
) -> None:
    """Validate all updates, then replace files without removing unselected groups."""
    outputs: dict[Path, str] = {}
    for profile, values, dimensions in updates:
        path = _profile_path(project, profile)
        if path in outputs:
            raise ValueError(f"multiple open profiles write to '{path}'")
        rendered = render_profile(project, profile, values, dimensions)
        text, groups = _parsed_groups(path) if path.exists() else ("", {})
        for key, group in reversed(list(groups.items())):
            if key in rendered:
                replacement = rendered.pop(key).rstrip("\n")
                text = text[: group.span.start.offset] + replacement + text[group.span.end.offset :]
        for replacement in rendered.values():
            text += ("\n" if text and not text.endswith("\n") else "") + replacement
        outputs[path] = text
    for path, text in outputs.items():
        _atomic_write(path, text)


def _atomic_write(path: Path, content: str) -> None:
    """Replace a namelist file atomically after writing beside the target."""
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
