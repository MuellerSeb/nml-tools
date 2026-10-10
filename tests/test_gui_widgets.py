"""Offscreen checks of direct namelist editing and singleton fields."""

import os

import pytest

from nml_tools.gui.model import (
    GUI_REF_ORIGIN_KEY,
    MISSING,
    GuiProfile,
    GuiProject,
    GuiProjectProfile,
    NamelistPage,
)
from nml_tools.schema import resolve_schema

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("qtpy")
try:
    from qtpy.QtCore import Qt
    from qtpy.QtTest import QTest
    from qtpy.QtWidgets import QApplication, QMessageBox
except ImportError:
    pytest.skip("Qt binding unavailable", allow_module_level=True)

from nml_tools.gui.app import ConfigurationDialog, ProfileConfigTab
from nml_tools.gui.fields import (
    ArrayField,
    FieldRow,
    NamelistForm,
    ObjectField,
    ScalarField,
)


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


def _add_project(dialog, key="default"):
    index = next(
        (
            index
            for index in range(dialog.sourceComboBox_loadProject.count())
            if dialog.sourceComboBox_loadProject.itemData(index) == ("configured", key)
        ),
        -1,
    )
    assert index >= 0
    dialog.sourceComboBox_loadProject.setCurrentIndex(index)
    dialog._add_selected_project()
    return dialog


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


def test_numeric_fields_use_appropriate_controls(application):
    from qtpy.QtWidgets import QLineEdit, QSpinBox

    integer = ScalarField({"type": "integer", "minimum": -3, "maximum": 9}, 4)
    assert isinstance(integer.control, QSpinBox)
    assert (integer.control.minimum(), integer.control.maximum(), integer.value()) == (-3, 9, 4)
    singleton = FieldRow(
        "values", {"type": "array", "x-fortran-shape": 1, "items": {"type": "integer"}}, [2], {}
    )
    assert isinstance(singleton.field.inline.control, QSpinBox)

    number = ScalarField({"type": "number", "minimum": 0.0, "maximum": 1.0}, 0.25)
    assert isinstance(number.control, QLineEdit)
    assert number.value() == 0.25
    number.control.setText("not-a-number")
    with pytest.raises(ValueError, match="not a valid number"):
        number.value()

    wide = ScalarField({"type": "integer", "maximum": 2**40}, 4)
    assert isinstance(wide.control, QLineEdit)


