# mypy: disable-error-code="attr-defined, import-not-found, import-untyped, misc"
"""Schema-driven Qt field widgets."""

from __future__ import annotations

import copy
import math
import os
from collections.abc import Mapping
from itertools import product
from pathlib import Path
from typing import Any, cast

from qtpy.QtCore import QDateTime, QEvent, Qt
from qtpy.QtGui import QKeySequence, QPalette
from qtpy.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QWidget,
)

from ..schema import DERIVED_REF_ORIGIN_KEY
from .arrays import (
    array_shape,
    axis_labels,
    canonical_array,
    display_array,
    initial_array,
    resolve_shape,
    table_axes,
)
from .model import GUI_REF_ORIGIN_KEY, MISSING, InputArray, overlay_values, suggestion
from .ui import load_ui


def _exec(dialog: Any) -> int:
    """Execute a Qt dialog through the Qt 5 or Qt 6 method name."""
    method = getattr(dialog, "exec", None)
    if method is None:
        method = dialog.exec_
    return int(method())


def _accepted(dialog: Any) -> int:
    """Return the accepted-dialog result code across supported Qt bindings."""
    value = getattr(dialog, "Accepted", None)
    value = value if value is not None else dialog.DialogCode.Accepted
    return int(getattr(value, "value", value))


def _derived_array_editor(editor_type: type[Any], parent: QWidget) -> Any:
    """Create a guidata editor that correctly commits derived-type cells."""

    # guidata's fixed-size record handler cannot commit (field, *indices) keys.
    class DerivedArrayEditor(editor_type):
        def accept(self) -> None:
            """Commit structured edits before accepting the dialog."""
            for (name, *indices), value in self._data.current_changes.items():
                self._data.get_array()[name][tuple(indices)] = value
            self._data.current_changes.clear()
            super().accept()

    return DerivedArrayEditor(parent)


def _output_root(widget: QWidget) -> Path:
    """Find the output directory attached to a widget's parent form."""
    current: QWidget | None = widget
    while current is not None:
        root = getattr(current, "output_root", None)
        if isinstance(root, Path):
            return root
        current = current.parentWidget()
    return Path.cwd()


def _relative_path(path: str, widget: QWidget) -> str:
    """Express a selected file relative to the namelist output directory."""
    return Path(os.path.relpath(path, _output_root(widget))).as_posix()


def _palette_color(role: Any) -> str:
    """Return a theme-aware palette color for lightweight hint styling."""
    return str(QApplication.palette().color(role).name())


def _hint_style(default: bool) -> str:
    """Return the distinct schema-hint style requested by the editor."""
    color = "#e6a0a0" if default else "#b8b8b8"
    return f"color: {color}; font-style: italic;"


def _parse_date_time(value: Any) -> QDateTime:
    """Parse supported namelist date-time strings into a Qt date-time."""
    text = str(value)
    for pattern in (
        "yyyy-MM-dd HH:mm:ss",
        "yyyy-MM-dd HH:mm",
        "yyyy-MM-dd HH",
        "yyyy-MM-dd",
        "yyyy-MM-ddTHH:mm:ss",
        "yyyy-MM-ddTHH:mm",
    ):
        result = QDateTime.fromString(text, pattern)
        if result.isValid():
            return result
    if not text:
        return QDateTime.fromString("2000-01-01 00:00", "yyyy-MM-dd HH:mm")
    raise ValueError(f"'{text}' is not a valid date-time")


def _add_path_array_controls(editor: Any, owner: QWidget) -> tuple[Any, Any, Any]:
    """Add browse-and-apply controls below a guidata path array editor."""
    line = QLineEdit(editor)
    browse = QPushButton("...", editor)
    update = QPushButton("Update selected", editor)
    controls = QHBoxLayout()
    controls.addWidget(line, 1)
    controls.addWidget(browse)
    controls.addWidget(update)
    editor.arraywidget.layout().addLayout(controls)

    def choose() -> None:
        path, _ = QFileDialog.getOpenFileName(editor, "Select file", str(_output_root(owner)))
        if path:
            line.setText(_relative_path(path, owner))

    def apply() -> None:
        model = editor.arraywidget.model
        for index in editor.arraywidget.view.selectedIndexes():
            model.setData(index, line.text())

    browse.clicked.connect(choose)
    update.clicked.connect(apply)
    return line, browse, update


def _install_date_time_delegate(editor: Any) -> None:
    """Use a date-time control when editing string array cells in guidata."""
    from guidata.widgets.arrayeditor.editorwidget import ArrayDelegate

    class DateTimeDelegate(ArrayDelegate):
        def createEditor(self, parent: QWidget, option: Any, index: Any) -> QDateTimeEdit:
            """Create the date-time control for one guidata cell."""
            control = QDateTimeEdit(parent)
            control.setCalendarPopup(True)
            control.setDisplayFormat("yyyy-MM-dd HH:mm")
            return control

        def setEditorData(self, control: QDateTimeEdit, index: Any) -> None:
            """Load the current cell text into the date-time control."""
            control.setDateTime(_parse_date_time(index.model().data(index)))

        def setModelData(self, control: QDateTimeEdit, model: Any, index: Any) -> None:
            """Write the selected date-time back to the guidata model."""
            model.setData(index, control.dateTime().toString("yyyy-MM-dd HH:mm"))

    view = editor.arraywidget.view
    view.setItemDelegate(DateTimeDelegate(view.model().get_array().dtype, view))


def _seeded(schema: Mapping[str, Any]) -> bool:
    """Return whether this property itself supplies an effective default."""
    return "default" in schema


def _contains_default(schema: Mapping[str, Any]) -> bool:
    """Return whether a nested item can supply values after explicit reset."""
    if "default" in schema:
        return True
    properties = schema.get("properties", {})
    return isinstance(properties, Mapping) and any(
        _contains_default(child) for child in properties.values() if isinstance(child, Mapping)
    )


