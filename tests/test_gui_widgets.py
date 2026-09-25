"""Offscreen checks of direct namelist editing and singleton fields."""

import os

import pytest

from nml_tools.gui.model import GuiProfile, GuiProject, NamelistPage
from nml_tools.schema import resolve_schema

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("qtpy")
try:
    from qtpy.QtWidgets import QApplication, QMessageBox
except ImportError:
    pytest.skip("Qt binding unavailable", allow_module_level=True)

from nml_tools.gui.app import ConfigurationDialog, ProfileConfigTab
from nml_tools.gui.fields import ArrayField, FieldRow, NamelistForm, ObjectField, ScalarField


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def project(tmp_path):
    schema = {
        "type": "object",
        "x-fortran-namelist": "run",
        "properties": {
            "count": {"type": "integer", "default": 3, "examples": [99]},
            "label": {"type": "string", "x-fortran-len": 16, "default": "default"},
            "weights": {
                "type": "array",
                "x-fortran-shape": "n",
                "items": {"type": "number"},
                "default": [1.0],
                "x-fortran-default-repeat": True,
            },
            "periods": {
                "type": "array",
                "x-fortran-shape": "n",
                "items": {
                    "type": "object",
                    "x-fortran-type": "period_t",
                    "properties": {"year": {"type": "integer", "default": 2000}},
                },
            },
        },
    }
    page = NamelistPage("run", "run", schema)
    profile = GuiProfile("main", "main", "Main", None, "run.nml", (page,))
    return GuiProject(tmp_path, {}, {"n": 1}, (profile,), namelists=(page,))


def test_singletons_keep_array_values_and_restore_schema_defaults(application):
    schema = {"type": "array", "x-fortran-shape": "n", "items": {"type": "integer", "default": 7}}
    row = FieldRow("counts", schema, [8], {"n": 1})
    assert isinstance(row.field, ArrayField)
    assert isinstance(row.field.inline, ScalarField)
    assert row.field.button.isHidden()
    row.field.inline.set_value(12)
    assert row.value() == [12]
    row.reset({"n": 2})
    assert row.field.inline is None
    assert row.value() == [7, 7]
    row.reset({"n": 1})
    assert isinstance(row.field.inline, ScalarField)
    assert row.value() == [7]
    deferred = FieldRow("counts", {**schema, "x-fortran-shape": ":"}, [8], {})
    assert isinstance(deferred.field.inline, ScalarField)
    assert not deferred.field.button.isHidden()


def test_derived_singletons_use_inline_object_fields(application, project):
    schema = project.namelists[0].schema["properties"]["periods"]
    row = FieldRow("periods", schema, [{"year": 2020}], {"n": 1})
    assert isinstance(row.field.inline, ObjectField)
    row.field.inline.rows["year"].field.set_value(2025)
    assert row.value() == [{"year": 2025}]
    row.reset({"n": 1})
    assert row.value() == [{"year": 2000}]
    scalar = ObjectField(schema["items"], {"year": 2021}, {})
    assert scalar.value() == {"year": 2021}


def test_path_and_date_time_fields(application, tmp_path, monkeypatch):
    from qtpy.QtCore import QDateTime

    from nml_tools.gui import fields
    from nml_tools.gui.fields import DateTimeField, PathField

    schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "format": "file-path"},
            "paths": {
                "type": "array",
                "x-fortran-shape": "n",
                "items": {"type": "string", "format": "file-path"},
            },
            "when": {"type": "string", "format": "date-time"},
        },
    }
    form = NamelistForm(
        schema,
        {"path": "old.nc", "paths": ["one.nc"], "when": "2025-01-01"},
        {"n": 1},
        output_root=tmp_path,
    )
    path = form.rows["path"].field
    assert isinstance(path, PathField)
    assert isinstance(form.rows["paths"].field.inline, PathField)
    monkeypatch.setattr(
        fields.QFileDialog,
        "getOpenFileName",
        lambda *args: (str(tmp_path / "data" / "input.nc"), ""),
    )
    path.browse.click()
    assert path.value() == "data/input.nc"

    date_time = form.rows["when"].field
    assert isinstance(date_time, DateTimeField)
    assert date_time.value() == "2025-01-01"
    date_time.control.setDateTime(
        QDateTime.fromString("2026-02-03 04:05", "yyyy-MM-dd HH:mm")
    )
    assert date_time.value() == "2026-02-03 04:05"


