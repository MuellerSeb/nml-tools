"""Direct namelist persistence and profile selection checks."""

import os
from dataclasses import replace
from pathlib import Path
from textwrap import dedent

import pytest

from nml_tools._dimensions import DimensionSource
from nml_tools.gui.model import (
    GUI_REF_ORIGIN_KEY,
    InputArray,
    create_virtual_project,
    load_profile,
    load_project,
    load_project_profile_file,
    overlay_values,
    recover_dimensions,
    save_profiles,
    save_project_profile,
    suggestion,
    validate_project_filename,
    validate_project_name,
)


def test_input_array_equality_includes_explicit_assignments():
    left = InputArray([1.0, 2.0], {(1,)})
    assert left != InputArray([1.0, 2.0], {(2,)})
    assert left == InputArray([1.0, 2.0], {(1,)})


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


def test_profiles_filter_in_toml_order_and_validate_names(tmp_path):
    _write_project(tmp_path)
    project = load_project(tmp_path, tmp_path / "output", {"MAIN": ["alpha"], "secondary": []})
    assert [p.name for p in project.profiles] == ["secondary", "main"]
    assert [p.name for p in project.profile("main").pages] == ["alpha"]
    assert [p.name for p in project.profile("secondary").pages] == ["beta"]
    assert len(load_project(tmp_path, file_profiles={}).profiles) == 2
    for selection in ({"missing": []}, {"main": ["missing"]}, {"main": "alpha"}):
        with pytest.raises(ValueError):
            load_project(tmp_path, file_profiles=selection)


def test_load_project_falls_back_to_pyproject_tool_table(tmp_path):
    _write_project(tmp_path)
    config = (tmp_path / "nml-config.toml").read_text(encoding="utf-8")
    config = "[tool.nml-tools]\n" + config.replace(
        "[dimensions]", "[tool.nml-tools.dimensions]"
    ).replace("[[namelists]]", "[[tool.nml-tools.namelists]]").replace(
        "[[file_profiles]]", "[[tool.nml-tools.file_profiles]]"
    )
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(config, encoding="utf-8")
    assert load_project(tmp_path).config_path == (tmp_path / "nml-config.toml").resolve()
    assert load_project(pyproject).config_path == pyproject.resolve()
    (tmp_path / "nml-config.toml").unlink()
    project = load_project(tmp_path)
    assert project.config_path == pyproject.resolve()
    assert [profile.key for profile in project.profiles] == ["secondary", "main"]


def test_load_project_marks_only_referenced_arrays(tmp_path):
    _write_project(tmp_path)
    schemas = tmp_path / "nml-schemas"
    (schemas / "parameter.yml").write_text(
        "$defs:\n  parameter:\n    type: array\n    x-fortran-shape: 2\n"
        "    items:\n      type: number\n",
        encoding="utf-8",
    )
    alpha = schemas / "alpha.yml"
    alpha.write_text(
        alpha.read_text(encoding="utf-8").replace(
            "  weights:\n    type: array\n    x-fortran-shape: n_items\n"
            "    items:\n      type: number\n",
            "  weights:\n    $ref: parameter.yml#/$defs/parameter\n",
        ),
        encoding="utf-8",
    )
    properties = load_project(tmp_path).profile("main").pages[1].schema["properties"]
    assert properties["weights"][GUI_REF_ORIGIN_KEY] == "parameter.yml#/$defs/parameter"
    assert GUI_REF_ORIGIN_KEY not in properties["settings"]


def test_save_reload_preserves_unselected_groups_and_uses_no_json(tmp_path):
    _write_project(tmp_path)
    project = load_project(tmp_path, file_profiles={"main": ["alpha"]})
    path = tmp_path / "main.nml"
    untouched = "! keep this\n&beta enabled=.true. / ! keep too\n"
    path.write_text(untouched + "&ALPHA count=1 /\n")
    profile = project.profile("main")
    values = {
        "alpha": {
            "count": 4,
            "label": 'a "quote" / !',
            "weights": [1.5, 2.5],
            "options": {"enabled": True, "label": "single"},
            "settings": [{"enabled": True, "name": "first"}, {"enabled": False, "name": "second"}],
        }
    }
    save_profiles(project, [(profile, values, {"n_items": 2})])
    saved = path.read_text()
    assert saved.startswith(untouched)
    assert "weights(2) = 2.5" in saved
    assert "settings(1)%enabled = .true." in saved
    assert load_profile(project, profile, {"n_items": 2}) == values
    assert not list(tmp_path.glob("*.json"))


def test_all_saves_validate_before_replacing_any_file(tmp_path):
    _write_project(tmp_path)
    project = load_project(tmp_path)
    path = tmp_path / "secondary.nml"
    original = "&beta enabled=.true. /\n"
    path.write_text(original)
    with pytest.raises(ValueError):
        save_profiles(
            project,
            [
                (project.profile("secondary"), {"beta": {"enabled": False}}, {}),
                (project.profile("main"), {"alpha": {"count": "invalid"}}, {}),
            ],
        )
    assert path.read_text() == original
    assert not (tmp_path / "main.nml").exists()