class ScalarField(QWidget):
    def __init__(self, schema: Mapping[str, Any], value: Any, parent: QWidget | None = None):
        super().__init__(parent)
        self.schema = schema
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        enum = schema.get("enum")
        kind = schema.get("type")
        control: QComboBox | QCheckBox | QSpinBox | QLineEdit
        if isinstance(enum, list) and enum:
            combo = QComboBox(self)
            for item in enum:
                combo.addItem(str(item), item)
            control = combo
        elif kind == "boolean":
            control = QCheckBox(self)
        elif kind == "integer":
            lower = int(schema.get("minimum", schema.get("exclusiveMinimum", -2_147_483_648)))
            upper = int(schema.get("maximum", schema.get("exclusiveMaximum", 2_147_483_647)))
            lower += "exclusiveMinimum" in schema
            upper -= "exclusiveMaximum" in schema
            if -2_147_483_648 <= lower <= int(value) <= upper <= 2_147_483_647:
                spin = QSpinBox(self)
                spin.setRange(lower, upper)
                control = spin
            else:
                control = QLineEdit(self)
        else:
            control = QLineEdit(self)
        self.control = control
        self._hint_visible = False
        examples = schema.get("examples")
        self._hint = (
            (schema["default"], True)
            if "default" in schema
            else (examples[0], False)
            if isinstance(examples, list) and examples
            else None
        )
        layout.addWidget(control)
        control.installEventFilter(self)
        self.set_value(value)
        self.modified = False
        signal = (
            control.textEdited
            if isinstance(control, QLineEdit)
            else control.toggled
            if isinstance(control, QCheckBox)
            else control.valueChanged
            if isinstance(control, QSpinBox)
            else control.currentIndexChanged
        )
        signal.connect(self._mark_modified)

    def _mark_modified(self, *_args: Any) -> None:
        """Mark a user choice and remove hint-only styling."""
        self.modified = True
        if isinstance(self.control, QLineEdit) and not self.control.text() and self._hint:
            self._apply_hint(*self._hint)
            return
        self.control.setStyleSheet("")
        self._hint_visible = False
        if isinstance(self.control, QSpinBox):
            self.control.setPrefix("")
        if isinstance(self.control, QCheckBox):
            self.control.setTristate(False)

    def show_hint(self, value: Any, default: bool) -> None:
        """Display a default or example without treating it as user input."""
        self._hint = (value, default)
        self._apply_hint(value, default)
        self.modified = False

    def _apply_hint(self, value: Any, default: bool) -> None:
        """Apply a remembered hint without changing modification state."""
        label = "Default" if default else "Example"
        text = f"{label}: {value}"
        if isinstance(self.control, QLineEdit):
            self.control.clear()
            self.control.setPlaceholderText(text)
        elif isinstance(self.control, QComboBox):
            self.control.insertItem(0, text, MISSING)
            self.control.setCurrentIndex(0)
        elif isinstance(self.control, QCheckBox):
            self.control.setTristate(True)
            self.control.setCheckState(Qt.PartiallyChecked)
            self.control.setText(text)
        elif isinstance(self.control, QSpinBox):
            self.control.setPrefix(f"{label}: ")
        self.control.setStyleSheet(_hint_style(default))
        self._hint_visible = True

    def show_unset(self) -> None:
        """Display an explicit unset state without producing a value."""
        self._hint = None
        self._hint_visible = False
        if isinstance(self.control, QLineEdit):
            self.control.clear()
            self.control.setPlaceholderText("…")
        elif isinstance(self.control, QComboBox):
            self.control.insertItem(0, "…", MISSING)
            self.control.setCurrentIndex(0)
        elif isinstance(self.control, QCheckBox):
            self.control.setTristate(True)
            self.control.setCheckState(Qt.PartiallyChecked)
        elif isinstance(self.control, QSpinBox) and self.control.minimum() > -2_147_483_648:
            self.control.setMinimum(self.control.minimum() - 1)
            self.control.setSpecialValueText("…")
            self.control.setValue(self.control.minimum())
        self.modified = False

    def set_value(self, value: Any) -> None:
        """Display a Python value in the scalar control."""
        self._hint_visible = False
        self.control.setStyleSheet("")
        if isinstance(self.control, QComboBox):
            index = self.control.findData(value)
            self.control.setCurrentIndex(max(index, 0))
        elif isinstance(self.control, QCheckBox):
            self.control.setTristate(False)
            self.control.setText("")
            self.control.setChecked(bool(value))
        elif isinstance(self.control, QSpinBox):
            self.control.setPrefix("")
            self.control.setValue(value)
        else:
            self.control.setText(str(value))
        self.modified = True

    def eventFilter(self, watched: Any, event: Any) -> bool:
        """Accept a visible schema hint when leaving its control with Tab."""
        if (
            watched is self.control
            and event.type() == QEvent.KeyPress
            and event.key() in {Qt.Key_Tab, Qt.Key_Backtab}
            and self._hint_visible
            and self._hint
        ):
            self.set_value(self._hint[0])
        return bool(super().eventFilter(watched, event))

    def value(self) -> Any:
        """Return the control value converted to its schema type."""
        if isinstance(self.control, QComboBox):
            return self.control.currentData()
        if isinstance(self.control, QCheckBox):
            return self.control.isChecked()
        if isinstance(self.control, QSpinBox):
            return self.control.value()
        text = self.control.text()
        kind = self.schema.get("type")
        try:
            if kind == "integer":
                return int(text)
            if kind == "number":
                value = float(text)
                if not math.isfinite(value):
                    raise ValueError
                return value
        except ValueError as exc:
            raise ValueError(f"'{text}' is not a valid {kind}") from exc
        return text

    def reset(self, sizes: Mapping[str, int]) -> None:
        """Restore the scalar's schema suggestion without marking an edit."""
        self.set_value(suggestion(self.schema, sizes))
        self.modified = False


class PathField(ScalarField):
    def __init__(self, schema: Mapping[str, Any], value: Any, parent: QWidget | None = None):
        super().__init__(schema, value, parent)
        self.browse = QPushButton("...", self)
        self.layout().addWidget(self.browse)
        self.browse.clicked.connect(self._browse)

    def _browse(self) -> None:
        """Select a file and display its path relative to the output directory."""
        path, _ = QFileDialog.getOpenFileName(self, "Select file", str(_output_root(self)))
        if path:
            self.set_value(_relative_path(path, self))


class DateTimeField(ScalarField):
    def __init__(self, schema: Mapping[str, Any], value: Any, parent: QWidget | None = None):
        QWidget.__init__(self, parent)
        self.schema = schema
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.control = QDateTimeEdit(self)
        self.control.setCalendarPopup(True)
        self.control.setDisplayFormat("yyyy-MM-dd HH:mm")
        layout.addWidget(self.control)
        self._hint = None
        self._hint_visible = False
        self.control.installEventFilter(self)
        self.set_value(value)
        self.modified = False
        self.control.dateTimeChanged.connect(self._mark_modified)

    def show_hint(self, value: Any, default: bool) -> None:
        """Style the displayed date-time as a non-literal hint."""
        self.set_value(value)
        self._hint = (value, default)
        self._hint_visible = True
        self.control.setStyleSheet(_hint_style(default))
        self.control.setToolTip(f"{'Default' if default else 'Example'}: {value}")
        self.modified = False

    def set_value(self, value: Any) -> None:
        """Display a namelist date-time while preserving its original spelling."""
        self._hint_visible = False
        self.control.setStyleSheet("")
        self.control.setToolTip("")
        self._original = str(value)
        self.control.setDateTime(_parse_date_time(value))
        self.modified = True

    def value(self) -> str:
        """Return the original or user-edited date-time string."""
        if not self.modified:
            return self._original
        return str(self.control.dateTime().toString("yyyy-MM-dd HH:mm"))

    def show_unset(self) -> None:
        """Display an unset date-time using the control's special text."""
        self._hint = None
        self._hint_visible = False
        value = QDateTime.fromString("1900-01-01 00:00", "yyyy-MM-dd HH:mm")
        self.control.setMinimumDateTime(value)
        self.control.setSpecialValueText("…")
        self.control.setDateTime(value)
        self.modified = False


