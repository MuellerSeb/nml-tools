# mypy: disable-error-code="attr-defined, import-not-found, misc"
"""Project-oriented Qt editor for direct namelist input and output."""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import product
from pathlib import Path
from shutil import copy2
from typing import Any

from qtpy.QtCore import QSignalBlocker, Qt, QTimer
from qtpy.QtGui import QColor, QFont, QPalette
from qtpy.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidgetItem,
    QToolButton,
    QToolTip,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .arrays import array_shape
from .fields import InputValidationError, NamelistForm, _exec, validation_focus_widget
from .highlighter import NamelistHighlighter
from .model import (
    MISSING,
    GuiProfile,
    GuiProject,
    GuiProjectProfile,
    GuiProjectRequest,
    InputArray,
    _normalize_dimensions,
    _normalize_profile_values,
    _profile_path,
    _select_profiles,
    create_virtual_project,
    dimension_source_values,
    discover_project_files,
    ensure_dimension_sources,
    load_profile,
    load_project,
    load_project_profile_file,
    overlay_values,
    persistence_default,
    profile_from_namelist,
    recover_dimensions,
    render_profile,
    save_profiles,
    save_project_profile,
    suggestion,
    validate_project_filename,
    validate_project_name,
)
from .ui import load_ui

_UNSET = object()


def _untouched_page_values(
    schema: Mapping[str, Any], source: Mapping[str, Any] | None, sizes: Mapping[str, int]
) -> dict[str, Any]:
    """Collect loaded values and defaults without constructing an unseen page."""
    properties = schema.get("properties", {})
    required = {str(name).lower() for name in schema.get("required", [])}
    raw = source or {}
    result: dict[str, Any] = {}
    for name, child in properties.items():
        if not isinstance(name, str) or not isinstance(child, Mapping):
            continue
        try:
            value = _untouched_value(
                child,
                raw.get(name, _UNSET),
                name.lower() in required or "default" in child,
                name,
                sizes,
            )
        except ValueError as exc:
            raise InputValidationError(name, None, str(exc)) from exc
        if value is not _UNSET:
            result[name] = value
    return result


def _untouched_value(
    schema: Mapping[str, Any],
    value: Any,
    required: bool,
    name: str,
    sizes: Mapping[str, int],
) -> Any:
    """Apply GUI default/required rules to an unvisited field."""
    kind = schema.get("type")
    if value is not _UNSET:
        if kind == "string" and value == "":
            if "default" in schema:
                return copy.deepcopy(schema["default"])
            if required:
                raise ValueError(f"required field '{name}' has no value")
            return _UNSET
        if kind != "object" or not isinstance(value, Mapping):
            return copy.deepcopy(value)
        base = schema.get("default", {})
        source = overlay_values(base, value) if isinstance(base, Mapping) else dict(value)
    elif "default" in schema:
        return suggestion(schema, sizes) if kind == "array" else copy.deepcopy(schema["default"])
    elif kind == "array":
        default = persistence_default(schema, sizes)
        if default is _UNSET or default is MISSING:
            if required:
                raise ValueError(f"required field '{name}' has no value")
            return _UNSET
        shape = array_shape(default)
        return InputArray(
            default,
            set(product(*(range(1, size + 1) for size in shape))),
        )
    elif kind != "object":
        if required:
            raise ValueError(f"required field '{name}' has no value")
        return _UNSET
    else:
        source = {}
        if not required:
            return _UNSET
    properties = schema.get("properties", {})
    child_required = {str(item).lower() for item in schema.get("required", [])}
    result: dict[str, Any] = {}
    for child_name, child in properties.items():
        if not isinstance(child_name, str) or not isinstance(child, Mapping):
            continue
        child_value = _untouched_value(
            child,
            source.get(child_name, _UNSET),
            child_name.lower() in child_required or "default" in child,
            f"{name}%{child_name}",
            sizes,
        )
        if child_value is not _UNSET:
            result[child_name] = child_value
    if required and not result:
        raise ValueError(f"required field '{name}' has no value")
    return result


