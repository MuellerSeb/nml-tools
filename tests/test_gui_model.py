"""Headless tests for the optional GUI's project and persistence model."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest

from nml_tools.gui.model import (
    append_virtual_profile,
    create_virtual_project,
    discover_configuration_files,
    discover_json_files,
    document_dimensions,
    empty_document,
    load_document,
    load_namelist_document,
    load_project,
    merge_initial_dimensions,
    merge_initial_values,
    profile_is_saved,
    profile_values,
    project_for_document,
    save_profile,
    save_profiles,
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
              weights:
                type: array
                x-fortran-shape: n_items
                items:
                  type: number
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


def _remove_file_profiles(root: Path) -> None:
    config = root / "nml-config.toml"
    text = config.read_text(encoding="utf-8")
    config.write_text(text.split("[[file_profiles]]", 1)[0], encoding="utf-8")


def test_load_project_preserves_profile_and_page_order(tmp_path: Path) -> None:
    _write_project(tmp_path)

    project = load_project(tmp_path)

    assert project.root == tmp_path.resolve()
    assert project.output_root == tmp_path.resolve()
    assert [profile.name for profile in project.profiles] == ["secondary", "main"]
    assert project.profiles[0].title == "Second profile"
    assert [page.name for page in project.profile("MAIN").pages] == ["beta", "alpha"]
    assert [page.name for page in project.namelists] == ["alpha", "beta"]
    assert project.default_dimensions == {"n_items": 2}


def test_load_project_without_profiles_supports_one_virtual_profile(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    _remove_file_profiles(tmp_path)

    project = load_project(tmp_path)
    virtual = create_virtual_project(
        project,
        "custom",
        "nested/custom.nml",
        ["beta", "alpha"],
    )

    assert project.profiles == ()
    assert [page.name for page in project.namelists] == ["alpha", "beta"]
    assert len(virtual.profiles) == 1
    assert virtual.profile("CUSTOM").default_file == "nested/custom.nml"
    assert [page.name for page in virtual.profile("custom").pages] == ["beta", "alpha"]


def test_append_virtual_profiles_rejects_name_and_output_collisions(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    project = load_project(tmp_path)

    extended = append_virtual_profile(project, "custom", "custom.nml", ["alpha"])

    assert [profile.name for profile in extended.profiles] == [
        "secondary",
        "main",
        "custom",
    ]
    with pytest.raises(ValueError, match="already exists"):
        append_virtual_profile(extended, "CUSTOM", "other.nml", ["beta"])
    with pytest.raises(ValueError, match="already used"):
        append_virtual_profile(extended, "other", "CUSTOM.NML", ["beta"])


@pytest.mark.parametrize(
    ("name", "default_file", "namelists", "message"),
    [
        ("", "custom.nml", ["alpha"], "name must not be empty"),
        ("custom", "", ["alpha"], "file name must not be empty"),
        ("custom", "../custom.nml", ["alpha"], "inside the output directory"),
        ("custom", "nml.json", ["alpha"], "reserved nml.json"),
        ("custom", "custom.nml", [], "at least one"),
        ("custom", "custom.nml", ["missing"], "unknown"),
        ("custom", "custom.nml", ["alpha", "ALPHA"], "duplicated"),
    ],
)
def test_create_virtual_project_rejects_invalid_metadata(
    tmp_path: Path,
    name: str,
    default_file: str,
    namelists: list[str],
    message: str,
) -> None:
    _write_project(tmp_path)
    _remove_file_profiles(tmp_path)
    project = load_project(tmp_path)

    with pytest.raises(ValueError, match=message):
        create_virtual_project(project, name, default_file, namelists)


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
    (output_dir / "main.nml").write_text("", encoding="utf-8")
    assert [path.name for path in discover_configuration_files(project)] == [
        "nml.json",
        "Alpha.json",
        "main.nml",
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


def test_load_document_derives_one_virtual_profile_from_values(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    _remove_file_profiles(tmp_path)
    project = load_project(tmp_path)
    path = tmp_path / "virtual.json"
    path.write_text(
        json.dumps(
            {
                "file_profiles": {
                    "custom": {
                        "profile": "custom",
                        "default_filename": "custom-input.nml",
                        "values": {
                            "beta": {"enabled": True},
                            "alpha": {"count": 3},
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    document = load_document(path, project)

    assert document["file_profiles"]["custom"] == {
        "profile": "custom",
        "default_filename": "custom-input.nml",
        "values": {
            "beta": {"enabled": True},
            "alpha": {"count": 3},
        },
    }

    path.write_text(
        json.dumps(
            {
                "file_profiles": {
                    "custom": {
                        "values": {
                            "alpha": {"count": 3},
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    legacy = load_document(path, project)
    assert (
        legacy["file_profiles"]["custom"]["default_filename"]
        == "custom.nml"
    )


def test_load_document_supports_multiple_virtual_profiles_and_filename_mismatch(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    _remove_file_profiles(tmp_path)
    project = load_project(tmp_path)
    path = tmp_path / "virtual.json"
    path.write_text(
        json.dumps(
            {
                "file_profiles": {
                    "first": {"values": {"alpha": {}}},
                    "second": {"values": {"beta": {}}},
                }
            }
        ),
        encoding="utf-8",
    )
    document = load_document(path, project)
    active = project_for_document(project, document)
    assert [profile.name for profile in active.profiles] == ["first", "second"]
    assert list(document["file_profiles"]) == ["first", "second"]

    configured_root = tmp_path / "configured"
    configured_root.mkdir()
    _write_project(configured_root)
    configured = load_project(configured_root)
    path.write_text(
        json.dumps(
            {
                "file_profiles": {
                    "main": {
                        "default_filename": "different.nml",
                        "values": {},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="mismatched 'default_filename'"):
        load_document(path, configured)


def test_load_namelist_document_imports_indexed_derived_values(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    project = load_project(tmp_path)
    path = tmp_path / "imported.nml"
    path.write_text(
        """&alpha
