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
    assert dialog.tabs.count() == 2
    assert dialog.tabs.tabText(0) == "Config"
    assert dialog.tabs.tabText(1) == "+"

    dialog.tabs.setCurrentWidget(dialog.plus_tab)
    extra = dialog.tabs.currentWidget()
    assert isinstance(extra, app_module.ProfileConfigTab)
    assert extra.source_combo is not None
    assert extra.source_combo.currentText() == "No configuration file"
    assert extra.source_combo.findText("nml.json") == -1
    dialog.tabs.setCurrentWidget(dialog.config_tab)
    dialog._close_tab(dialog.tabs.indexOf(extra))

    dialog._run_configuration()

    assert [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())] == [
        "First",
        "Second",
        "+",
    ]
    assert list(dialog.profile_tabs) == ["first", "second"]
    assert dialog.save_all.isEnabled()

    dialog.tabs.setCurrentWidget(dialog.plus_tab)
    empty_config = dialog.tabs.currentWidget()
    assert isinstance(empty_config, app_module.ProfileConfigTab)
    assert empty_config.source_combo.currentText() == "No configuration file"
    assert empty_config.source_combo.findText("nml.json") == -1
    for editor in list(dialog.profile_tabs.values()):
        dialog._close_tab(dialog.tabs.indexOf(editor))
    assert empty_config.source_combo.findText("nml.json") >= 0
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
    context = dialog.config_tab.context
    assert context is not None
    values = profile_values(context.document, profile)
    assert dialog.tabs.count() == 2
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
    project = GuiProject(
        tmp_path,
        {},
        {"n_items": 2},
        (profile,),
        namelists=profile.pages,
    )

    dialog = ConfigurationDialog(
        project,
        initial_values={"main": {"run": {"paths": ["input.nc"]}}},
        initial_dimensions={"n_items": 1},
    )

    assert dialog.dimension_boxes["n_items"].value() == 1
    context = dialog.config_tab.context
    assert context is not None
    assert profile_values(context.document, profile) == {
        "run": {"paths": ["input.nc"]}
    }
    assert not (tmp_path / "nml.json").exists()
    dialog.close()