def test_inline_array_title_and_hint_styles(application, monkeypatch):
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[1:]))
    array = FieldRow(
        "weights",
        {
            "title": "Body weights",
            "description": "Weight for each body.",
            "type": "array",
            "x-fortran-shape": 2,
            "items": {"type": "number"},
        },
        [1.0, 2.0],
        {},
        required=True,
        show_label=True,
    )
    inline = array.field.table_editor
    assert inline.titleLabel.text() == "Body weights (weights) *"
    assert inline.separatorLine is not None and not inline.infoButton.isHidden()
    assert array.fieldLabel.isHidden() and array.infoButton.isHidden()
    assert inline.tableWidget.columnCount() == 2
    assert [inline.tableWidget.horizontalHeaderItem(i).text() for i in range(2)] == ["1", "2"]
    assert inline.tableWidget.height() < 100
    assert inline.tableWidget.height() >= (
        inline.tableWidget.horizontalHeader().height()
        + inline.tableWidget.rowHeight(0)
        + inline.tableWidget.horizontalScrollBar().sizeHint().height()
    )
    inline.infoButton.click()
    assert messages == [("Body weights", "Weight for each body.")]

    aligned = NamelistForm(
        {
            "type": "object",
            "properties": {
                "short": {"type": "integer"},
                "long": {"title": "A much longer field label", "type": "string"},
            },
        },
        {"short": 1, "long": "value"},
        {},
    )
    aligned.show()
    application.processEvents()
    assert len({row.editorHost.geometry().x() for row in aligned.rows.values()}) == 1

    default = FieldRow("label", {"type": "string", "default": "fallback"}, MISSING, {})
    example = FieldRow("note", {"type": "string", "examples": ["sample"]}, MISSING, {})
    assert default.field.control.placeholderText() == "fallback"
    assert example.field.control.placeholderText() == "sample"
    assert "#cc7070" in default.field.control.styleSheet()
    assert "#888888" in example.field.control.styleSheet()
    default.field.control.setText("changed")
    default.field.control.textEdited.emit("changed")
    default.field.control.clear()
    default.field.control.textEdited.emit("")
    assert "#cc7070" in default.field.control.styleSheet()
    assert default.value() == "fallback" and example.value() is MISSING
    QTest.keyClick(default.field.control, Qt.Key_Tab)
    QTest.keyClick(example.field.control, Qt.Key_Tab)
    assert default.field.control.text() == "fallback"
    assert example.value() == "sample"
    count = FieldRow("count", {"type": "integer", "default": 4}, MISSING, {})
    QTest.keyClick(count.field.control, Qt.Key_Tab)
    assert count.field.control.prefix() == "" and count.field.modified
    count.field.control.lineEdit().selectAll()
    QTest.keyClick(count.field.control.lineEdit(), Qt.Key_Backspace)
    assert count.field.control.lineEdit().text() == ""
    assert count.field.control.lineEdit().placeholderText() == "4"
    assert count.value() == 4

    optional = FieldRow("optional", {"type": "integer", "minimum": 0}, 5, {})
    optional.field.control.lineEdit().selectAll()
    QTest.keyClick(optional.field.control.lineEdit(), Qt.Key_Backspace)
    assert optional.value() is MISSING

    flag = FieldRow("flag", {"type": "boolean", "default": False}, MISSING, {})
    assert flag.field.control.checkState() == Qt.Unchecked
    assert flag.field.control.text() == flag.field.control.toolTip() == "False"
    flag.field.control.click()
    assert flag.field.control.isChecked() and not flag.field.control.text()
    assert flag.field.control.toolTip() == "False" and not flag.field.control.styleSheet()

    default_array = FieldRow(
        "counts",
        {
            "type": "array",
            "x-fortran-shape": 2,
            "items": {"type": "integer", "minimum": 0},
            "default": [1, 2],
        },
        [9, 8],
        {},
    )
    default_cell = default_array.field.table_editor.cells[(1,)].field.control
    default_cell.lineEdit().selectAll()
    QTest.keyClick(default_cell.lineEdit(), Qt.Key_Backspace)
    assert default_cell.lineEdit().placeholderText() == "1"
    assert default_array.value() == [1, 8]

    example_array = FieldRow(
        "counts",
        {
            "type": "array",
            "x-fortran-shape": 2,
            "items": {"type": "integer", "minimum": 0},
            "examples": [[1, 2]],
        },
        [9, 8],
        {},
    )
    example_cell = example_array.field.table_editor.cells[(1,)].field.control
    example_cell.lineEdit().selectAll()
    QTest.keyClick(example_cell.lineEdit(), Qt.Key_Backspace)
    assert example_cell.lineEdit().placeholderText() == "1"
    assert example_array.value().assigned == {(2,)}

    labeled = NamelistForm(
        {
            "type": "object",
            "properties": {
                "codes": {
                    "type": "array",
                    "x-fortran-shape": 3,
                    "items": {"type": "number"},
                    "axes": {"1": {"labels": ["X", "Y", "Z"]}},
                },
                "vector": {
                    "type": "array",
                    "x-fortran-shape": 3,
                    "items": {"type": "number"},
                    "axes": {"1": {"labels": ["X", "Y", "Z"]}},
                },
            },
        },
        None,
        {},
    )
    assert not labeled.tables
    assert labeled.rows["vector"].field.table_editor.tableWidget.columnCount() == 3


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
    date_time.control.setDateTime(QDateTime.fromString("2026-02-03 04:05", "yyyy-MM-dd HH:mm"))
    assert date_time.value() == "2026-02-03 04:05"
    hinted_row = FieldRow(
        "when",
        {"type": "string", "format": "date-time", "examples": ["2027-03-04 05:06"]},
        MISSING,
        {},
    )
    hinted = hinted_row.field
    QTest.keyClick(hinted.control, Qt.Key_Tab)
    assert hinted.modified and hinted.value() == "2027-03-04 05:06"