class ObjectField(QGroupBox):
    def __init__(
        self,
        schema: Mapping[str, Any],
        value: Any,
        sizes: Mapping[str, int],
        parent: QWidget | None = None,
        *,
        fit_arrays: bool = False,
    ):
        super().__init__(str(schema.get("x-fortran-type", "Derived value")), parent)
        self.schema = schema
        self.sizes = sizes
        properties = schema.get("properties")
        if not isinstance(properties, Mapping):
            raise ValueError("derived field must define object 'properties'")
        default = schema.get("default")
        self.has_default = isinstance(default, Mapping)
        self.base_default: dict[str, Any] = (
            copy.deepcopy(dict(default)) if isinstance(default, Mapping) else {}
        )
        examples = schema.get("examples")
        example = examples[0] if isinstance(examples, list) and examples else {}
        hint_source: Mapping[str, Any] = self.base_default
        if not self.has_default:
            hint_source = example if isinstance(example, Mapping) else {}
        source = copy.deepcopy(dict(hint_source))
        supplied = isinstance(value, Mapping)
        if isinstance(value, Mapping):
            source = overlay_values(source, value)
        required = {item.lower() for item in schema.get("required", []) if isinstance(item, str)}
        layout = QFormLayout(self)
        self.rows: dict[str, FieldRow] = {}
        for name, child in properties.items():
            if not isinstance(name, str) or not isinstance(child, Mapping):
                continue
            child_value = source.get(name, MISSING) if isinstance(source, Mapping) else MISSING
            is_required = name.lower() in required
            row = FieldRow(
                name,
                child,
                child_value,
                sizes,
                self,
                fit_arrays=fit_arrays,
                required=is_required,
                show_label=True,
            )
            if not supplied and name in hint_source and isinstance(row.field, ScalarField):
                row._provided = False
                row._hint_override = copy.deepcopy(hint_source[name])
                row.field.show_hint(hint_source[name], self.has_default)
            layout.addRow(row)
            self.rows[name] = row

    def value(self) -> dict[str, Any]:
        """Collect the present component values from this derived object."""
        result: dict[str, Any] = copy.deepcopy(dict(self.base_default))
        for name, row in self.rows.items():
            value = row.value()
            if value is not MISSING:
                result[name] = value
        return result

    def reset(self, sizes: Mapping[str, int]) -> None:
        """Restore defaults for every component of the derived object."""
        examples = self.schema.get("examples")
        example = examples[0] if isinstance(examples, list) and examples else {}
        hints = self.base_default if self.has_default else example
        for name, row in self.rows.items():
            if isinstance(hints, Mapping) and name in hints:
                row.set_value(hints[name], sizes)
                row._provided = False
                row._hint_override = copy.deepcopy(hints[name])
                if isinstance(row.field, ScalarField):
                    row.field.show_hint(hints[name], self.has_default)
            else:
                row.reset(sizes)


