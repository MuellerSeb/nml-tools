"""Small offscreen widget checks, skipped when no Qt binding is installed."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from nml_tools.gui.model import GuiProfile, GuiProject, NamelistPage, profile_values

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from qtpy.QtWidgets import QApplication, QCheckBox
except Exception as exc:  # QtPy may be present without an installed Qt binding.
    pytest.skip(f"optional Qt GUI is unavailable: {exc}", allow_module_level=True)

np = pytest.importorskip("numpy")
fields = pytest.importorskip("nml_tools.gui.fields")
app_module = pytest.importorskip("nml_tools.gui.app")
ArrayField = fields.ArrayField
NamelistForm = fields.NamelistForm
ScalarField = fields.ScalarField
ObjectField = fields.ObjectField
ConfigurationDialog = app_module.ConfigurationDialog
ProfileTab = app_module.ProfileTab


@pytest.fixture(scope="module")
def application() -> Any:
    app = QApplication.instance() or QApplication([])
    yield app


def test_namelist_form_always_includes_enabled_suggested_fields(application: Any) -> None:
    form = NamelistForm(
        {
            "type": "object",
            "required": ["count"],
            "properties": {
                "count": {"type": "integer"},
                "label": {"type": "string", "default": "suggested"},
                "enabled": {"type": "boolean"},
            },
        },
        {"count": 3},
        {},
    )

    assert form.values() == {"count": 3, "label": "suggested", "enabled": False}
    assert all(row.field.isEnabled() for row in form.rows.values())
    assert not any(box.text() == "Set" for box in form.findChildren(QCheckBox))

    label = form.rows["label"]
    assert isinstance(label.field, ScalarField)
    label.field.set_value("chosen")
    assert form.values()["label"] == "chosen"

    form.reset()
    assert form.values() == {"count": 0, "label": "suggested", "enabled": False}


def test_required_field_labels_end_with_asterisk_including_nested(
    application: Any,
) -> None:
    form = NamelistForm(
        {
            "type": "object",
            "required": ["settings"],
            "properties": {
                "label": {"type": "string", "title": "Label"},
                "settings": {
                    "type": "object",
                    "x-fortran-type": "setting_t",
                    "required": ["count"],
                    "properties": {
                        "count": {"type": "integer", "title": "Count"},
                        "name": {"type": "string", "title": "Name"},
                    },
                },
            },
        },
        None,
        {},
    )

    layout = form.layout()
    assert layout.labelForField(form.rows["label"]).text() == "Label (label)"
    assert layout.labelForField(form.rows["settings"]).text() == "settings *"

    settings = form.rows["settings"].field
    assert isinstance(settings, ObjectField)
    nested_layout = settings.layout()
    assert nested_layout.labelForField(settings.rows["count"]).text() == "Count (count) *"
    assert nested_layout.labelForField(settings.rows["name"]).text() == "Name (name)"


def test_derived_array_structured_round_trip(application: Any) -> None:
    schema = {
        "type": "array",
        "x-fortran-shape": 2,
        "items": {
            "type": "object",
            "x-fortran-type": "setting_t",
            "properties": {
                "count": {"type": "integer", "title": "Count"},
                "enabled": {"type": "boolean"},
                "name": {"type": "string", "title": "Name"},
            },
        },
    }
    values = [
        {"count": 1, "enabled": True},
        {"count": 2, "name": "second"},
    ]
    field = ArrayField("settings", schema, values, {})

    structured = field._structured_array(np)

    assert structured.dtype.names == ("count", "enabled", "name")
    assert field._objects_from_structured(structured, 1, np) == values


def test_derived_array_editor_applies_structured_changes(application: Any) -> None:
    module = pytest.importorskip("guidata.widgets.arrayeditor")
    data = np.zeros((1, 1), dtype=[("yStart", np.int64)])
    editor = fields._derived_array_editor(module.ArrayEditor, None)
    try:
        assert editor.setup_and_check(data, "Evaluation period")
        model = editor.arraywidgets[0].model
        assert model.setData(model.index(0, 0), "1991")
        editor.accept()
        assert data["yStart"][0, 0] == 1991
    finally:
        editor.close()


def test_configuration_dialog_uses_dynamic_profiles_and_prefers_nml_json(
    application: Any, tmp_path: Path
) -> None:
    (tmp_path / "z.json").write_text("{}", encoding="utf-8")
    (tmp_path / "nml.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "dimensions": {"n_items": 3},
                "file_profiles": {
                    "first": {"values": {}},
                    "second": {"values": {}},
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "first.nml").write_text("", encoding="utf-8")
    (tmp_path / "second.nml").write_text("", encoding="utf-8")
    project = GuiProject(
        root=tmp_path,
        constants={},
        default_dimensions={"n_items": 2},
        profiles=(
            GuiProfile("first", "first", "First", None, "first.nml", ()),
            GuiProfile("second", "second", "Second", None, "second.nml", ()),
        ),
    )

    dialog = ConfigurationDialog(project)

    assert dialog.json_combo.currentText() == "nml.json"
    assert dialog.dimension_boxes["n_items"].value() == 3
    assert dialog.tabs.count() == 1
    assert dialog.tabs.tabText(0) == "Config"

    dialog._run_configuration()

    assert [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())] == [
        "Config",
        "First",
        "Second",
    ]
    assert list(dialog.profile_tabs) == ["first", "second"]
    assert dialog.save_all.isEnabled()

    dialog.json_combo.setCurrentIndex(dialog.json_combo.findText("z.json"))

    assert dialog.tabs.count() == 1
    assert dialog.profile_tabs == {}
    assert not dialog.save_all.isEnabled()
    dialog.close()


def test_configuration_dialog_populates_editable_initial_values(
    application: Any, tmp_path: Path
) -> None:
    schema = {
        "x-fortran-namelist": "run",
        "type": "object",
        "properties": {
            "count": {"type": "integer"},
            "label": {"type": "string", "x-fortran-len": 16},
        },
    }
    profile = GuiProfile(
        "main",
        "main",
        "Main",
        None,
        "main.nml",
        (NamelistPage("run", "run", schema),),
    )
    project = GuiProject(tmp_path, {}, {}, (profile,))
    (tmp_path / "nml.json").write_text(
        json.dumps(
            {
                "file_profiles": {
                    "main": {"values": {"run": {"count": 1, "label": "saved"}}}
                }
            }
        ),
        encoding="utf-8",
    )

    dialog = ConfigurationDialog(
        project,
        initial_values={"main": {"run": {"count": 5}}},
    )
    values = profile_values(dialog.document, profile)
    assert dialog.tabs.count() == 1
    dialog._run_configuration()
    editor = dialog.profile_tabs["main"]
    count = editor.forms["run"].rows["count"].field

    assert values == {"run": {"count": 5, "label": "saved"}}
    assert count.isEnabled()
    count.set_value(8)
    assert editor.forms["run"].values()["count"] == 8
    dialog.close()


def test_configuration_dialog_applies_dimensions_before_initial_values(
    application: Any, tmp_path: Path
) -> None:
    schema = {
        "x-fortran-namelist": "run",
        "type": "object",
        "properties": {
            "paths": {
                "type": "array",
                "x-fortran-shape": "n_items",
                "items": {"type": "string", "x-fortran-len": 32},
            }
        },
    }
    profile = GuiProfile(
        "main",
        "main",
        "Main",
        None,
        "main.nml",
        (NamelistPage("run", "run", schema),),
    )
    project = GuiProject(tmp_path, {}, {"n_items": 2}, (profile,))

    dialog = ConfigurationDialog(
        project,
        initial_values={"main": {"run": {"paths": ["input.nc"]}}},
        initial_dimensions={"n_items": 1},
    )

    assert dialog.dimension_boxes["n_items"].value() == 1
    assert profile_values(dialog.document, profile) == {
        "run": {"paths": ["input.nc"]}
    }
    assert not (tmp_path / "nml.json").exists()
    dialog.close()


def test_guidata_array_editor_accepts_custom_axis_labels(application: Any) -> None:
    module = pytest.importorskip("guidata.widgets.arrayeditor")
    editor = module.ArrayEditor()
    try:
        assert editor.setup_and_check(
            np.zeros((2, 5)),
            "Parameters",
            xlabels=["Lower", "Upper", "Value", "Flag", "Scaling"],
            ylabels=["Domain 1", "Domain 2"],
            variable_size=False,
        )
    finally:
        editor.close()


def test_profile_tab_list_navigation_and_cancel_restore_loaded_values(
    application: Any,
    tmp_path: Path,
) -> None:
    first_schema = {
        "x-fortran-namelist": "run",
        "type": "object",
        "properties": {"count": {"type": "integer"}},
    }
    second_schema = {
        "x-fortran-namelist": "output",
        "type": "object",
        "properties": {"enabled": {"type": "boolean"}},
    }
    profile = GuiProfile(
        "main",
        "main",
        "Main",
        None,
        "main.nml",
        (
            NamelistPage("run", "run", first_schema),
            NamelistPage("output", "output", second_schema),
        ),
    )
    project = GuiProject(tmp_path, {}, {}, (profile,))
    (tmp_path / "nml.json").write_text(
        json.dumps(
            {
                "file_profiles": {
                    "main": {
                        "profile": "main",
                        "default_filename": "main.nml",
                        "values": {"run": {"count": 3}},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    dialog = ConfigurationDialog(project)
    dialog._run_configuration()
    editor = dialog.profile_tabs["main"]

    assert editor.selector.currentRow() == 0
    assert editor.stack.currentIndex() == 0
    assert editor.back.isEnabled() is False
    editor.next.click()
    assert editor.selector.currentRow() == 1
    assert editor.stack.currentIndex() == 1
    assert editor.next.isEnabled() is False
    editor.back.click()

    count = editor.forms["run"].rows["count"].field
    count.set_value(8)
    editor.cancel.click()

    restored = dialog.profile_tabs["main"]
    assert restored.forms["run"].values()["count"] == 3
    dialog.close()


def test_profile_save_keeps_invalid_edits_open(
    application: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema = {
        "x-fortran-namelist": "run",
        "type": "object",
        "required": ["count"],
        "properties": {"count": {"type": "integer", "minimum": 1}},
    }
    profile = GuiProfile(
        "main",
        "main",
        "Main",
        None,
        "main.nml",
        (NamelistPage("run", "run", schema),),
    )
    project = GuiProject(tmp_path, {}, {}, (profile,))
    messages: list[str] = []
    monkeypatch.setattr(
        app_module.QMessageBox,
        "critical",
        lambda _parent, _title, message: messages.append(str(message)),
    )
    dialog = ConfigurationDialog(
        project, initial_values={"main": {"run": {"count": 0}}}
    )
    dialog._run_configuration()

    dialog.profile_tabs["main"].save.click()

    assert messages
    assert dialog.tabs.indexOf(dialog.profile_tabs["main"]) >= 0
    assert not (tmp_path / "nml.json").exists()
    dialog.close()


def test_run_refits_existing_arrays_after_dimension_change(
    application: Any, tmp_path: Path
) -> None:
    schema = {
        "x-fortran-namelist": "run",
        "type": "object",
        "properties": {
            "paths": {
                "type": "array",
                "x-fortran-shape": "n_items",
                "items": {"type": "string", "x-fortran-len": 32},
            }
        },
    }
    profile = GuiProfile(
        "main",
        "main",
        "Main",
        None,
        "main.nml",
        (NamelistPage("run", "run", schema),),
    )
    project = GuiProject(tmp_path, {}, {"n_items": 2}, (profile,))
    dialog = ConfigurationDialog(
        project,
        initial_values={"main": {"run": {"paths": ["a.nc", "b.nc"]}}},
    )
    dialog._run_configuration()
    dialog.dimension_boxes["n_items"].setValue(3)

    dialog._run_configuration()

    paths = dialog.profile_tabs["main"].forms["run"].rows["paths"].field
    assert paths.value() == ["a.nc", "b.nc", "a.nc"]
    dialog.close()


def test_virtual_profile_selection_builds_tab_and_save_all(
    application: Any, tmp_path: Path
) -> None:
    alpha = NamelistPage(
        "alpha",
        "alpha",
        {
            "x-fortran-namelist": "alpha",
            "type": "object",
            "properties": {"count": {"type": "integer"}},
        },
    )
    beta = NamelistPage(
        "beta",
        "beta",
        {
            "x-fortran-namelist": "beta",
            "type": "object",
            "properties": {"enabled": {"type": "boolean"}},
        },
    )
    project = GuiProject(
        root=tmp_path,
        constants={},
        default_dimensions={},
        profiles=(),
        namelists=(alpha, beta),
    )
    dialog = ConfigurationDialog(project)

    assert [dialog.available_schemas.item(index).text() for index in range(2)] == [
        "alpha",
        "beta",
    ]
    dialog._move_all(dialog.available_schemas, dialog.selected_schemas)
    assert dialog.available_schemas.count() == 0
    assert dialog.selected_schemas.count() == 2
    dialog._move_all(dialog.selected_schemas, dialog.available_schemas)
    dialog.available_schemas.item(1).setSelected(True)
    dialog._move_selected(dialog.available_schemas, dialog.selected_schemas)
    dialog.available_schemas.item(0).setSelected(True)
    dialog._move_selected(dialog.available_schemas, dialog.selected_schemas)
    dialog.profile_name.setText("main")
    dialog.default_filename.setText("mhm.nml")
    dialog.run.click()

    editor = dialog.profile_tabs["main"]
    assert [editor.selector.item(index).text() for index in range(2)] == [
        "beta",
        "alpha",
    ]
    count = editor.forms["alpha"].rows["count"].field
    count.set_value(7)
    dialog.restore_all.click()
    assert editor.forms["alpha"].values()["count"] == 0
    dialog.save_all.click()

    saved = json.loads((tmp_path / "nml.json").read_text(encoding="utf-8"))
    assert saved["file_profiles"]["main"]["default_filename"] == "mhm.nml"
    assert (tmp_path / "mhm.nml").is_file()
    dialog.close()
