"""Qt application and dialogs for the nml-tools GUI."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .fields import NamelistForm, _exec
from .model import (
    GuiProfile,
    GuiProject,
    create_virtual_project,
    discover_json_files,
    document_dimensions,
    empty_document,
    load_document,
    load_project,
    merge_initial_dimensions,
    merge_initial_values,
    profile_values,
    save_profile,
    save_profiles,
)


class ProfileTab(QWidget):
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
    ):
        super().__init__(parent)
        self.profile = profile
        sizes = {**project.constants, **dimensions}

        root = QVBoxLayout(self)
        if profile.description:
            description = QLabel(profile.description, self)
            description.setWordWrap(True)
            root.addWidget(description)

        pages = QHBoxLayout()
        self.selector = QListWidget(self)
        self.selector.setMaximumWidth(240)
        self.stack = QStackedWidget(self)
        self.forms: dict[str, NamelistForm] = {}
        for page in profile.pages:
            item = QListWidgetItem(page.name)
            item.setData(Qt.ItemDataRole.UserRole, page.key)
            title = page.schema.get("title")
            if isinstance(title, str):
                item.setToolTip(title)
            self.selector.addItem(item)
            form = NamelistForm(
                page.schema,
                values.get(page.name),
                sizes,
                fit_arrays=fit_arrays,
            )
            scroll = QScrollArea(self)
            scroll.setWidgetResizable(True)
            scroll.setWidget(form)
            self.stack.addWidget(scroll)
            self.forms[page.name] = form
        self.selector.currentRowChanged.connect(self.stack.setCurrentIndex)
        pages.addWidget(self.selector)
        pages.addWidget(self.stack, 1)
        root.addLayout(pages, 1)

        buttons = QHBoxLayout()
        self.back = QPushButton("Back", self)
        self.next = QPushButton("Next", self)
        self.restore = QPushButton("Restore defaults", self)
        self.cancel = QPushButton("Cancel", self)
        self.save = QPushButton("Save", self)
        self.back.clicked.connect(
            lambda: self.selector.setCurrentRow(self.selector.currentRow() - 1)
        )
        self.next.clicked.connect(
            lambda: self.selector.setCurrentRow(self.selector.currentRow() + 1)
        )
        self.restore.clicked.connect(self.restore_page)
        buttons.addWidget(self.back)
        buttons.addWidget(self.next)
        buttons.addStretch(1)
        buttons.addWidget(self.restore)
        buttons.addWidget(self.cancel)
        buttons.addWidget(self.save)
        root.addLayout(buttons)

        self.selector.currentRowChanged.connect(self._update_navigation)
        if profile.pages:
            self.selector.setCurrentRow(0)
        else:
            self._update_navigation(-1)

    def values(self) -> dict[str, Any]:
        """Return the values of every namelist page."""
        return {
            page.name: self.forms[page.name].values() for page in self.profile.pages
        }

    def restore_page(self) -> None:
        """Restore defaults on the currently selected page."""
        index = self.selector.currentRow()
        if index >= 0:
            page = self.profile.pages[index]
            self.forms[page.name].reset()

    def restore_all(self) -> None:
        """Restore defaults on every page."""
        for form in self.forms.values():
            form.reset()

    def _update_navigation(self, index: int) -> None:
        self.back.setEnabled(index > 0)
        self.next.setEnabled(0 <= index < len(self.profile.pages) - 1)
        self.restore.setEnabled(index >= 0)


class ConfigurationDialog(QDialog):
    """Single-dialog project and file-profile editor."""

    def __init__(
        self,
        project: GuiProject,
        parent: QWidget | None = None,
        initial_values: Mapping[str, Any] | None = None,
        initial_dimensions: Mapping[str, int] | None = None,
    ):
        super().__init__(parent)
        self.base_project = project
        self.project = project
        self.document = empty_document(project)
        self.source_path: Path | None = None
        self._loading = False
        self.dimension_boxes: dict[str, QSpinBox] = {}
        self.profile_tabs: dict[str, ProfileTab] = {}

        self.setWindowTitle("Namelist configuration")
        self.resize(1000, 700)
        root = QVBoxLayout(self)
        self.tabs = QTabWidget(self)
        self.config_tab = QWidget(self)
        self.tabs.addTab(self.config_tab, "Config")
        root.addWidget(self.tabs, 1)
        self._build_config_tab()

        actions = QHBoxLayout()
        self.restore_all = QPushButton("Restore all", self)
        self.save_all = QPushButton("Save all", self)
        close = QPushButton("Close", self)
        self.restore_all.clicked.connect(self._restore_all)
        self.save_all.clicked.connect(self._save_all)
        close.clicked.connect(self.accept)
        actions.addStretch(1)
        actions.addWidget(self.restore_all)
        actions.addWidget(self.save_all)
        actions.addWidget(close)
        root.addLayout(actions)
        self._set_profile_actions_enabled(False)

        self.browse.clicked.connect(self._browse_json)
        self._populate_json_files()
        self.json_combo.currentIndexChanged.connect(self._load_selected_json)
        self._load_selected_json(self.json_combo.currentIndex())
        if initial_dimensions is not None:
            self.document = merge_initial_dimensions(
                self.document, initial_dimensions, self.base_project
            )
        if initial_values is not None:
            self._prepare_virtual_initial_values(initial_values)
            self.document = merge_initial_values(
                self.document, initial_values, self.project
            )
        if initial_dimensions is not None or initial_values is not None:
            self._set_dimensions(document_dimensions(self.document, self.project))
            self._sync_virtual_controls()

    def _build_config_tab(self) -> None:
        layout = QVBoxLayout(self.config_tab)
        source_layout = QHBoxLayout()
        source_layout.addWidget(QLabel("Load configuration", self.config_tab))
        self.json_combo = QComboBox(self.config_tab)
        self.browse = QPushButton("Browse…", self.config_tab)
        source_layout.addWidget(self.json_combo, 1)
        source_layout.addWidget(self.browse)
        layout.addLayout(source_layout)

        self.dimensions_group = QGroupBox("Runtime dimensions", self.config_tab)
        self.dimensions_layout = QFormLayout(self.dimensions_group)
        for name, default in self.base_project.default_dimensions.items():
            box = QSpinBox(self.dimensions_group)
            box.setRange(1, 2_147_483_647)
            box.setValue(default)
            self.dimensions_layout.addRow(name, box)
            self.dimension_boxes[name] = box
        if self.dimension_boxes:
            layout.addWidget(self.dimensions_group)
        else:
            self.dimensions_group.hide()

        if not self.base_project.profiles:
            self._build_virtual_profile_controls(layout)

        layout.addStretch(1)
        run_row = QHBoxLayout()
        run_row.addStretch(1)
        self.run = QPushButton("Run", self.config_tab)
        self.run.clicked.connect(self._run_configuration)
        run_row.addWidget(self.run)
        layout.addLayout(run_row)

    def _build_virtual_profile_controls(self, layout: QVBoxLayout) -> None:
        group = QGroupBox("File profile", self.config_tab)
        group_layout = QVBoxLayout(group)
        lists = QHBoxLayout()
        self.available_schemas = QListWidget(group)
        self.selected_schemas = QListWidget(group)
        selection_mode = QAbstractItemView.ExtendedSelection
        self.available_schemas.setSelectionMode(selection_mode)
        self.selected_schemas.setSelectionMode(selection_mode)
        for page in self.base_project.namelists:
            self.available_schemas.addItem(self._schema_item(page.name, page.key))

        transfers = QVBoxLayout()
        transfers.addStretch(1)
        for label, handler in (
            (
                ">",
                lambda: self._move_selected(
                    self.available_schemas, self.selected_schemas
                ),
            ),
            (
                ">>",
                lambda: self._move_all(
                    self.available_schemas, self.selected_schemas
                ),
            ),
            (
                "<",
                lambda: self._move_selected(
                    self.selected_schemas, self.available_schemas
                ),
            ),
            (
                "<<",
                lambda: self._move_all(
                    self.selected_schemas, self.available_schemas
                ),
            ),
        ):
            button = QPushButton(label, group)
            button.clicked.connect(handler)
            transfers.addWidget(button)
        transfers.addStretch(1)
        lists.addWidget(self.available_schemas, 1)
        lists.addLayout(transfers)
        lists.addWidget(self.selected_schemas, 1)
        group_layout.addLayout(lists)

        metadata = QFormLayout()
        self.profile_name = QLineEdit(group)
        self.default_filename = QLineEdit(group)
        metadata.addRow("Profile name", self.profile_name)
        metadata.addRow("Default file name", self.default_filename)
        group_layout.addLayout(metadata)
        layout.addWidget(group, 1)

    @staticmethod
    def _schema_item(name: str, key: str) -> QListWidgetItem:
        item = QListWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, key)
        return item

    @staticmethod
    def _move_selected(source: QListWidget, target: QListWidget) -> None:
        for item in sorted(source.selectedItems(), key=source.row):
            target.addItem(source.takeItem(source.row(item)))

    @staticmethod
    def _move_all(source: QListWidget, target: QListWidget) -> None:
        while source.count():
            target.addItem(source.takeItem(0))

    def _populate_json_files(self, selected: Path | None = None) -> None:
        self._loading = True
        self.json_combo.clear()
        paths = discover_json_files(self.base_project)
        if not paths:
            self.json_combo.addItem("nml.json (new)", None)
        else:
            for path in paths:
                self.json_combo.addItem(path.name, str(path))
        if selected is not None:
            selected_text = str(selected.resolve())
            index = self.json_combo.findData(selected_text)
            if index < 0:
                label = (
                    selected.name
                    if selected.parent == self.base_project.output_root
                    else str(selected)
                )
                self.json_combo.addItem(label, selected_text)
                index = self.json_combo.count() - 1
            self.json_combo.setCurrentIndex(index)
        self._loading = False

    def _load_selected_json(self, _index: int) -> None:
        if self._loading:
            return
        raw_path = self.json_combo.currentData()
        if raw_path is None:
            self.source_path = None
            self.project = self.base_project
            self.document = empty_document(self.base_project)
        else:
            path = Path(raw_path)
            try:
                document = load_document(path, self.base_project)
                project = self._virtual_project_from_document(document)
            except ValueError as exc:
                QMessageBox.critical(self, "Load configuration", str(exc))
                self.json_combo.blockSignals(True)
                previous = (
                    self.json_combo.findData(str(self.source_path.resolve()))
                    if self.source_path is not None
                    else -1
                )
                self.json_combo.setCurrentIndex(previous)
                self.json_combo.blockSignals(False)
                return
            self.source_path = path
            self.project = project
            self.document = document
        self._set_dimensions(document_dimensions(self.document, self.project))
        self._sync_virtual_controls()
        self._clear_profile_tabs()
        self._set_profile_actions_enabled(False)
        self.tabs.setCurrentWidget(self.config_tab)

    def _virtual_project_from_document(
        self, document: Mapping[str, Any]
    ) -> GuiProject:
        if self.base_project.profiles:
            return self.base_project
        raw_profiles = document.get("file_profiles", {})
        if not isinstance(raw_profiles, Mapping) or not raw_profiles:
            return self.base_project
        entry = next(iter(raw_profiles.values()))
        if not isinstance(entry, Mapping):
            return self.base_project
        name = str(entry.get("profile", ""))
        default_file = str(entry.get("default_filename", f"{name}.nml"))
        values = entry.get("values", {})
        keys = list(values) if isinstance(values, Mapping) else []
        return create_virtual_project(self.base_project, name, default_file, keys)

    def _prepare_virtual_initial_values(
        self, initial_values: Mapping[str, Any]
    ) -> None:
        if (
            self.base_project.profiles
            or self.project.profiles
            or len(initial_values) != 1
        ):
            return
        name, values = next(iter(initial_values.items()))
        if not isinstance(name, str) or not isinstance(values, Mapping):
            return
        self.project = create_virtual_project(
            self.base_project, name, f"{name}.nml", values
        )
        self._set_virtual_controls(
            name, f"{name}.nml", [page.key for page in self.project.profiles[0].pages]
        )

    def _sync_virtual_controls(self) -> None:
        if self.base_project.profiles:
            return
        if not self.project.profiles:
            self._set_virtual_controls("", "", [])
            return
        profile = self.project.profiles[0]
        self._set_virtual_controls(
            profile.name,
            profile.default_file,
            [page.key for page in profile.pages],
        )

    def _set_virtual_controls(
        self, name: str, default_file: str, selected_keys: list[str]
    ) -> None:
        self.profile_name.setText(name)
        self.default_filename.setText(default_file)
        selected = {key.lower() for key in selected_keys}
        self.available_schemas.clear()
        self.selected_schemas.clear()
        by_key = {page.key: page for page in self.base_project.namelists}
        for key in selected_keys:
            page = by_key.get(key.lower())
            if page is not None:
                self.selected_schemas.addItem(self._schema_item(page.name, page.key))
        for page in self.base_project.namelists:
            if page.key not in selected:
                self.available_schemas.addItem(self._schema_item(page.name, page.key))

    def _browse_json(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Load namelist JSON",
            str(self.base_project.output_root),
            "JSON files (*.json)",
        )
        if not filename:
            return
        path = Path(filename).resolve()
        self._populate_json_files(path)
        self._load_selected_json(self.json_combo.currentIndex())

    def _set_dimensions(self, dimensions: Mapping[str, int]) -> None:
        for name, box in self.dimension_boxes.items():
            box.blockSignals(True)
            box.setValue(dimensions[name])
            box.blockSignals(False)

    def _current_dimensions(self) -> dict[str, int]:
        return {name: box.value() for name, box in self.dimension_boxes.items()}

    def _run_configuration(self) -> None:
        try:
            current = {
                key: tab.values() for key, tab in self.profile_tabs.items()
            }
            if self.base_project.profiles:
                project = self.base_project
            else:
                keys = []
                for index in range(self.selected_schemas.count()):
                    item = self.selected_schemas.item(index)
                    if item is not None:
                        keys.append(str(item.data(Qt.ItemDataRole.UserRole)))
                project = create_virtual_project(
                    self.base_project,
                    self.profile_name.text(),
                    self.default_filename.text(),
                    keys,
                )
        except (ValueError, KeyError) as exc:
            QMessageBox.critical(self, "Invalid configuration", str(exc))
            return

        old_pages = {
            name: values
            for profile_values_ in current.values()
            for name, values in profile_values_.items()
        }
        self.project = project
        self._clear_profile_tabs()
        dimensions = self._current_dimensions()
        for profile in project.profiles:
            values = current.get(profile.key, profile_values(self.document, profile))
            if not values and old_pages:
                values = {
                    page.name: old_pages[page.name]
                    for page in profile.pages
                    if page.name in old_pages
                }
            self._add_profile_tab(profile, values, dimensions, fit_arrays=True)
        self._set_profile_actions_enabled(bool(self.profile_tabs))
        if self.profile_tabs:
            self.tabs.setCurrentIndex(1)

    def _add_profile_tab(
        self,
        profile: GuiProfile,
        values: Mapping[str, Any],
        dimensions: Mapping[str, int],
        *,
        fit_arrays: bool,
        index: int | None = None,
    ) -> ProfileTab:
        editor = ProfileTab(
            self.project,
            profile,
            values,
            dimensions,
            self,
            fit_arrays=fit_arrays,
        )
        editor.cancel.clicked.connect(lambda: self._cancel_profile(profile))
        editor.save.clicked.connect(lambda: self._save_profile(profile))
        if index is None:
            self.tabs.addTab(editor, profile.title)
        else:
            self.tabs.insertTab(index, editor, profile.title)
        self.profile_tabs[profile.key] = editor
        return editor

    def _clear_profile_tabs(self) -> None:
        while self.tabs.count() > 1:
            widget = self.tabs.widget(1)
            self.tabs.removeTab(1)
            if widget is not None:
                widget.deleteLater()
        self.profile_tabs.clear()

    def _cancel_profile(self, profile: GuiProfile) -> None:
        old = self.profile_tabs[profile.key]
        index = self.tabs.indexOf(old)
        self.tabs.removeTab(index)
        old.deleteLater()
        self._add_profile_tab(
            profile,
            profile_values(self.document, profile),
            self._current_dimensions(),
            fit_arrays=True,
            index=index,
        )
        self.tabs.setCurrentIndex(index)

    def _save_profile(self, profile: GuiProfile) -> None:
        try:
            self.document = save_profile(
                self.project,
                self.document,
                profile,
                self.profile_tabs[profile.key].values(),
                self._current_dimensions(),
            )
        except (OSError, UnicodeError, ValueError, KeyError) as exc:
            QMessageBox.critical(self, "Save configuration", str(exc))
            return
        self._saved()

    def _restore_all(self) -> None:
        for tab in self.profile_tabs.values():
            tab.restore_all()

    def _save_all(self) -> None:
        try:
            values = {
                key: tab.values() for key, tab in self.profile_tabs.items()
            }
            self.document = save_profiles(
                self.project,
                self.document,
                values,
                self._current_dimensions(),
            )
        except (OSError, UnicodeError, ValueError, KeyError) as exc:
            QMessageBox.critical(self, "Save configuration", str(exc))
            return
        self._saved()

    def _saved(self) -> None:
        self.source_path = self.base_project.output_root / "nml.json"
        self._populate_json_files(self.source_path)

    def _set_profile_actions_enabled(self, enabled: bool) -> None:
        self.restore_all.setEnabled(enabled)
        self.save_all.setEnabled(enabled)


def launch_gui(
    schemas_dir: Path | str | None = None,
    output_dir: Path | str | None = None,
    initial_values: Mapping[str, Any] | None = None,
    initial_dimensions: Mapping[str, int] | None = None,
) -> int:
    """Launch the GUI with optional output, values, and runtime dimensions."""
    project = load_project(schemas_dir, output_dir)
    application = QApplication.instance()
    owns_application = application is None
    if application is None:
        application = QApplication(sys.argv[:1])
        application.setApplicationName("nml-tools")
    dialog = ConfigurationDialog(
        project,
        initial_values=initial_values,
        initial_dimensions=initial_dimensions,
    )
    if not owns_application:
        _exec(dialog)
        return 0
    dialog.show()
    method = getattr(application, "exec", None)
    if method is None:
        method = application.exec_
    return int(method())
