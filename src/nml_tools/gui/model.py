"""Qt-independent project and persistence model used by the GUI."""

from __future__ import annotations

import copy
import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import click

from .._namelist_eval import evaluate_group
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
from .arrays import validate_array_shape

FORMAT_VERSION = 1
MISSING = object()


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

    if not configured_profiles:
        raise RuntimeError("nml-config.toml does not define any file profiles")

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
        pages = tuple(
            NamelistPage(item.name, item.key, item.schema)
            for item in (registry[key] for key in configured.namelists)
        )
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

    return GuiProject(root, constants, dimensions, tuple(profiles), output_root)


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

    known_profiles = {profile.key: profile for profile in project.profiles}
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
        values = _normalize_profile_values(entry.get("values", {}), profile, sizes)
        normalized_profiles[key] = {"profile": profile.name, "values": values}
    document["file_profiles"] = {
        profile.key: normalized_profiles[profile.key]
        for profile in project.profiles
        if profile.key in normalized_profiles
    }
    return document


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
            key, {"profile": selected.name, "values": {}}
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
) -> dict[str, Any]:
    """Update ``nml.json`` and the profile namelist using atomic file replacements."""
    clean_dimensions = _normalize_dimensions(dimensions, project)
    sizes = {**project.constants, **clean_dimensions}
    normalized = _normalize_profile_values(values, profile, sizes)
    rendered = render_profile(project, profile, normalized, clean_dimensions)

    updated = copy.deepcopy(dict(document))
    updated["format_version"] = FORMAT_VERSION
    updated["dimensions"] = clean_dimensions
    profiles = updated.setdefault("file_profiles", {})
    if not isinstance(profiles, dict):
        profiles = {}
        updated["file_profiles"] = profiles
    profiles[profile.key] = {"profile": profile.name, "values": normalized}
    updated["file_profiles"] = {
        item.key: profiles[item.key]
        for item in project.profiles
        if item.key in profiles
    }

    json_text = json.dumps(updated, indent=2, ensure_ascii=False) + "\n"
    _atomic_write(project.output_root / profile.default_file, rendered)
    _atomic_write(project.output_root / "nml.json", json_text)
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