def test_dialog_load_overlay_save_reload_and_dimension_changes(application, project, monkeypatch):
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: errors.append(args[-1]))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    path = project.root / "run.nml"
    path.write_text('&run count=8 label="saved" weights(1)=2.0 periods(1)%year=2021 /\n')
    dialog = _add_project(
        ConfigurationDialog(project, initial_values={"main": {"run": {"count": 9}}})
    )
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
    resized = dialog.editors[path]
    assert resized.saved_dimensions == {"n": 1}
    resized.forms["run"].rows["count"].field.set_value(77)
    resized.cancel.click()
    assert resized.parent() is None
    assert dialog.project_dimensions["default"] == dialog.editors[path].dimensions == {"n": 2}
    assert dialog.editors[path].values()["run"]["weights"] == [2.0, 1.0]
    dialog._save_all()
    loaded = _add_project(ConfigurationDialog(project))
    assert loaded.config_tab.dimension_boxes["n"].value() == 2
    loaded.close()
    dialog.config_tab.dimension_boxes["n"].setValue(1)
    dialog.config_tab.run.click()
    assert isinstance(dialog.editors[path].forms["run"].rows["weights"].field.inline, ScalarField)
    dialog._save_all()
    reloaded = _add_project(ConfigurationDialog(project))
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
    extra = dialog.editors[project.root / "extra.nml"]
    extra.forms["run"].rows["count"].field.set_value(17)
    index = next(
        i
        for i in range(builder.source_combo.count())
        if builder.source_combo.itemData(i) == ("profile", "extra")
    )
    assert index >= 0
    builder.source_combo.setCurrentIndex(index)
    builder.default_filename.setText("extra-renamed.nml")
    builder.run.click()
    renamed = project.root / "extra-renamed.nml"
    assert dialog.editors[renamed].values()["run"]["count"] == 17
    assert [item.key for item in dialog.loaded_projects["default"].profiles].count("extra") == 1
    assert 'default_file = "extra-renamed.nml"' in (project.root / "default.toml").read_text()
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
    assert not errors and not dialog.editors
    _add_project(dialog)
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


def test_profile_sources_exclude_namelists_and_include_project_toml(application, project):
    path = project.root / "external.nml"
    path.write_text("&run count=42 weights(3)=9.0 /\n")
    (project.root / "external.toml").write_text(
        '[[file_profiles]]\nname = "copy"\ndefault_file = "copy.nml"\n'
        'namelists = ["run"]\n\n[[project_profiles]]\nname = "external"\n'
        'file_profiles = ["copy"]\n'
    )
    dialog = _add_project(ConfigurationDialog(project))
    dialog.tabs.setCurrentWidget(dialog.plus_tab)
    config = dialog.tabs.currentWidget()
    assert config.source_combo.findData(str(path)) < 0
    assert any(
        config.source_combo.itemData(index) == ("profile", "copy")
        for index in range(config.source_combo.count())
    )
    index = next(
        index
        for index in range(config.source_combo.count())
        if config.source_combo.itemData(index) == ("profile", "copy")
    )
    config.source_combo.setCurrentIndex(index)
    assert config.profile_name.text() == "copy"
    config.source_combo.setCurrentIndex(0)
    assert not config.profile_name.text() and not config.default_filename.text()
    assert config.selected_schemas.count() == 0
    dialog.close()