def test_dialog_load_overlay_save_reload_and_dimension_changes(application, project, monkeypatch):
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: errors.append(args[-1]))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    path = project.root / "run.nml"
    path.write_text('&run count=8 label="saved" weights(1)=2.0 periods(1)%year=2021 /\n')
    dialog = ConfigurationDialog(project, initial_values={"main": {"run": {"count": 9}}})
    editor = dialog.editors[path]
    assert editor.values()["run"]["count"] == 9
    assert editor.values()["run"]["label"] == "saved"
    editor.forms["run"].rows["periods"].field.inline.rows["year"].field.set_value(2025)
    dialog._save_all()
    assert "periods(1)%year = 2025" in path.read_text()
    dialog.config_tab.dimension_boxes["n"].setValue(2)
    dialog.config_tab.run.click()
    assert dialog.editors[path].forms["run"].rows["weights"].field.inline is None
    assert dialog.editors[path].values()["run"]["weights"] == [2.0, 1.0]
    dialog._save_all()
    loaded = ConfigurationDialog(project)
    assert loaded.config_tab.dimension_boxes["n"].value() == 2
    loaded.close()
    dialog.config_tab.dimension_boxes["n"].setValue(1)
    dialog.config_tab.run.click()
    assert isinstance(dialog.editors[path].forms["run"].rows["weights"].field.inline, ScalarField)
    dialog._save_all()
    reloaded = ConfigurationDialog(project)
    assert reloaded.editors[path].values()["run"]["periods"] == [{"year": 2025}]
    dialog.tabs.setCurrentWidget(dialog.plus_tab)
    builder = dialog.tabs.currentWidget()
    assert isinstance(builder, ProfileConfigTab)
    builder.profile_name.setText("extra")
    builder.default_filename.setText("extra.nml")
    dialog._move_all(builder.available_schemas, builder.selected_schemas)
    builder.run.click()
    assert project.root / "extra.nml" in dialog.editors
    dialog._save_all()
    assert (project.root / "extra.nml").is_file()
    assert not list(project.root.glob("*.json"))
    assert not errors
    dialog.close()
    reloaded.close()


def test_invalid_existing_input_is_reported_and_never_replaced(application, project, monkeypatch):
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: errors.append(args[-1]))
    path = project.root / "run.nml"
    invalid = '&run count="wrong type" /'
    path.write_text(invalid)
    dialog = ConfigurationDialog(project)
    assert errors and not dialog.editors
    dialog._save_all()
    assert path.read_text() == invalid
    dialog.close()


def test_guidata_derived_edits_commit(application):
    np = pytest.importorskip("numpy")
    pytest.importorskip("guidata")
    from guidata.widgets.arrayeditor import ArrayEditor

    from nml_tools.gui.fields import _derived_array_editor

    data = np.array([(2000,)], dtype=[("year", "i4")]).reshape(1, 1)
    editor = _derived_array_editor(ArrayEditor, None)
    try:
        assert editor.setup_and_check(data)
        editor._data.current_changes[("year", 0, 0)] = 2025
        editor.accept()
        assert data["year"][0, 0] == 2025
    finally:
        editor.close()


def test_guidata_path_update_and_date_time_editor(application):
    np = pytest.importorskip("numpy")
    pytest.importorskip("guidata")
    from guidata.widgets.arrayeditor import ArrayEditor
    from qtpy.QtCore import QDateTime
    from qtpy.QtWidgets import QDateTimeEdit

    from nml_tools.gui.fields import _add_path_array_controls, _install_date_time_delegate

    data = np.array([["a.nc", "b.nc"]], dtype="U1024")
    editor = ArrayEditor(None)
    try:
        assert editor.setup_and_check(data)
        line, _, update = _add_path_array_controls(editor, editor)
        editor.arraywidget.view.selectAll()
        line.setText("data/input.nc")
        update.click()
        model = editor.arraywidget.model
        assert model.get_value((0, 0)) == model.get_value((0, 1)) == "data/input.nc"

        _install_date_time_delegate(editor)
        view = editor.arraywidget.view
        index = view.model().index(0, 0)
        delegate = view.itemDelegate()
        control = delegate.createEditor(view, None, index)
        assert isinstance(control, QDateTimeEdit)
        control.setDateTime(QDateTime.fromString("2026-02-03 04:05", "yyyy-MM-dd HH:mm"))
        delegate.setModelData(control, view.model(), index)
        assert model.get_value((0, 0)) == "2026-02-03 04:05"
    finally:
        editor.close()