def test_all_saves_roll_back_when_one_replace_fails(tmp_path, monkeypatch):
    from nml_tools.gui import model

    _write_project(tmp_path)
    project = load_project(tmp_path)
    secondary = tmp_path / "secondary.nml"
    main = tmp_path / "main.nml"
    secondary.write_text("&beta enabled=.true. /\n")
    main.write_text("&alpha count=1 /\n")
    original = {path: path.read_text() for path in (secondary, main)}
    replace = model.os.replace

    def fail_second(source, destination):
        source_path, destination_path = Path(source), Path(destination)
        if destination_path == main and ".backup." not in source_path.name:
            raise OSError("simulated replacement failure")
        replace(source, destination)

    monkeypatch.setattr(model.os, "replace", fail_second)
    with pytest.raises(OSError, match="simulated replacement failure"):
        save_profiles(
            project,
            [
                (project.profile("secondary"), {"beta": {"enabled": False}}, {}),
                (project.profile("main"), {"alpha": {"count": 2}}, {}),
            ],
        )
    assert {path: path.read_text() for path in (secondary, main)} == original
    assert not list(tmp_path.glob(".*.nml.*"))


def test_missing_input_errors_and_partial_array_input(tmp_path):
    _write_project(tmp_path)
    project = load_project(tmp_path)
    profile = project.profile("main")
    assert load_profile(project, profile, {}) == {}
    path = tmp_path / "main.nml"
    path.write_text("&alpha count=2 weights(2)=3.5 options%enabled=.true. /\n")
    values = load_profile(project, profile, {})
    assert values["alpha"]["weights"] == [0.0, 3.5]
    assert values["alpha"]["options"] == {"enabled": True}
    for text in (
        "&alpha count=2 / &alpha count=3 /",
        "&alpha count=2 weights(3)=1 /",
        "&alpha count=2",
    ):
        path.write_text(text)
        with pytest.raises(ValueError):
            load_profile(project, profile, {})


def test_complete_arrays_and_recover_dimensions_before_loading(tmp_path):
    _write_project(tmp_path)
    project = load_project(tmp_path)
    profile = project.profile("main")
    schema = next(page.schema for page in project.namelists if page.key == "alpha")
    weights = schema["properties"]["weights"]
    weights["x-fortran-shape"] = [2, "n_items"]
    path = tmp_path / "main.nml"
    for size in (3, 1):
        values = {"alpha": {"count": 1, "weights": [[4.0] * size, [5.0] * size]}}
        save_profiles(project, [(profile, values, {"n_items": size})])
        assert f"weights(2,{size}) =" in path.read_text()
        dimensions = recover_dimensions(project)
        assert dimensions == {"n_items": size}
        assert load_profile(project, profile, dimensions)["alpha"]["weights"] == [
            [4.0] * size,
            [5.0] * size,
        ]
    weights["x-fortran-shape"] = "n_items"
    path.write_text("&alpha count=1 weights(2:6:2)=3*1.0 /\n")
    assert recover_dimensions(project) == {"n_items": 6}
    assert recover_dimensions(project, overrides={"N_ITEMS": 7}) == {"n_items": 7}
    with pytest.raises(ValueError, match="smaller than saved extent"):
        recover_dimensions(project, overrides={"n_items": 1})
    path.write_text("&alpha count=1 weights(2:)=3*1.0 /\n")
    assert recover_dimensions(project) == {"n_items": 4}
    schema["properties"]["n_items"] = {"type": "integer"}
    path.write_text("&alpha count=1 n_items=7 weights(1)=4.0 /\n")
    assert recover_dimensions(project) == {"n_items": 7}


def test_array_defaults_use_fortran_order_and_declared_padding():
    schema = {
        "type": "array",
        "items": {"type": "integer"},
        "x-fortran-shape": [2, 2],
        "default": [1, 2, 3, 4],
        "examples": [[9]],
    }
    assert suggestion(schema, {}) == [[1, 3], [2, 4]]
    assert suggestion({**schema, "x-fortran-default-order": "C"}, {}) == [[1, 2], [3, 4]]
    assert suggestion({**schema, "default": [1], "x-fortran-default-pad": 7}, {}) == [
        [1, 7],
        [7, 7],
    ]
    assert suggestion({"type": "integer", "default": 4, "examples": [9]}, {}) == 4


def test_overlay_keeps_unspecified_derived_components():
    original = {"alpha": {"options": {"enabled": False, "label": "keep"}}}
    merged = overlay_values(original, {"alpha": {"options": {"enabled": True}}})
    assert merged["alpha"]["options"] == {"enabled": True, "label": "keep"}
    assert original["alpha"]["options"]["enabled"] is False