def test_browsed_project_source_loads(application, project, monkeypatch):
    from nml_tools.gui import app

    path = project.root / "external.toml"
    path.write_text(
        '[[file_profiles]]\nname = "copy"\ndefault_file = "copy.nml"\n'
        'namelists = ["run"]\n\n[[project_profiles]]\nname = "external"\n'
        'file_profiles = ["copy"]\n'
    )
    monkeypatch.setattr(app.QFileDialog, "getOpenFileName", lambda *args: (str(path), ""))
    dialog = ConfigurationDialog(project)
    dialog._browse_project()
    assert dialog.sourceComboBox_loadProject.currentData() == ("path", str(path.resolve()))
    dialog._add_selected_project()
    assert "external" in dialog.loaded_projects
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
    dialog = _add_project(ConfigurationDialog(project))
    assert dialog.projectSourceLayout.stretch(0) == 1
    assert dialog.projectSourceLayout.stretch(1) == 2
    assert dialog.browseButton_addProject.text() == "+"
    assert dialog.treeWidget_projectStructure.maximumWidth() > 275
    assert dialog.tabs.tabText(dialog.tabs.indexOf(dialog.config_tab)) == "⚙️"
    assert next(iter(dialog.editors.values())).label.text() == "Selected Namelist:"
    editor = next(iter(dialog.editors.values()))
    dialog.tabs.setCurrentWidget(dialog.config_tab)
    dialog.tabs.setCurrentWidget(editor)
    selected = dialog.treeWidget_projectStructure.currentItem()
    assert selected.data(0, Qt.ItemDataRole.UserRole)[:3] == ("profile", "default", "main")
    assert selected.isExpanded()
    dialog.tabs.setCurrentWidget(dialog.plus_tab)
    builder = dialog.tabs.currentWidget()
    dialog._close_tab(dialog.tabs.indexOf(builder))
    assert dialog.tabs.indexOf(builder) == -1
    dialog._close_tab(dialog.tabs.indexOf(dialog.config_tab))
    assert dialog.config_tab is None
    dialog._close_tab(dialog.tabs.indexOf(next(iter(dialog.editors.values()))))
    last = dialog.config_tab
    dialog._close_tab(dialog.tabs.indexOf(last))
    assert dialog.config_tab is not last and dialog.tabs.count() == 2
    dialog.close()


def test_inactive_projects_stay_hidden_and_tree_fills_splitter(application, project):
    from dataclasses import replace

    profile = project.profiles[0]
    project = replace(
        project,
        project_profiles=(
            GuiProjectProfile("one", "one", "One", None, (profile,), custom=True),
            GuiProjectProfile("two", "two", "Two", None, (profile,), custom=True),
        ),
    )
    dialog = ConfigurationDialog(project)
    assert not dialog.loaded_projects
    assert dialog.treeWidget_projectStructure.topLevelItemCount() == 0
    _add_project(dialog, "one")
    _add_project(dialog, "two")
    dialog.treeWidget_projectStructure.setCurrentItem(dialog.project_items["one"])
    dialog.show()
    dialog.splitter.setSizes([400, 600])
    application.processEvents()
    tree = dialog.treeWidget_projectStructure
    assert tree.width() == dialog.splitter.sizes()[0]
    assert tree.columnCount() == 2 and tree.columnWidth(1) == 28
    assert sum(tree.columnWidth(i) for i in range(2)) == tree.viewport().width()
    assert not dialog.project_configs["two"].isVisible()
    assert not any(editor.isVisible() for editor in dialog.project_editors["two"].values())
    file_item = tree.topLevelItem(0).child(0)
    assert not file_item.isExpanded()
    tree.setCurrentItem(file_item)
    assert file_item.isExpanded()
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
                "start": {
                    "$ref": "#/$defs/period",
                    "title": "Starting evaluation period",
                    "description": "First configured period.",
                    "default": {"year": 2001},
                },
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
    form.resize(800, 600)
    (table,) = form.tables
    form.show()
    application.processEvents()
    assert table.y() < 50
    assert table.cellWidget(0, 0).isVisible()
    assert (table.rowCount(), table.columnCount()) == (4, 3)
    assert table.horizontalHeaderItem(0).text() == "Namelist Property"
    assert table.horizontalHeaderItem(1).text() == "year *"
    assert table.cellWidget(0, 0).fieldLabel.text() == "start *"
    assert not table.cellWidget(0, 0).infoButton.isHidden()
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
        assert (single_table.rowCount(), single_table.columnCount()) == (1, 3)
        assert single_table.horizontalHeaderItem(1).text() == "year *"
        defaults = single.values()
        single_table.objects[name, indices].rows["year"].field.set_value(2035)
        edited = {"year": 2035, "enabled": False}
        assert single.values()[name] == ([edited] if indices else edited)
        single.reset()
        assert single.values() == defaults


