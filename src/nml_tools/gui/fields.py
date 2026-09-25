"""Schema-driven Qt field widgets."""

from __future__ import annotations

import copy
import math
import os
from collections.abc import Mapping
from itertools import product
from pathlib import Path
from typing import Any, cast

from qtpy.QtCore import QDateTime
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
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
from .model import MISSING, InputArray, overlay_values, suggestion


def _exec(dialog: Any) -> int:
    method = getattr(dialog, "exec", None)
    if method is None:
        method = dialog.exec_
    return int(method())


def _accepted(dialog: Any) -> int:
    value = getattr(dialog, "Accepted", None)
    value = value if value is not None else dialog.DialogCode.Accepted
    return int(getattr(value, "value", value))


def _derived_array_editor(editor_type: type[Any], parent: QWidget) -> Any:
    # guidata's fixed-size record handler cannot commit (field, *indices) keys.
    class DerivedArrayEditor(editor_type):  # type: ignore[misc]
        def accept(self) -> None:
            for (name, *indices), value in self._data.current_changes.items():
                self._data.get_array()[name][tuple(indices)] = value
            self._data.current_changes.clear()
            super().accept()

    return DerivedArrayEditor(parent)


def _output_root(widget: QWidget) -> Path:
    current: QWidget | None = widget
    while current is not None:
        root = getattr(current, "output_root", None)
        if isinstance(root, Path):
            return root
        current = current.parentWidget()
    return Path.cwd()


def _relative_path(path: str, widget: QWidget) -> str:
    return Path(os.path.relpath(path, _output_root(widget))).as_posix()


def _parse_date_time(value: Any) -> QDateTime:
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
    from guidata.widgets.arrayeditor.editorwidget import (  # type: ignore[import-untyped]
        ArrayDelegate,
    )

    class DateTimeDelegate(ArrayDelegate):  # type: ignore[misc]
        def createEditor(self, parent: QWidget, option: Any, index: Any) -> QDateTimeEdit:
            control = QDateTimeEdit(parent)
            control.setCalendarPopup(True)
            control.setDisplayFormat("yyyy-MM-dd HH:mm")
            return control

        def setEditorData(self, control: QDateTimeEdit, index: Any) -> None:
            control.setDateTime(_parse_date_time(index.model().data(index)))

        def setModelData(self, control: QDateTimeEdit, model: Any, index: Any) -> None:
            model.setData(index, control.dateTime().toString("yyyy-MM-dd HH:mm"))

    view = editor.arraywidget.view
    view.setItemDelegate(DateTimeDelegate(view.model().get_array().dtype, view))


def _seeded(schema: Mapping[str, Any]) -> bool:
    if "default" in schema or schema.get("examples"):
        return True
    kind = schema.get("type")
    if kind == "array":
        return _seeded(schema["items"])
    if kind == "object":
        return any(_seeded(child) for child in schema["properties"].values())
    return False


class ScalarField(QWidget):
    def __init__(self, schema: Mapping[str, Any], value: Any, parent: QWidget | None = None):
        super().__init__(parent)
        self.schema = schema
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        enum = schema.get("enum")
        kind = schema.get("type")
        control: QComboBox | QCheckBox | QLineEdit
        if isinstance(enum, list) and enum:
            combo = QComboBox(self)
            for item in enum:
                combo.addItem(str(item), item)
            control = combo
        elif kind == "boolean":
            control = QCheckBox(self)
        else:
            control = QLineEdit(self)
        self.control = control
        layout.addWidget(control)
        self.set_value(value)
        self.modified = False
        signal = (
            control.textEdited if isinstance(control, QLineEdit)
            else control.toggled if isinstance(control, QCheckBox)
            else control.currentIndexChanged
        )
        signal.connect(lambda *_: setattr(self, "modified", True))

    def set_value(self, value: Any) -> None:
        if isinstance(self.control, QComboBox):
            index = self.control.findData(value)
            self.control.setCurrentIndex(max(index, 0))
        elif isinstance(self.control, QCheckBox):
            self.control.setChecked(bool(value))
        else:
            self.control.setText(str(value))
        self.modified = True

    def value(self) -> Any:
        if isinstance(self.control, QComboBox):
            return self.control.currentData()
        if isinstance(self.control, QCheckBox):
            return self.control.isChecked()
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
        self.set_value(suggestion(self.schema, sizes))
        self.modified = False


