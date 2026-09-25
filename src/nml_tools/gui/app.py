"""Tabbed Qt editor for namelist files."""

from __future__ import annotations

import copy
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from qtpy.QtCore import QSignalBlocker, Qt
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
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .fields import NamelistForm, _exec
from .model import (
    GuiProfile,
    GuiProject,
    _normalize_dimensions,
    _normalize_profile_values,
    create_virtual_project,
    import_profile,
    load_profile,
    load_project,
    overlay_values,
    recover_dimensions,
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
                output_root=project.output_root,
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
        return {page.name: self.forms[page.name].values() for page in self.profile.pages}

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


class ProfileConfigTab(QWidget):
    """Inputs used to activate or create file-profile tabs."""

    def __init__(
        self,
        project: GuiProject,
        dimensions: Mapping[str, int],
        parent: QWidget,
        *,
        builder: bool,
        primary: bool = False,
    ):
        super().__init__(parent)
        self.builder = builder
        self.primary = primary
        self.source_path: Path | None = None
        self.source_combo = QComboBox(self)
        self.browse = QPushButton("Browse…", self)
        self.dimension_boxes: dict[str, QSpinBox] = {}
        self.available_schemas: QListWidget | None = None
        self.selected_schemas: QListWidget | None = None
        self.profile_name: QLineEdit | None = None
        self.default_filename: QLineEdit | None = None

        layout = QVBoxLayout(self)
        source_layout = QHBoxLayout()
        source_layout.addWidget(QLabel("Load configuration", self))
        source_layout.addWidget(self.source_combo, 1)
        source_layout.addWidget(self.browse)
        layout.addLayout(source_layout)

        dimensions_group = QGroupBox("Runtime dimensions", self)
        dimensions_layout = QFormLayout(dimensions_group)
        for name, default in project.default_dimensions.items():
            box = QSpinBox(dimensions_group)
            box.setRange(1, 2_147_483_647)
            box.setValue(dimensions.get(name, default))
            dimensions_layout.addRow(name, box)
            self.dimension_boxes[name] = box
        if self.dimension_boxes:
            layout.addWidget(dimensions_group)
        else:
            dimensions_group.hide()

        if builder:
            self._build_profile_controls(project, layout)
        layout.addStretch(1)
        run_row = QHBoxLayout()
        run_row.addStretch(1)
        self.run = QPushButton("Run", self)
        run_row.addWidget(self.run)
        layout.addLayout(run_row)

    def _build_profile_controls(self, project: GuiProject, layout: QVBoxLayout) -> None:
        group = QGroupBox("File profile", self)
        group_layout = QVBoxLayout(group)
        lists = QHBoxLayout()
        available = QListWidget(group)
        selected = QListWidget(group)
        self.available_schemas = available
        self.selected_schemas = selected
        selection_mode = QAbstractItemView.ExtendedSelection
        available.setSelectionMode(selection_mode)
        selected.setSelectionMode(selection_mode)
        for page in project.namelists:
            available.addItem(ConfigurationDialog._schema_item(page.name, page.key))

        transfers = QVBoxLayout()
        transfers.addStretch(1)
        for label, source, target, move_all in (
            (">", available, selected, False),
            (">>", available, selected, True),
            ("<", selected, available, False),
            ("<<", selected, available, True),
        ):
            button = QPushButton(label, group)
            handler = (
                ConfigurationDialog._move_all if move_all else ConfigurationDialog._move_selected
            )
            button.clicked.connect(lambda _checked=False, s=source, t=target, h=handler: h(s, t))
            transfers.addWidget(button)
        transfers.addStretch(1)
        lists.addWidget(available, 1)
        lists.addLayout(transfers)
        lists.addWidget(selected, 1)
        group_layout.addLayout(lists)

        metadata = QFormLayout()
        self.profile_name = QLineEdit(group)
        self.default_filename = QLineEdit(group)
        metadata.addRow("Profile name", self.profile_name)
        metadata.addRow("Default file name", self.default_filename)
        group_layout.addLayout(metadata)
        layout.addWidget(group, 1)

    def dimensions(self) -> dict[str, int]:
        return {name: box.value() for name, box in self.dimension_boxes.items()}

    def schema_keys(self) -> list[str]:
        if self.selected_schemas is None:
            return []
        result: list[str] = []
        for index in range(self.selected_schemas.count()):
            item = self.selected_schemas.item(index)
            if item is not None:
                result.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return result


class ConfigurationDialog(QDialog):
    """Edit configured profiles and optional imported or user-created namelists."""

    def __init__(
        self,
        project: GuiProject,
        parent: QWidget | None = None,
        initial_values: Mapping[str, Any] | None = None,
        initial_dimensions: Mapping[str, int] | None = None,
    ):
        super().__init__(parent)
        self.project = project
        self.dimensions = _normalize_dimensions(
            {} if initial_dimensions is None else initial_dimensions, project
        )
        self.dimension_overrides = initial_dimensions or {}
        recovery_error = None
        try:
            self.dimensions = recover_dimensions(project, overrides=self.dimension_overrides)
        except (OSError, ValueError) as exc:
            recovery_error = str(exc)
        self.initial_values: dict[str, Any] = {}
        if initial_values is not None:
            if not isinstance(initial_values, Mapping):
                raise ValueError("initial_values must map profile names to namelist values")
            for name, values in initial_values.items():
                if not isinstance(name, str):
                    raise ValueError("initial value profile names must be strings")
                try:
                    profile = project.profile(name)
                except KeyError as exc:
                    raise ValueError(f"unknown initial value profile '{name}'") from exc
                if profile.key in self.initial_values:
                    raise ValueError(f"duplicate initial value profile '{name}'")
                self.initial_values[profile.key] = _normalize_profile_values(
                    values, profile, {**project.constants, **self.dimensions}
                )
        self.editors: dict[Path, ProfileTab] = {}
        self.config_tabs: set[ProfileConfigTab] = set()
        self.setWindowTitle("Namelist configuration")
        self.resize(1000, 700)
        root = QVBoxLayout(self)
        self.tabs = QTabWidget(self)
        self.tabs.setTabsClosable(True)
        root.addWidget(self.tabs, 1)
        self.plus_tab = QWidget(self.tabs)
        self.tabs.addTab(self.plus_tab, "+")
        self.config_tab: ProfileConfigTab | None = self._add_config(primary=True)
        for side in (QTabBar.LeftSide, QTabBar.RightSide):
            self.tabs.tabBar().setTabButton(self.tabs.indexOf(self.plus_tab), side, None)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        actions = QHBoxLayout()
        actions.addStretch(1)
        for label, callback in (
            ("Restore all", self._restore_all),
            ("Save all", self._save_all),
            ("Close", self.accept),
        ):
            button = QPushButton(label, self)
            button.clicked.connect(callback)
            actions.addWidget(button)
        root.addLayout(actions)
        if recovery_error:
            QMessageBox.critical(self, "Invalid configuration", recovery_error)
        elif project.profiles and self.config_tab is not None:
            self._run_configuration(self.config_tab)

    @staticmethod
    def _schema_item(name: str, key: str) -> QListWidgetItem:
        item = QListWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, key)
        return item

    @staticmethod
    def _move_selected(source: QListWidget, target: QListWidget) -> None:
        for item in source.selectedItems():
            target.addItem(source.takeItem(source.row(item)))

    @staticmethod
    def _move_all(source: QListWidget, target: QListWidget) -> None:
        while source.count():
            target.addItem(source.takeItem(0))

    def _add_config(self, *, primary: bool = False) -> ProfileConfigTab:
        tab = ProfileConfigTab(
            self.project,
            self.dimensions,
            self,
            builder=not primary or not self.project.profiles,
            primary=primary,
        )
        tab.source_combo.addItem("Configured profiles" if not tab.builder else "New file profile")
        for path in sorted(self.project.output_root.glob("*.nml")):
            tab.source_combo.addItem(path.name, str(path))
        tab.browse.clicked.connect(lambda: self._browse(tab))
        tab.source_combo.currentIndexChanged.connect(lambda: self._select_source(tab))
        tab.run.clicked.connect(lambda: self._run_configuration(tab))
        self.config_tabs.add(tab)
        self.tabs.insertTab(self.tabs.indexOf(self.plus_tab), tab, "Config")
        self.tabs.setCurrentWidget(tab)
        return tab

    def _tab_changed(self, index: int) -> None:
        if self.tabs.widget(index) is self.plus_tab:
            self.tabs.blockSignals(True)
            try:
                self._add_config()
            finally:
                self.tabs.blockSignals(False)

    def _close_tab(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if widget is None or widget is self.plus_tab:
            return
        try:
            dirty = isinstance(widget, ProfileTab) and (
                widget.values() != widget.saved_values
                or widget.dimensions != widget.saved_dimensions
            )
        except ValueError:
            dirty = True
        if dirty:
            if (
                QMessageBox.question(self, "Unsaved changes", "Discard changes in this profile?")
                != QMessageBox.Yes
            ):
                return
        self.editors = {path: tab for path, tab in self.editors.items() if tab is not widget}
        self._remove_tab(widget)

    def _remove_tab(self, widget: QWidget) -> None:
        with QSignalBlocker(self.tabs):
            index = self.tabs.indexOf(widget)
            self.config_tabs.discard(widget)
            self.tabs.removeTab(index)
            if widget is self.config_tab:
                self.config_tab = None
            widget.deleteLater()
            if self.tabs.count() == 1:
                self.config_tab = self._add_config(primary=True)
            elif self.tabs.currentWidget() is self.plus_tab:
                self.tabs.setCurrentIndex(min(index, self.tabs.count() - 2))

    def _browse(self, tab: ProfileConfigTab) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self, "Load namelist", str(self.project.output_root), "Namelist files (*.nml)"
        )
        if name:
            index = tab.source_combo.findData(name)
            if index < 0:
                tab.source_combo.addItem(Path(name).name, name)
                index = tab.source_combo.count() - 1
            tab.source_combo.setCurrentIndex(index)

    def _select_source(self, tab: ProfileConfigTab) -> None:
        name = tab.source_combo.currentData()
        tab.source_path = Path(name) if name else None
        if not name:
            return
        try:
            dimensions = recover_dimensions(self.project, [Path(name)], self.dimension_overrides)
            profile, _ = import_profile(self.project, Path(name), dimensions)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Invalid namelist", str(exc))
            return
        for key, size in dimensions.items():
            tab.dimension_boxes[key].setValue(size)
        if not tab.builder:
            return
        tab.profile_name.setText(profile.name)
        tab.default_filename.setText(profile.default_file)
        tab.available_schemas.clear()
        tab.selected_schemas.clear()
        selected = {page.key for page in profile.pages}
        for page in self.project.namelists:
            target = tab.selected_schemas if page.key in selected else tab.available_schemas
            target.addItem(self._schema_item(page.name, page.key))

    def _run_configuration(self, config: ProfileConfigTab) -> None:
        prepared: list[ProfileTab] = []
        allow_shrink = False
        try:
            dimensions = _normalize_dimensions(config.dimensions(), self.project)
            imported: dict[str, Any] | None = None
            if config.source_path is not None:
                profile, imported = import_profile(self.project, config.source_path, dimensions)
                profiles = (profile,)
            if config.builder:
                profiles = create_virtual_project(
                    self.project,
                    config.profile_name.text(),
                    config.default_filename.text(),
                    config.schema_keys(),
                ).profiles
                if imported is not None:
                    imported = {
                        page.name: imported.get(page.name, {}) for page in profiles[0].pages
                    }
            elif config.source_path is None:
                profiles = self.project.profiles
            for profile in profiles:
                target = (self.project.output_root / profile.default_file).resolve()
                previous = self.editors.get(target)
                if previous is not None and (config.builder or config.source_path is not None):
                    raise ValueError(f"'{target.name}' is already open")
                if (
                    previous
                    and not allow_shrink
                    and any(size < previous.dimensions[key] for key, size in dimensions.items())
                ):
                    if (
                        QMessageBox.question(
                            self,
                            "Resize arrays",
                            "Smaller dimensions will discard trailing array values. Continue?",
                        )
                        != QMessageBox.Yes
                    ):
                        for editor in prepared:
                            editor.deleteLater()
                        return
                    allow_shrink = True
                values = (
                    previous.values()
                    if previous
                    else (
                        imported
                        if imported is not None
                        else load_profile(self.project, profile, dimensions)
                    )
                )
                if previous is None:
                    values = overlay_values(values, self.initial_values.get(profile.key, {}))
                editor = ProfileTab(
                    self.project,
                    profile,
                    values,
                    dimensions,
                    self,
                    fit_arrays=previous is not None and previous.dimensions != dimensions,
                )
                editor.dimensions = dict(dimensions)
                editor.saved_dimensions = dict(
                    previous.saved_dimensions if previous else dimensions
                )
                editor.saved_values = copy.deepcopy(
                    previous.saved_values if previous else editor.values()
                )
                prepared.append(editor)
            for editor in prepared:
                self._put_editor(editor)
            self.dimensions = dimensions
            if config.builder or config.source_path is not None:
                self._remove_tab(config)
        except (OSError, ValueError, KeyError) as exc:
            for editor in prepared:
                editor.deleteLater()
            QMessageBox.critical(self, "Invalid configuration", str(exc))

    def _put_editor(self, editor: ProfileTab) -> None:
        self.tabs.blockSignals(True)
        path = (self.project.output_root / editor.profile.default_file).resolve()
        old = self.editors.get(path)
        index = self.tabs.indexOf(old) if old else self.tabs.indexOf(self.plus_tab)
        if old:
            self.tabs.removeTab(index)
            old.deleteLater()
        self.editors[path] = editor
        self.tabs.insertTab(index, editor, editor.profile.title)
        self.tabs.setCurrentWidget(editor)
        self.tabs.blockSignals(False)
        editor.save.clicked.connect(lambda: self._save([editor]))
        editor.cancel.clicked.connect(lambda: self._cancel_profile(editor))

    def _cancel_profile(self, editor: ProfileTab) -> None:
        replacement = ProfileTab(
            self.project, editor.profile, editor.saved_values, editor.saved_dimensions, self
        )
        replacement.dimensions = dict(editor.saved_dimensions)
        replacement.saved_dimensions = dict(editor.saved_dimensions)
        replacement.saved_values = copy.deepcopy(editor.saved_values)
        self._put_editor(replacement)

    def _save(self, editors: list[ProfileTab]) -> None:
        try:
            values = [(editor, editor.values()) for editor in editors]
            save_profiles(
                self.project,
                [(editor.profile, value, editor.dimensions) for editor, value in values],
            )
            for editor, value in values:
                editor.saved_values = copy.deepcopy(value)
                editor.saved_dimensions = dict(editor.dimensions)
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.critical(self, "Save namelist", str(exc))

    def _save_all(self) -> None:
        self._save(list(self.editors.values()))

    def _restore_all(self) -> None:
        for editor in self.editors.values():
            editor.restore_all()


def launch_gui(
    schemas_dir: Path | str | None = None,
    output_dir: Path | str | None = None,
    file_profiles: Mapping[str, list[str]] | None = None,
    initial_values: Mapping[str, Any] | None = None,
    initial_dimensions: Mapping[str, int] | None = None,
) -> int:
    """Launch independently or reuse the caller's QApplication."""
    project = load_project(schemas_dir, output_dir, file_profiles)
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