class InlineArrayTable(QWidget):
    """Inline editor for one- and two-dimensional schema arrays."""

    def __init__(
        self,
        name: str,
        schema: Mapping[str, Any],
        value: list[Any],
        assigned: set[tuple[int, ...]],
        hinted: set[tuple[int, ...]],
        sizes: Mapping[str, int],
        required: bool,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        load_ui("array_table.ui", self)
        self.name, self.schema, self.sizes = name, schema, sizes
        self.items = schema["items"]
        self._value = copy.deepcopy(value)
        self._assigned = set(assigned)
        self._hinted = set(hinted)
        self.cells: dict[tuple[int, ...], FieldRow] = {}
        self.titleLabel.setText(_field_label(name, schema, required))
        description = schema.get("description")
        self.infoButton.setVisible(isinstance(description, str) and bool(description.strip()))
        self.infoButton.setStyleSheet(f"color: {_palette_color(QPalette.Link)}; font-weight: bold;")
        if self.infoButton.isVisible():
            self.infoButton.clicked.connect(
                lambda: QMessageBox.information(
                    self, str(schema.get("title", name)), str(description).strip()
                )
            )
        self.pathControls.setVisible(self.items.get("format") == "file-path")
        self.browsePathButton.clicked.connect(self._browse_path)
        self.updatePathButton.clicked.connect(self._update_paths)
        self.tableWidget.installEventFilter(self)
        self._populate()

    @property
    def modified(self) -> bool:
        """Return whether any cell has been explicitly edited."""
        return any(_field_modified(cell.field) for cell in self.cells.values())

    def _populate(self) -> None:
        """Create cell editors using schema axis labels when available."""
        shape = array_shape(self._value)
        rank = len(shape)
        table = self.tableWidget
        positions: list[tuple[tuple[int, ...], int, int]]
        if rank == 1:
            table.setRowCount(1)
            table.setColumnCount(shape[0])
            labels = axis_labels(self.schema, 1, shape[0]) or [
                str(i) for i in range(1, shape[0] + 1)
            ]
            table.setHorizontalHeaderLabels(labels)
            table.verticalHeader().setVisible(False)
            positions = [((index,), 0, index - 1) for index in range(1, shape[0] + 1)]
        else:
            axes = table_axes(self.schema, 2) or (0, 1)
            shown = display_array(self._value, self.schema)
            table.setRowCount(shown.shape[0])
            table.setColumnCount(shown.shape[1])
            table.setHorizontalHeaderLabels(
                axis_labels(self.schema, axes[1] + 1, shown.shape[1])
                or [str(i) for i in range(1, shown.shape[1] + 1)]
            )
            table.setVerticalHeaderLabels(
                axis_labels(self.schema, axes[0] + 1, shown.shape[0])
                or [str(i) for i in range(1, shown.shape[0] + 1)]
            )
            positions = []
            for row in range(shown.shape[0]):
                for column in range(shown.shape[1]):
                    displayed = [row, column]
                    canonical = [0, 0]
                    canonical[axes[0]], canonical[axes[1]] = displayed
                    positions.append((tuple(index + 1 for index in canonical), row, column))
        defaulted = "default" in self.schema
        for indices, row, column in positions:
            raw = _nested_get(self._value, tuple(index - 1 for index in indices))
            cell = FieldRow(self.name, self.items, raw, self.sizes, self)
            if indices in self._hinted or indices not in self._assigned:
                cell._provided = False
                if isinstance(cell.field, ScalarField):
                    if indices in self._hinted:
                        cell.field.show_hint(raw, defaulted)
                    else:
                        cell.field.show_unset()
            table.setCellWidget(row, column, cell)
            self.cells[indices] = cell
        cast(QHeaderView, table.horizontalHeader()).setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        table.resizeRowsToContents()

    def value(self) -> InputArray:
        """Return dense values and only defaulted, loaded, or edited indices."""
        result = copy.deepcopy(self._value)
        assigned = set(self._assigned)
        for indices, cell in self.cells.items():
            modified = _field_modified(cell.field)
            value = (
                cell.field.value()
                if modified or indices in self._assigned and indices not in self._hinted
                else _nested_get(self._value, tuple(index - 1 for index in indices))
            )
            target = _nested_get(result, tuple(index - 1 for index in indices[:-1]))
            target[indices[-1] - 1] = value
            if modified:
                assigned.add(indices)
        return InputArray(result, assigned)

    def _browse_path(self) -> None:
        """Choose a path for later application to selected cells."""
        path, _ = QFileDialog.getOpenFileName(self, "Select file", str(_output_root(self)))
        if path:
            self.pathEdit.setText(_relative_path(path, self))

    def _update_paths(self) -> None:
        """Apply the path entry to selected editable cells."""
        for index in self.tableWidget.selectedIndexes():
            cell = self.tableWidget.cellWidget(index.row(), index.column())
            if isinstance(cell, FieldRow):
                cell.set_value(self.pathEdit.text(), self.sizes)

    def eventFilter(self, watched: Any, event: Any) -> bool:
        """Provide spreadsheet-style copy and paste for inline cells."""
        if watched is self.tableWidget and event.type() == QEvent.KeyPress:
            if event.matches(QKeySequence.Copy):
                indexes = [
                    index
                    for index in self.tableWidget.selectedIndexes()
                    if self.tableWidget.cellWidget(index.row(), index.column())
                ]
                if indexes:
                    rows = sorted({index.row() for index in indexes})
                    columns = sorted({index.column() for index in indexes})
                    QApplication.clipboard().setText(
                        "\n".join(
                            "\t".join(
                                str(self.tableWidget.cellWidget(row, column).field.value())
                                for column in columns
                                if isinstance(self.tableWidget.cellWidget(row, column), FieldRow)
                            )
                            for row in rows
                        )
                    )
                return True
            if event.matches(QKeySequence.Paste):
                current = self.tableWidget.currentIndex()
                for row_offset, line in enumerate(QApplication.clipboard().text().splitlines()):
                    for column_offset, text in enumerate(line.split("\t")):
                        cell = self.tableWidget.cellWidget(
                            current.row() + row_offset, current.column() + column_offset
                        )
                        if isinstance(cell, FieldRow):
                            cell.set_value(_parse_text(text, self.items), self.sizes)
                return True
        return bool(super().eventFilter(watched, event))


class ArrayField(QWidget):
    def __init__(
        self,
        name: str,
        schema: Mapping[str, Any],
        value: Any,
        sizes: Mapping[str, int],
        parent: QWidget | None = None,
        *,
        fit_existing: bool = False,
        required: bool = False,
    ):
        super().__init__(parent)
        self.name = name
        self.schema = schema
        self.sizes = sizes
        self.required = required
        saved = value is not MISSING
        candidate = suggestion(schema, sizes) if not saved else value
        items = schema.get("items")
        if not isinstance(items, Mapping):
            raise ValueError("array field must define object 'items'")
        self.items = items
        self._value = initial_array(
            schema,
            sizes,
            candidate,
            suggestion(items, sizes),
            strict=saved and not fit_existing,
            resize=saved and fit_existing,
            defaults=suggestion(
                {**schema, "x-fortran-shape": list(resolve_shape(schema, sizes, candidate))}, sizes
            )
            if saved and fit_existing
            else None,
        )
        shape = array_shape(self._value)
        positions = set(product(*(range(1, size + 1) for size in shape)))
        self.assigned = (
            set(value.assigned) if isinstance(value, InputArray) else positions if saved else set()
        ) & positions
        if _seeded(schema):
            self.assigned.update(positions)
        self.hinted = (
            positions if not saved and ("default" in schema or schema.get("examples")) else set()
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel(self)
        self.inline: Any = None
        self.table_editor: InlineArrayTable | None = None
        self.button = QPushButton("Edit array…", self)
        self.button.clicked.connect(self._edit)
        layout.addWidget(self.summary, 1)
        layout.addWidget(self.button)
        self._update_summary()

    def value(self) -> InputArray:
        """Return dense array values plus the indices selected for output."""
        if self.table_editor is not None:
            return self.table_editor.value()
        if self.inline is not None:
            value = self.inline.value()
            if getattr(self.inline, "modified", False) or isinstance(value, dict) and value:
                self.assigned.add((1,))
            return InputArray([value], set(self.assigned))
        return InputArray(copy.deepcopy(self._value), set(self.assigned))

    def reset(self, sizes: Mapping[str, int]) -> None:
        """Restore the array suggestion and its assigned indices."""
        self.sizes = sizes
        self._value = suggestion(self.schema, sizes)
        shape = array_shape(self._value)
        self.assigned = (
            set(product(*(range(1, size + 1) for size in shape)))
            if _seeded(self.schema) or _contains_default(self.items)
            else set()
        )
        self.hinted = (
            set(product(*(range(1, size + 1) for size in shape)))
            if "default" in self.schema or self.schema.get("examples")
            else set()
        )
        self._update_summary()

    def _update_summary(self) -> None:
        """Show the array shape or an inline editor for a single element."""
        shape = array_shape(self._value)
        if self.table_editor is not None:
            self.layout().removeWidget(self.table_editor)
            self.table_editor.deleteLater()
            self.table_editor = None
        self.inline = None
        if len(shape) <= 2:
            self.table_editor = InlineArrayTable(
                self.name,
                self.schema,
                self._value,
                self.assigned,
                self.hinted,
                self.sizes,
                self.required,
                self,
            )
            self.layout().insertWidget(0, self.table_editor, 1)
            if shape == (1,):
                self.inline = next(iter(self.table_editor.cells.values())).field
        self.summary.setVisible(self.table_editor is None)
        raw = self.schema.get("x-fortran-shape")
        deferred = raw == ":" or isinstance(raw, list) and ":" in raw
        self.button.setVisible(self.table_editor is None or deferred)
        self.button.setText("Resize…" if self.table_editor is not None else "Edit array…")
        self.summary.setText("×".join(str(value) for value in shape))

    def _edit(self) -> None:
        """Edit the array in guidata and record changed Fortran indices."""
        try:
            if self.table_editor is not None:
                text, accepted = QInputDialog.getText(
                    self,
                    "Resize array",
                    "Shape",
                    text=",".join(map(str, array_shape(self._value))),
                )
                if not accepted:
                    return
                shape = tuple(int(part.strip()) for part in text.split(","))
                if len(shape) != len(array_shape(self._value)) or any(size <= 0 for size in shape):
                    raise ValueError("shape must contain one positive size per array axis")
                old = self.value()
                self._value = initial_array(
                    {**self.schema, "x-fortran-shape": list(shape)},
                    self.sizes,
                    old,
                    suggestion(self.items, self.sizes),
                    resize=True,
                )
                self.assigned = {
                    indices
                    for indices in old.assigned
                    if all(index <= size for index, size in zip(indices, shape))
                }
                self.hinted = set()
                self._update_summary()
                return
            import numpy as np
            from guidata.widgets.arrayeditor import ArrayEditor

            before = self.value()
            self._value = before
            rank = len(resolve_shape(self.schema, self.sizes, self._value))
            derived = self.items.get("type") == "object"
            canonical = self._structured_array(np) if derived else self._intrinsic_array(np)
            displayed = display_array(canonical, self.schema)
            xlabels, ylabels = self._display_labels(displayed.shape, rank)
            editor = _derived_array_editor(ArrayEditor, self) if derived else ArrayEditor(self)
            raw_shape = self.schema.get("x-fortran-shape")
            deferred = raw_shape == ":" or (isinstance(raw_shape, list) and ":" in raw_shape)
            if not editor.setup_and_check(
                displayed,
                str(self.schema.get("title", self.name)),
                xlabels=xlabels,
                ylabels=ylabels,
                variable_size=deferred,
            ):
                return
            if self.items.get("format") == "file-path" and not derived:
                _add_path_array_controls(editor, self)
            if self.items.get("format") == "date-time" and not derived:
                _install_date_time_delegate(editor)
            if _exec(editor) != _accepted(editor):
                return
            edited = editor.get_value()
            if derived:
                self._value = self._objects_from_structured(edited, rank, np)
            else:
                self._value = canonical_array(edited, self.schema, rank)
            shape = array_shape(self._value)
            old_shape = array_shape(before)
            self.assigned = {
                indices
                for indices in self.assigned
                if all(index <= size for index, size in zip(indices, shape))
            }
            for indices in product(*(range(size) for size in shape)):
                if any(index >= size for index, size in zip(indices, old_shape)) or _nested_get(
                    before, indices
                ) != _nested_get(self._value, indices):
                    self.assigned.add(tuple(index + 1 for index in indices))
            self._update_summary()
        except (ImportError, RuntimeError, TypeError, ValueError) as exc:
            QMessageBox.critical(self, "Array editor", str(exc))

    def _intrinsic_array(self, np: Any) -> Any:
        """Convert intrinsic array values to a typed NumPy array."""
        kind = self.items.get("type")
        if not isinstance(kind, str):
            raise ValueError("array items must define a string type")
        dtype = {
            "integer": np.int64,
            "number": np.float64,
            "boolean": np.bool_,
            "string": "U1024",
        }.get(kind)
        if dtype is None:
            raise ValueError(f"unsupported array item type '{kind}'")
        return np.asarray(self._value, dtype=dtype)

    def _structured_array(self, np: Any) -> Any:
        """Convert derived-type values to a structured NumPy array."""
        properties = self.items.get("properties")
        if not isinstance(properties, Mapping):
            raise ValueError("derived array items must define properties")
        fields = []
        for name, child in properties.items():
            if not isinstance(name, str) or not isinstance(child, Mapping):
                continue
            child_kind = child.get("type")
            if not isinstance(child_kind, str):
                raise ValueError("derived components must define a string type")
            dtype = {
                "integer": np.int64,
                "number": np.float64,
                "boolean": np.bool_,
                "string": "U1024",
            }.get(child_kind)
            if dtype is None:
                raise ValueError(f"unsupported derived component type '{child_kind}'")
            title = str(child.get("title", name))
            fields.append((name, dtype) if title == name else ((title, name), dtype))
        shape = array_shape(self._value)
        result = np.empty(shape, dtype=np.dtype(fields))
        defaults = suggestion(self.items, self.sizes)
        for index in np.ndindex(shape):
            item = _nested_get(self._value, index)
            if not isinstance(item, Mapping):
                item = defaults
            for name in result.dtype.names or ():
                result[index][name] = item.get(name, defaults[name])
        return result

    def _objects_from_structured(self, value: Any, rank: int, np: Any) -> list[Any]:
        """Convert an edited structured array back to derived-value mappings."""
        data = np.asarray(value)
        if rank == 1:
            data = data.reshape((-1,))
        else:
            axes = table_axes(self.schema, rank)
            if axes is not None and axes != (0, 1):
                data = np.transpose(data, np.argsort(axes))
        edited = _structured_to_objects(data)
        defaults = suggestion(self.items, self.sizes)
        return cast(list[Any], _preserve_omissions(edited, self._value, defaults))

    def _display_labels(
        self, displayed_shape: tuple[int, ...], rank: int
    ) -> tuple[list[str] | None, list[str] | None]:
        """Return configured column and row labels for the displayed array."""
        if rank == 1:
            return axis_labels(self.schema, 1, displayed_shape[1]), None
        if rank != 2:
            return None, None
        axes = table_axes(self.schema, rank) or (0, 1)
        return (
            axis_labels(self.schema, axes[1] + 1, displayed_shape[1]),
            axis_labels(self.schema, axes[0] + 1, displayed_shape[0]),
        )


class FieldRow(QWidget):
    def __init__(
        self,
        name: str,
        schema: Mapping[str, Any],
        value: Any,
        sizes: Mapping[str, int],
        parent: QWidget | None = None,
        *,
        fit_arrays: bool = False,
        required: bool = False,
        show_label: bool = False,
    ):
        super().__init__(parent)
        load_ui("field_row.ui", self)
        self.name = name
        self.schema = schema
        self.sizes = sizes
        self.required = required or "default" in schema
        self.show_label = show_label
        self._provided = value is not MISSING
        self._hint_override = MISSING
        self.fieldLabel.setText(_field_label(name, schema, self.required))
        self.fieldLabel.setVisible(show_label)
        initial = value
        if value is MISSING and schema.get("type") not in {"array", "object"}:
            initial = suggestion(schema, sizes)
        self.field = _field_widget(
            name, schema, initial, sizes, self, fit_arrays=fit_arrays, required=self.required
        )
        description = schema.get("description")
        if isinstance(description, str):
            description = description.strip()
            self.field.setToolTip(description)
            self.infoButton.clicked.connect(
                lambda: QMessageBox.information(self, str(schema.get("title", name)), description)
            )
        self.infoButton.setStyleSheet(f"color: {_palette_color(QPalette.Link)}; font-weight: bold;")
        self._update_decorations()
        self.editorLayout.addWidget(self.field)
        if isinstance(self.field, ScalarField) and (value is MISSING or value == ""):
            examples = schema.get("examples")
            if "default" in schema:
                self.field.show_hint(schema["default"], True)
            elif isinstance(examples, list) and examples:
                self.field.show_hint(examples[0], False)
            else:
                self.field.show_unset()

    def _update_decorations(self) -> None:
        """Keep labels and information actions outside inline array tables."""
        inline = isinstance(self.field, ArrayField) and self.field.table_editor is not None
        self.fieldLabel.setVisible(self.show_label and not inline)
        description = str(self.schema.get("description", "")).strip()
        self.infoButton.setVisible(self.show_label and not inline and bool(description))

    def value(self) -> Any:
        """Return the row value, omitting untouched fields without seed data."""
        untouched = not self._provided and not getattr(self.field, "modified", False)
        if untouched and isinstance(self.field, ScalarField):
            if self._hint_override is not MISSING:
                return copy.deepcopy(self._hint_override)
            if "default" in self.schema:
                return copy.deepcopy(self.schema["default"])
            if self.required:
                raise ValueError(f"required field '{self.name}' has no value")
            return MISSING
        if (
            not self._provided
            and isinstance(self.field, ObjectField)
            and not _field_modified(self.field)
        ):
            if "default" in self.schema:
                return copy.deepcopy(self.schema["default"])
            if not self.required:
                return MISSING
            if self.schema.get("examples"):
                raise ValueError(f"required field '{self.name}' has no value")
        if (
            isinstance(self.field, ScalarField)
            and isinstance(self.field.control, QLineEdit)
            and not self.field.control.text()
        ):
            if "default" in self.schema:
                return copy.deepcopy(self.schema["default"])
            if self.required:
                raise ValueError(f"required field '{self.name}' has no value")
            return MISSING
        value = self.field.value()
        if isinstance(value, InputArray) and not value.assigned:
            if self.required:
                raise ValueError(f"required field '{self.name}' has no value")
            return MISSING
        if isinstance(self.field, ObjectField) and not value:
            if self.required:
                raise ValueError(f"required field '{self.name}' has no value")
            return MISSING
        return value

    def reset(self, sizes: Mapping[str, int]) -> None:
        """Replace this row with a fresh field using schema suggestions."""
        if isinstance(self.field, ArrayField):
            self._provided = False
            self.sizes = sizes
            self.field.reset(sizes)
            self._update_decorations()
            return
        self.set_value(MISSING, sizes)

    def set_value(self, value: Any, sizes: Mapping[str, int]) -> None:
        """Rebuild the row field for a supplied value and array dimensions."""
        self._provided = value is not MISSING
        self._hint_override = MISSING
        self.sizes = sizes
        initial = value
        if value is MISSING and self.schema.get("type") not in {"array", "object"}:
            initial = suggestion(self.schema, sizes)
        replacement = _field_widget(
            self.name, self.schema, initial, sizes, self, required=self.required
        )
        replacement.setToolTip(self.field.toolTip())
        self.editorLayout.replaceWidget(self.field, replacement)
        self.field.deleteLater()
        self.field = replacement
        self._update_decorations()
        if isinstance(self.field, ScalarField) and (value is MISSING or value == ""):
            examples = self.schema.get("examples")
            if "default" in self.schema:
                self.field.show_hint(self.schema["default"], True)
            elif isinstance(examples, list) and examples:
                self.field.show_hint(examples[0], False)
            else:
                self.field.show_unset()
        elif isinstance(self.field, ScalarField):
            self.field.modified = True


class DerivedTable(QTableWidget):
    """Same-reference objects as rows, reusing the existing component editors."""

    def __init__(
        self,
        schemas: Mapping[str, Mapping[str, Any]],
        values: Mapping[str, Any],
        sizes: Mapping[str, int],
        required: set[str],
        parent: QWidget,
        *,
        fit_arrays: bool,
    ) -> None:
        super().__init__(parent)
        self.schemas, self.sizes, self.required = schemas, sizes, required
        self.data: dict[str, Any] = {}
        self.objects: dict[tuple[str, tuple[int, ...]], ObjectField] = {}
        self.present: set[str] = set()
        self.example_only: set[str] = set()
        self.table_rows: list[tuple[str, tuple[int, ...], Mapping[str, Any]]] = []
        first = next(iter(schemas.values()))
        first = first["items"] if first["type"] == "array" else first
        columns = list(first["properties"])
        self.setColumnCount(len(columns))
        self.setHorizontalHeaderLabels(columns)
        header = cast(QHeaderView, self.horizontalHeader())
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        for name, schema in schemas.items():
            value = values.get(name, MISSING)
            is_array = schema["type"] == "array"
            item = schema["items"] if is_array else schema
            if is_array:
                dense = initial_array(
                    schema,
                    sizes,
                    suggestion(schema, sizes) if value is MISSING else value,
                    suggestion(item, sizes),
                    strict=value is not MISSING and not fit_arrays,
                    resize=value is not MISSING and fit_arrays,
                    defaults=suggestion(
                        {**schema, "x-fortran-shape": list(resolve_shape(schema, sizes, value))},
                        sizes,
                    )
                    if value is not MISSING and fit_arrays
                    else None,
                )
                shape = array_shape(dense)
                positions = set(product(*(range(1, n + 1) for n in shape)))
                source_positions = (
                    set(value.assigned)
                    if isinstance(value, InputArray)
                    else positions
                    if value is not MISSING
                    else set()
                ) & positions
                self.data[name] = InputArray(
                    dense, source_positions | (positions if _seeded(schema) else set())
                )
            else:
                self.data[name] = {} if value is MISSING else value
                if value is not MISSING or _seeded(schema) or name.lower() in required:
                    self.present.add(name)
                if value is MISSING and not _seeded(schema) and schema.get("examples"):
                    self.example_only.add(name)
            shape = array_shape(self.data[name]) if is_array else ()
            for indices in product(*(range(n) for n in shape)):
                source = (
                    _nested_get(self.data[name], indices)
                    if not is_array or tuple(index + 1 for index in indices) in source_positions
                    else MISSING
                )
                obj = ObjectField(item, source, sizes, self)
                obj.hide()
                row = self.rowCount()
                self.insertRow(row)
                suffix = "(" + ",".join(str(i + 1) for i in indices) + ")" if indices else ""
                label = QTableWidgetItem(name + suffix + (" *" if name.lower() in required else ""))
                label.setToolTip(str(schema.get("description", schema.get("title", name))))
                self.setVerticalHeaderItem(row, label)
                for column, component in enumerate(columns):
                    component_row = obj.rows[component]
                    component_row.fieldLabel.hide()
                    self.setCellWidget(row, column, component_row)
                    label = QTableWidgetItem(
                        component + (" *" if component in item.get("required", []) else "")
                    )
                    label.setToolTip(
                        str(item["properties"][component].get("description", component))
                    )
                    self.setHorizontalHeaderItem(column, label)
                description = str(schema.get("description", "")).strip()
                if description and columns:
                    title = str(schema.get("title", name))
                    info = QToolButton(obj.rows[columns[0]])
                    info.setText("i")
                    info.setToolTip(f"About {name}")
                    info.setAccessibleName(f"Information about {name}")
                    info.setStyleSheet(
                        f"color: {_palette_color(QPalette.Link)}; font-weight: bold;"
                    )
                    info.clicked.connect(
                        lambda _checked=False, heading=title, text=description: (
                            QMessageBox.information(self, heading, text)
                        )
                    )
                    obj.rows[columns[0]].layout().addWidget(info)
                self.objects[name, indices] = obj
                self.table_rows.append((name, indices, item))
        self.resizeRowsToContents()
        self.setMinimumHeight(
            min(400, header.height() + sum(self.rowHeight(i) for i in range(self.rowCount())) + 4)
        )
        self.installEventFilter(self)

    def values(self) -> dict[str, Any]:
        """Collect each table row into scalar or indexed derived values."""
        result = copy.deepcopy(self.data)
        for (name, indices), obj in self.objects.items():
            value = obj.value()
            if (
                not indices
                and name in self.example_only
                and name.lower() in self.required
                and not _field_modified(obj)
            ):
                raise ValueError(f"required field '{name}' has no value")
            if indices:
                _nested_get(result[name], indices[:-1])[indices[-1]] = value
                if _field_modified(obj):
                    result[name].assigned.add(tuple(index + 1 for index in indices))
            else:
                if name in self.present or _field_modified(obj):
                    result[name] = value
                else:
                    result.pop(name, None)
        for name, value in result.items():
            if (
                name.lower() in self.required
                and isinstance(value, InputArray)
                and not value.assigned
            ):
                raise ValueError(f"required field '{name}' has no value")
        return result

    def reset(self) -> None:
        """Restore defaults and assigned positions for all derived rows."""
        self.present = {
            name
            for name, schema in self.schemas.items()
            if _seeded(schema) or name.lower() in self.required
        }
        for name, data in self.data.items():
            if isinstance(data, InputArray):
                shape = array_shape(data)
                data.assigned = (
                    set(product(*(range(1, n + 1) for n in shape)))
                    if _seeded(self.schemas[name]) or _contains_default(self.schemas[name]["items"])
                    else set()
                )
        for obj in self.objects.values():
            obj.reset(self.sizes)

    def eventFilter(self, watched: Any, event: Any) -> bool:
        """Provide copy and paste for inline derived-type component cells."""
        if watched is self and event.type() == QEvent.KeyPress:
            if event.matches(QKeySequence.Copy):
                _copy_table_selection(self)
                return True
            if event.matches(QKeySequence.Paste):
                current = self.currentIndex()
                columns = list(next(iter(self.table_rows))[2]["properties"])
                for row_offset, line in enumerate(QApplication.clipboard().text().splitlines()):
                    row = current.row() + row_offset
                    if row >= self.rowCount():
                        break
                    schema = self.table_rows[row][2]
                    for column_offset, text in enumerate(line.split("\t")):
                        column = current.column() + column_offset
                        cell = self.cellWidget(row, column)
                        if isinstance(cell, FieldRow) and column < len(columns):
                            cell.set_value(
                                _parse_text(text, schema["properties"][columns[column]]),
                                self.sizes,
                            )
                return True
        return bool(super().eventFilter(watched, event))


class ReferencedArrayTable(QTableWidget):
    """One row per referenced one-dimensional parameter array."""

    def __init__(
        self,
        schemas: Mapping[str, Mapping[str, Any]],
        values: Mapping[str, Any],
        sizes: Mapping[str, int],
        required: set[str],
        parent: QWidget,
        *,
        fit_arrays: bool,
    ) -> None:
        super().__init__(parent)
        self.schemas, self.sizes, self.required = schemas, sizes, required
        self.rows: dict[str, list[FieldRow]] = {}
        self.data: dict[str, list[Any]] = {}
        self.assigned: dict[str, set[tuple[int, ...]]] = {}
        self.hinted: dict[str, set[tuple[int, ...]]] = {}
        self.row_names = list(schemas)
        first = next(iter(schemas.values()))
        shape = resolve_shape(first, sizes)
        if len(shape) != 1:
            raise ValueError("referenced parameter arrays must be one-dimensional")
        size = shape[0]
        self.setRowCount(len(schemas))
        self.setColumnCount(size + 1)
        self.setHorizontalHeaderLabels(
            [
                "Namelist Property",
                *(axis_labels(first, 1, size) or [str(index) for index in range(1, size + 1)]),
            ]
        )
        cast(QHeaderView, self.horizontalHeader()).setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        for row_index, (name, schema) in enumerate(schemas.items()):
            item = schema["items"]
            raw = values.get(name, MISSING)
            saved = raw is not MISSING
            dense = initial_array(
                schema,
                sizes,
                raw if saved else suggestion(schema, sizes),
                suggestion(item, sizes),
                strict=saved and not fit_arrays,
                resize=saved and fit_arrays,
            )
            positions: set[tuple[int, ...]] = {(index,) for index in range(1, size + 1)}
            assigned: set[tuple[int, ...]] = (
                set(raw.assigned) if isinstance(raw, InputArray) else positions if saved else set()
            ) & positions
            if _seeded(schema):
                assigned.update(positions)
            hinted: set[tuple[int, ...]] = (
                positions
                if not saved and ("default" in schema or schema.get("examples"))
                else set()
            )
            self.data[name] = dense
            self.assigned[name] = assigned
            self.hinted[name] = hinted
            label = QTableWidgetItem(name + (" *" if name.lower() in required else ""))
            label.setToolTip(str(schema.get("description", schema.get("title", name))))
            self.setItem(row_index, 0, label)
            description = schema.get("description")
            if isinstance(description, str) and description.strip():
                self.setCellWidget(
                    row_index,
                    0,
                    _property_widget(name, schema, name.lower() in required, self),
                )
            cells = []
            for index in range(size):
                position = (index + 1,)
                cell = FieldRow(name, item, dense[index], sizes, self)
                if position in hinted or position not in assigned:
                    cell._provided = False
                    if isinstance(cell.field, ScalarField):
                        if position in hinted:
                            cell.field.show_hint(dense[index], "default" in schema)
                        else:
                            cell.field.show_unset()
                self.setCellWidget(row_index, index + 1, cell)
                cells.append(cell)
            self.rows[name] = cells
        self.resizeRowsToContents()
        header = cast(QHeaderView, self.horizontalHeader())
        self.setMinimumHeight(
            min(400, header.height() + sum(self.rowHeight(i) for i in range(self.rowCount())) + 4)
        )
        self.installEventFilter(self)

    def values(self) -> dict[str, InputArray]:
        """Collect non-empty table cells as explicitly assigned arrays."""
        result = {}
        for name, cells in self.rows.items():
            values = copy.deepcopy(self.data[name])
            assigned = set(self.assigned[name])
            for index, cell in enumerate(cells, 1):
                if _field_modified(cell.field):
                    values[index - 1] = cell.field.value()
                    assigned.add((index,))
            if assigned:
                result[name] = InputArray(values, assigned)
            elif name.lower() in self.required:
                raise ValueError(f"required field '{name}' has no value")
        return result

    def reset(self) -> None:
        """Restore defaults in every referenced-array table row."""
        for name, cells in self.rows.items():
            schema = self.schemas[name]
            defaults = suggestion(schema, self.sizes)
            positions: set[tuple[int, ...]] = {(index,) for index in range(1, len(cells) + 1)}
            self.assigned[name] = (
                positions if _seeded(schema) or _contains_default(schema["items"]) else set()
            )
            self.hinted[name] = (
                positions if "default" in schema or schema.get("examples") else set()
            )
            self.data[name] = copy.deepcopy(defaults)
            for index, cell in enumerate(cells):
                position = (index + 1,)
                cell.set_value(defaults[index], self.sizes)
                cell._provided = False
                if isinstance(cell.field, ScalarField):
                    if position in self.hinted[name]:
                        cell.field.show_hint(defaults[index], "default" in schema)
                    elif position not in self.assigned[name]:
                        cell.field.show_unset()

    def eventFilter(self, watched: Any, event: Any) -> bool:
        """Provide copy and paste for grouped one-dimensional arrays."""
        if watched is self and event.type() == QEvent.KeyPress:
            if event.matches(QKeySequence.Copy):
                _copy_table_selection(self)
                return True
            if event.matches(QKeySequence.Paste):
                current = self.currentIndex()
                for row_offset, line in enumerate(QApplication.clipboard().text().splitlines()):
                    row = current.row() + row_offset
                    if row >= self.rowCount():
                        break
                    item_schema = self.schemas[self.row_names[row]]["items"]
                    for column_offset, text in enumerate(line.split("\t")):
                        cell = self.cellWidget(row, current.column() + column_offset)
                        if isinstance(cell, FieldRow):
                            cell.set_value(_parse_text(text, item_schema), self.sizes)
                return True
        return bool(super().eventFilter(watched, event))


class NamelistForm(QWidget):
    """Editable form for one namelist schema."""

    def __init__(
        self,
        schema: Mapping[str, Any],
        values: Mapping[str, Any] | None,
        sizes: Mapping[str, int],
        parent: QWidget | None = None,
        *,
        fit_arrays: bool = False,
        output_root: Path | None = None,
        read_only: set[str] | None = None,
    ):
        super().__init__(parent)
        self.schema = schema
        self.sizes = sizes
        self.output_root = (output_root or Path.cwd()).resolve()
        properties = schema.get("properties")
        if not isinstance(properties, Mapping):
            raise ValueError("namelist schema must define object 'properties'")
        source = values or {}
        required = {item.lower() for item in schema.get("required", []) if isinstance(item, str)}
        required.update(
            name.lower()
            for name, child in properties.items()
            if isinstance(name, str) and isinstance(child, Mapping) and "default" in child
        )
        layout = QFormLayout(self)
        self.rows: dict[str, FieldRow] = {}
        self.tables: list[DerivedTable | ReferencedArrayTable] = []
        groups: dict[tuple[str, ...], dict[str, Mapping[str, Any]]] = {}
        identities = {}
        for name, child in properties.items():
            item = child.get("items", {}) if child.get("type") == "array" else child
            origin = item.get(DERIVED_REF_ORIGIN_KEY) if item.get("type") == "object" else None
            identity = tuple(origin["identity"]) if origin else ()
            if identity and child.get("type") == "array" and len(resolve_shape(child, sizes)) > 2:
                identity = ()
            if child.get("type") == "array" and child.get(GUI_REF_ORIGIN_KEY):
                shape = resolve_shape(child, sizes)
                if len(shape) == 1:
                    identity = ("array", str(child[GUI_REF_ORIGIN_KEY]))
            if identity:
                identities[name] = identity
                groups.setdefault(identity, {})[name] = child
        for name, child in properties.items():
            if not isinstance(name, str) or not isinstance(child, Mapping):
                continue
            is_required = name.lower() in required
            identity = identities.get(name, ())
            children = groups.get(identity)
            if children and (identity[0] != "array" or len(children) > 1):
                if name == next(iter(children)):
                    table_type = (
                        ReferencedArrayTable
                        if child.get("type") == "array" and child["items"].get("type") != "object"
                        else DerivedTable
                    )
                    table = table_type(
                        children, source, sizes, required, self, fit_arrays=fit_arrays
                    )
                    layout.addRow(table)
                    self.tables.append(table)
                continue
            row = FieldRow(
                name,
                child,
                source.get(name, MISSING),
                sizes,
                self,
                fit_arrays=fit_arrays,
                required=is_required,
                show_label=True,
            )
            if name.lower() in (read_only or set()):
                row.field.setEnabled(False)
            layout.addRow(row)
            self.rows[name] = row

    def values(self) -> dict[str, Any]:
        """Collect fields and grouped tables in original schema order."""
        result: dict[str, Any] = {}
        for name, row in self.rows.items():
            value = row.value()
            if value is not MISSING:
                result[name] = value
        for table in self.tables:
            result.update(table.values())
        return {name: result[name] for name in self.schema["properties"] if name in result}

    def reset(self) -> None:
        """Restore every standalone field and grouped table on the form."""
        for row in self.rows.values():
            row.reset(self.sizes)
        for table in self.tables:
            table.reset()


def _field_widget(
    name: str,
    schema: Mapping[str, Any],
    value: Any,
    sizes: Mapping[str, int],
    parent: QWidget,
    *,
    fit_arrays: bool = False,
    required: bool = False,
) -> Any:
    """Choose the editor widget that matches a property's schema type."""
    kind = schema.get("type")
    if kind == "array":
        return ArrayField(
            name, schema, value, sizes, parent, fit_existing=fit_arrays, required=required
        )
    if kind == "object":
        return ObjectField(schema, value, sizes, parent, fit_arrays=fit_arrays)
    if kind == "string" and schema.get("format") == "file-path":
        return PathField(schema, value, parent)
    if kind == "string" and schema.get("format") == "date-time":
        return DateTimeField(schema, value, parent)
    return ScalarField(schema, value, parent)


def _field_label(name: str, schema: Mapping[str, Any], required: bool) -> str:
    """Build a field label from its title, name, and required marker."""
    title = schema.get("title")
    label = f"{title} ({name})" if isinstance(title, str) and title.strip() else name
    return f"{label} *" if required else label


def _field_modified(field: Any) -> bool:
    """Return whether an editor or one of its component editors changed."""
    if isinstance(field, ObjectField):
        return any(_field_modified(row.field) for row in field.rows.values())
    if isinstance(field, ArrayField):
        return bool(field.value().assigned)
    return bool(getattr(field, "modified", False))


def _parse_text(text: str, schema: Mapping[str, Any]) -> Any:
    """Convert pasted table text to the intrinsic schema type."""
    kind = schema.get("type")
    if kind == "integer":
        return int(text)
    if kind == "number":
        value = float(text)
        if not math.isfinite(value):
            raise ValueError(f"'{text}' is not a valid number")
        return value
    if kind == "boolean":
        normalized = text.strip().lower().strip(".")
        if normalized not in {"true", "false"}:
            raise ValueError(f"'{text}' is not a valid boolean")
        return normalized == "true"
    return text


def _copy_table_selection(table: QTableWidget) -> None:
    """Copy selected editor-cell values as tab-separated text."""
    indexes = [
        index
        for index in table.selectedIndexes()
        if isinstance(table.cellWidget(index.row(), index.column()), FieldRow)
    ]
    if not indexes:
        return
    rows = sorted({index.row() for index in indexes})
    columns = sorted({index.column() for index in indexes})
    QApplication.clipboard().setText(
        "\n".join(
            "\t".join(
                str(table.cellWidget(row, column).field.value())
                for column in columns
                if isinstance(table.cellWidget(row, column), FieldRow)
            )
            for row in rows
        )
    )


def _property_widget(
    name: str, schema: Mapping[str, Any], required: bool, parent: QWidget
) -> QWidget:
    """Build the Designer property label and information action for a table."""
    widget = QWidget(parent)
    load_ui("field_row.ui", widget)
    widget.fieldLabel.setText(_field_label(name, schema, required))
    widget.editorHost.hide()
    description = str(schema.get("description", "")).strip()
    widget.infoButton.setVisible(bool(description))
    widget.infoButton.setStyleSheet(f"color: {_palette_color(QPalette.Link)}; font-weight: bold;")
    if description:
        widget.infoButton.clicked.connect(
            lambda: QMessageBox.information(widget, str(schema.get("title", name)), description)
        )
    return widget


def _nested_get(value: Any, indices: tuple[int, ...]) -> Any:
    """Retrieve a value from nested lists using zero-based indices."""
    for index in indices:
        value = value[index]
    return value


def _structured_to_objects(data: Any) -> list[Any]:
    """Convert a structured NumPy array into nested component mappings."""
    names = data.dtype.names or ()

    def build(axis: int, prefix: tuple[int, ...]) -> Any:
        if axis == data.ndim:
            record = data[prefix]
            return {name: _numpy_scalar(record[name]) for name in names}
        return [build(axis + 1, (*prefix, index)) for index in range(data.shape[axis])]

    return cast(list[Any], build(0, ()))


def _numpy_scalar(value: Any) -> Any:
    """Convert a NumPy scalar to its native Python equivalent."""
    return value.item() if hasattr(value, "item") else value


def _preserve_omissions(edited: Any, original: Any, defaults: Any) -> Any:
    """Drop untouched default components that were absent from saved input."""
    if isinstance(edited, list) and isinstance(original, list):
        return [
            _preserve_omissions(item, original[index], defaults) if index < len(original) else item
            for index, item in enumerate(edited)
        ]
    if isinstance(edited, Mapping) and isinstance(original, Mapping):
        return {
            name: value
            for name, value in edited.items()
            if name in original or not isinstance(defaults, Mapping) or value != defaults.get(name)
        }
    return edited
