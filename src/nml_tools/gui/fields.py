"""Schema-driven Qt field widgets."""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import Any, cast

from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QWidget,
)

from .arrays import (
    array_shape,
    axis_labels,
    canonical_array,
    display_array,
    flex_tail_dims,
    initial_array,
    resolve_shape,
    table_axes,
)
from .model import MISSING


def _exec(dialog: Any) -> int:
    method = getattr(dialog, "exec", None)
    if method is None:
        method = dialog.exec_
    return int(method())


def _accepted(dialog: Any) -> int:
    value = getattr(dialog, "Accepted", None)
    value = value if value is not None else dialog.DialogCode.Accepted
    return int(getattr(value, "value", value))


def suggestion(schema: Mapping[str, Any], sizes: Mapping[str, int]) -> Any:
    """Return a deterministic editable suggestion for a resolved field schema."""
    examples = schema.get("examples")
    if isinstance(examples, list) and examples:
        candidate = copy.deepcopy(examples[0])
    elif "default" in schema:
        candidate = copy.deepcopy(schema["default"])
    else:
        candidate = MISSING

    kind = schema.get("type")
    if kind == "array":
        items = schema.get("items")
        if not isinstance(items, Mapping):
            raise ValueError("array field must define object 'items'")
        leaf = suggestion(items, sizes)
        return initial_array(schema, sizes, None if candidate is MISSING else candidate, leaf)
    if kind == "object":
        raw = candidate if isinstance(candidate, Mapping) else {}
        properties = schema.get("properties")
        if not isinstance(properties, Mapping):
            raise ValueError("derived field must define object 'properties'")
        return {
            name: copy.deepcopy(raw[name]) if name in raw else suggestion(child, sizes)
            for name, child in properties.items()
            if isinstance(name, str) and isinstance(child, Mapping)
        }
    if candidate is not MISSING:
        return candidate
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return copy.deepcopy(enum[0])
    if kind == "boolean":
        return False
    if kind == "integer":
        minimum = schema.get("minimum")
        return int(minimum) if isinstance(minimum, int) and not isinstance(minimum, bool) else 0
    if kind == "number":
        minimum = schema.get("minimum")
        return float(minimum) if isinstance(minimum, (int, float)) else 0.0
    if kind == "string":
        return ""
    raise ValueError(f"unsupported schema type '{kind}'")


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

    def set_value(self, value: Any) -> None:
        if isinstance(self.control, QComboBox):
            index = self.control.findData(value)
            self.control.setCurrentIndex(max(index, 0))
        elif isinstance(self.control, QCheckBox):
            self.control.setChecked(bool(value))
        else:
            self.control.setText(str(value))

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


class ObjectField(QGroupBox):
    def __init__(
        self,
        schema: Mapping[str, Any],
        value: Any,
        sizes: Mapping[str, int],
        parent: QWidget | None = None,
    ):
        super().__init__(str(schema.get("x-fortran-type", "Derived value")), parent)
        self.schema = schema
        self.sizes = sizes
        properties = schema.get("properties")
        if not isinstance(properties, Mapping):
            raise ValueError("derived field must define object 'properties'")
        if isinstance(value, Mapping):
            source = value
        elif isinstance(schema.get("default"), Mapping):
            source = schema["default"]
        else:
            examples = schema.get("examples")
            source = examples[0] if isinstance(examples, list) and examples else {}
            if not isinstance(source, Mapping):
                source = {}
        required = {
            item.lower() for item in schema.get("required", []) if isinstance(item, str)
        }
        layout = QFormLayout(self)
        self.rows: dict[str, FieldRow] = {}
        for name, child in properties.items():
            if not isinstance(name, str) or not isinstance(child, Mapping):
                continue
            child_value = source.get(name, MISSING) if isinstance(source, Mapping) else MISSING
            is_required = name.lower() in required
            row = FieldRow(name, child, child_value, sizes, self)
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
        for row in self.rows.values():
            row.reset(sizes)