def test_configuration_documents_keep_independent_values_and_dimensions(
    application: Any, tmp_path: Path
) -> None:
    page = NamelistPage(
        "alpha",
        "alpha",
        {
            "x-fortran-namelist": "alpha",
            "type": "object",
            "properties": {"count": {"type": "integer"}},
        },
    )
    project = GuiProject(
        tmp_path,
        {},
        {"n_items": 2},
        (),
        namelists=(page,),
    )
    canonical = tmp_path / "nml.json"
    other = tmp_path / "other.json"
    canonical.write_text(
        json.dumps(
            {
                "dimensions": {"n_items": 1},
                "file_profiles": {
                    "first": {
                        "default_filename": "first.nml",
                        "values": {"alpha": {"count": 1}},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    other.write_text(
        json.dumps(
            {
                "dimensions": {"n_items": 3},
                "file_profiles": {
                    "second": {
                        "default_filename": "second.nml",
                        "values": {"alpha": {"count": 2}},
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    dialog = ConfigurationDialog(project)
    assert dialog.json_combo.currentText() == "nml.json"
    assert dialog.dimension_boxes["n_items"].value() == 1
    dialog.run.click()

    dialog.tabs.setCurrentWidget(dialog.plus_tab)
    config = dialog.tabs.currentWidget()
    assert isinstance(config, app_module.ProfileConfigTab)
    assert config.source_combo is not None
    assert config.source_combo.currentText() == "No configuration file"
    config.source_combo.setCurrentIndex(config.source_combo.findText("other.json"))
    assert config.dimension_boxes["n_items"].value() == 3
    config.run.click()

    first = dialog.profile_tabs["first"]
    second = dialog.profile_tabs["second"]
    first.forms["alpha"].rows["count"].field.set_value(11)
    second.forms["alpha"].rows["count"].field.set_value(22)
    dialog.save_all.click()

    first_saved = json.loads(canonical.read_text(encoding="utf-8"))
    second_saved = json.loads(other.read_text(encoding="utf-8"))
    assert first_saved["dimensions"] == {"n_items": 1}
    assert second_saved["dimensions"] == {"n_items": 3}
    assert first_saved["file_profiles"]["first"]["values"]["alpha"]["count"] == 11
    assert second_saved["file_profiles"]["second"]["values"]["alpha"]["count"] == 22
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
    project = GuiProject(
        tmp_path,
        {},
        {"n_items": 2},
        (profile,),
        namelists=profile.pages,
    )
    dialog = ConfigurationDialog(
        project,
        initial_values={"main": {"run": {"paths": ["a.nc", "b.nc"]}}},
    )
    dialog._run_configuration()
    dialog.tabs.setCurrentWidget(dialog.plus_tab)
    config = dialog.tabs.currentWidget()
    assert isinstance(config, app_module.ProfileConfigTab)
    config.dimension_boxes["n_items"].setValue(3)
    assert config.available_schemas is not None
    assert config.selected_schemas is not None
    dialog._move_all(config.available_schemas, config.selected_schemas)
    assert config.profile_name is not None
    assert config.default_filename is not None
    config.profile_name.setText("secondary")
    config.default_filename.setText("secondary.nml")
    config.run.click()

    main_paths = dialog.profile_tabs["main"].forms["run"].rows["paths"].field
    secondary_paths = (
        dialog.profile_tabs["secondary"].forms["run"].rows["paths"].field
    )
    assert main_paths.value() == ["a.nc", "b.nc"]
    assert secondary_paths.value() == ["", "", ""]
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


def test_plus_tab_creates_repeated_closable_runtime_profiles(
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
    configured = GuiProfile(
        "main", "main", "Main", None, "main.nml", (alpha,)
    )
    project = GuiProject(tmp_path, {}, {}, (configured,), namelists=(alpha,))
    dialog = ConfigurationDialog(project)
    dialog._run_configuration()

    assert [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())] == [
        "Main",
        "+",
    ]

    for number in (1, 2):
        dialog.tabs.setCurrentWidget(dialog.plus_tab)
        config = dialog.tabs.currentWidget()
        assert isinstance(config, app_module.ProfileConfigTab)
        assert dialog.tabs.tabText(dialog.tabs.count() - 1) == "+"
        assert config.available_schemas is not None
        assert config.selected_schemas is not None
        dialog._move_all(config.available_schemas, config.selected_schemas)
        assert config.profile_name is not None
        assert config.default_filename is not None
        config.profile_name.setText(f"custom{number}")
        config.default_filename.setText(f"custom{number}.nml")
        config.run.click()

        assert f"custom{number}" in dialog.profile_tabs
        assert config not in dialog.config_tabs
        assert dialog.tabs.indexOf(config) == -1
        assert dialog.tabs.tabText(dialog.tabs.count() - 1) == "+"

    custom = dialog.profile_tabs["custom2"]
    dialog._close_tab(dialog.tabs.indexOf(custom))
    assert "custom2" not in dialog.profile_tabs
    assert dialog.tabs.tabText(dialog.tabs.count() - 1) == "+"
    dialog.close()


def test_configuration_dialog_loads_namelist_input(
    application: Any, tmp_path: Path
) -> None:
    page = NamelistPage(
        "run",
        "run",
        {
            "x-fortran-namelist": "run",
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
        },
    )
    (tmp_path / "loaded.nml").write_text(
        "&run\ncount = 7\n/\n", encoding="utf-8"
    )
    project = GuiProject(tmp_path, {}, {}, (), namelists=(page,))

    dialog = ConfigurationDialog(project)
    assert dialog.json_combo.currentText() == "No configuration file"
    dialog.json_combo.setCurrentIndex(dialog.json_combo.findText("loaded.nml"))
    dialog.run.click()

    profile = dialog.profile_tabs["loaded"].profile
    assert profile.default_file == "loaded.nml"
    editor = dialog.profile_tabs["loaded"]
    assert editor.forms["run"].values()["count"] == 7
    assert [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())] == [
        "loaded",
        "+",
    ]
    dialog.save_all.click()
    saved = json.loads((tmp_path / "loaded.json").read_text(encoding="utf-8"))
    assert saved["file_profiles"]["loaded"]["default_filename"] == "loaded.nml"
    assert not (tmp_path / "nml.json").exists()
    dialog.close()