def test_multidimensional_and_deferred_arrays_round_trip(tmp_path):
    _write_project(tmp_path)
    project = load_project(tmp_path)
    profile = project.profile("main")
    alpha = next(page.schema for page in profile.pages if page.name == "alpha")
    alpha["properties"]["weights"]["x-fortran-shape"] = [2, 2]
    alpha["properties"]["settings"]["x-fortran-shape"] = [2, 2]
    values = {
        "alpha": {
            "count": 1,
            "weights": [[1.0, 2.0], [3.0, 4.0]],
            "settings": [
                [{"enabled": True, "name": "a"}, {"enabled": False, "name": "b"}],
                [{"enabled": False, "name": "c"}, {"enabled": True, "name": "d"}],
            ],
        }
    }
    save_profiles(project, [(profile, values, {})])
    assert "weights(2,1) = 3.0" in (tmp_path / "main.nml").read_text()
    assert 'settings(1,2)%name = "b"' in (tmp_path / "main.nml").read_text()
    assert load_profile(project, profile, {}) == values
    alpha["properties"]["weights"]["x-fortran-shape"] = ":"
    values["alpha"]["weights"] = [1.0, 2.0, 3.0]
    save_profiles(project, [(profile, values, {})])
    assert load_profile(project, profile, {}) == values


def test_virtual_profiles_without_toml_profiles_and_output_safety(tmp_path):
    _write_project(tmp_path)
    config = tmp_path / "nml-config.toml"
    config.write_text(config.read_text().split("[[file_profiles]]")[0])
    project = load_project(tmp_path)
    assert not project.profiles
    virtual = create_virtual_project(project, "custom", "custom.nml", ["alpha"])
    assert virtual.profiles[0].name == "custom"
    with pytest.raises(ValueError, match="inside"):
        create_virtual_project(project, "bad", "../outside.nml", ["alpha"])


def test_external_project_profiles_cannot_escape_output_directory(tmp_path):
    _write_project(tmp_path)
    project = load_project(tmp_path)
    path = tmp_path / "unsafe.toml"
    path.write_text(
        '[[file_profiles]]\nname = "unsafe"\ndefault_file = "../outside.nml"\n'
        'namelists = ["alpha"]\n\n[[project_profiles]]\nname = "unsafe"\n'
        'file_profiles = ["unsafe"]\n'
    )
    with pytest.raises(ValueError, match="inside"):
        load_project_profile_file(project, path)


def test_save_rejects_strings_that_fortran_would_truncate(tmp_path):
    _write_project(tmp_path)
    project = load_project(tmp_path)
    with pytest.raises(ValueError, match="length"):
        save_profiles(
            project,
            [
                (
                    project.profile("main"),
                    {
                        "alpha": {"count": 1, "label": "x" * 33},
                    },
                    {},
                )
            ],
        )
    assert not (tmp_path / "main.nml").exists()


def test_mixed_dimension_sources_recover_unsourced_extents(tmp_path):
    _write_project(tmp_path)
    project = replace(
        load_project(tmp_path),
        default_dimensions={"n_items": 2, "n_source": 1},
        dimension_sources={"n_source": DimensionSource("alpha", "count")},
    )
    (tmp_path / "main.nml").write_text("&alpha count=4 weights(5)=1.0 /\n")
    assert recover_dimensions(project) == {"n_items": 5, "n_source": 4}


def test_sparse_derived_components_round_trip_without_suggestions(tmp_path):
    _write_project(tmp_path)
    project = load_project(tmp_path)
    profile = project.profile("main")
    path = tmp_path / "main.nml"
    path.write_text("&alpha count=1 settings(1)%enabled=.true. /\n")
    values = load_profile(project, profile, {"n_items": 2})
    save_profiles(project, [(profile, values, {"n_items": 2})])
    text = path.read_text()
    assert "settings(1)%enabled = .true." in text
    assert "settings(1)%name" not in text


def test_custom_project_ownership_names_and_file_mode(tmp_path):
    _write_project(tmp_path)
    project = load_project(tmp_path)
    profile = project.project_profiles[0]
    custom = replace(
        profile,
        name="my-project_1",
        key="my-project_1",
        custom=True,
        source=None,
        toml_file="chosen.toml",
    )
    assert validate_project_name(custom.name) == custom.name
    path = save_project_profile(project, custom)
    assert path.name == "chosen.toml"
    owned = replace(custom, source=path)
    os.chmod(path, 0o640)
    save_project_profile(project, owned)
    assert path.stat().st_mode & 0o777 == 0o640
    with pytest.raises(ValueError, match="TOML file 'chosen.toml' already exists"):
        save_project_profile(project, replace(owned, source=None))
    with pytest.raises(ValueError, match="may contain"):
        validate_project_name("bad/name")
    with pytest.raises(ValueError, match="plain .toml filename"):
        validate_project_filename("folder/project.toml")
    for reserved in ("nml-config.toml", "pyproject.toml"):
        with pytest.raises(ValueError, match="reserved for nml-tools configuration"):
            validate_project_filename(reserved)