def test_required_derived_array_writes_item_defaults(application, tmp_path):
    from nml_tools.gui.model import save_profiles

    schema = resolve_schema(
        {
            "type": "object",
            "x-fortran-namelist": "baseflow_1",
            "$defs": {
                "parameter": {
                    "type": "object",
                    "x-fortran-type": "parameter_t",
                    "properties": {
                        "value": {"type": "number"},
                        "optimize": {"type": "boolean", "default": False},
                        "min": {"type": "number"},
                        "max": {"type": "number"},
                    },
                    "required": ["value", "min", "max"],
                }
            },
            "properties": {
                "baseflow_recession": {
                    "type": "array",
                    "x-fortran-shape": "n_geo_units",
                    "items": {
                        "$ref": "#/$defs/parameter",
                        "default": {"value": 100.0, "min": 1.0, "max": 1000.0},
                    },
                }
            },
            "required": ["baseflow_recession"],
        }
    )
    form = NamelistForm(schema, None, {"n_geo_units": 2})
    values = form.values()
    assert values["baseflow_recession"].assigned == {(1,), (2,)}
    page = NamelistPage("baseflow_1", "baseflow_1", schema)
    profile = GuiProfile("parameters", "parameters", "Parameters", None, "parameters.nml", (page,))
    project = GuiProject(tmp_path, {}, {"n_geo_units": 2}, (profile,), namelists=(page,))
    save_profiles(project, [(profile, {"baseflow_1": values}, {"n_geo_units": 2})])
    text = (tmp_path / "parameters.nml").read_text()
    assert "baseflow_recession(1)%value = 100.0" in text
    assert "baseflow_recession(2)%max = 1000.0" in text


def test_single_referenced_array_uses_top_aligned_resizable_table(application):
    schema = {
        "title": "Long descriptive parameter title",
        "description": "Parameter explanation.",
        "type": "array",
        "x-fortran-shape": 2,
        "items": {"type": "number"},
        "default": [75.0, 200.0],
        "examples": [[75.0, 200.0]],
        GUI_REF_ORIGIN_KEY: "parameter.yml#/$defs/parameter",
    }
    form = NamelistForm(
        {"type": "object", "properties": {"factor": schema}, "required": ["factor"]},
        None,
        {},
    )
    form.show()
    application.processEvents()
    (table,) = form.tables
    assert not form.rows and table.y() < 50
    assert table.cellWidget(0, 0).fieldLabel.text() == "factor *"
    assert not table.cellWidget(0, 0).infoButton.isHidden()
    assert table.horizontalHeaderItem(0).text() == "Namelist Property"
    assert table.horizontalHeader().sectionResizeMode(0) == table.horizontalHeader().Interactive
    assert table.horizontalHeader().minimumSectionSize() == 88
    assert table.columnWidth(0) >= 180 and table.columnWidth(1) >= 88
    table.rows["factor"][0].set_value(12.0, {})
    table.reset()
    control = table.rows["factor"][0].field.control
    assert control.placeholderText() == "75.0"
    assert table.values()["factor"] == [75.0, 200.0]