class PathField(ScalarField):
    def __init__(self, schema: Mapping[str, Any], value: Any, parent: QWidget | None = None):
        super().__init__(schema, value, parent)
        self.browse = QPushButton("...", self)
        self.layout().addWidget(self.browse)
        self.browse.clicked.connect(self._browse)

    def _browse(self) -> None:
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
        self.set_value(value)
        self.modified = False
        self.control.dateTimeChanged.connect(lambda *_: setattr(self, "modified", True))

    def set_value(self, value: Any) -> None:
        self._original = str(value)
        self.control.setDateTime(_parse_date_time(value))
        self.modified = True

    def value(self) -> str:
        if not self.modified:
            return self._original
        return self.control.dateTime().toString("yyyy-MM-dd HH:mm")


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
        source = (
            suggestion(schema, sizes) if "default" in schema or schema.get("examples") else {}
        )
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
            row = FieldRow(name, child, child_value, sizes, self, fit_arrays=fit_arrays)
            layout.addRow(_field_label(name, child, is_required), row)
            self.rows[name] = row

    def value(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, row in self.rows.items():
            value = row.value()
            if value is not MISSING:
                result[name] = value
        return result

    def reset(self, sizes: Mapping[str, int]) -> None:
        defaults = (
            suggestion(self.schema, sizes)
            if "default" in self.schema or self.schema.get("examples")
            else {}
        )
        for name, row in self.rows.items():
            if name in defaults:
                row.set_value(defaults[name], sizes)
            else:
                row.reset(sizes)


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
    ):
        super().__init__(parent)
        self.name = name
        self.schema = schema
        self.sizes = sizes
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
            set(value.assigned) if isinstance(value, InputArray)
            else positions if saved else set()
        ) & positions
        if _seeded(schema):
            self.assigned.update(positions)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel(self)
        self.inline: Any = None
        self.button = QPushButton("Edit array…", self)
        self.button.clicked.connect(self._edit)
        layout.addWidget(self.summary, 1)
        layout.addWidget(self.button)
        self._update_summary()

    def value(self) -> list[Any]:
        if self.inline is not None:
            value = self.inline.value()
            if getattr(self.inline, "modified", False) or isinstance(value, dict) and value:
                self.assigned.add((1,))
            return InputArray([value], set(self.assigned))
        return InputArray(copy.deepcopy(self._value), set(self.assigned))

    def reset(self, sizes: Mapping[str, int]) -> None:
        self.sizes = sizes
        self._value = suggestion(self.schema, sizes)
        shape = array_shape(self._value)
        self.assigned = (
            set(product(*(range(1, size + 1) for size in shape)))
            if _seeded(self.schema) else set()
        )
        self._update_summary()

    def _update_summary(self) -> None:
        shape = array_shape(self._value)
        if self.inline is not None:
            self.layout().removeWidget(self.inline)
            self.inline.deleteLater()
            self.inline = None
        if shape == (1,):
            self.inline = _field_widget(self.name, self.items, self._value[0], self.sizes, self)
            self.layout().insertWidget(0, self.inline, 1)
        raw = self.schema.get("x-fortran-shape")
        resizable = raw == ":" or (isinstance(raw, list) and ":" in raw)
        self.summary.setVisible(self.inline is None)
        self.button.setVisible(self.inline is None or resizable)
        self.button.setText("Resize…" if self.inline is not None else "Edit array…")
        self.summary.setText("×".join(str(value) for value in shape))

    def _edit(self) -> None:
        try:
            import numpy as np
            from guidata.widgets.arrayeditor import ArrayEditor  # type: ignore[import-untyped]

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
                if (
                    any(index >= size for index, size in zip(indices, old_shape))
                    or _nested_get(before, indices) != _nested_get(self._value, indices)
                ):
                    self.assigned.add(tuple(index + 1 for index in indices))
            self._update_summary()
        except (ImportError, RuntimeError, TypeError, ValueError) as exc:
            QMessageBox.critical(self, "Array editor", str(exc))

    def _intrinsic_array(self, np: Any) -> Any:
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
    ):
        super().__init__(parent)
        self.name = name
        self.schema = schema
        self.sizes = sizes
        self._provided = value is not MISSING
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        initial = value
        if value is MISSING and schema.get("type") not in {"array", "object"}:
            initial = suggestion(schema, sizes)
        self.field = _field_widget(name, schema, initial, sizes, self, fit_arrays=fit_arrays)
        description = schema.get("description")
        if isinstance(description, str):
            self.field.setToolTip(description.strip())
        layout.addWidget(self.field, 1)

    def value(self) -> Any:
        if isinstance(self.field, ScalarField) and not (
            self._provided or _seeded(self.schema) or self.field.modified
        ):
            return MISSING
        value = self.field.value()
        if isinstance(value, InputArray) and not value.assigned:
            return MISSING
        return MISSING if isinstance(self.field, ObjectField) and not value else value

    def reset(self, sizes: Mapping[str, int]) -> None:
        self.set_value(MISSING, sizes)

    def set_value(self, value: Any, sizes: Mapping[str, int]) -> None:
        self._provided = value is not MISSING
        self.sizes = sizes
        initial = value
        if value is MISSING and self.schema.get("type") not in {"array", "object"}:
            initial = suggestion(self.schema, sizes)
        replacement = _field_widget(self.name, self.schema, initial, sizes, self)
        replacement.setToolTip(self.field.toolTip())
        self.layout().replaceWidget(self.field, replacement)
        self.field.deleteLater()
        self.field = replacement


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
        self.schemas, self.sizes = schemas, sizes
        self.data: dict[str, Any] = {}
        self.objects: dict[tuple[str, tuple[int, ...]], ObjectField] = {}
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
                    set(value.assigned) if isinstance(value, InputArray)
                    else positions if value is not MISSING else set()
                ) & positions
                self.data[name] = InputArray(
                    dense, source_positions | (positions if _seeded(schema) else set())
                )
            else:
                self.data[name] = {} if value is MISSING else value
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
                    self.setCellWidget(row, column, obj.rows[component])
                    label = QTableWidgetItem(
                        component + (" *" if component in item.get("required", []) else "")
                    )
                    label.setToolTip(
                        str(item["properties"][component].get("description", component))
                    )
                    self.setHorizontalHeaderItem(column, label)
                self.objects[name, indices] = obj
        self.resizeRowsToContents()
        self.setMinimumHeight(
            min(400, header.height() + sum(self.rowHeight(i) for i in range(self.rowCount())) + 4)
        )

    def values(self) -> dict[str, Any]:
        result = copy.deepcopy(self.data)
        for (name, indices), obj in self.objects.items():
            value = obj.value()
            if indices:
                _nested_get(result[name], indices[:-1])[indices[-1]] = value
                if value:
                    result[name].assigned.add(tuple(index + 1 for index in indices))
            else:
                result[name] = value
        return result

    def reset(self) -> None:
        for name, data in self.data.items():
            if isinstance(data, InputArray):
                shape = array_shape(data)
                data.assigned = (
                    set(product(*(range(1, n + 1) for n in shape)))
                    if _seeded(self.schemas[name]) else set()
                )
        for obj in self.objects.values():
            obj.reset(self.sizes)


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
        self.schemas, self.sizes = schemas, sizes
        self.rows: dict[str, list[FieldRow]] = {}
        first = next(iter(schemas.values()))
        shape = resolve_shape(first, sizes)
        if len(shape) != 1:
            raise ValueError("referenced parameter arrays must be one-dimensional")
        size = shape[0]
        self.setRowCount(len(schemas))
        self.setColumnCount(size)
        self.setHorizontalHeaderLabels(
            axis_labels(first, 1, size) or [str(index) for index in range(1, size + 1)]
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
            positions = {(index,) for index in range(1, size + 1)}
            assigned = (
                set(raw.assigned) if isinstance(raw, InputArray)
                else positions if saved else set()
            ) & positions
            if _seeded(schema):
                assigned.update(positions)
            label = QTableWidgetItem(name + (" *" if name.lower() in required else ""))
            label.setToolTip(str(schema.get("description", schema.get("title", name))))
            self.setVerticalHeaderItem(row_index, label)
            cells = []
            for index in range(size):
                value = dense[index] if (index + 1,) in assigned else MISSING
                cell = FieldRow(name, item, value, sizes, self)
                self.setCellWidget(row_index, index, cell)
                cells.append(cell)
            self.rows[name] = cells
        self.resizeRowsToContents()
        header = cast(QHeaderView, self.horizontalHeader())
        self.setMinimumHeight(
            min(400, header.height() + sum(self.rowHeight(i) for i in range(self.rowCount())) + 4)
        )

    def values(self) -> dict[str, InputArray]:
        result = {}
        for name, cells in self.rows.items():
            assigned = {
                (index,)
                for index, cell in enumerate(cells, 1)
                if cell.value() is not MISSING
            }
            if assigned:
                result[name] = InputArray([cell.field.value() for cell in cells], assigned)
        return result

    def reset(self) -> None:
        for name, cells in self.rows.items():
            schema = self.schemas[name]
            defaults = suggestion(schema, self.sizes)
            for index, cell in enumerate(cells):
                if _seeded(schema):
                    cell.set_value(defaults[index], self.sizes)
                else:
                    cell.reset(self.sizes)


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
        layout = QFormLayout(self)
        self.rows: dict[str, FieldRow] = {}
        self.tables: list[DerivedTable | ReferencedArrayTable] = []
        groups: dict[tuple[str, ...], dict[str, Mapping[str, Any]]] = {}
        identities = {}
        for name, child in properties.items():
            item = child.get("items", {}) if child.get("type") == "array" else child
            origin = item.get(DERIVED_REF_ORIGIN_KEY) if item.get("type") == "object" else None
            identity = tuple(origin["identity"]) if origin else ()
            if child.get("type") == "array" and item.get("type") in {
                "boolean", "integer", "number", "string"
            }:
                shape = resolve_shape(child, sizes)
                labels = axis_labels(child, 1, shape[0]) if len(shape) == 1 else None
                if labels:
                    identity = (
                        "array",
                        str(shape[0]),
                        str(item["type"]),
                        str(item.get("x-fortran-kind")),
                        str(item.get("x-fortran-len")),
                        *labels,
                    )
            if identity:
                identities[name] = identity
                groups.setdefault(identity, {})[name] = child
        for name, child in properties.items():
            if not isinstance(name, str) or not isinstance(child, Mapping):
                continue
            is_required = name.lower() in required
            children = groups.get(identities.get(name, ()))
            if children:
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
            )
            layout.addRow(_field_label(name, child, is_required), row)
            self.rows[name] = row

    def values(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, row in self.rows.items():
            value = row.value()
            if value is not MISSING:
                result[name] = value
        for table in self.tables:
            result.update(table.values())
        return {name: result[name] for name in self.schema["properties"] if name in result}

    def reset(self) -> None:
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
) -> Any:
    kind = schema.get("type")
    if kind == "array":
        return ArrayField(name, schema, value, sizes, parent, fit_existing=fit_arrays)
    if kind == "object":
        return ObjectField(schema, value, sizes, parent, fit_arrays=fit_arrays)
    if kind == "string" and schema.get("format") == "file-path":
        return PathField(schema, value, parent)
    if kind == "string" and schema.get("format") == "date-time":
        return DateTimeField(schema, value, parent)
    return ScalarField(schema, value, parent)


def _field_label(name: str, schema: Mapping[str, Any], required: bool) -> str:
    title = schema.get("title")
    label = f"{title} ({name})" if isinstance(title, str) and title.strip() else name
    return f"{label} *" if required else label


def _nested_get(value: Any, indices: tuple[int, ...]) -> Any:
    for index in indices:
        value = value[index]
    return value


def _structured_to_objects(data: Any) -> list[Any]:
    names = data.dtype.names or ()

    def build(axis: int, prefix: tuple[int, ...]) -> Any:
        if axis == data.ndim:
            record = data[prefix]
            return {name: _numpy_scalar(record[name]) for name in names}
        return [build(axis + 1, (*prefix, index)) for index in range(data.shape[axis])]

    return cast(list[Any], build(0, ()))


def _numpy_scalar(value: Any) -> Any:
    return value.item() if hasattr(value, "item") else value


def _preserve_omissions(edited: Any, original: Any, defaults: Any) -> Any:
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