class ArrayField(QWidget):
    def __init__(
        self,
        name: str,
        schema: Mapping[str, Any],
        value: Any,
        sizes: Mapping[str, int],
        parent: QWidget | None = None,
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
            strict=saved,
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel(self)
        button = QPushButton("Edit array…", self)
        button.clicked.connect(self._edit)
        layout.addWidget(self.summary, 1)
        layout.addWidget(button)
        self._update_summary()

    def value(self) -> list[Any]:
        return copy.deepcopy(self._value)

    def reset(self, sizes: Mapping[str, int]) -> None:
        self.sizes = sizes
        self._value = suggestion(self.schema, sizes)
        self._update_summary()

    def _update_summary(self) -> None:
        shape = array_shape(self._value)
        self.summary.setText("×".join(str(value) for value in shape))

    def _edit(self) -> None:
        try:
            import numpy as np
            from guidata.widgets.arrayeditor import ArrayEditor  # type: ignore[import-untyped]

            rank = len(resolve_shape(self.schema, self.sizes, self._value))
            derived = self.items.get("type") == "object"
            canonical = self._structured_array(np) if derived else self._intrinsic_array(np)
            displayed = display_array(canonical, self.schema)
            xlabels, ylabels = self._display_labels(displayed.shape, rank)
            editor = ArrayEditor(self)
            raw_shape = self.schema.get("x-fortran-shape")
            deferred = raw_shape == ":" or (
                isinstance(raw_shape, list) and ":" in raw_shape
            )
            if not editor.setup_and_check(
                displayed,
                str(self.schema.get("title", self.name)),
                xlabels=xlabels,
                ylabels=ylabels,
                variable_size=flex_tail_dims(self.schema, rank) > 0 or deferred,
            ):
                return
            if _exec(editor) != _accepted(editor):
                return
            edited = editor.get_value()
            if derived:
                self._value = self._objects_from_structured(edited, rank, np)
            else:
                self._value = canonical_array(edited, self.schema, rank)
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
        shape = resolve_shape(self.schema, self.sizes, self._value)
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
    ):
        super().__init__(parent)
        self.name = name
        self.schema = schema
        self.sizes = sizes
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        initial = value
        if value is MISSING and schema.get("type") not in {"array", "object"}:
            initial = suggestion(schema, sizes)
        self.field = _field_widget(name, schema, initial, sizes, self)
        description = schema.get("description")
        if isinstance(description, str):
            self.field.setToolTip(description.strip())
        layout.addWidget(self.field, 1)

    def value(self) -> Any:
        return self.field.value()

    def reset(self, sizes: Mapping[str, int]) -> None:
        self.sizes = sizes
        self.field.reset(sizes)


class NamelistForm(QWidget):
    """Editable form for one namelist schema."""

    def __init__(
        self,
        schema: Mapping[str, Any],
        values: Mapping[str, Any] | None,
        sizes: Mapping[str, int],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.schema = schema
        self.sizes = sizes
        properties = schema.get("properties")
        if not isinstance(properties, Mapping):
            raise ValueError("namelist schema must define object 'properties'")
        source = values or {}
        required = {
            item.lower() for item in schema.get("required", []) if isinstance(item, str)
        }
        layout = QFormLayout(self)
        self.rows: dict[str, FieldRow] = {}
        for name, child in properties.items():
            if not isinstance(name, str) or not isinstance(child, Mapping):
                continue
            is_required = name.lower() in required
            row = FieldRow(name, child, source.get(name, MISSING), sizes, self)
            layout.addRow(_field_label(name, child, is_required), row)
            self.rows[name] = row

    def values(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, row in self.rows.items():
            value = row.value()
            if value is not MISSING:
                result[name] = value
        return result

    def reset(self) -> None:
        for row in self.rows.values():
            row.reset(self.sizes)


def _field_widget(
    name: str,
    schema: Mapping[str, Any],
    value: Any,
    sizes: Mapping[str, int],
    parent: QWidget,
) -> Any:
    kind = schema.get("type")
    if kind == "array":
        return ArrayField(name, schema, value, sizes, parent)
    if kind == "object":
        return ObjectField(schema, value, sizes, parent)
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
            return {
                name: _numpy_scalar(record[name])
                for name in names
            }
        return [build(axis + 1, (*prefix, index)) for index in range(data.shape[axis])]

    return cast(list[Any], build(0, ()))


def _numpy_scalar(value: Any) -> Any:
    return value.item() if hasattr(value, "item") else value


def _preserve_omissions(edited: Any, original: Any, defaults: Any) -> Any:
    if isinstance(edited, list) and isinstance(original, list):
        return [
            _preserve_omissions(item, old, defaults)
            for item, old in zip(edited, original)
        ]
    if isinstance(edited, Mapping) and isinstance(original, Mapping):
        return {
            name: value
            for name, value in edited.items()
            if name in original
            or not isinstance(defaults, Mapping)
            or value != defaults.get(name)
        }
    return edited