count = 4
label = "abc"
weights(2) = 2.5
settings(1)%enabled = .true.
settings(1)%name = "first"
settings(2)%name = "second"
/
&beta
enabled = .false.
/
""",
        encoding="utf-8",
    )

    active, document = load_namelist_document(path, project, {"n_items": 2})

    profile = active.profile("imported")
    assert profile.default_file == "imported.nml"
    assert [page.name for page in profile.pages] == ["alpha", "beta"]
    assert profile_values(document, profile) == {
        "alpha": {
            "count": 4,
            "label": "abc",
            "weights": [0.0, 2.5],
            "settings": [
                {"enabled": True, "name": "first"},
                {"enabled": False, "name": "second"},
            ],
        },
        "beta": {"enabled": False},
    }


def test_load_namelist_document_rejects_unknown_group(tmp_path: Path) -> None:
    _write_project(tmp_path)
    path = tmp_path / "other.nml"
    path.write_text("&outside\nvalue = 1\n/\n", encoding="utf-8")

    with pytest.raises(ValueError, match="not part of this nml-config.toml project"):
        load_namelist_document(path, load_project(tmp_path), {"n_items": 2})


def test_load_namelist_document_reuses_matching_configured_profile(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    project = load_project(tmp_path)
    path = tmp_path / "main.nml"
    path.write_text("&alpha\ncount = 4\n/\n", encoding="utf-8")

    active, document = load_namelist_document(path, project, {"n_items": 2})

    assert [profile.name for profile in active.profiles] == ["main"]
    assert list(document["file_profiles"]) == ["main"]
    assert document["file_profiles"]["main"]["values"]["alpha"]["count"] == 4


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
    assert (
        merged["file_profiles"]["main"]["default_filename"]
        == "main.nml"
    )
    assert profile_values(document, project.profile("main"))["alpha"]["count"] == 2


def test_merge_initial_dimensions_overlays_without_mutating_document(tmp_path: Path) -> None:
    _write_project(tmp_path)
    project = load_project(tmp_path)
    document = empty_document(project)

    merged = merge_initial_dimensions(document, {"N_ITEMS": 1}, project)

    assert document_dimensions(merged, project) == {"n_items": 1}
    assert document_dimensions(document, project) == {"n_items": 2}


@pytest.mark.parametrize(
    ("dimensions", "message"),
    [
        ({"unknown": 1}, "unknown dimension"),
        ({"n_items": 0}, "positive integer"),
        ({"n_items": True}, "positive integer"),
        ({"n_items": 1, "N_ITEMS": 2}, "case-insensitively"),
    ],
)
def test_merge_initial_dimensions_rejects_invalid_values(
    tmp_path: Path, dimensions: dict[str, object], message: str
) -> None:
    _write_project(tmp_path)
    project = load_project(tmp_path)

    with pytest.raises(ValueError, match=message):
        merge_initial_dimensions(
            empty_document(project), dimensions, project  # type: ignore[arg-type]
        )


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
    assert (
        saved_json["file_profiles"]["main"]["default_filename"]
        == "main.nml"
    )
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


def test_save_profiles_validates_every_profile_before_writing(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    project = load_project(tmp_path)

    with pytest.raises(ValueError, match="must be an integer"):
        save_profiles(
            project,
            empty_document(project),
            {
                "secondary": {"beta": {"enabled": True}},
                "main": {"alpha": {"count": "invalid"}},
            },
            {"n_items": 2},
        )

    assert not (tmp_path / "secondary.nml").exists()
    assert not (tmp_path / "main.nml").exists()
    assert not (tmp_path / "nml.json").exists()

    document = save_profiles(
        project,
        empty_document(project),
        {
            "secondary": {"beta": {"enabled": True}},
            "main": {
                "beta": {"enabled": False},
                "alpha": {"count": 2},
            },
        },
        {"n_items": 2},
    )

    assert (tmp_path / "secondary.nml").is_file()
    assert (tmp_path / "main.nml").is_file()
    assert document["file_profiles"]["secondary"]["default_filename"] == "secondary.nml"
    assert document["file_profiles"]["main"]["default_filename"] == "main.nml"


def test_save_profile_accepts_an_explicit_json_destination(tmp_path: Path) -> None:
    _write_project(tmp_path)
    project = load_project(tmp_path)
    target = tmp_path / "separate.json"

    document = save_profile(
        project,
        empty_document(project),
        project.profile("secondary"),
        {"beta": {"enabled": True}},
        {"n_items": 2},
        json_path=target,
    )

    assert json.loads(target.read_text(encoding="utf-8")) == document
    assert not (tmp_path / "nml.json").exists()
