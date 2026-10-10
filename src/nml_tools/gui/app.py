# mypy: disable-error-code="attr-defined, import-not-found, misc"
"""Project-oriented Qt editor for direct namelist input and output."""

from __future__ import annotations

import copy
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from qtpy.QtCore import QSignalBlocker, Qt
from qtpy.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHeaderView,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QTabBar,
    QToolButton,
    QTreeWidgetItem,
    QWidget,
)

from .fields import NamelistForm, _exec
from .model import (
    GuiProfile,
    GuiProject,
    GuiProjectProfile,
    _normalize_dimensions,
    _normalize_profile_values,
    _profile_path,
    create_virtual_project,
    dimension_source_values,
    discover_project_files,
    ensure_dimension_sources,
    load_profile,
    load_project,
    load_project_profile_file,
    overlay_values,
    recover_dimensions,
    save_profiles,
    save_project_profile,
)
from .ui import load_ui

_UNSET = object()


def _untouched_page_values(
    schema: Mapping[str, Any], source: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Collect loaded values and defaults without constructing an unseen page."""
    properties = schema.get("properties", {})
    required = {str(name).lower() for name in schema.get("required", [])}
    raw = source or {}
    result: dict[str, Any] = {}
    for name, child in properties.items():
        if not isinstance(name, str) or not isinstance(child, Mapping):
            continue
        value = _untouched_value(
            child,
            raw.get(name, _UNSET),
            name.lower() in required or "default" in child,
            name,
        )
        if value is not _UNSET:
            result[name] = value
    return result


def _untouched_value(schema: Mapping[str, Any], value: Any, required: bool, name: str) -> Any:
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
        return copy.deepcopy(schema["default"])
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
        )
        if child_value is not _UNSET:
            result[child_name] = child_value
    if required and not result:
        raise ValueError(f"required field '{name}' has no value")
    return result


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
    ) -> None:
        super().__init__(parent)
        load_ui("profile_tab.ui", self)
        self.project = project
        self.profile = profile
        self.dimensions = dict(dimensions)
        self.saved_dimensions = dict(dimensions)
        self._values = copy.deepcopy(dict(values))
        self._sizes = {**project.constants, **dimensions}
        self._fit_arrays = fit_arrays
        self.forms: dict[str, NamelistForm] = {}
        self.form_saved: dict[str, dict[str, Any]] = {}
        self.selector: QComboBox = self.namelistComboBox
        self.stack = self.namelistStack
        self.back = self.backButton
        self.next = self.nextButton
        self.restore = self.restoreButton
        self.cancel = self.cancelButton
        self.save = self.saveButton
        self.descriptionLabel.setText(profile.description or "")
        self.descriptionLabel.setVisible(bool(profile.description))
        for page in profile.pages:
            self.selector.addItem(page.name, page.key)
            self.stack.addWidget(QWidget(self.stack))
        self.selector.currentIndexChanged.connect(self._page_changed)
        self.back.clicked.connect(
            lambda: self.selector.setCurrentIndex(self.selector.currentIndex() - 1)
        )
        self.next.clicked.connect(
            lambda: self.selector.setCurrentIndex(self.selector.currentIndex() + 1)
        )
        self.restore.clicked.connect(self.restore_page)
        self.selector.setCurrentIndex(-1)
        self.selector.setCurrentIndex(0 if profile.pages else -1)
        self.saved_values = copy.deepcopy(dict(values))

    def values(self) -> dict[str, Any]:
        """Return values from every namelist page."""
        result = {}
        for index, page in enumerate(self.profile.pages):
            form = self.forms.get(page.name)
            result[page.name] = (
                (form or self._ensure_form(index)).values()
                if form is not None or self._fit_arrays
                else _untouched_page_values(page.schema, self._values.get(page.name))
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

    def restore_page(self) -> None:
        """Restore the active namelist page."""
        index = self.selector.currentIndex()
        if index >= 0:
            self._ensure_form(index).reset()

    def restore_all(self) -> None:
        """Restore every page in this file profile."""
        for index in range(len(self.profile.pages)):
            self._ensure_form(index).reset()

    def select_page(self, key: str) -> None:
        """Select a namelist page by normalized name."""
        index = self.selector.findData(key)
        if index >= 0:
            self.selector.setCurrentIndex(index)

    def _page_changed(self, index: int) -> None:
        """Build the selected page on first use and display it."""
        if index >= 0:
            self._ensure_form(index)
        self.stack.setCurrentIndex(index)
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
            output_root=self.project.output_root,
            read_only=read_only,
        )
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(form)
        old = self.stack.widget(index)
        self.stack.removeWidget(old)
        old.deleteLater()
        self.stack.insertWidget(index, scroll)
        self.forms[page.name] = form
        try:
            self.form_saved[page.name] = copy.deepcopy(form.values())
        except ValueError:
            self.form_saved[page.name] = copy.deepcopy(dict(self._values.get(page.name, {})))
        return form

    def _update_navigation(self, index: int) -> None:
        """Update Back/Next availability for the active page."""
        self.back.setEnabled(index > 0)
        self.next.setEnabled(0 <= index < self.selector.count() - 1)
        self.restore.setEnabled(index >= 0)


class ProfileConfigTab(QWidget):
    """Create, add, or import one file profile within a project."""

    def __init__(
        self,
        project: GuiProject,
        dimensions: Mapping[str, int],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        load_ui("profile_config.ui", self)
        self.project = project
        self.source_profile: GuiProfile | None = None
        self.source_profiles: dict[str, GuiProfile] = {}
        self.source_combo = self.sourceComboBox_loadProfile
        self.browse = self.browseButton_loadProfile
        self.run = self.runButton
        self.available_schemas: QListWidget = self.availableSchemasList
        self.selected_schemas: QListWidget = self.selectedSchemasList
        self.profile_name = self.profileNameEdit
        self.default_filename = self.defaultFileEdit
        self.dimension_boxes: dict[str, QSpinBox] = {}
        mode = QAbstractItemView.ExtendedSelection
        self.available_schemas.setSelectionMode(mode)
        self.selected_schemas.setSelectionMode(mode)
        for name, default in project.default_dimensions.items():
            box = QSpinBox(self.dimensionsGroup)
            box.setRange(1, 2_147_483_647)
            box.setValue(dimensions.get(name, default))
            self.dimensionsLayout.addRow(name, box)
            self.dimension_boxes[name] = box
        self.dimensionsGroup.setVisible(bool(self.dimension_boxes))
        for page in project.namelists:
            self.available_schemas.addItem(ConfigurationDialog._schema_item(page.name, page.key))
        for button, source, target, all_items in (
            (self.addSchemaButton, self.available_schemas, self.selected_schemas, False),
            (self.addAllSchemasButton, self.available_schemas, self.selected_schemas, True),
            (self.removeSchemaButton, self.selected_schemas, self.available_schemas, False),
            (self.removeAllSchemasButton, self.selected_schemas, self.available_schemas, True),
        ):
            callback = (
                ConfigurationDialog._move_all if all_items else ConfigurationDialog._move_selected
            )
            button.clicked.connect(lambda _checked=False, s=source, t=target, fn=callback: fn(s, t))

    def dimensions(self) -> dict[str, int]:
        """Return runtime dimensions entered on this tab."""
        return {name: box.value() for name, box in self.dimension_boxes.items()}

    def schema_keys(self) -> list[str]:
        """Return selected namelist keys in visible order."""
        return [
            str(self.selected_schemas.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.selected_schemas.count())
        ]

    def reset_builder(self, profiles: tuple[GuiProfile, ...]) -> None:
        """Reset the file-profile builder and refresh reusable definitions."""
        self.source_combo.clear()
        self.source_combo.addItem("<new>", ("new", ""))
        self.source_profiles = {profile.key: profile for profile in self.project.profiles}
        for path in discover_project_files(self.project):
            try:
                discovered = load_project_profile_file(self.project, path)
            except (OSError, ValueError):
                continue
            for profile in discovered.profiles:
                self.source_profiles.setdefault(profile.key, profile)
        self.source_profiles.update((profile.key, profile) for profile in profiles)
        for profile in self.source_profiles.values():
            self.source_combo.addItem(profile.title, ("profile", profile.key))
        self.clear_builder()

    def clear_builder(self) -> None:
        """Clear the editable definition for a new file profile."""
        self.source_profile = None
        self.profile_name.clear()
        self.default_filename.clear()
        self.available_schemas.clear()
        self.selected_schemas.clear()
        for page in self.project.namelists:
            self.available_schemas.addItem(ConfigurationDialog._schema_item(page.name, page.key))


class ConfigurationDialog(QDialog):
    """Edit one or more project profiles and their direct namelist files."""

    def __init__(
        self,
        project: GuiProject,
        parent: QWidget | None = None,
        initial_values: Mapping[str, Any] | None = None,
        initial_dimensions: Mapping[str, int] | None = None,
    ) -> None:
        super().__init__(parent)
        load_ui("app.ui", self)
        self.project = project
        if initial_values is not None and not isinstance(initial_values, Mapping):
            raise ValueError("initial_values must map file profiles to namelist values")
        self.initial_values: dict[str, Any] = {}
        for name, values in (initial_values or {}).items():
            if not isinstance(name, str):
                raise ValueError("initial value profile names must be strings")
            try:
                profile = project.profile(name)
            except KeyError as exc:
                raise ValueError(f"unknown initial value profile '{name}'") from exc
            if profile.key in self.initial_values:
                raise ValueError(f"duplicate initial value profile '{name}'")
            self.initial_values[profile.key] = values
        self.dimension_overrides = initial_dimensions or {}
        profiles = project.project_profiles or (
            GuiProjectProfile("default", "default", "Default", None, project.profiles, custom=True),
        )
        self.available_projects = {profile.key: profile for profile in profiles}
        self.loaded_projects: dict[str, GuiProjectProfile] = {}
        self.project_items: dict[str, QTreeWidgetItem] = {}
        self.project_editors: dict[str, dict[Path, ProfileTab]] = {}
        self.project_configs: dict[str, ProfileConfigTab] = {}
        self.project_dimensions: dict[str, dict[str, int]] = {}
        self.active_project: str | None = None
        self.editors: dict[Path, ProfileTab] = {}
        self.config_tab: ProfileConfigTab | None = None
        self.plus_tab = QWidget(self.tabs)
        self.tabs.setTabsClosable(True)
        self.splitter.setSizes([self.width(), self.width() * 3])
        self.treeWidget_projectStructure.setColumnCount(2)
        self.treeWidget_projectStructure.setHeaderLabels(["Project structure", ""])
        header = self.treeWidget_projectStructure.header()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(28)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        self.treeWidget_projectStructure.setColumnWidth(1, 28)
        self._populate_project_sources()
        self.browseButton_loadProject.clicked.connect(self._browse_project)
        self.browseButton_addProject.clicked.connect(self._add_selected_project)
        self.treeWidget_projectStructure.currentItemChanged.connect(self._tree_selected)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.restoreAllButton.clicked.connect(self._restore_all)
        self.saveAllButton.clicked.connect(self._save_all)
        self.closeButton.clicked.connect(self.accept)

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
        while source.count():
            target.addItem(source.takeItem(0))

    def _populate_project_sources(self) -> None:
        """List configured and discoverable project-profile sources."""
        combo = self.sourceComboBox_loadProject
        combo.addItem("<new>", ("new", ""))
        for profile in self.available_projects.values():
            combo.addItem(profile.title, ("configured", profile.key))
        for path in discover_project_files(self.project):
            combo.addItem(path.name, ("path", str(path)))

    def _browse_project(self) -> None:
        """Add a browsed TOML path to the source chooser without loading it."""
        name, _ = QFileDialog.getOpenFileName(
            self, "Load project profile", str(self.project.root), "TOML files (*.toml)"
        )
        if name:
            data = ("path", str(Path(name).resolve()))
            index = next(
                (
                    index
                    for index in range(self.sourceComboBox_loadProject.count())
                    if self.sourceComboBox_loadProject.itemData(index) == data
                ),
                -1,
            )
            if index < 0:
                self.sourceComboBox_loadProject.addItem(Path(name).name, data)
                index = self.sourceComboBox_loadProject.count() - 1
            self.sourceComboBox_loadProject.setCurrentIndex(index)

    def _add_selected_project(self) -> None:
        """Load the selected configured, external, or new project into the tree."""
        try:
            kind, value = self.sourceComboBox_loadProject.currentData()
            if kind == "new":
                name, accepted = QInputDialog.getText(self, "New project", "Project name")
                name = name.strip()
                if not accepted:
                    return
                if not name or not name.replace("-", "_").isalnum():
                    raise ValueError("project name may contain only letters, numbers, '-' and '_'")
                profile = GuiProjectProfile(name, name.lower(), name, None, (), custom=True)
                if profile.key in self.loaded_projects:
                    raise ValueError(f"project '{name}' is already loaded")
            elif kind == "configured":
                profile = self.available_projects[value]
            else:
                profile = load_project_profile_file(self.project, Path(value))
            self._register_project(profile)
            self.treeWidget_projectStructure.setCurrentItem(self.project_items[profile.key])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            QMessageBox.critical(self, "Load project", str(exc))

    def _register_project(self, profile: GuiProjectProfile) -> None:
        """Validate and add one project profile without duplicating it."""
        if profile.key in self.loaded_projects:
            return
        profiles = ensure_dimension_sources(self.project, profile.profiles)
        profile = replace(profile, profiles=profiles)
        paths = [_profile_path(self.project, item) for item in profiles]
        for loaded in self.loaded_projects.values():
            for left in loaded.profiles:
                for right in profiles:
                    if left.default_file == right.default_file and left != right:
                        raise ValueError(
                            f"projects '{loaded.name}' and '{profile.name}' define "
                            f"'{left.default_file}' differently"
                        )
        if len(paths) != len(set(paths)):
            raise ValueError(f"project '{profile.name}' writes more than one profile to one file")
        dimensions = recover_dimensions(self.project, paths, self.dimension_overrides)
        source_values = dimension_source_values(self.project, profiles, dimensions)
        prepared: dict[Path, ProfileTab] = {}
        try:
            for item, path in zip(profiles, paths):
                values = load_profile(self.project, item, dimensions)
                supplied = self.initial_values.get(item.key, {})
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
                prepared[path] = ProfileTab(self.project, item, values, dimensions, self)
                prepared[path].hide()
        except Exception:
            for editor in prepared.values():
                editor.deleteLater()
            raise
        self.loaded_projects[profile.key] = profile
        self.project_dimensions[profile.key] = dimensions
        self.project_editors[profile.key] = prepared
        for editor in prepared.values():
            editor.save.clicked.connect(lambda _checked=False, item=editor: self._save([item]))
            editor.cancel.clicked.connect(
                lambda _checked=False, item=editor: self._cancel_profile(profile.key, item)
            )
        self._new_config(profile.key)
        self._build_tree(profile)

    def _new_config(self, project_key: str) -> ProfileConfigTab:
        """Create the single reusable Config tab for one loaded project."""
        old = self.project_configs.get(project_key)
        if old is not None:
            old.deleteLater()
        config = ProfileConfigTab(self.project, self.project_dimensions[project_key], self)
        config.hide()
        config.reset_builder(self.loaded_projects[project_key].profiles)
        config.browse.clicked.connect(lambda: self._browse_profile(config))
        config.source_combo.currentIndexChanged.connect(lambda: self._select_profile_source(config))
        config.run.clicked.connect(lambda: self._run_configuration(config))
        self.project_configs[project_key] = config
        return config

    def _build_tree(self, profile: GuiProjectProfile) -> None:
        """Build one project/file/namelist branch with removal controls."""
        root = QTreeWidgetItem([profile.title, ""])
        root.setData(0, Qt.ItemDataRole.UserRole, ("project", profile.key, "", ""))
        self.treeWidget_projectStructure.addTopLevelItem(root)
        self._remove_button(root)
        for file_profile in profile.profiles:
            file_item = QTreeWidgetItem([file_profile.title, ""])
            file_item.setData(
                0, Qt.ItemDataRole.UserRole, ("profile", profile.key, file_profile.key, "")
            )
            root.addChild(file_item)
            self._remove_button(file_item)
            for page in file_profile.pages:
                child = QTreeWidgetItem([page.name, ""])
                child.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    ("namelist", profile.key, file_profile.key, page.key),
                )
                file_item.addChild(child)
                self._remove_button(child)
        root.setExpanded(True)
        self.project_items[profile.key] = root

    def _remove_button(self, item: QTreeWidgetItem) -> None:
        """Install the tree action used to remove this item from the session."""
        button = QToolButton(self.treeWidget_projectStructure)
        button.setText("×")
        button.setAutoRaise(True)
        button.clicked.connect(lambda: self._remove_tree_item(item))
        self.treeWidget_projectStructure.setItemWidget(item, 1, button)

    def _show_project(self, key: str) -> None:
        """Show only the selected project's cached tabs."""
        if key not in self.loaded_projects:
            return
        self.active_project = key
        self.editors = self.project_editors[key]
        self.config_tab = self.project_configs[key]
        with QSignalBlocker(self.tabs):
            while self.tabs.count():
                widget = self.tabs.widget(0)
                self.tabs.removeTab(0)
                widget.hide()
            self.tabs.addTab(self.config_tab, "⚙️")
            for editor in self.editors.values():
                self.tabs.addTab(editor, editor.profile.title)
            self.tabs.addTab(self.plus_tab, "+")
            for side in (QTabBar.LeftSide, QTabBar.RightSide):
                self.tabs.tabBar().setTabButton(self.tabs.indexOf(self.plus_tab), side, None)
            self.tabs.setCurrentIndex(1 if self.editors else 0)

    def _tree_selected(self, current: QTreeWidgetItem | None, _previous: Any) -> None:
        """Navigate from a tree identity to its project, file, or namelist page."""
        if current is None:
            return
        kind, project_key, profile_key, page_key = current.data(0, Qt.ItemDataRole.UserRole)
        self._show_project(project_key)
        if kind in {"profile", "namelist"}:
            if kind == "profile":
                current.setExpanded(True)
            profile = next(
                item
                for item in self.loaded_projects[project_key].profiles
                if item.key == profile_key
            )
            editor = self._ensure_editor(project_key, profile)
            self._insert_editor_tab(editor)
            if kind == "namelist":
                editor.select_page(page_key)

    def _tab_changed(self, index: int) -> None:
        """Synchronize profile tabs with the tree and handle the trailing plus tab."""
        widget = self.tabs.widget(index)
        if isinstance(widget, ProfileTab) and self.active_project is not None:
            root = self.project_items[self.active_project]
            for child_index in range(root.childCount()):
                item = root.child(child_index)
                if item.data(0, Qt.ItemDataRole.UserRole)[2] == widget.profile.key:
                    item.setExpanded(True)
                    with QSignalBlocker(self.treeWidget_projectStructure):
                        self.treeWidget_projectStructure.setCurrentItem(item)
                    break
        elif widget is self.plus_tab and self.active_project is not None:
            profile = self.loaded_projects[self.active_project]
            config = self.project_configs[self.active_project]
            self.config_tab = (
                self._new_config(self.active_project)
                if self.tabs.indexOf(config) < 0 and self.config_tab is None
                else config
            )
            self.config_tab.reset_builder(profile.profiles)
            if self.tabs.indexOf(self.config_tab) < 0:
                self.tabs.insertTab(0, self.config_tab, "⚙️")
            self.tabs.setCurrentWidget(self.config_tab)

    def _close_tab(self, index: int) -> None:
        """Hide a Config or profile tab while keeping its cached state."""
        widget = self.tabs.widget(index)
        if widget is None or widget is self.plus_tab:
            return
        if isinstance(widget, ProfileTab):
            if (
                widget.is_dirty()
                and QMessageBox.question(
                    self, "Unsaved changes", "Hide this profile with unsaved changes?"
                )
                != QMessageBox.Yes
            ):
                return
        with QSignalBlocker(self.tabs):
            self.tabs.removeTab(index)
            widget.hide()
        if widget is self.config_tab:
            self.config_tab = None
        if self.tabs.count() == 1:
            self._tab_changed(self.tabs.indexOf(self.plus_tab))

    def _browse_profile(self, config: ProfileConfigTab) -> None:
        """Add file profiles from a selected project-profile TOML file."""
        name, _ = QFileDialog.getOpenFileName(
            self, "Load file profiles", str(self.project.root), "TOML files (*.toml)"
        )
        if name:
            try:
                profiles = load_project_profile_file(self.project, Path(name)).profiles
                for profile in profiles:
                    config.source_profiles[profile.key] = profile
                    data = ("profile", profile.key)
                    index = next(
                        (
                            index
                            for index in range(config.source_combo.count())
                            if config.source_combo.itemData(index) == data
                        ),
                        -1,
                    )
                    if index < 0:
                        config.source_combo.addItem(profile.title, data)
                if profiles:
                    config.source_combo.setCurrentIndex(
                        next(
                            index
                            for index in range(config.source_combo.count())
                            if config.source_combo.itemData(index) == ("profile", profiles[0].key)
                        )
                    )
            except (OSError, ValueError) as exc:
                QMessageBox.critical(self, "Invalid profile", str(exc))

    def _select_profile_source(self, config: ProfileConfigTab) -> None:
        """Populate builder values from a reusable file profile."""
        data = config.source_combo.currentData()
        if not data:
            return
        kind, value = data
        config.source_profile = None
        try:
            if kind != "profile":
                config.clear_builder()
                return
            config.source_profile = config.source_profiles[value]
            profile = config.source_profile
            config.profile_name.setText(profile.name)
            config.default_filename.setText(profile.default_file)
            selected = {page.key for page in profile.pages}
            config.available_schemas.clear()
            config.selected_schemas.clear()
            for page in self.project.namelists:
                target = (
                    config.selected_schemas if page.key in selected else config.available_schemas
                )
                target.addItem(self._schema_item(page.name, page.key))
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.critical(self, "Invalid namelist", str(exc))

    def _run_configuration(self, config: ProfileConfigTab) -> None:
        """Apply dimensions and create or add the selected file profile."""
        if self.active_project is None:
            return
        try:
            dimensions = _normalize_dimensions(config.dimensions(), self.project)
            imported: Mapping[str, Any] | None = None
            if (
                config.source_profile is None
                and not config.profile_name.text().strip()
                and not config.schema_keys()
            ):
                current = self.loaded_projects[self.active_project]
                self.project_dimensions[current.key] = dimensions
                self._rebuild_project_editors(current.key, fit_arrays=True)
                return
            profile = create_virtual_project(
                self.project,
                config.profile_name.text(),
                config.default_filename.text(),
                config.schema_keys(),
            ).profiles[0]
            source = config.source_profile
            if source is not None:
                selected = {page.key for page in profile.pages}
                profile = replace(
                    profile,
                    title=source.title if profile.name == source.name else profile.name,
                    description=source.description,
                    required=tuple(name for name in source.required if name in selected),
                )
            current = self.loaded_projects[self.active_project]
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
                if index != replace_index and item.default_file == profile.default_file:
                    raise ValueError(f"output file '{profile.default_file}' is already used")
            if replace_index is None:
                profiles = (*current.profiles, profile)
            else:
                profiles_list = list(current.profiles)
                old = profiles_list[replace_index]
                profiles_list[replace_index] = profile
                profiles = tuple(profiles_list)
                if old.default_file != profile.default_file:
                    old_path = _profile_path(self.project, old)
                    imported = self.project_editors[current.key][old_path].values()
            profiles = ensure_dimension_sources(self.project, profiles)
            current = self._customize(current)
            current = replace(current, profiles=profiles)
            save_project_profile(self.project, current)
            self._replace_project(current)
            self.project_dimensions[current.key] = dimensions
            if imported is not None:
                self.initial_values = {
                    **self.initial_values,
                    profile.key: {page.name: imported.get(page.name, {}) for page in profile.pages},
                }
            self._rebuild_project_editors(current.key, fit_arrays=True)
            config.reset_builder(current.profiles)
            editor = self._ensure_editor(current.key, profile)
            self._insert_editor_tab(editor)
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.critical(self, "Invalid configuration", str(exc))

    def _customize(self, profile: GuiProjectProfile) -> GuiProjectProfile:
        """Copy a configured project before a structural edit."""
        if profile.custom:
            return profile
        name, accepted = QInputDialog.getText(
            self, "Custom project", "Save structural changes as", text=f"{profile.name}-custom"
        )
        name = name.strip()
        if not accepted:
            raise ValueError("structural change cancelled")
        if not name or not name.replace("-", "_").isalnum():
            raise ValueError("project name may contain only letters, numbers, '-' and '_'")
        if name.lower() in self.loaded_projects and name.lower() != profile.key:
            raise ValueError(f"project '{name}' is already loaded")
        return replace(profile, name=name, key=name.lower(), title=name, source=None, custom=True)

    def _replace_project(self, profile: GuiProjectProfile) -> None:
        """Replace the active project model and rebuild its tree branch."""
        old_key = self.active_project
        if old_key is None:
            return
        item = self.project_items.pop(old_key)
        index = self.treeWidget_projectStructure.indexOfTopLevelItem(item)
        self.treeWidget_projectStructure.takeTopLevelItem(index)
        editors = self.project_editors.pop(old_key)
        config = self.project_configs.pop(old_key)
        dimensions = self.project_dimensions.pop(old_key)
        self.loaded_projects.pop(old_key)
        self.loaded_projects[profile.key] = profile
        self.project_editors[profile.key] = editors
        self.project_configs[profile.key] = config
        self.project_dimensions[profile.key] = dimensions
        self.active_project = profile.key
        self._build_tree(profile)
        self.treeWidget_projectStructure.setCurrentItem(self.project_items[profile.key])

    def _ensure_editor(self, project_key: str, profile: GuiProfile) -> ProfileTab:
        """Return a cached editor, loading its direct namelist file once."""
        path = _profile_path(self.project, profile)
        editors = self.project_editors[project_key]
        if path in editors:
            return editors[path]
        dimensions = self.project_dimensions[project_key]
        values = load_profile(self.project, profile, dimensions)
        supplied = self.initial_values.get(profile.key, {})
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
        editor = ProfileTab(self.project, profile, values, dimensions, self)
        editor.hide()
        editor.save.clicked.connect(lambda: self._save([editor]))
        editor.cancel.clicked.connect(lambda: self._cancel_profile(project_key, editor))
        editors[path] = editor
        return editor

    def _insert_editor_tab(self, editor: ProfileTab) -> None:
        """Show and activate a cached file-profile editor."""
        index = self.tabs.indexOf(editor)
        if index < 0:
            index = self.tabs.indexOf(self.plus_tab)
            self.tabs.insertTab(index, editor, editor.profile.title)
        self.tabs.setCurrentWidget(editor)

    def _rebuild_project_editors(self, key: str, *, fit_arrays: bool = False) -> None:
        """Rebuild a project's editors after dimensions or membership change."""
        old = self.project_editors[key]
        old_values = {path: editor.values() for path, editor in old.items()}
        sources = dimension_source_values(
            self.project,
            self.loaded_projects[key].profiles,
            self.project_dimensions[key],
        )
        for editor in old.values():
            self.tabs.removeTab(self.tabs.indexOf(editor))
            editor.deleteLater()
        self.project_editors[key] = {}
        for profile in self.loaded_projects[key].profiles:
            path = _profile_path(self.project, profile)
            if path in old_values:
                previous = old[path]
                values = overlay_values(old_values[path], sources.get(profile.key, {}))
                editor = ProfileTab(
                    self.project,
                    profile,
                    values,
                    self.project_dimensions[key],
                    self,
                    fit_arrays=fit_arrays,
                )
                editor.hide()
                editor.save.clicked.connect(lambda _checked=False, item=editor: self._save([item]))
                editor.cancel.clicked.connect(
                    lambda _checked=False, item=editor: self._cancel_profile(key, item)
                )
                editor.saved_values = copy.deepcopy(previous.saved_values)
                editor.saved_dimensions = dict(previous.saved_dimensions)
                self.project_editors[key][path] = editor
            else:
                self._ensure_editor(key, profile)
        self._show_project(key)

    def _cancel_profile(self, project_key: str, editor: ProfileTab) -> None:
        """Replace one editor with its last successfully saved state."""
        path = _profile_path(self.project, editor.profile)
        dimensions = self.project_dimensions[project_key]
        replacement = ProfileTab(
            self.project,
            editor.profile,
            editor.saved_values,
            dimensions,
            self,
            fit_arrays=dimensions != editor.saved_dimensions,
        )
        replacement.hide()
        replacement.save.clicked.connect(lambda: self._save([replacement]))
        replacement.cancel.clicked.connect(lambda: self._cancel_profile(project_key, replacement))
        self.project_editors[project_key][path] = replacement
        self._show_project(project_key)
        self._insert_editor_tab(replacement)
        editor.setParent(None)
        editor.deleteLater()

    def _save(self, editors: list[ProfileTab]) -> None:
        """Validate and atomically save supplied profile editors."""
        try:
            unique: dict[Path, tuple[ProfileTab, dict[str, Any]]] = {}
            collected: list[tuple[ProfileTab, dict[str, Any]]] = []
            for editor in editors:
                path = _profile_path(self.project, editor.profile)
                values = editor.values()
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
            )
            for editor, values in collected:
                editor.mark_saved(values)
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.critical(self, "Save namelist", str(exc))

    def _save_all(self) -> None:
        """Save all loaded projects without writing duplicate files twice."""
        self._save(
            [editor for editors in self.project_editors.values() for editor in editors.values()]
        )

    def _restore_all(self) -> None:
        """Restore schema defaults in every editor of the selected project."""
        for editor in self.editors.values():
            editor.restore_all()

    def _remove_tree_item(self, item: QTreeWidgetItem) -> None:
        """Confirm and apply a project, file-profile, or namelist removal."""
        kind, project_key, profile_key, page_key = item.data(0, Qt.ItemDataRole.UserRole)
        if (
            QMessageBox.question(self, "Remove item", f"Remove '{item.text(0)}'?")
            != QMessageBox.Yes
        ):
            return
        try:
            if kind == "project":
                root = self.project_items.pop(project_key)
                self.treeWidget_projectStructure.takeTopLevelItem(
                    self.treeWidget_projectStructure.indexOfTopLevelItem(root)
                )
                self.loaded_projects.pop(project_key)
                self.project_editors.pop(project_key)
                self.project_configs.pop(project_key)
                self.project_dimensions.pop(project_key)
                if self.loaded_projects:
                    self._show_project(next(iter(self.loaded_projects)))
                else:
                    while self.tabs.count():
                        widget = self.tabs.widget(0)
                        self.tabs.removeTab(0)
                        widget.hide()
                return
            current = self._customize(self.loaded_projects[project_key])
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
            # Validation intentionally occurs before replacing the visible tree.
            checked = ensure_dimension_sources(self.project, profiles)
            if checked != tuple(profiles):
                raise ValueError("this item supplies a runtime dimension used by the project")
            current = replace(current, profiles=tuple(profiles))
            save_project_profile(self.project, current)
            self._replace_project(current)
            self._rebuild_project_editors(current.key)
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.critical(self, "Remove item", str(exc))


def launch_gui(
    schemas_dir: Path | str | None = None,
    output_dir: Path | str | None = None,
    project_profiles: str
    | Mapping[str, Mapping[str, list[str]]]
    | Mapping[str, list[str]]
    | None = None,
    initial_values: Mapping[str, Any] | None = None,
    initial_dimensions: Mapping[str, int] | None = None,
) -> int:
    """Launch independently or reuse the caller's QApplication."""
    project = load_project(schemas_dir, output_dir, project_profiles)
    application = QApplication.instance()
    owns_application = application is None
    if application is None:
        application = QApplication(sys.argv[:1])
        application.setApplicationName("nml-tools")
    dialog = ConfigurationDialog(
        project, initial_values=initial_values, initial_dimensions=initial_dimensions
    )
    if not owns_application:
        _exec(dialog)
        return 0
    dialog.show()
    method = getattr(application, "exec", None) or application.exec_
    return int(method())