class NamelistPage(QWidget):
    """Ordered namelist pages for one file profile."""

    def __init__(
        self,
        project: GuiProject,
        profile: GuiProfile,
        values: Mapping[str, Any],
        dimensions: Mapping[str, int],
        parent: QWidget | None = None,
        *,
        fit_arrays: bool = False,
        output_root: Path | None = None,
        source_values: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(parent)
        load_ui("page_namelist.ui", self)
        self.project = project
        self.profile = profile
        self.dimensions = dict(dimensions)
        self.saved_dimensions = dict(dimensions)
        self._values = copy.deepcopy(dict(values))
        self._sizes = {**project.constants, **dimensions}
        self._fit_arrays = fit_arrays
        self.output_root = (output_root or project.output_root).resolve()
        self.source_values = copy.deepcopy(dict(source_values or {}))
        self.forms: dict[str, NamelistForm] = {}
        self.form_saved: dict[str, dict[str, Any]] = {}
        self.stack = self.namelistStack
        self.back = self.backButton_namelist
        self.next = self.nextButton_namelist
        self.restore = self.restoreButton_namelist
        self.cancel = self.cancelButton_namelist
        self.save = self.saveButton_namelist
        for _page in profile.pages:
            self.stack.addWidget(QWidget(self.stack))
        self.stack.currentChanged.connect(self._page_changed)
        self.back.clicked.connect(
            lambda: self.stack.setCurrentIndex(self.stack.currentIndex() - 1)
        )
        self.next.clicked.connect(
            lambda: self.stack.setCurrentIndex(self.stack.currentIndex() + 1)
        )
        self.restore.clicked.connect(self.restore_page)
        self._page_changed(self.stack.currentIndex())
        self.saved_values = copy.deepcopy(dict(values))

    def values(self) -> dict[str, Any]:
        """Return values from every namelist page."""
        result = {}
        for index, page in enumerate(self.profile.pages):
            form = self.forms.get(page.name)
            try:
                result[page.name] = (
                    (form or self._ensure_form(index)).values()
                    if form is not None or self._fit_arrays
                    else _untouched_page_values(
                        page.schema, self._values.get(page.name), self._sizes
                    )
                )
            except InputValidationError as exc:
                exc.page_key, exc.page_name = page.key, page.name
                raise
            if page.name in self.source_values:
                result[page.name] = overlay_values(
                    result[page.name], self.source_values[page.name]
                )
        return result

    def is_dirty(self) -> bool:
        """Check only pages already visited by the user."""
        if self.dimensions != self.saved_dimensions:
            return True
        try:
            return any(form.values() != self.form_saved[name] for name, form in self.forms.items())
        except ValueError:
            return True

    def mark_saved(self, values: Mapping[str, Any]) -> None:
        """Record a successful save without rebuilding any unvisited page."""
        self.saved_values = copy.deepcopy(dict(values))
        self.saved_dimensions = dict(self.dimensions)
        for name, form in self.forms.items():
            self.form_saved[name] = copy.deepcopy(form.values())

    def mark_page_saved(self, page: Any, values: Mapping[str, Any]) -> None:
        """Record a successful save for one namelist page only."""
        saved = copy.deepcopy(dict(values))
        self.saved_values[page.name] = saved
        self._values[page.name] = copy.deepcopy(saved)
        form = self.forms.get(page.name)
        self.form_saved[page.name] = copy.deepcopy(
            form.values() if form is not None else saved
        )

    def restore_page(self) -> None:
        """Restore the active namelist page."""
        index = self.stack.currentIndex()
        if index >= 0:
            form = self._ensure_form(index)
            form.reset()
            self._apply_sources(self.profile.pages[index], form)

    def restore_all(self) -> None:
        """Restore every page in this file profile."""
        for index in range(len(self.profile.pages)):
            form = self._ensure_form(index)
            form.reset()
            self._apply_sources(self.profile.pages[index], form)

    def page_values(self) -> tuple[Any, dict[str, Any]]:
        """Return the active page and only its current values."""
        index = self.stack.currentIndex()
        page = self.profile.pages[index]
        try:
            values = self._ensure_form(index).values()
        except InputValidationError as exc:
            exc.page_key, exc.page_name = page.key, page.name
            raise
        if page.name in self.source_values:
            values = overlay_values(values, self.source_values[page.name])
        return page, values

    def discard_page(self) -> None:
        """Replace the active page with its last saved values."""
        index = self.stack.currentIndex()
        if index < 0:
            return
        page = self.profile.pages[index]
        saved = copy.deepcopy(
            self.form_saved.get(page.name, self.saved_values.get(page.name, {}))
        )
        self._values[page.name] = saved
        self.forms.pop(page.name, None)
        old = self.stack.widget(index)
        placeholder = QWidget(self.stack)
        with QSignalBlocker(self.stack):
            self.stack.removeWidget(old)
            self.stack.insertWidget(index, placeholder)
            self.stack.setCurrentIndex(index)
        old.deleteLater()
        self._ensure_form(index)

    def select_page(self, key: str) -> None:
        """Select a namelist page by normalized name."""
        for index, page in enumerate(self.profile.pages):
            if page.key == key:
                self.stack.setCurrentIndex(index)
                return

    def reveal_property(
        self,
        page_key: str,
        property_name: str,
        message: str = "",
        widget: QWidget | None = None,
    ) -> None:
        """Open, focus, and explain one invalid namelist property."""
        for index, page in enumerate(self.profile.pages):
            if page.key != page_key:
                continue
            self.stack.setCurrentIndex(index)
            form = self._ensure_form(index)
            target = widget if widget is not None and form.isAncestorOf(widget) else None
            target = target or form.validation_widget(property_name)
            focus = validation_focus_widget(target)
            scroll = self.stack.currentWidget()

            def reveal(
                area: QWidget = scroll,
                container: QWidget = target,
                control: QWidget = focus,
                text: str = message,
            ) -> None:
                if isinstance(area, QScrollArea):
                    area.ensureWidgetVisible(container)
                control.setFocus(Qt.OtherFocusReason)
                if text:
                    QToolTip.showText(
                        control.mapToGlobal(control.rect().bottomLeft()), text, control
                    )

            QTimer.singleShot(0, reveal)
            return

    def _page_changed(self, index: int) -> None:
        """Build the selected page on first use and display it."""
        if index >= 0:
            self._ensure_form(index)
            description = str(self.profile.pages[index].schema.get("description") or "")
            self.descriptionLabel.setText(description)
            self.descriptionLabel.setVisible(bool(description))
        else:
            self.descriptionLabel.clear()
            self.descriptionLabel.hide()
        self._update_navigation(index)

    def _ensure_form(self, index: int) -> NamelistForm:
        """Construct one schema page only when it becomes visible or saved."""
        page = self.profile.pages[index]
        existing = self.forms.get(page.name)
        if existing is not None:
            return existing
        read_only = {
            source.property.lower()
            for source in self.project.dimension_sources.values()
            if source.namelist == page.key
        }
        form = NamelistForm(
            page.schema,
            self._values.get(page.name),
            self._sizes,
            fit_arrays=self._fit_arrays,
            output_root=self.output_root,
            read_only=read_only,
        )
        self._apply_sources(page, form)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(form)
        old = self.stack.widget(index)
        with QSignalBlocker(self.stack):
            self.stack.removeWidget(old)
            self.stack.insertWidget(index, scroll)
            self.stack.setCurrentIndex(index)
        old.deleteLater()
        self.forms[page.name] = form
        try:
            self.form_saved[page.name] = copy.deepcopy(form.values())
        except ValueError:
            self.form_saved[page.name] = copy.deepcopy(dict(self._values.get(page.name, {})))
        return form

    def _apply_sources(self, page: Any, form: NamelistForm) -> None:
        """Project current dimensions back into read-only source fields."""
        for name, value in self.source_values.get(page.name, {}).items():
            row = form.rows.get(name)
            if row is not None:
                row.set_value(value, self._sizes)
                row.field.setEnabled(False)

    def _update_navigation(self, index: int) -> None:
        """Update Back/Next availability for the active page."""
        self.back.setEnabled(index > 0)
        self.next.setEnabled(0 <= index < len(self.profile.pages) - 1)
        self.restore.setEnabled(index >= 0)


class FilePage(QWidget):
    """Read-only summary and preview for one namelist file."""

    def __init__(
        self,
        project: GuiProject,
        profile: GuiProfile,
        editor: NamelistPage,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        load_ui("page_file.ui", self)
        self.back = self.backButton_file
        self.next = self.nextButton_file
        self.restore = self.restoreButton_file
        self.cancel = self.cancelButton_file
        self.save = self.saveButton_file
        path = _profile_path(project, profile, editor.output_root)
        self.fileNameEdit.setText(profile.default_file)
        self.currentPathLabel.setText(str(path))
        self.namelistsTable.setRowCount(len(profile.pages))
        for row, page in enumerate(profile.pages):
            self.namelistsTable.setItem(row, 0, QTableWidgetItem(page.name))
            self.namelistsTable.setItem(
                row, 1, QTableWidgetItem(str(page.schema.get("description") or ""))
            )
        header = self.namelistsTable.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.sectionResized.connect(self._resize_rows)
        QTimer.singleShot(0, self._resize_rows)
        try:
            if path.exists():
                preview = path.read_text(encoding="utf-8")
            else:
                rendered = render_profile(project, profile, editor.values(), editor.dimensions)
                preview = "\n".join(text.rstrip() for text in rendered.values()) + "\n"
        except (OSError, ValueError, KeyError) as exc:
            preview = f"Preview unavailable: {exc}"
        self.previewBrowser.setFont(QFont("JetBrains Mono", 11))
        self.highlighter = NamelistHighlighter(self.previewBrowser.document())
        self.previewBrowser.setPlainText(preview)

    def _resize_rows(self, *_args: Any) -> None:
        """Refit wrapped rows after the description column receives its width."""
        self.namelistsTable.resizeRowsToContents()
        self.namelistsTable.updateGeometry()


class ProjectPage(QWidget):
    """Set one project's output directory and runtime dimensions."""

    def __init__(
        self,
        project: GuiProject,
        dimensions: Mapping[str, int],
        parent: QWidget,
        linked_dimensions: Iterable[str] = (),
    ) -> None:
        super().__init__(parent)
        load_ui("page_project.ui", self)
        self.setAutoFillBackground(True)
        self.project = project
        self.set = self.setButton
        self.back = self.backButton_project
        self.next = self.nextButton_project
        self.restore = self.restoreButton_project
        self.cancel = self.cancelButton_project
        self.save = self.saveButton_project
        self.profile_type = self.label_projectProfileTypeValue
        self.custom_group = self.groupBox_customProjectProfile
        self.custom_name = self.lineEdit_customProjectProfileName
        self.custom_filename = self.lineEdit_customTomlFileName
        self.save_custom = self.pushButton_saveCustomTomlFile
        self.dimension_boxes: dict[str, QSpinBox] = {}
        self.dimension_source_buttons: dict[str, QPushButton] = {}
        linked = set(linked_dimensions)
        for name, default in project.default_dimensions.items():
            box = QSpinBox(self.dimensionsGroup)
            box.setRange(1, 2_147_483_647)
            box.setValue(dimensions.get(name, default))
            source = project.dimension_sources.get(name) if name in linked else None
            if source is None:
                self.dimensionsLayout.addRow(name, box)
            else:
                container = QWidget(self.dimensionsGroup)
                layout = QHBoxLayout(container)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.addWidget(box)
                button = QPushButton("R", container)
                button.setObjectName("dimensionSourceButton")
                button.setFixedWidth(24)
                font = button.font()
                font.setBold(True)
                button.setFont(font)
                palette = button.palette()
                palette.setColor(QPalette.ButtonText, QColor("red"))
                button.setPalette(palette)
                button.setToolTip(f"Open source: {source.namelist}%{source.property}")
                layout.addWidget(button)
                self.dimensionsLayout.addRow(name, container)
                self.dimension_source_buttons[name] = button
            self.dimension_boxes[name] = box
        self.dimensionsGroup.setVisible(bool(self.dimension_boxes))
        header = self.fileProfilesTable.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.sectionResized.connect(self._resize_rows)
        QTimer.singleShot(0, self._resize_rows)

    def dimensions(self) -> dict[str, int]:
        """Return runtime dimensions entered on this tab."""
        return {name: box.value() for name, box in self.dimension_boxes.items()}

    def set_project_profile(self, profile: GuiProjectProfile) -> None:
        """Show whether this project is configured or user-owned."""
        self.profile_type.setText("Custom" if profile.custom else "Standard")
        name = profile.name if profile.custom else f"{profile.name}-custom"
        self.custom_name.setText(name)
        self.custom_filename.setText(
            profile.toml_file if profile.custom and profile.toml_file else f"{name}.toml"
        )
        self.custom_group.setChecked(profile.custom)

    def set_profiles(self, profiles: Sequence[GuiProfile], output_root: Path) -> None:
        """Refresh the project file-profile summary."""
        self.fileProfilesTable.setRowCount(len(profiles))
        for row, profile in enumerate(profiles):
            values = (
                profile.name,
                str(_profile_path(self.project, profile, output_root)),
                profile.description or "",
            )
            for column, value in enumerate(values):
                self.fileProfilesTable.setItem(row, column, QTableWidgetItem(value))
        QTimer.singleShot(0, self._resize_rows)

    def _resize_rows(self, *_args: Any) -> None:
        """Refit wrapped file-profile rows after columns receive their width."""
        self.fileProfilesTable.resizeRowsToContents()
        self.fileProfilesTable.updateGeometry()


class FileProfileBuilder(QWidget):
    """Create or update one file profile from configured or saved sources."""

    def __init__(
        self,
        project: GuiProject,
        profiles: Sequence[GuiProfile],
        output_root: Path,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        load_ui("file_profile_builder.ui", self)
        self.project = project
        self.output_root = output_root
        self.source_profile: GuiProfile | None = None
        self.source_path: Path | None = None
        self.source_profiles: dict[str, GuiProfile] = {}
        self.active_source: tuple[str, str] | None = None
        self.source_combo = self.sourceComboBox_loadProfile
        self.add = self.addButton
        self.add.setDefault(True)
        self.available_schemas: QListWidget = self.availableSchemasList
        self.selected_schemas: QListWidget = self.selectedSchemasList
        self.profile_name = self.profileNameEdit
        self.default_filename = self.defaultFileEdit
        self.description = self.fileDescriptionEdit
        mode = QAbstractItemView.ExtendedSelection
        self.available_schemas.setSelectionMode(mode)
        self.selected_schemas.setSelectionMode(mode)
        for button, source, target, all_items in (
            (self.addSchemaButton, self.available_schemas, self.selected_schemas, False),
            (self.addAllSchemasButton, self.available_schemas, self.selected_schemas, True),
            (self.removeSchemaButton, self.selected_schemas, self.available_schemas, False),
            (self.removeAllSchemasButton, self.selected_schemas, self.available_schemas, True),
        ):
            callback = (
                AppDialog._move_all if all_items else AppDialog._move_selected
            )
            button.clicked.connect(lambda _checked=False, s=source, t=target, fn=callback: fn(s, t))
        self.reset_sources(profiles)

    def schema_keys(self) -> list[str]:
        """Return selected namelist keys in visible order."""
        return [
            str(self.selected_schemas.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.selected_schemas.count())
        ]

    def reset_sources(self, current: Sequence[GuiProfile]) -> None:
        """Group configured, saved-file and custom profile sources without duplicates."""
        standard = list(self.project.profiles)
        standard_keys = {profile.key for profile in standard}
        custom: dict[str, GuiProfile] = {}
        for path in discover_project_files(self.project, (self.output_root,)):
            try:
                profiles = load_project_profile_file(self.project, path, self.output_root).profiles
            except (OSError, ValueError):
                continue
            for profile in profiles:
                if profile.key not in standard_keys:
                    custom.setdefault(profile.key, profile)
        for profile in current:
            if profile.key not in standard_keys:
                custom[profile.key] = profile
        self.source_profiles = {
            profile.key: profile for profile in (*standard, *custom.values())
        }
        combo = self.source_combo
        with QSignalBlocker(combo):
            combo.clear()
            self._add_profiles(standard)
            if custom:
                combo.insertSeparator(combo.count())
                self._add_profiles(custom.values())
            if combo.count():
                combo.insertSeparator(combo.count())
            combo.addItem("Browse…", ("browse", ""))
            combo.insertSeparator(combo.count())
            combo.addItem("<custom>", ("custom", ""))
            combo.setCurrentIndex(0 if self.source_profiles else combo.count() - 1)
            self.active_source = combo.currentData()

    def _add_profiles(self, profiles: Iterable[GuiProfile]) -> None:
        """Append profile choices while keeping identity in item data."""
        for profile in profiles:
            self.source_combo.addItem(profile.title, ("profile", profile.key))

    def set_profile(self, profile: GuiProfile, *, configured: bool = True) -> None:
        """Populate the builder from one reusable profile."""
        self.source_profile = profile
        self.profile_name.setText(profile.name)
        self.default_filename.setText(profile.default_file)
        self.description.setText(profile.description or "")
        standard = (
            next((item for item in self.project.profiles if item.key == profile.key), None)
            if configured
            else None
        )
        selected = {page.key for page in profile.pages}
        required = set(standard.required if standard is not None else ())
        self.available_schemas.clear()
        self.selected_schemas.clear()
        pages = profile.pages if standard is not None else self.project.namelists
        for page in pages:
            target = self.selected_schemas if page.key in selected else self.available_schemas
            item = AppDialog._schema_item(page.name, page.key)
            if page.key in required:
                item.setFlags(
                    item.flags()
                    & ~Qt.ItemFlag.ItemIsEnabled
                    & ~Qt.ItemFlag.ItemIsSelectable
                )
            target.addItem(item)

    def clear_builder(self) -> None:
        """Clear metadata and make every configured namelist available."""
        self.source_profile = None
        self.source_path = None
        self.profile_name.clear()
        self.default_filename.clear()
        self.description.clear()
        self.available_schemas.clear()
        self.selected_schemas.clear()
        for page in self.project.namelists:
            self.available_schemas.addItem(AppDialog._schema_item(page.name, page.key))


class NamelistPicker(QWidget):
    """Select additional schemas for one existing file profile."""

    def __init__(self, project: GuiProject, profile: GuiProfile, parent: QWidget) -> None:
        super().__init__(parent)
        load_ui("namelist_picker.ui", self)
        self.available = self.availableNamelistsList
        self.available.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.add = self.addButton
        present = {page.key for page in profile.pages}
        standard = next(
            (item for item in project.profiles if item.key == profile.key), None
        )
        allowed = {page.key for page in standard.pages} if standard is not None else None
        for page in project.namelists:
            if page.key not in present:
                item = AppDialog._schema_item(page.name, page.key)
                if allowed is not None and page.key not in allowed:
                    item.setForeground(
                        self.palette().color(
                            QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text
                        )
                    )
                    item.setToolTip(
                        f"The standard file profile '{profile.name}' does not contain "
                        "this namelist."
                    )
                self.available.addItem(item)

    def schema_keys(self) -> list[str]:
        """Return selected schema keys in list order."""
        return [
            str(self.available.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.available.count())
            if self.available.item(index).isSelected()
        ]


class ProjectPickerDialog(QDialog):
    """Choose one project and its namelist input/output paths."""

    def __init__(self, project: GuiProject, parent: QWidget) -> None:
        super().__init__(parent)
        load_ui("project_picker.ui", self)
        self.project = project
        self.profile: GuiProjectProfile | None = None
        self.source_combo: QComboBox = self.sourceComboBox_loadProject
        self.output_path: QLineEdit = self.lineEdit_pathProjectOutputDirectory
        self.output_browse: QPushButton = self.pushButton_browseProjectOutputDirectory
        self.file_paths: dict[str, QLineEdit] = {}
        self.output_browse.clicked.connect(self._browse_output)
        self.output_path.editingFinished.connect(self._populate_files)

    def set_profile(self, profile: GuiProjectProfile, output_root: Path) -> None:
        """Show one project's file profiles below its output directory."""
        self.profile = profile
        for widget in (
            self.sourceLabel_namelistOutputDirectory,
            self.output_path,
            self.output_browse,
        ):
            widget.setEnabled(True)
        self.output_path.setText(str(output_root))
        self._populate_files()

    def output_root(self) -> Path:
        """Resolve the selected project output directory."""
        text = self.output_path.text().strip()
        if not text:
            raise ValueError("namelist output directory must not be empty")
        path = Path(text).expanduser()
        return (path if path.is_absolute() else self.project.root / path).resolve()

    def paths(self) -> dict[str, Path]:
        """Return the selected input/output path for each file profile."""
        root = self.output_root()
        result = {}
        for key, edit in self.file_paths.items():
            text = edit.text().strip()
            if not text:
                raise ValueError("namelist file path must not be empty")
            path = Path(text).expanduser()
            result[key] = (path if path.is_absolute() else root / path).resolve()
        return result

    def _clear_files(self) -> None:
        """Remove dynamically created file-profile path rows."""
        while self.gridLayout_fileProfileOutputs.count():
            item = self.gridLayout_fileProfileOutputs.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.file_paths.clear()

    def _populate_files(self) -> None:
        """Rebuild file-profile paths for the selected output directory."""
        self._clear_files()
        if self.profile is None or not self.output_path.text().strip():
            return
        root = self.output_root()
        for row, profile in enumerate(self.profile.profiles):
            label = QLabel(profile.name, self)
            edit = QLineEdit(str((root / profile.default_file).resolve()), self)
            button = QPushButton("Browse…", self)
            edit.textChanged.connect(lambda _text, item=edit: self._color_path(item))
            button.clicked.connect(
                lambda _checked=False, item=edit: self._browse_file(item)
            )
            self.gridLayout_fileProfileOutputs.addWidget(label, row, 0)
            self.gridLayout_fileProfileOutputs.addWidget(edit, row, 1)
            self.gridLayout_fileProfileOutputs.addWidget(button, row, 2)
            self.file_paths[profile.key] = edit
            self._color_path(edit)

    def _browse_output(self) -> None:
        """Select the directory receiving this project's namelists."""
        path = QFileDialog.getExistingDirectory(
            self, "Namelist output directory", self.output_path.text()
        )
        if path:
            self.output_path.setText(path)
            self._populate_files()

    def _browse_file(self, edit: QLineEdit) -> None:
        """Select an existing namelist source for one file profile."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load namelist",
            edit.text() or self.output_path.text(),
            "Fortran namelist files (*.nml)",
        )
        if path:
            edit.setText(str(Path(path).resolve()))

    def _color_path(self, edit: QLineEdit) -> None:
        """Color existing namelists blue and future outputs red."""
        path = Path(edit.text()).expanduser()
        if not path.is_absolute() and self.output_path.text().strip():
            path = self.output_root() / path
        palette = edit.palette()
        palette.setColor(
            QPalette.ColorRole.Text,
            QColor("blue" if path.is_file() else "red"),
        )
        edit.setPalette(palette)


@dataclass(frozen=True)
class _ProjectFile:
    """One validated file-profile source and final destination."""

    profile: GuiProfile
    source: Path
    target: Path


@dataclass(frozen=True)
class _ProjectSelection:
    """One confirmed project selection ready to register."""

    profile: GuiProjectProfile
    files: tuple[_ProjectFile, ...]


class AppDialog(QDialog):
    """Edit one or more project profiles and their direct namelist files."""

    def __init__(
        self,
        project: GuiProject,
        parent: QWidget | None = None,
        project_requests: Sequence[GuiProjectRequest] = (),
    ) -> None:
        super().__init__(parent)
        load_ui("app.ui", self)
        self.project = project
        profiles = project.project_profiles or (
            GuiProjectProfile(
                "default",
                "default",
                "Default",
                None,
                project.profiles,
                custom=True,
                output_dir=project.output_root,
            ),
        )
        self.available_projects = {profile.key: profile for profile in profiles}
        self.project_initial_values: dict[str, dict[str, Any]] = {}
        self.project_initial_dimensions: dict[str, dict[str, int]] = {}
        requested_keys: list[str] = []
        requested_profiles: list[GuiProjectProfile] = []
        for request in project_requests:
            if not isinstance(request, GuiProjectRequest):
                raise ValueError("projects must contain GuiProjectRequest objects")
            if not isinstance(request.project_profile, str):
                raise ValueError("project_profile must be a string")
            key = request.project_profile.strip().lower()
            if key not in self.available_projects:
                raise ValueError(f"unknown project profile '{request.project_profile}'")
            if not isinstance(request.output_dir, (str, Path)):
                raise ValueError("project output_dir must be a directory path")
            profile = replace(
                self.available_projects[key], output_dir=Path(request.output_dir).resolve()
            )
            if request.file_profiles is not None:
                if not isinstance(request.file_profiles, Mapping):
                    raise ValueError(
                        "file_profiles must map profile names to namelist names"
                    )
                if request.file_profiles:
                    selection = {
                        name: list(names) for name, names in request.file_profiles.items()
                    }
                    profile = replace(
                        profile,
                        profiles=_select_profiles(
                            replace(project, profiles=profile.profiles), selection
                        ),
                    )
            instance_key = key
            suffix = 2
            while instance_key in requested_keys:
                instance_key = f"{key}_{suffix}"
                suffix += 1
            profile = replace(profile, key=instance_key)
            available = {item.key: item for item in profile.profiles}
            values: dict[str, Any] = {}
            if not isinstance(request.initial_values, Mapping):
                raise ValueError("initial_values must map file profiles to namelist values")
            for name, supplied in request.initial_values.items():
                if not isinstance(name, str) or name.lower() not in available:
                    raise ValueError(f"unknown initial value profile '{name}'")
                profile_key = name.lower()
                if profile_key in values:
                    raise ValueError(f"duplicate initial value profile '{name}'")
                values[profile_key] = copy.deepcopy(supplied)
            if not isinstance(request.initial_dimensions, Mapping):
                raise ValueError("initial_dimensions must map dimension names to sizes")
            _normalize_dimensions(request.initial_dimensions, project)
            self.project_initial_values[instance_key] = values
            self.project_initial_dimensions[instance_key] = {
                str(name).lower(): size for name, size in request.initial_dimensions.items()
            }
            requested_keys.append(instance_key)
            requested_profiles.append(profile)
        self.loaded_projects: dict[str, GuiProjectProfile] = {}
        self.project_items: dict[str, QTreeWidgetItem] = {}
        self.project_editors: dict[str, dict[Path, NamelistPage]] = {}
        self.project_configs: dict[str, ProjectPage] = {}
        self.project_dimensions: dict[str, dict[str, int]] = {}
        self.project_saved_dimensions: dict[str, dict[str, int]] = {}
        self.active_project: str | None = None
        self.editors: dict[Path, NamelistPage] = {}
        self.config_tab: ProjectPage | None = None
        self.current_overview: FilePage | None = None
        self.current_tool: QWidget | None = None
        self.empty_view: QWidget | None = None
        self.schemas_path = self.lineEdit_pathSchemasConfigFile
        self.schemas_browse = self.browseButton_browseSchemasConfigFile
        self.schemas_scan = self.browseButton_scanSchemasConfigFile
        self.schemas_path.setText(
            str(project.config_path or (project.root / "nml-config.toml").resolve())
        )
        self.tabs.setTabsClosable(False)
        self.splitter.setSizes([self.width(), self.width() * 3])
        self.treeWidget_projectStructure.setColumnCount(2)
        self.treeWidget_projectStructure.setHeaderLabels(["Project structure", ""])
        header = self.treeWidget_projectStructure.header()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(28)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        self.treeWidget_projectStructure.setColumnWidth(1, 28)
        self.schemas_browse.clicked.connect(self._browse_schemas)
        self.schemas_scan.clicked.connect(self._scan_schemas)
        self.treeWidget_projectStructure.currentItemChanged.connect(self._tree_selected)
        self.restoreAllButton.clicked.connect(self._restore_all)
        self.saveAllButton.clicked.connect(self._save_all)
        self.closeButton.clicked.connect(self.accept)
        self.project_add_item = self._action_item(
            None, "Project", ("add_project", "", "", ""), self._add_selected_project
        )
        self.project_add_button = self.treeWidget_projectStructure.itemWidget(
            self.project_add_item, 0
        )
        self.project_add_button.setToolTip("Click here to add a project")
        if requested_keys:
            try:
                for profile in requested_profiles:
                    self._register_project(profile)
                first = requested_keys[0]
                self.treeWidget_projectStructure.setCurrentItem(self.project_items[first])
            except (OSError, ValueError, KeyError) as exc:
                QMessageBox.critical(self, "Invalid configuration", str(exc))
        if not self.loaded_projects:
            self._show_empty_project()

    @staticmethod
    def _schema_item(name: str, key: str) -> QListWidgetItem:
        """Create a schema-list item carrying its normalized name."""
        item = QListWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, key)
        return item

    @staticmethod
    def _move_selected(source: QListWidget, target: QListWidget) -> None:
        """Move selected schemas between profile-builder lists."""
        for item in source.selectedItems():
            target.addItem(source.takeItem(source.row(item)))

    @staticmethod
    def _move_all(source: QListWidget, target: QListWidget) -> None:
        """Move every schema between profile-builder lists."""
        index = 0
        while index < source.count():
            item = source.item(index)
            if item.flags() & Qt.ItemFlag.ItemIsEnabled:
                target.addItem(source.takeItem(index))
            else:
                index += 1

    def _project_root(self, profile: GuiProjectProfile) -> Path:
        """Return the resolved namelist directory owned by a project profile."""
        return (profile.output_dir or self.project.output_root).resolve()

    def _available_root(self, profile: GuiProjectProfile) -> Path:
        """Choose a non-overlapping default root for a newly added project."""
        root = self._project_root(profile)
        if any(
            self._roots_overlap(root, self._project_root(item))
            for item in self.loaded_projects.values()
        ):
            root = self.project.output_root.with_name(
                f"{self.project.output_root.name}-{profile.key}"
            ).resolve()
        return root

    @staticmethod
    def _roots_overlap(left: Path, right: Path) -> bool:
        """Return whether two roots could address the same namelist file."""
        return left == right or left in right.parents or right in left.parents

    def _validate_project_root(self, key: str, root: Path) -> None:
        """Reject output roots shared or nested across loaded projects."""
        for other_key, other in self.loaded_projects.items():
            if other_key != key and self._roots_overlap(root, self._project_root(other)):
                raise ValueError(
                    f"projects '{other.name}' and '{key}' must use separate output directories"
                )

    def _available_project_key(self, configured_key: str) -> str:
        """Return a session-only key for another instance of one project profile."""
        candidate = configured_key
        suffix = 2
        while candidate in self.loaded_projects:
            candidate = f"{configured_key}_{suffix}"
            suffix += 1
        return candidate

    def _project_sources(
        self,
    ) -> tuple[list[tuple[str, tuple[str, str]]], list[tuple[str, tuple[str, str]]]]:
        """Return configured and user-created project choices."""
        configured = [
            (f"{profile.title} [{profile.name}] (configured)", ("configured", profile.key))
            for profile in self.available_projects.values()
        ]
        roots = [self._project_root(item) for item in self.loaded_projects.values()]
        custom = [
            (f"{path.name} — {path.parent}", ("path", str(path)))
            for path in discover_project_files(self.project, roots)
        ]
        return configured, custom

    def _choose_project_source(self) -> _ProjectSelection | None:
        """Choose, validate, and confirm one project's input and output files."""
        configured, custom = self._project_sources()
        dialog = ProjectPickerDialog(self.project, self)
        combo = dialog.source_combo
        for label, data in configured:
            combo.addItem(label, data)
        if configured:
            combo.insertSeparator(combo.count())
        for label, data in custom:
            combo.addItem(label, data)
        combo.addItem("Browse Custom Project from .toml", ("browse", ""))
        combo.insertSeparator(combo.count())
        combo.addItem("<custom>", ("custom", ""))
        selected: list[GuiProjectProfile | None] = [None]
        selected_kind = [""]
        previous = [-1]

        def select_source(index: int) -> None:
            data = combo.itemData(index)
            if not data:
                return
            kind, value = data
            try:
                if kind == "browse":
                    value, _ = QFileDialog.getOpenFileName(
                        self,
                        "Load project profile",
                        str(self.project.root),
                        "TOML files (*.toml)",
                    )
                    if not value:
                        with QSignalBlocker(combo):
                            combo.setCurrentIndex(previous[0])
                        return
                    profile = load_project_profile_file(self.project, Path(value))
                elif kind == "configured":
                    profile = self.available_projects[value]
                elif kind == "path":
                    profile = load_project_profile_file(self.project, Path(value))
                else:
                    profile = GuiProjectProfile(
                        "custom", "custom", "Custom", None, (), custom=True
                    )
                selected[0] = profile
                selected_kind[0] = kind
                previous[0] = index
                dialog.set_profile(profile, self._available_root(profile))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                QMessageBox.critical(self, "Load project", str(exc))
                with QSignalBlocker(combo):
                    combo.setCurrentIndex(previous[0])

        combo.currentIndexChanged.connect(select_source)
        if combo.count():
            select_source(combo.currentIndex())
        while _exec(dialog):
            try:
                profile = selected[0]
                if profile is None:
                    raise ValueError("select a project type")
                if selected_kind[0] == "custom":
                    identity = self._custom_project_identity(
                        "New project", "", None, dialog.output_root()
                    )
                    if identity is None:
                        continue
                    name, filename = identity
                    profile = replace(
                        profile,
                        name=name,
                        key=name.lower(),
                        title=name,
                        toml_file=filename,
                    )
                profile = replace(profile, output_dir=dialog.output_root())
                choice = self._prepare_project_selection(profile, dialog.paths())
                if self._confirm_project_selection(choice):
                    return choice
            except (OSError, ValueError, KeyError, TypeError) as exc:
                QMessageBox.critical(self, "Load project", str(exc))
        return None

    def _prepare_project_selection(
        self, profile: GuiProjectProfile, paths: Mapping[str, Path]
    ) -> _ProjectSelection:
        """Resolve destinations and validate every existing namelist source."""
        profile = replace(profile, key=self._available_project_key(profile.key))
        root = self._project_root(profile)
        self._validate_project_root(profile.key, root)
        files = []
        destinations: set[Path] = set()
        profiles = []
        for item in profile.profiles:
            source = paths[item.key].resolve()
            if source.exists() and not source.is_file():
                raise ValueError(f"namelist path '{source}' is not a file")
            try:
                relative = source.relative_to(root)
                target = source
            except ValueError:
                if not source.exists():
                    raise ValueError(
                        f"new namelist '{source}' must be inside output directory '{root}'"
                    ) from None
                target = (root / source.name).resolve()
                relative = target.relative_to(root)
                if target.exists():
                    raise ValueError(
                        f"destination namelist '{target}' already exists"
                    ) from None
            if target in destinations:
                raise ValueError(f"more than one file profile writes to '{target}'")
            destinations.add(target)
            updated = replace(item, default_file=relative.as_posix())
            profiles.append(updated)
            files.append(_ProjectFile(updated, source, target))
        updated_project = replace(profile, profiles=tuple(profiles), output_dir=root)
        existing = [item.source for item in files if item.source.exists()]
        dimensions = recover_dimensions(
            self.project,
            existing,
            self.project_initial_dimensions.get(profile.key, {}),
            output_root=root,
            profiles=updated_project.profiles,
        )
        for item in files:
            if not item.source.exists():
                continue
            parsed = profile_from_namelist(self.project, item.source)
            actual = {page.key for page in parsed.pages}
            allowed = {page.key for page in item.profile.pages}
            extra = actual - allowed
            missing = set(item.profile.required) - actual
            if extra:
                raise ValueError(
                    f"'{item.source.name}' contains namelists outside profile "
                    f"'{item.profile.name}': " + ", ".join(sorted(extra))
                )
            if missing:
                raise ValueError(
                    f"'{item.source.name}' is missing required namelists from profile "
                    f"'{item.profile.name}': " + ", ".join(sorted(missing))
                )
            load_profile(self.project, item.profile, dimensions, path=item.source)
        return _ProjectSelection(updated_project, tuple(files))

    def _confirm_project_selection(self, choice: _ProjectSelection) -> bool:
        """Summarize file handling before creating or copying anything."""
        lines = [f"Project output directory:\n{self._project_root(choice.profile)}", ""]
        for item in choice.files:
            if not item.source.exists():
                status = (
                    f"File absent; create on save from schema defaults and user input:\n"
                    f"  {item.target}"
                )
            elif item.source == item.target:
                status = (
                    "Load existing values, overriding schema defaults, and edit in place:\n"
                    f"  {item.target}"
                )
            else:
                status = (
                    "Copy existing file and load its values, overriding schema defaults:\n"
                    f"  From: {item.source}\n  To:   {item.target}"
                )
            lines.extend((f"{item.profile.name}:", status, ""))
        if not choice.files:
            lines.append("No file profiles are currently included.")
        return (
            QMessageBox.question(
                self,
                "Add project",
                "\n".join(lines).rstrip(),
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            == QMessageBox.Yes
        )

    @staticmethod
    def _copy_project_sources(choice: _ProjectSelection) -> list[Path]:
        """Copy confirmed external sources and clean up if any copy fails."""
        copied = []
        try:
            for item in choice.files:
                if not item.source.exists() or item.source == item.target:
                    continue
                item.target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    copy2(item.source, item.target)
                except Exception:
                    item.target.unlink(missing_ok=True)
                    raise
                copied.append(item.target)
        except Exception:
            for path in copied:
                path.unlink(missing_ok=True)
            raise
        return copied

    def _browse_schemas(self) -> None:
        """Select nml-config.toml without loading it yet."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load schemas configuration",
            self.schemas_path.text(),
            "nml-tools config (nml-config.toml pyproject.toml);;TOML files (*.toml)",
        )
        if path:
            self.schemas_path.setText(str(Path(path).resolve()))

    def _scan_schemas(self) -> None:
        """Replace the schema catalog after validating the selected config file."""
        try:
            config_path = Path(self.schemas_path.text()).expanduser().resolve()
            if (
                config_path.name not in {"nml-config.toml", "pyproject.toml"}
                or not config_path.is_file()
            ):
                raise ValueError("select an existing nml-config.toml or pyproject.toml file")
            replacement = load_project(config_path, self.project.output_root)
            if self._has_dirty() and QMessageBox.question(
                self,
                "Unsaved changes",
                "Changing the schema directory will discard unsaved changes. Continue?",
            ) != QMessageBox.Yes:
                return
            self._clear_projects()
            self.project = replacement
            self.available_projects = {
                profile.key: profile for profile in replacement.project_profiles
            }
            self.schemas_path.setText(str(replacement.config_path))
        except (OSError, RuntimeError, ValueError) as exc:
            QMessageBox.critical(self, "Invalid schema directory", str(exc))

    def _has_dirty(self) -> bool:
        """Return whether any loaded project contains unsaved editor changes."""
        return any(
            editor.is_dirty()
            for editors in self.project_editors.values()
            for editor in editors.values()
        )

    def _add_selected_project(self) -> None:
        """Ask for and load a configured, external, or new project."""
        try:
            selected = self._choose_project_source()
            if selected is None:
                return
            copied = self._copy_project_sources(selected)
            created_profile: Path | None = None
            try:
                if selected.profile.custom and selected.profile.source is None:
                    root = self._project_root(selected.profile)
                    created_profile = save_project_profile(
                        self.project, selected.profile, root
                    )
                    selected = replace(
                        selected,
                        profile=replace(selected.profile, source=created_profile),
                    )
                self._register_project(selected.profile)
            except Exception:
                for path in copied:
                    path.unlink(missing_ok=True)
                if created_profile is not None:
                    created_profile.unlink(missing_ok=True)
                raise
            self.treeWidget_projectStructure.setCurrentItem(
                self.project_items[selected.profile.key]
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            QMessageBox.critical(self, "Load project", str(exc))

    def _custom_project_identity(
        self,
        title: str,
        suggested: str = "",
        current_key: str | None = None,
        output_root: Path | None = None,
    ) -> tuple[str, str] | None:
        """Ask for a unique custom project name and TOML filename."""
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QFormLayout(dialog)
        name_edit = QLineEdit(suggested, dialog)
        name_edit.setObjectName("projectNameEdit")
        filename_edit = QLineEdit(f"{suggested}.toml" if suggested else "", dialog)
        filename_edit.setObjectName("projectFilenameEdit")
        automatic = [filename_edit.text()]

        def update_filename(name: str) -> None:
            if filename_edit.text() == automatic[0]:
                automatic[0] = f"{name}.toml" if name else ""
                filename_edit.setText(automatic[0])

        name_edit.textChanged.connect(update_filename)
        layout.addRow("Project name", name_edit)
        layout.addRow("Project profile TOML filename", filename_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if not _exec(dialog):
            return None
        name = validate_project_name(name_edit.text())
        if name.lower() in self.loaded_projects and name.lower() != current_key:
            raise ValueError(f"project '{name}' is already loaded")
        filename = validate_project_filename(filename_edit.text())
        if ((output_root or self.project.output_root) / filename).exists():
            raise ValueError(f"TOML file '{filename}' already exists")
        return name, filename

    def _register_project(self, profile: GuiProjectProfile) -> None:
        """Validate and add one project profile without duplicating it."""
        if profile.key in self.loaded_projects:
            return
        if profile.output_dir is None:
            profile = replace(profile, output_dir=self._available_root(profile))
        root = self._project_root(profile)
        self._validate_project_root(profile.key, root)
        profile = replace(profile, output_dir=root)
        profiles = ensure_dimension_sources(self.project, profile.profiles)
        profile = replace(profile, profiles=profiles)
        paths = [_profile_path(self.project, item, root) for item in profiles]
        if len(paths) != len(set(paths)):
            raise ValueError(f"project '{profile.name}' writes more than one profile to one file")
        dimensions = recover_dimensions(
            self.project,
            paths,
            self.project_initial_dimensions.get(profile.key, {}),
            output_root=root,
            profiles=profiles,
        )
        initial_values = self.project_initial_values.get(profile.key, {})
        source_values = dimension_source_values(self.project, profiles, dimensions)
        prepared: dict[Path, NamelistPage] = {}
        try:
            for item, path in zip(profiles, paths):
                values = load_profile(self.project, item, dimensions, output_root=root)
                supplied = initial_values.get(item.key, {})
                if supplied:
                    values = overlay_values(
                        values,
                        _normalize_profile_values(
                            supplied,
                            item,
                            {**self.project.constants, **dimensions},
                        ),
                    )
                values = overlay_values(values, source_values.get(item.key, {}))
                prepared[path] = NamelistPage(
                    self.project,
                    item,
                    values,
                    dimensions,
                    self,
                    output_root=root,
                    source_values=source_values.get(item.key),
                )
                prepared[path].hide()
        except Exception:
            for editor in prepared.values():
                editor.deleteLater()
            raise
        self.loaded_projects[profile.key] = profile
        self.project_dimensions[profile.key] = dimensions
        self.project_saved_dimensions[profile.key] = dict(dimensions)
        self.project_editors[profile.key] = prepared
        for editor in prepared.values():
            self._wire_editor(profile.key, editor)
        self._new_config(profile.key)
        self._build_tree(profile)
        self.project_initial_values.pop(profile.key, None)

    def _new_config(self, project_key: str) -> ProjectPage:
        """Create the single reusable Config tab for one loaded project."""
        old = self.project_configs.get(project_key)
        if old is not None:
            self._detach_tab(old)
            old.deleteLater()
        profiles = self.loaded_projects[project_key].profiles
        linked = {
            name
            for name, source in self.project.dimension_sources.items()
            if sum(
                any(page.key == source.namelist for page in profile.pages)
                for profile in profiles
            )
            == 1
        }
        config = ProjectPage(
            self.project,
            self.project_dimensions[project_key],
            self,
            linked,
        )
        config.hide()
        config.set_project_profile(self.loaded_projects[project_key])
        config.set_profiles(
            profiles,
            self._project_root(self.loaded_projects[project_key]),
        )
        config.set.clicked.connect(lambda: self._set_configuration(project_key, config))
        config.save_custom.clicked.connect(
            lambda: self._save_custom_project(project_key, config)
        )
        config.back.clicked.connect(
            lambda: self._navigate_scope("project", project_key, "", -1)
        )
        config.next.clicked.connect(
            lambda: self._navigate_scope("project", project_key, "", 1)
        )
        config.restore.clicked.connect(lambda: self._restore_project(project_key))
        config.cancel.clicked.connect(lambda: self._discard_project(project_key))
        config.save.clicked.connect(lambda: self._save_project(project_key))
        for dimension, button in config.dimension_source_buttons.items():
            button.clicked.connect(
                lambda _checked=False, key=project_key, name=dimension: (
                    self._open_dimension_source(key, name)
                )
            )
        self.project_configs[project_key] = config
        return config

    def _open_dimension_source(self, project_key: str, dimension: str) -> None:
        """Open and reveal one configured dimension-source property."""
        source = self.project.dimension_sources[dimension]
        profile = next(
            item
            for item in self.loaded_projects[project_key].profiles
            if any(page.key == source.namelist for page in item.pages)
        )
        file_item = self._profile_tree_item(project_key, profile.key)
        if file_item is None:
            return
        for index in range(file_item.childCount()):
            item = file_item.child(index)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data[0] == "namelist" and data[3] == source.namelist:
                file_item.setExpanded(True)
                self.treeWidget_projectStructure.setCurrentItem(item)
                self._ensure_editor(project_key, profile).reveal_property(
                    source.namelist, source.property
                )
                tree = self.treeWidget_projectStructure

                def highlight(
                    selected_tree: QTreeWidget = tree,
                    selected_item: QTreeWidgetItem = item,
                ) -> None:
                    selected_tree.clearSelection()
                    selected_item.setSelected(True)
                    selected_tree.scrollToItem(selected_item)
                    selected_tree.setFocus()

                QTimer.singleShot(0, highlight)
                return

    def _build_tree(self, profile: GuiProjectProfile) -> None:
        """Build one project/file/namelist branch with removal controls."""
        root = QTreeWidgetItem([f"Project: {profile.name}", ""])
        root.setData(0, Qt.ItemDataRole.UserRole, ("project", profile.key, "", ""))
        root.setToolTip(0, f"Output directory: {self._project_root(profile)}")
        index = self.treeWidget_projectStructure.indexOfTopLevelItem(self.project_add_item)
        self.treeWidget_projectStructure.insertTopLevelItem(max(index, 0), root)
        self._remove_button(root)
        standard_files = {item.key: item for item in self.project.profiles}
        for file_profile in profile.profiles:
            standard = standard_files.get(file_profile.key)
            editable = profile.custom and standard is None
            file_item = QTreeWidgetItem([f"File: {file_profile.default_file}", ""])
            file_item.setData(
                0, Qt.ItemDataRole.UserRole, ("profile", profile.key, file_profile.key, "")
            )
            root.addChild(file_item)
            if editable:
                self._remove_button(file_item)
            for page in file_profile.pages:
                child = QTreeWidgetItem([f"Namelist: &{page.name}", ""])
                child.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    ("namelist", profile.key, file_profile.key, page.key),
                )
                file_item.addChild(child)
                if standard is None or page.key not in standard.required:
                    self._remove_button(child)
            self._action_item(
                file_item,
                "Namelist",
                ("add_namelist", profile.key, file_profile.key, ""),
                lambda _checked=False, p=profile.key, f=file_profile.key: (
                    self._show_namelist_picker(p, f)
                ),
            )
        if profile.custom:
            self._action_item(
                root,
                "File",
                ("add_profile", profile.key, "", ""),
                lambda _checked=False, key=profile.key: self._show_file_builder(key),
            )
        root.setExpanded(True)
        self.project_items[profile.key] = root

    def _action_item(
        self,
        parent: QTreeWidgetItem | None,
        label: str,
        data: tuple[str, str, str, str],
        callback: Any,
    ) -> QTreeWidgetItem:
        """Add one non-navigating tree action button."""
        item = QTreeWidgetItem(["", ""])
        item.setData(0, Qt.ItemDataRole.UserRole, data)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        if parent is None:
            self.treeWidget_projectStructure.addTopLevelItem(item)
        else:
            parent.addChild(item)
        button = QPushButton(self.treeWidget_projectStructure)
        button.setText(f"+ : {label}")
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        button.setStyleSheet("text-align: left; padding-left: 4px")
        button.clicked.connect(callback)
        self.treeWidget_projectStructure.setItemWidget(item, 0, button)
        return item

    def _remove_button(self, item: QTreeWidgetItem) -> None:
        """Install the tree action used to remove this item from the session."""
        button = QToolButton(self.treeWidget_projectStructure)
        button.setText("×")
        button.setAutoRaise(True)
        button.clicked.connect(lambda: self._remove_tree_item(item))
        self.treeWidget_projectStructure.setItemWidget(item, 1, button)

    def _detach_tab(self, widget: QWidget) -> None:
        """Hide and remove a cached page from Qt's internal tab stack."""
        index = self.tabs.indexOf(widget)
        if index >= 0:
            self.tabs.removeTab(index)
        widget.hide()
        widget.setParent(self)

    def _show_view(self, widget: QWidget, title: str) -> None:
        """Show one unclosable page for the selected tree item."""
        with QSignalBlocker(self.tabs):
            while self.tabs.count():
                self._detach_tab(self.tabs.widget(0))
            self.tabs.addTab(widget, title)
            self.tabs.setCurrentWidget(widget)
        widget.show()

    def _show_empty_project(self) -> None:
        """Show the primary project action when no project is loaded."""
        self._clear_overview()
        view = QWidget(self)
        layout = QVBoxLayout(view)
        layout.addStretch()
        label = QLabel("Click here to add a project", view)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        button = QPushButton("+ : Project", view)
        button.clicked.connect(self._add_selected_project)
        layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()
        self.empty_view = view
        self._show_view(view, "Projects")

    def _clear_overview(self) -> None:
        """Dispose transient overview and add-form pages."""
        empty_view, self.empty_view = self.empty_view, None
        if empty_view is not None:
            self._detach_tab(empty_view)
            empty_view.deleteLater()
        overview, self.current_overview = self.current_overview, None
        if overview is not None:
            self._detach_tab(overview)
            overview.deleteLater()
        tool, self.current_tool = self.current_tool, None
        if tool is not None:
            self._detach_tab(tool)
            tool.deleteLater()

    def _show_project(self, key: str) -> None:
        """Activate one project's cached editor state."""
        if key not in self.loaded_projects:
            return
        self.active_project = key
        self.editors = self.project_editors[key]
        self.config_tab = self.project_configs[key]

    def _scope_items(
        self, kind: str, project_key: str, profile_key: str = ""
    ) -> list[QTreeWidgetItem]:
        """Return navigable siblings for one project-tree scope."""
        if kind == "project":
            return [
                self.treeWidget_projectStructure.topLevelItem(index)
                for index in range(self.treeWidget_projectStructure.topLevelItemCount())
                if (
                    self.treeWidget_projectStructure.topLevelItem(index).data(
                        0, Qt.ItemDataRole.UserRole
                    )
                    or ("",)
                )[0]
                == "project"
            ]
        parent = self.project_items[project_key]
        if kind == "namelist":
            parent = next(
                parent.child(index)
                for index in range(parent.childCount())
                if (parent.child(index).data(0, Qt.ItemDataRole.UserRole) or ("", "", ""))[2]
                == profile_key
            )
        return [
            parent.child(index)
            for index in range(parent.childCount())
            if (parent.child(index).data(0, Qt.ItemDataRole.UserRole) or ("",))[0]
            == kind
        ]

    def _navigate_scope(
        self, kind: str, project_key: str, profile_key: str, step: int
    ) -> None:
        """Move to the adjacent tree item at the requested scope."""
        items = self._scope_items(kind, project_key, profile_key)
        current = (
            self.project_items[project_key]
            if kind == "project"
            else self._profile_tree_item(project_key, profile_key)
        )
        if current in items:
            index = items.index(current) + step
            if 0 <= index < len(items):
                self.treeWidget_projectStructure.setCurrentItem(items[index])

    def _update_scope_navigation(
        self, widget: Any, kind: str, project_key: str, profile_key: str = ""
    ) -> None:
        """Enable scoped Back/Next buttons at valid tree boundaries."""
        items = self._scope_items(kind, project_key, profile_key)
        current = (
            self.project_items[project_key]
            if kind == "project"
            else self._profile_tree_item(project_key, profile_key)
        )
        index = items.index(current) if current in items else -1
        widget.back.setEnabled(index > 0)
        widget.next.setEnabled(0 <= index < len(items) - 1)

    def _tree_selected(self, current: QTreeWidgetItem | None, _previous: Any) -> None:
        """Navigate from a tree identity to its project, file, or namelist page."""
        if current is None:
            return
        data = current.data(0, Qt.ItemDataRole.UserRole)
        if not data or str(data[0]).startswith("add_"):
            return
        kind, project_key, profile_key, page_key = data
        self._show_project(project_key)
        self._clear_overview()
        if kind == "project":
            config = self.project_configs[project_key]
            self._update_scope_navigation(config, "project", project_key)
            self._show_view(config, "⚙️")
            return
        profile = next(
            item for item in self.loaded_projects[project_key].profiles if item.key == profile_key
        )
        editor = self._ensure_editor(project_key, profile)
        if kind == "profile":
            current.setExpanded(True)
            self.current_overview = FilePage(self.project, profile, editor, self)
            overview = self.current_overview
            overview.back.clicked.connect(
                lambda: self._navigate_scope("profile", project_key, profile_key, -1)
            )
            overview.next.clicked.connect(
                lambda: self._navigate_scope("profile", project_key, profile_key, 1)
            )
            overview.restore.clicked.connect(lambda: self._restore_file(editor))
            overview.cancel.clicked.connect(
                lambda: self._cancel_profile(project_key, editor)
            )
            overview.save.clicked.connect(lambda: self._save([editor]))
            self._update_scope_navigation(overview, "profile", project_key, profile_key)
            self._show_view(self.current_overview, profile.title)
            return
        editor.select_page(page_key)
        page = next(item for item in profile.pages if item.key == page_key)
        self._show_view(editor, f"{profile.name} / &&{page.name}")

    def _editor_page_selected(self, project_key: str, editor: NamelistPage, index: int) -> None:
        """Highlight the tree namelist selected inside an editor."""
        if (
            index < 0
            or project_key != self.active_project
            or self.tabs.currentWidget() is not editor
        ):
            return
        page = editor.profile.pages[index]
        page_key = page.key
        self.tabs.setTabText(0, f"{editor.profile.name} / &&{page.name}")
        root = self.project_items[project_key]
        for profile_index in range(root.childCount()):
            profile_item = root.child(profile_index)
            if profile_item.data(0, Qt.ItemDataRole.UserRole)[2] != editor.profile.key:
                continue
            for page_index in range(profile_item.childCount()):
                page_item = profile_item.child(page_index)
                if page_item.data(0, Qt.ItemDataRole.UserRole)[3] == page_key:
                    with QSignalBlocker(self.treeWidget_projectStructure):
                        self.treeWidget_projectStructure.setCurrentItem(page_item)
                    return

    def _refresh_current_view(self) -> None:
        """Rebuild the single view from the current tree selection."""
        current = self.treeWidget_projectStructure.currentItem()
        if current is not None:
            self._tree_selected(current, current)

    def _show_file_builder(self, project_key: str) -> None:
        """Show the transient file-profile builder for one project."""
        self._show_project(project_key)
        self._clear_overview()
        current = self.loaded_projects[project_key]
        builder = FileProfileBuilder(
            self.project, current.profiles, self._project_root(current), self
        )
        builder.source_combo.currentIndexChanged.connect(
            lambda: self._select_profile_source(builder)
        )
        builder.add.clicked.connect(lambda: self._add_file_profile(project_key, builder))
        self.current_tool = builder
        self._select_profile_source(builder)
        self._show_view(builder, "Add file profile")

    def _show_namelist_picker(self, project_key: str, profile_key: str) -> None:
        """Show schemas that are not already present in one file profile."""
        self._show_project(project_key)
        self._clear_overview()
        profile = next(
            item for item in self.loaded_projects[project_key].profiles if item.key == profile_key
        )
        picker = NamelistPicker(self.project, profile, self)
        picker.add.clicked.connect(
            lambda: self._add_namelists(project_key, profile_key, picker.schema_keys())
        )
        self.current_tool = picker
        self._show_view(picker, f"Add namelist to {profile.name}")

    def _choose_namelist_profile(
        self, builder: FileProfileBuilder
    ) -> tuple[str, str] | None:
        """Choose the file-profile contract followed by a saved namelist."""
        standard = list(self.project.profiles)
        standard_keys = {profile.key for profile in standard}
        custom = [
            profile
            for profile in builder.source_profiles.values()
            if profile.key not in standard_keys
        ]
        dialog = QInputDialog(self)
        dialog.setWindowTitle("Namelist file profile")
        dialog.setLabelText("Which file profile does this namelist follow?")
        dialog.setComboBoxEditable(False)
        dialog.setComboBoxItems([""])
        combo = dialog.findChild(QComboBox)
        if combo is None:
            return None
        combo.clear()
        for profile in standard:
            combo.addItem(profile.title, ("profile", profile.key))
        if standard and custom:
            combo.insertSeparator(combo.count())
        for profile in custom:
            combo.addItem(profile.title, ("profile", profile.key))
        if combo.count():
            combo.insertSeparator(combo.count())
        combo.addItem("<custom>", ("custom", ""))
        return combo.currentData() if _exec(dialog) else None

    def _associate_namelist(
        self, builder: FileProfileBuilder, path: Path
    ) -> tuple[GuiProfile, tuple[str, str]] | None:
        """Validate a saved namelist against its selected file profile."""
        parsed = profile_from_namelist(self.project, path)
        selected = self._choose_namelist_profile(builder)
        if selected is None:
            return None
        kind, key = selected
        if kind == "custom":
            return parsed, selected
        profile = builder.source_profiles[key]
        actual = {page.key for page in parsed.pages}
        allowed = {page.key for page in profile.pages}
        extra = actual - allowed
        missing = set(profile.required) - actual
        if extra:
            raise ValueError(
                f"'{path.name}' contains namelists outside profile '{profile.name}': "
                + ", ".join(sorted(extra))
            )
        if missing:
            raise ValueError(
                f"'{path.name}' is missing required namelists from profile "
                f"'{profile.name}': " + ", ".join(sorted(missing))
            )
        return replace(profile, default_file=path.name), selected

    @staticmethod
    def _set_profile_source(
        builder: FileProfileBuilder, selected: tuple[str, str]
    ) -> None:
        """Select a source-combo entry without re-running its handler."""
        with QSignalBlocker(builder.source_combo):
            for index in range(builder.source_combo.count()):
                if builder.source_combo.itemData(index) == selected:
                    builder.source_combo.setCurrentIndex(index)
                    return

    def _browse_namelist(self, builder: FileProfileBuilder) -> bool:
        """Browse and associate one namelist with a configured profile type."""
        name, _ = QFileDialog.getOpenFileName(
            self,
            "Load namelist",
            str(builder.output_root),
            "Fortran namelist files (*.nml)",
        )
        if not name:
            return False
        path = Path(name).resolve()
        associated = self._associate_namelist(builder, path)
        if associated is None:
            return False
        profile, selected = associated
        self._set_profile_source(builder, selected)
        builder.set_profile(profile, configured=selected[0] != "custom")
        if selected[0] == "custom":
            builder.source_profile = None
        builder.source_path = path
        builder.active_source = selected
        return True

    def _select_profile_source(self, builder: FileProfileBuilder) -> None:
        """Populate builder values from a reusable file profile."""
        data = builder.source_combo.currentData()
        if not data:
            return
        kind, value = data
        previous = builder.active_source
        try:
            if kind == "browse":
                if not self._browse_namelist(builder):
                    if previous is not None:
                        self._set_profile_source(builder, previous)
                return
            if kind == "custom":
                builder.clear_builder()
            else:
                builder.source_path = None
                builder.set_profile(builder.source_profiles[value])
            builder.active_source = data
        except (OSError, ValueError, KeyError) as exc:
            if previous is not None:
                self._set_profile_source(builder, previous)
            QMessageBox.critical(self, "Invalid namelist", str(exc))

    def _set_configuration(self, project_key: str, config: ProjectPage) -> bool:
        """Apply one project's runtime dimensions."""
        try:
            dimensions = _normalize_dimensions(config.dimensions(), self.project)
            current = self.loaded_projects[project_key]
            if dimensions == self.project_dimensions[project_key]:
                config.set_profiles(current.profiles, self._project_root(current))
                return True
            self._rebuild_project_editors(
                current.key, fit_arrays=True, dimensions=dimensions
            )
            config.set_profiles(current.profiles, self._project_root(current))
            return True
        except InputValidationError as exc:
            if exc.editor is not None:
                path = _profile_path(
                    self.project, exc.editor.profile, exc.editor.output_root
                )
                self._show_validation_error(exc.editor, path, exc)
            else:
                QMessageBox.critical(self, "Invalid configuration", str(exc))
            return False
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.critical(self, "Invalid configuration", str(exc))
            return False

    def _add_file_profile(self, project_key: str, builder: FileProfileBuilder) -> None:
        """Validate and persist one added or updated file profile."""
        try:
            current = self.loaded_projects[project_key]
            output_root = self._project_root(current)
            profile = create_virtual_project(
                self.project,
                builder.profile_name.text(),
                builder.default_filename.text(),
                builder.schema_keys(),
                output_root,
            ).profiles[0]
            source = builder.source_profile
            if source is not None:
                selected = {page.key for page in profile.pages}
                profile = replace(
                    profile,
                    title=source.title if profile.name == source.name else profile.name,
                    description=source.description,
                    required=tuple(name for name in source.required if name in selected),
                )
            profile = replace(profile, description=builder.description.text().strip() or None)
            imported: Mapping[str, Any] | None = None
            if builder.source_path is not None:
                imported = load_profile(
                    self.project,
                    profile,
                    self.project_dimensions[current.key],
                    path=builder.source_path,
                    output_root=output_root,
                )
            replace_index = next(
                (
                    index
                    for index, item in enumerate(current.profiles)
                    if source is not None and item.key == source.key
                ),
                None,
            )
            for index, item in enumerate(current.profiles):
                if index != replace_index and item.key == profile.key:
                    raise ValueError(f"file profile '{profile.name}' already exists")
                if index != replace_index and _profile_path(
                    self.project, item, output_root
                ) == _profile_path(self.project, profile, output_root):
                    raise ValueError(f"output file '{profile.default_file}' is already used")
            if replace_index is None:
                profiles = (*current.profiles, profile)
            else:
                profiles_list = list(current.profiles)
                old = profiles_list[replace_index]
                profiles_list[replace_index] = profile
                profiles = tuple(profiles_list)
                if imported is None and old.default_file != profile.default_file:
                    old_path = _profile_path(self.project, old, output_root)
                    imported = self.project_editors[current.key][old_path].values()
            profiles = ensure_dimension_sources(self.project, profiles)
            customized = self._customize(current)
            if customized is None:
                return
            current = customized
            current = replace(current, profiles=profiles)
            saved_path = save_project_profile(
                self.project, current, self._project_root(current)
            )
            current = replace(current, source=saved_path)
            self._replace_project(project_key, current)
            if imported is not None:
                self.project_initial_values.setdefault(current.key, {})[profile.key] = {
                    page.name: imported.get(page.name, {}) for page in profile.pages
                }
            self._rebuild_project_editors(current.key)
            tree_item = self._profile_tree_item(current.key, profile.key)
            if tree_item is not None:
                self.treeWidget_projectStructure.setCurrentItem(tree_item)
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.critical(self, "Invalid file profile", str(exc))

    def _add_namelists(
        self, project_key: str, profile_key: str, selected: Sequence[str]
    ) -> None:
        """Persist selected schemas at the end of one file profile."""
        try:
            if not selected:
                raise ValueError("select at least one namelist")
            current = self.loaded_projects[project_key]
            profiles = list(current.profiles)
            index = next(i for i, item in enumerate(profiles) if item.key == profile_key)
            profile = profiles[index]
            selected_keys = set(selected)
            additions = tuple(page for page in self.project.namelists if page.key in selected_keys)
            if len(additions) != len(selected_keys):
                raise ValueError("selected namelist is unknown")
            standard = next(
                (item for item in self.project.profiles if item.key == profile_key), None
            )
            allowed = {page.key for page in standard.pages} if standard is not None else set()
            outside = [page.name for page in additions if page.key not in allowed]
            if standard is not None and outside and not current.custom:
                QMessageBox.information(
                    self,
                    "Custom project required",
                    f"Standard file profile '{standard.name}' does not contain: "
                    f"{', '.join(outside)}.\n\nA custom project will be created.",
                )
            if current.custom or standard is None or outside:
                customized = self._customize(current)
                if customized is None:
                    return
                current = customized
            profiles = list(current.profiles)
            profile = profiles[index]
            profiles[index] = replace(profile, pages=(*profile.pages, *additions))
            checked = ensure_dimension_sources(self.project, profiles)
            current = replace(current, profiles=checked)
            if current.custom:
                saved_path = save_project_profile(
                    self.project, current, self._project_root(current)
                )
                current = replace(current, source=saved_path)
            self._replace_project(project_key, current)
            self._rebuild_project_editors(current.key)
            file_item = self._profile_tree_item(current.key, profile_key)
            if file_item is not None:
                for row in range(file_item.childCount()):
                    item = file_item.child(row)
                    data = item.data(0, Qt.ItemDataRole.UserRole)
                    if data and data[0] == "namelist" and data[3] == additions[0].key:
                        self.treeWidget_projectStructure.setCurrentItem(item)
                        break
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.critical(self, "Add namelist", str(exc))

    def _save_custom_project(self, project_key: str, config: ProjectPage) -> None:
        """Save the current project structure as an output-owned TOML file."""
        try:
            current = self.loaded_projects[project_key]
            name = validate_project_name(config.custom_name.text())
            key = name.lower()
            if key != project_key and key in self.loaded_projects:
                raise ValueError(f"project '{name}' is already loaded")
            filename = validate_project_filename(config.custom_filename.text())
            root = self._project_root(current)
            target = (root / filename).resolve()
            source = (
                current.source
                if current.source is not None and current.source.resolve() == target
                else None
            )
            updated = replace(
                current,
                name=name,
                key=key,
                title=name,
                source=source,
                custom=True,
                toml_file=filename,
            )
            path = save_project_profile(self.project, updated, root)
            updated = replace(updated, source=path)
            self._replace_project(project_key, updated)
            self._rebuild_project_editors(updated.key)
            QMessageBox.information(
                self,
                "Project profile saved",
                f"Project profile saved to:\n{path}",
            )
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.critical(self, "Save project profile", str(exc))

    def _customize(self, profile: GuiProjectProfile) -> GuiProjectProfile | None:
        """Copy a configured project before a structural edit."""
        if profile.custom:
            return profile
        identity = self._custom_project_identity(
            "Custom project",
            f"{profile.name}-custom",
            profile.key,
            self._project_root(profile),
        )
        if identity is None:
            return None
        name, filename = identity
        return replace(
            profile,
            name=name,
            key=name.lower(),
            title=name,
            source=None,
            custom=True,
            toml_file=filename,
        )

    def _replace_project(self, old_key: str | None, profile: GuiProjectProfile) -> None:
        """Replace one explicit project model and preserve unrelated active state."""
        if old_key is None or old_key not in self.loaded_projects:
            return
        was_active = old_key == self.active_project
        item = self.project_items.pop(old_key)
        index = self.treeWidget_projectStructure.indexOfTopLevelItem(item)
        self.treeWidget_projectStructure.takeTopLevelItem(index)
        editors = self.project_editors.pop(old_key)
        config = self.project_configs.pop(old_key)
        self._detach_tab(config)
        config.deleteLater()
        dimensions = self.project_dimensions.pop(old_key)
        saved_dimensions = self.project_saved_dimensions.pop(old_key)
        initial_values = self.project_initial_values.pop(old_key, {})
        initial_dimensions = self.project_initial_dimensions.pop(old_key, {})
        self.loaded_projects.pop(old_key)
        self.loaded_projects[profile.key] = profile
        self.project_editors[profile.key] = editors
        self.project_dimensions[profile.key] = dimensions
        self.project_saved_dimensions[profile.key] = saved_dimensions
        self.project_initial_values[profile.key] = initial_values
        self.project_initial_dimensions[profile.key] = initial_dimensions
        if was_active:
            self.active_project = None
        self._new_config(profile.key)
        self._build_tree(profile)
        if was_active:
            self.treeWidget_projectStructure.setCurrentItem(self.project_items[profile.key])

    def _wire_editor(self, project_key: str, editor: NamelistPage) -> None:
        """Connect one cached editor to project-level actions and navigation."""
        editor.save.clicked.connect(
            lambda _checked=False: self._save_namelist(editor)
        )
        editor.cancel.clicked.connect(
            lambda _checked=False: editor.discard_page()
        )
        editor.stack.currentChanged.connect(
            lambda index: self._editor_page_selected(project_key, editor, index)
        )

    def _profile_tree_item(
        self, project_key: str, profile_key: str
    ) -> QTreeWidgetItem | None:
        """Find one file-profile node in the project tree."""
        root = self.project_items.get(project_key)
        if root is not None:
            for index in range(root.childCount()):
                item = root.child(index)
                if item.data(0, Qt.ItemDataRole.UserRole)[2] == profile_key:
                    return item
        return None

    def _ensure_editor(self, project_key: str, profile: GuiProfile) -> NamelistPage:
        """Return a cached editor, loading its direct namelist file once."""
        root = self._project_root(self.loaded_projects[project_key])
        path = _profile_path(self.project, profile, root)
        editors = self.project_editors[project_key]
        if path in editors:
            return editors[path]
        dimensions = self.project_dimensions[project_key]
        values = load_profile(self.project, profile, dimensions, output_root=root)
        supplied = self.project_initial_values.get(project_key, {}).get(profile.key, {})
        if supplied:
            values = overlay_values(
                values,
                _normalize_profile_values(
                    supplied, profile, {**self.project.constants, **dimensions}
                ),
            )
        sources = dimension_source_values(
            self.project, self.loaded_projects[project_key].profiles, dimensions
        )
        values = overlay_values(values, sources.get(profile.key, {}))
        editor = NamelistPage(
            self.project,
            profile,
            values,
            dimensions,
            self,
            output_root=root,
            source_values=sources.get(profile.key),
        )
        editor.hide()
        self._wire_editor(project_key, editor)
        editors[path] = editor
        return editor

    def _rebuild_project_editors(
        self,
        key: str,
        *,
        fit_arrays: bool = False,
        dimensions: Mapping[str, int] | None = None,
    ) -> None:
        """Rebuild a project's editors after dimensions or membership change."""
        root = self._project_root(self.loaded_projects[key])
        old = self.project_editors[key]
        old_values = {}
        for path, editor in old.items():
            try:
                old_values[path] = editor.values()
            except InputValidationError as exc:
                exc.editor = editor
                raise
        new_dimensions = dict(
            self.project_dimensions[key] if dimensions is None else dimensions
        )
        sources = dimension_source_values(
            self.project,
            self.loaded_projects[key].profiles,
            new_dimensions,
        )
        prepared: dict[Path, NamelistPage] = {}
        try:
            for profile in self.loaded_projects[key].profiles:
                path = _profile_path(self.project, profile, root)
                previous = old.get(path)
                values = (
                    old_values[path]
                    if previous is not None
                    else load_profile(
                        self.project,
                        profile,
                        new_dimensions,
                        output_root=root,
                    )
                )
                supplied = self.project_initial_values.get(key, {}).get(profile.key, {})
                if supplied:
                    values = overlay_values(
                        values,
                        _normalize_profile_values(
                            supplied,
                            profile,
                            {**self.project.constants, **new_dimensions},
                        ),
                    )
                values = overlay_values(values, sources.get(profile.key, {}))
                editor = NamelistPage(
                    self.project,
                    profile,
                    values,
                    new_dimensions,
                    self,
                    fit_arrays=fit_arrays,
                    output_root=root,
                    source_values=sources.get(profile.key),
                )
                editor.hide()
                prepared[path] = editor
                self._wire_editor(key, editor)
                if previous is not None:
                    editor.saved_values = copy.deepcopy(previous.saved_values)
                    editor.saved_dimensions = dict(previous.saved_dimensions)
                    for index, page in enumerate(profile.pages):
                        if page.name in previous.forms:
                            editor._ensure_form(index)
                    editor.form_saved.update(
                        {
                            name: copy.deepcopy(values)
                            for name, values in previous.form_saved.items()
                            if name in editor.forms
                        }
                    )
        except Exception:
            for editor in prepared.values():
                editor.deleteLater()
            raise
        self.project_dimensions[key] = new_dimensions
        self.project_editors[key] = prepared
        for editor in old.values():
            self._detach_tab(editor)
            editor.deleteLater()
        if key == self.active_project:
            self._refresh_current_view()
        self.project_initial_values.pop(key, None)

    def _restore_file(self, editor: NamelistPage) -> None:
        """Restore schema defaults throughout one file profile."""
        editor.restore_all()
        self._refresh_current_view()

    def _cancel_profile(
        self, project_key: str, editor: NamelistPage, *, refresh: bool = True
    ) -> None:
        """Replace one editor with its last successfully saved state."""
        root = self._project_root(self.loaded_projects[project_key])
        path = _profile_path(self.project, editor.profile, root)
        dimensions = self.project_dimensions[project_key]
        sources = dimension_source_values(
            self.project, self.loaded_projects[project_key].profiles, dimensions
        )
        saved = overlay_values(
            editor.saved_values, sources.get(editor.profile.key, {})
        )
        replacement = NamelistPage(
            self.project,
            editor.profile,
            saved,
            dimensions,
            self,
            fit_arrays=dimensions != editor.saved_dimensions,
            output_root=root,
            source_values=sources.get(editor.profile.key),
        )
        replacement.hide()
        self._wire_editor(project_key, replacement)
        self.project_editors[project_key][path] = replacement
        editor.setParent(None)
        editor.deleteLater()
        if refresh:
            self._refresh_current_view()

    def _show_validation_error(
        self, editor: NamelistPage, path: Path, error: InputValidationError
    ) -> None:
        """Navigate to the first invalid field and explain it in context."""
        project_key = next(
            key
            for key, editors in self.project_editors.items()
            if editor in editors.values()
        )
        file_item = self._profile_tree_item(project_key, editor.profile.key)
        if file_item is not None:
            for index in range(file_item.childCount()):
                item = file_item.child(index)
                data = item.data(0, Qt.ItemDataRole.UserRole)
                if data and data[0] == "namelist" and data[3] == error.page_key:
                    file_item.setExpanded(True)
                    self.treeWidget_projectStructure.setCurrentItem(item)
                    break
        message = (
            f"File: {path}\n"
            f"Namelist: &{error.page_name}\n"
            f"Property: {error.property_name}\n\n{error}"
        )
        QMessageBox.critical(self, "Invalid namelist input", message)
        editor.reveal_property(
            error.page_key, error.property_name, str(error), error.widget
        )

    def _save_namelist(self, editor: NamelistPage) -> None:
        """Save only the active namelist group in one file."""
        try:
            page, values = editor.page_values()
            profile = replace(editor.profile, pages=(page,))
            save_profiles(
                self.project,
                [(profile, {page.name: values}, editor.dimensions)],
                editor.output_root,
            )
            editor.mark_page_saved(page, values)
            path = _profile_path(self.project, editor.profile, editor.output_root)
            QMessageBox.information(
                self,
                "Namelist saved",
                f"&{page.name} has been saved to:\n{path}",
            )
        except InputValidationError as exc:
            path = _profile_path(self.project, editor.profile, editor.output_root)
            self._show_validation_error(editor, path, exc)
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.critical(self, "Save namelist", str(exc))

    def _save(self, editors: list[NamelistPage]) -> bool:
        """Validate and atomically save supplied profile editors."""
        if not editors:
            return False
        try:
            roots = {editor.output_root for editor in editors}
            if len(roots) != 1:
                raise ValueError("one save operation cannot mix project output directories")
            output_root = roots.pop()
            unique: dict[Path, tuple[NamelistPage, dict[str, Any]]] = {}
            collected: list[tuple[NamelistPage, dict[str, Any]]] = []
            for editor in editors:
                path = _profile_path(self.project, editor.profile, output_root)
                try:
                    values = editor.values()
                except InputValidationError as exc:
                    self._show_validation_error(editor, path, exc)
                    return False
                collected.append((editor, values))
                previous = unique.get(path)
                if previous and (
                    previous[1] != values or previous[0].dimensions != editor.dimensions
                ):
                    raise ValueError(f"loaded projects have conflicting edits for '{path.name}'")
                unique[path] = (editor, values)
            save_profiles(
                self.project,
                [(editor.profile, values, editor.dimensions) for editor, values in unique.values()],
                output_root,
            )
            for editor, values in collected:
                editor.mark_saved(values)
            if self.current_overview is not None:
                self._refresh_current_view()
            paths = list(unique)
            if len(paths) == 1:
                message = f"{paths[0].name} has been saved to:\n{paths[0]}"
            else:
                files = "\n".join(f"• {path.name}" for path in paths)
                message = (
                    f"The following namelist files have been saved:\n\n{files}"
                    f"\n\nOutput directory:\n{output_root}"
                )
            title = "Namelist saved" if len(paths) == 1 else "Namelists saved"
            QMessageBox.information(self, title, message)
            return True
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.critical(self, "Save namelist", str(exc))
            return False

    def _save_project(self, project_key: str) -> bool:
        """Apply dimensions and save every file in one project."""
        config = self.project_configs[project_key]
        saved = self._set_configuration(project_key, config) and self._save(
            list(self.project_editors[project_key].values())
        )
        if saved:
            self.project_saved_dimensions[project_key] = dict(
                self.project_dimensions[project_key]
            )
        return saved

    def _restore_project(self, project_key: str) -> None:
        """Restore schema defaults throughout one project."""
        config = self.project_configs[project_key]
        for name, box in config.dimension_boxes.items():
            box.setValue(self.project.default_dimensions[name])
        if not self._set_configuration(project_key, config):
            return
        for editor in self.project_editors[project_key].values():
            editor.restore_all()
        if project_key == self.active_project:
            self._refresh_current_view()

    def _discard_project(self, project_key: str) -> None:
        """Discard every unsaved value and dimension in one project."""
        dimensions = dict(self.project_saved_dimensions[project_key])
        self.project_dimensions[project_key] = dimensions
        config = self.project_configs[project_key]
        for name, box in config.dimension_boxes.items():
            box.setValue(dimensions[name])
        for editor in list(self.project_editors[project_key].values()):
            self._cancel_profile(project_key, editor, refresh=False)
        if project_key == self.active_project:
            self._refresh_current_view()

    def _save_all(self) -> None:
        """Save every file profile in every loaded project."""
        for project_key in tuple(self.loaded_projects):
            if not self._save_project(project_key):
                break

    def _restore_all(self) -> None:
        """Restore schema defaults in every loaded project."""
        for project_key in tuple(self.loaded_projects):
            self._restore_project(project_key)

    def _clear_projects(self) -> None:
        """Dispose every project cache and reset all active aliases."""
        widgets = [
            *self.project_configs.values(),
            *(editor for editors in self.project_editors.values() for editor in editors.values()),
        ]
        if self.current_overview is not None:
            widgets.append(self.current_overview)
        if self.current_tool is not None:
            widgets.append(self.current_tool)
        if self.empty_view is not None:
            widgets.append(self.empty_view)
        with QSignalBlocker(self.tabs):
            while self.tabs.count():
                self._detach_tab(self.tabs.widget(0))
        for widget in widgets:
            widget.deleteLater()
        self.treeWidget_projectStructure.clear()
        self.loaded_projects.clear()
        self.project_items.clear()
        self.project_editors.clear()
        self.project_configs.clear()
        self.project_dimensions.clear()
        self.project_saved_dimensions.clear()
        self.project_initial_values.clear()
        self.project_initial_dimensions.clear()
        self.active_project = None
        self.editors = {}
        self.config_tab = None
        self.current_overview = None
        self.current_tool = None
        self.empty_view = None
        self.project_add_item = self._action_item(
            None, "Project", ("add_project", "", "", ""), self._add_selected_project
        )
        self.project_add_button = self.treeWidget_projectStructure.itemWidget(
            self.project_add_item, 0
        )
        self.project_add_button.setToolTip("Click here to add a project")
        self._show_empty_project()

    def _remove_tree_item(self, item: QTreeWidgetItem) -> None:
        """Confirm and apply a project, file-profile, or namelist removal."""
        kind, project_key, profile_key, page_key = item.data(0, Qt.ItemDataRole.UserRole)
        message = f"Remove '{item.text(0)}'?"
        removed_pages = {page_key} if kind == "namelist" else set()
        if kind == "namelist":
            message += "\n\nThe namelist values will be lost."
        if kind == "profile":
            removed_pages = {
                page.key
                for profile in self.loaded_projects[project_key].profiles
                if profile.key == profile_key
                for page in profile.pages
            }
        if removed_pages:
            affected = [
                name
                for name, source in self.project.dimension_sources.items()
                if source.namelist in removed_pages
            ]
            if affected:
                message += (
                    "\n\nThe following dimensions will no longer be referred and must be "
                    "set manually: " + ", ".join(affected)
                )
        if (
            QMessageBox.question(self, "Remove item", message) != QMessageBox.Yes
        ):
            return
        try:
            if kind == "project":
                was_active = project_key == self.active_project
                root = self.project_items.pop(project_key)
                self.treeWidget_projectStructure.takeTopLevelItem(
                    self.treeWidget_projectStructure.indexOfTopLevelItem(root)
                )
                self.loaded_projects.pop(project_key)
                editors = self.project_editors.pop(project_key)
                config = self.project_configs.pop(project_key)
                self.project_dimensions.pop(project_key)
                self.project_saved_dimensions.pop(project_key)
                self.project_initial_values.pop(project_key, None)
                self.project_initial_dimensions.pop(project_key, None)
                for widget in (*editors.values(), config):
                    self._detach_tab(widget)
                    widget.deleteLater()
                if self.loaded_projects and was_active:
                    next_key = next(iter(self.loaded_projects))
                    self.treeWidget_projectStructure.setCurrentItem(
                        self.project_items[next_key]
                    )
                elif not self.loaded_projects:
                    self._clear_projects()
                return
            current = self.loaded_projects[project_key]
            standard = next(
                (profile for profile in self.project.profiles if profile.key == profile_key),
                None,
            )
            optional_standard = (
                kind == "namelist"
                and standard is not None
                and page_key not in standard.required
            )
            if not current.custom and not optional_standard:
                customized = self._customize(current)
                if customized is None:
                    return
                current = customized
            profiles = list(current.profiles)
            index = next(i for i, profile in enumerate(profiles) if profile.key == profile_key)
            if kind == "profile":
                profiles.pop(index)
                if not profiles:
                    raise ValueError("a saved project must contain at least one file profile")
            else:
                profile = profiles[index]
                pages = tuple(page for page in profile.pages if page.key != page_key)
                if not pages:
                    raise ValueError("a file profile must contain at least one namelist")
                profiles[index] = replace(
                    profile,
                    pages=pages,
                    required=tuple(name for name in profile.required if name != page_key),
                )
            current = replace(
                current, profiles=ensure_dimension_sources(self.project, profiles)
            )
            if current.custom:
                saved_path = save_project_profile(
                    self.project, current, self._project_root(current)
                )
                current = replace(current, source=saved_path)
            self._replace_project(project_key, current)
            self._rebuild_project_editors(current.key)
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.critical(self, "Remove item", str(exc))

    def _confirm_close(self) -> bool:
        """Protect unsaved editor state for every loaded project."""
        return not self._has_dirty() or QMessageBox.question(
            self,
            "Unsaved changes",
            "Close and discard all unsaved namelist changes?",
        ) == QMessageBox.Yes

    def accept(self) -> None:
        """Close from the button only after the shared dirty-state guard."""
        if self._confirm_close():
            super().accept()

    def reject(self) -> None:
        """Close from Escape only after the shared dirty-state guard."""
        if self._confirm_close():
            super().reject()

    def closeEvent(self, event: Any) -> None:
        """Protect dirty state when the window manager closes the dialog."""
        event.accept() if self._confirm_close() else event.ignore()