def test_imported_profile_can_choose_its_output_and_keep_loaded_values(
    application, project, monkeypatch
):
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: errors.append(args[-1]))
    path = project.root / "external.nml"
    path.write_text("&run count=42 weights(3)=9.0 /\n")
    dialog = ConfigurationDialog(project)
    dialog.tabs.setCurrentWidget(dialog.plus_tab)
    config = dialog.tabs.currentWidget()
    config.source_combo.setCurrentIndex(config.source_combo.findData(str(path)))
    assert config.dimension_boxes["n"].value() == 3
    config.profile_name.setText("copy")
    config.default_filename.setText("copy.nml")
    config.run.click()
    copy_path = project.root / "copy.nml"
    assert dialog.editors[copy_path].values()["run"]["count"] == 42
    dialog.editors[copy_path].save.click()
    assert copy_path.exists()
    assert path.read_text() == "&run count=42 weights(3)=9.0 /\n"
    assert not errors
    dialog.close()


def test_public_launch_forwards_profile_selection(application, monkeypatch, tmp_path):
    from nml_tools.gui import app, launch_gui

    calls = []
    monkeypatch.setattr(app, "launch_gui", lambda *args: calls.append(args) or 0)
    selected = {"main": ["run"]}
    values = {"main": {"run": {"count": 8}}}
    assert launch_gui(tmp_path, tmp_path / "out", selected, values, {"n": 1}) == 0
    assert calls == [(tmp_path, tmp_path / "out", selected, values, {"n": 1})]


def test_active_and_last_config_tabs_close(application, project):
    dialog = ConfigurationDialog(project)
    dialog.tabs.setCurrentWidget(dialog.plus_tab)
    builder = dialog.tabs.currentWidget()
    dialog._close_tab(dialog.tabs.indexOf(builder))
    assert dialog.tabs.indexOf(builder) == -1 and len(dialog.config_tabs) == 1
    dialog._close_tab(dialog.tabs.indexOf(dialog.config_tab))
    assert dialog.config_tab is None
    dialog._close_tab(dialog.tabs.indexOf(next(iter(dialog.editors.values()))))
    last = dialog.config_tab
    dialog._close_tab(dialog.tabs.indexOf(last))
    assert dialog.config_tab is not last and dialog.tabs.count() == 2
    dialog.close()


def test_shared_reference_table_edit_reset_and_round_trip(application, tmp_path):
    from nml_tools.gui.model import load_profile, recover_dimensions, save_profiles

    schema = resolve_schema(
        {
            "type": "object",
            "x-fortran-namelist": "run",
            "$defs": {
                "period": {
                    "type": "object",
                    "x-fortran-type": "period_t",
                    "properties": {
                        "year": {"type": "integer", "default": 2000},
                        "enabled": {"type": "boolean", "default": False},
                    },
                    "required": ["year"],
                }
            },
            "properties": {
                "start": {"$ref": "#/$defs/period", "default": {"year": 2001}},
                "stop": {"$ref": "#/$defs/period", "default": {"year": 2002}},
                "periods": {
                    "type": "array",
                    "x-fortran-shape": "n",
                    "items": {"$ref": "#/$defs/period"},
                },
            },
        }
    )
    form = NamelistForm(schema, None, {"n": 2})
    (table,) = form.tables
    form.show()
    application.processEvents()
    assert table.cellWidget(0, 0).isVisible()
    assert (table.rowCount(), table.columnCount()) == (4, 2)
    assert table.horizontalHeaderItem(0).text() == "year *"
    table.objects["periods", (1,)].rows["year"].field.set_value(2025)
    table.objects["periods", (1,)].rows["enabled"].field.set_value(True)
    values = form.values()
    assert values["periods"][1] == {"year": 2025, "enabled": True}
    page = NamelistPage("run", "run", schema)
    profile = GuiProfile("main", "main", "Main", None, "run.nml", (page,))
    project = GuiProject(tmp_path, {}, {"n": 100}, (profile,), namelists=(page,))
    save_profiles(project, [(profile, {"run": values}, {"n": 2})])
    assert load_profile(project, profile, recover_dimensions(project)) == {"run": values}
    form.reset()
    assert form.values()["start"]["year"] == 2001
    assert form.values()["stop"]["year"] == 2002
    assert form.values()["periods"][1]["year"] == 2000
    for name, indices in (("start", ()), ("periods", (0,))):
        single = NamelistForm(
            {**schema, "properties": {name: schema["properties"][name]}}, None, {"n": 1}
        )
        (single_table,) = single.tables
        assert (single_table.rowCount(), single_table.columnCount()) == (1, 2)
        assert single_table.horizontalHeaderItem(0).text() == "year *"
        defaults = single.values()
        single_table.objects[name, indices].rows["year"].field.set_value(2035)
        edited = {"year": 2035, "enabled": False}
        assert single.values()[name] == ([edited] if indices else edited)
        single.reset()
        assert single.values() == defaults
