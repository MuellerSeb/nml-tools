"""Headless tests for the optional GUI's project and persistence model."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest

from nml_tools.gui.model import (
    discover_json_files,
    document_dimensions,
    empty_document,
    load_document,
    load_project,
    merge_initial_values,
    profile_is_saved,
    profile_values,
    save_profile,
)


def _write_project(root: Path, *, duplicate_output: bool = False) -> None:
    schemas = root / "nml-schemas"
    schemas.mkdir()
    (schemas / "alpha.yml").write_text(
        dedent(
            """
            title: Alpha settings
            x-fortran-namelist: alpha
            type: object
            properties:
              count:
                type: integer
              label:
                type: string
                x-fortran-len: 32
              options:
                type: object
                x-fortran-type: options_t
                properties:
                  enabled:
                    type: boolean
                  label:
                    type: string
                    x-fortran-len: 16
              settings:
                type: array
                x-fortran-shape: n_items
                items:
                  type: object
                  x-fortran-type: setting_t
                  properties:
                    enabled:
                      type: boolean
                    name:
                      type: string
                      x-fortran-len: 16
            required: [count]
            """
        ).lstrip(),
        encoding="utf-8",
    )
    (schemas / "beta.yml").write_text(
        dedent(
            """
            title: Beta settings
            x-fortran-namelist: beta
            type: object
            properties:
              enabled:
                type: boolean
            """
        ).lstrip(),
        encoding="utf-8",
    )
    second_output = "main.nml" if duplicate_output else "secondary.nml"
    (root / "nml-config.toml").write_text(
        dedent(
            f"""
            [dimensions]
            n_items = {{ default = 2 }}

            [[namelists]]
            name = "alpha"
            schema = "nml-schemas/alpha.yml"

            [[namelists]]
            name = "beta"
            schema = "nml-schemas/beta.yml"

            [[file_profiles]]
            name = "secondary"
            title = "Second profile"
            default_file = "{second_output}"
            namelists = ["beta"]

            [[file_profiles]]
            name = "main"
            default_file = "main.nml"
            namelists = ["beta", "alpha"]
            required = ["alpha"]
            """
        ).lstrip(),
        encoding="utf-8",
    )


def test_load_project_preserves_profile_and_page_order(tmp_path: Path) -> None:
    _write_project(tmp_path)

    project = load_project(tmp_path)

    assert project.root == tmp_path.resolve()
    assert project.output_root == tmp_path.resolve()
    assert [profile.name for profile in project.profiles] == ["secondary", "main"]
    assert project.profiles[0].title == "Second profile"
    assert [page.name for page in project.profile("MAIN").pages] == ["beta", "alpha"]
    assert project.default_dimensions == {"n_items": 2}


def test_load_project_uses_explicit_folder_outside_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schemas_dir = tmp_path / "schemas"
    output_dir = tmp_path / "output"
    schemas_dir.mkdir()
    output_dir.mkdir()
    _write_project(schemas_dir)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    project = load_project(schemas_dir, output_dir)

    assert project.root == schemas_dir.resolve()
    assert project.output_root == output_dir.resolve()
    assert [page.name for page in project.profile("main").pages] == ["beta", "alpha"]


def test_load_project_rejects_profiles_with_the_same_output(tmp_path: Path) -> None:
    _write_project(tmp_path, duplicate_output=True)

    with pytest.raises(RuntimeError, match="both write"):
        load_project(tmp_path)


def test_load_project_rejects_output_outside_output_directory(tmp_path: Path) -> None:
    schemas_dir = tmp_path / "schemas"
    output_dir = tmp_path / "output"
    schemas_dir.mkdir()
    _write_project(schemas_dir)
    config = schemas_dir / "nml-config.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            'default_file = "main.nml"',
            'default_file = "../schemas/escaped.nml"',
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="outside the output directory"):
        load_project(schemas_dir, output_dir)


def test_discover_json_files_prefers_nml_json_then_sorts(tmp_path: Path) -> None:
    schemas_dir = tmp_path / "schemas"
    output_dir = tmp_path / "output"
    schemas_dir.mkdir()
    output_dir.mkdir()
    _write_project(schemas_dir)
    project = load_project(schemas_dir, output_dir)
    for name in ("z.json", "nml.json", "Alpha.json"):
        (output_dir / name).write_text("{}", encoding="utf-8")
    (schemas_dir / "schema-only.json").write_text("{}", encoding="utf-8")
    (output_dir / "nested").mkdir()
    (output_dir / "nested" / "ignored.json").write_text("{}", encoding="utf-8")

    assert [path.name for path in discover_json_files(project)] == [
        "nml.json",
        "Alpha.json",
        "z.json",
    ]


def test_load_document_normalizes_canonical_and_single_profile_json(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    project = load_project(tmp_path)
    aggregate = tmp_path / "aggregate.json"
    aggregate.write_text(
        json.dumps(
            {
                "format_version": 1,
                "dimensions": {"N_ITEMS": 3},
                "file_profiles": {
                    "MAIN": {
                        "profile": "main",
                        "values": {"ALPHA": {"COUNT": 4}},
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    document = load_document(aggregate, project)

    assert document_dimensions(document, project) == {"n_items": 3}
    assert profile_values(document, project.profile("main")) == {
        "alpha": {"count": 4}
    }

    single = tmp_path / "single.json"
    single.write_text(
        json.dumps({"profile": "secondary", "values": {"beta": {"enabled": True}}}),
        encoding="utf-8",
    )
    loaded_single = load_document(single, project)
    assert profile_values(loaded_single, project.profile("secondary")) == {
        "beta": {"enabled": True}
    }


def test_load_document_rejects_unknown_profile_namelist_and_field(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    project = load_project(tmp_path)
    bad_values = [
        {"file_profiles": {"unknown": {"values": {}}}},
        {"profile": "main", "values": {"unknown": {}}},
        {"profile": "main", "values": {"alpha": {"unknown": 1}}},
    ]

    for index, payload in enumerate(bad_values):
        path = tmp_path / f"bad-{index}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError):
            load_document(path, project)


def test_load_document_rejects_invalid_types_and_normalizes_derived_components(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    project = load_project(tmp_path)
    invalid = tmp_path / "invalid.json"
    invalid.write_text(
        json.dumps(
            {
                "profile": "main",
                "values": {"beta": {"enabled": "false"}},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must be a boolean"):
        load_document(invalid, project)

    derived = tmp_path / "derived.json"
    derived.write_text(
        json.dumps(
            {
                "profile": "main",
                "values": {"alpha": {"options": {"ENABLED": True}}},
            }
        ),
        encoding="utf-8",
    )
    document = load_document(derived, project)
    assert profile_values(document, project.profile("main")) == {
        "alpha": {"options": {"enabled": True}}
    }

    derived.write_text(
        json.dumps(
            {
                "profile": "main",
                "values": {"alpha": {"options": {"typo": True}}},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown component"):
        load_document(derived, project)


def test_load_document_validates_version_and_canonicalizes_profile_order(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    project = load_project(tmp_path)
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "file_profiles": {
                    "main": {"values": {}},
                    "secondary": {"values": {}},
                },
            }
        ),
        encoding="utf-8",
    )
    document = load_document(path, project)
    assert list(document["file_profiles"]) == ["secondary", "main"]

    path.write_text(json.dumps({"format_version": 2}), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported JSON format_version"):
        load_document(path, project)


def test_merge_initial_values_overlays_loaded_document(tmp_path: Path) -> None:
    _write_project(tmp_path)
    project = load_project(tmp_path)
    document_path = tmp_path / "nml.json"
    document_path.write_text(
        json.dumps(
            {
                "file_profiles": {
                    "main": {
                        "values": {
                            "alpha": {"count": 2, "label": "saved"},
                            "beta": {"enabled": False},
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    document = load_document(document_path, project)

    merged = merge_initial_values(
        document,
        {"MAIN": {"ALPHA": {"COUNT": 7}}},
        project,
    )

    assert profile_values(merged, project.profile("main")) == {
        "alpha": {"count": 7, "label": "saved"},
        "beta": {"enabled": False},
    }
    assert profile_values(document, project.profile("main"))["alpha"]["count"] == 2


def test_merge_initial_values_uses_existing_validation(tmp_path: Path) -> None:
    _write_project(tmp_path)
    project = load_project(tmp_path)

    with pytest.raises(ValueError, match="must be an integer"):
        merge_initial_values(
            empty_document(project),
            {"main": {"alpha": {"count": "seven"}}},
            project,
        )


def test_save_profile_round_trips_derived_values_and_omits_absent_fields(
    tmp_path: Path,
) -> None:
    schemas_dir = tmp_path / "schemas"
    output_dir = tmp_path / "output"
    schemas_dir.mkdir()
    _write_project(schemas_dir)
    project = load_project(schemas_dir, output_dir)
    profile = project.profile("main")
    values = {
        "beta": {"enabled": True},
        "alpha": {
            "count": 3,
            "options": {"enabled": False},
            "settings": [{"enabled": True}, {"name": "second"}],
        },
    }

    document = save_profile(
        project,
        {"format_version": 1, "dimensions": {}, "file_profiles": {}},
        profile,
        values,
        {"n_items": 2},
    )

    rendered = (output_dir / "main.nml").read_text(encoding="utf-8")
    assert "options%enabled = .false." in rendered
    assert "settings(1)%enabled = .true." in rendered
    assert 'settings(2)%name = "second"' in rendered
    assert "label" not in rendered
    saved_json = json.loads((output_dir / "nml.json").read_text(encoding="utf-8"))
    assert saved_json == document
    assert not (schemas_dir / "nml.json").exists()
    assert not (schemas_dir / "main.nml").exists()
    assert "label" not in saved_json["file_profiles"]["main"]["values"]["alpha"]
    assert profile_is_saved(project, document, profile) is True

    main_namelist = rendered
    document = save_profile(
        project,
        document,
        project.profile("secondary"),
        {"beta": {"enabled": False}},
        {"n_items": 2},
    )
    assert set(document["file_profiles"]) == {"main", "secondary"}
    assert list(document["file_profiles"]) == ["secondary", "main"]
    assert (output_dir / "main.nml").read_text(encoding="utf-8") == main_namelist
    assert "enabled = .false." in (output_dir / "secondary.nml").read_text(
        encoding="utf-8"
    )

    (output_dir / "main.nml").write_text(
        rendered + "! changed\n", encoding="utf-8"
    )
    assert profile_is_saved(project, document, profile) is False
