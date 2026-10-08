"""Direct namelist persistence and profile selection checks."""

from pathlib import Path
from textwrap import dedent

import pytest

from nml_tools.gui.model import (
    create_virtual_project,
    import_profile,
    load_profile,
    load_project,
    overlay_values,
    recover_dimensions,
    save_profiles,
    suggestion,
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


def test_missing_input_import_errors_and_partial_array_input(tmp_path):
    _write_project(tmp_path)
    project = load_project(tmp_path)
    assert load_profile(project, project.profile("main"), {}) == {}
    path = tmp_path / "imported.nml"
    path.write_text("&alpha count=2 weights(2)=3.5 options%enabled=.true. /\n")
    profile, values = import_profile(project, path, {})
    assert profile.default_file == "imported.nml"
    assert values["alpha"]["weights"] == [0.0, 3.5]
    assert values["alpha"]["options"] == {"enabled": True}
    for text in (
        "&unknown a=1 /",
        "&alpha count=2 / &alpha count=3 /",
        "&alpha count=2 weights(3)=1 /",
        "&alpha count=2",
    ):
        path.write_text(text)
        with pytest.raises(ValueError):
            import_profile(project, path, {})


def test_complete_arrays_and_recover_dimensions_before_loading(tmp_path):
    _write_project(tmp_path)
    project = load_project(tmp_path)
    profile = project.profile("main")
    schema = next(page.schema for page in project.namelists if page.key == "alpha")
    weights = schema["properties"]["weights"]
    weights.update({"x-fortran-shape": [2, "n_items"], "x-fortran-flex-tail-dims": 1})
    path = tmp_path / "main.nml"
    for size in (3, 1):
        values = {"alpha": {"count": 1, "weights": [[4.0], [5.0]]}}
        save_profiles(project, [(profile, values, {"n_items": size})])
        assert f"weights(2,{size}) =" in path.read_text()
        dimensions = recover_dimensions(project)
        assert dimensions == {"n_items": size}
        assert load_profile(project, profile, dimensions)["alpha"]["weights"] == [
            [4.0] + [0.0] * (size - 1),
            [5.0] + [0.0] * (size - 1),
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
