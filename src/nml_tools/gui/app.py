"""Qt application and dialogs for the nml-tools GUI."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass, replace
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
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .fields import NamelistForm, _exec
from .model import (
    GuiProfile,
    GuiProject,
    append_virtual_profile,
    create_virtual_project,
    discover_configuration_files,
    document_dimensions,
    empty_document,
    load_document,
    load_namelist_document,
    load_project,
    merge_initial_dimensions,
    merge_initial_values,
    project_for_document,
    profile_values,
    save_profile,
    save_profiles,
)


@dataclass
class DocumentContext:
    """One independently loaded and saved namelist document."""

    source_path: Path | None
    json_path: Path
    project: GuiProject
    document: dict[str, Any]
    dimensions: dict[str, int]


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
        self.context: DocumentContext | None = None
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

    def _build_profile_controls(
        self, project: GuiProject, layout: QVBoxLayout
    ) -> None:
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
                ConfigurationDialog._move_all
                if move_all
                else ConfigurationDialog._move_selected
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
    """Single-dialog editor for independent namelist documents."""

    def __init__(
        self,
        project: GuiProject,
        parent: QWidget | None = None,
        initial_values: Mapping[str, Any] | None = None,
        initial_dimensions: Mapping[str, int] | None = None,
    ):
        super().__init__(parent)
        self.base_project = project
        self._changing_tabs = False
        self.config_tabs: set[ProfileConfigTab] = set()
        self.profile_tabs: dict[str, ProfileTab] = {}
        self.profile_contexts: dict[ProfileTab, DocumentContext] = {}

        self.setWindowTitle("Namelist configuration")
        self.resize(1000, 700)
        root = QVBoxLayout(self)
        self.tabs = QTabWidget(self)
        self.tabs.setTabsClosable(True)
        root.addWidget(self.tabs, 1)

        self.config_tab = self._insert_config_tab(
            builder=not project.profiles,
            primary=True,
            index=0,
        )
        self.plus_tab = QWidget(self.tabs)
        self.tabs.addTab(self.plus_tab, "+")
        self._hide_plus_close_button()
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabCloseRequested.connect(self._close_tab)

        self.json_combo = self.config_tab.source_combo
        self.browse = self.config_tab.browse
        self.dimension_boxes = self.config_tab.dimension_boxes
        self.run = self.config_tab.run
        if self.config_tab.builder:
            self.available_schemas = self.config_tab.available_schemas
            self.selected_schemas = self.config_tab.selected_schemas
            self.profile_name = self.config_tab.profile_name
            self.default_filename = self.config_tab.default_filename

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

        self._populate_configuration_files(self.config_tab, prefer_nml=True)
        self._load_selected_configuration(self.config_tab)
        context = self.config_tab.context
        assert context is not None
        if initial_dimensions is not None:
            context.document = merge_initial_dimensions(
                context.document, initial_dimensions, self.base_project
            )
            context.dimensions = document_dimensions(
                context.document, self.base_project
            )
        if initial_values is not None:
            self._prepare_virtual_initial_values(context, initial_values)
            context.document = merge_initial_values(
                context.document, initial_values, context.project
            )
        self._set_tab_dimensions(self.config_tab, context.dimensions)
        self._sync_profile_controls(self.config_tab)

    def _insert_config_tab(
        self,
        *,
        builder: bool,
        primary: bool = False,
        index: int | None = None,
    ) -> ProfileConfigTab:
        tab = ProfileConfigTab(
            self.base_project,
            self.base_project.default_dimensions,
            self.tabs,
            builder=builder,
            primary=primary,
        )
        tab.run.clicked.connect(lambda: self._run_configuration(tab))
        tab.browse.clicked.connect(lambda: self._browse_configuration(tab))
        tab.source_combo.currentIndexChanged.connect(
            lambda _selected: self._load_selected_configuration(tab)
        )
        if index is None:
            index = self.tabs.indexOf(self.plus_tab)
        self.tabs.insertTab(index, tab, "Config")
        self.config_tabs.add(tab)
        return tab

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

    def _tab_changed(self, index: int) -> None:
        if self._changing_tabs or self.tabs.widget(index) is not self.plus_tab:
            return
        self._changing_tabs = True
        tab = self._insert_config_tab(builder=True)
        self._populate_configuration_files(tab, prefer_nml=True)
        self._load_selected_configuration(tab)
        self._hide_plus_close_button()
        self.tabs.setCurrentWidget(tab)
        self._changing_tabs = False

    def _hide_plus_close_button(self) -> None:
        index = self.tabs.indexOf(self.plus_tab)
        if index < 0:
            return
        positions = getattr(QTabBar, "ButtonPosition", QTabBar)
        self.tabs.tabBar().setTabButton(index, positions.LeftSide, None)
        self.tabs.tabBar().setTabButton(index, positions.RightSide, None)

    def _close_tab(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if widget is None or widget is self.plus_tab:
            return
        self._changing_tabs = True
        if isinstance(widget, ProfileConfigTab):
            self.config_tabs.discard(widget)
        elif isinstance(widget, ProfileTab):
            self._forget_profile_tab(widget)
        self.tabs.removeTab(index)
        widget.deleteLater()
        self._changing_tabs = False
        self._set_profile_actions_enabled(bool(self.profile_tabs))
        self._hide_plus_close_button()
        self._refresh_configuration_files()
        if self.tabs.currentWidget() is self.plus_tab:
            self._tab_changed(self.tabs.indexOf(self.plus_tab))

    def _context_paths(self, context: DocumentContext) -> set[Path]:
        paths = {context.json_path.resolve()}
        if context.source_path is not None:
            paths.add(context.source_path.resolve())
        paths.update(
            (context.project.output_root / profile.default_file).resolve()
            for profile in context.project.profiles
        )
        return paths

    def _claimed_paths(self, exclude: ProfileConfigTab | None = None) -> set[Path]:
        paths: set[Path] = set()
        for tab in self.config_tabs:
            if tab is not exclude and tab.context is not None:
                paths.update(self._context_paths(tab.context))
        for context in self.profile_contexts.values():
            paths.update(self._context_paths(context))
        return paths

    @staticmethod
    def _input_paths(path: Path) -> set[Path]:
        paths = {path.resolve()}
        if path.suffix.lower() == ".nml":
            paths.add(path.with_suffix(".json").resolve())
        return paths

    def _populate_configuration_files(
        self,
        tab: ProfileConfigTab,
        selected: Path | None = None,
        *,
        prefer_nml: bool = False,
    ) -> None:
        combo = tab.source_combo
        claimed = self._claimed_paths(tab)
        paths = [
            path
            for path in discover_configuration_files(self.base_project)
            if not (self._input_paths(path) & claimed)
        ]
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("No configuration file", None)
        for path in paths:
            combo.addItem(path.name, str(path.resolve()))
        if selected is not None:
            selected_text = str(selected.resolve())
            index = combo.findData(selected_text)
            if index < 0 and not (self._input_paths(selected) & claimed):
                combo.addItem(str(selected), selected_text)
                index = combo.count() - 1
            combo.setCurrentIndex(max(index, 0))
        elif prefer_nml:
            canonical = self.base_project.output_root / "nml.json"
            index = combo.findData(str(canonical.resolve()))
            combo.setCurrentIndex(max(index, 0))
        combo.blockSignals(False)

    def _load_selected_configuration(self, tab: ProfileConfigTab) -> None:
        combo = tab.source_combo
        previous = tab.context
        raw_path = combo.currentData()
        try:
            if raw_path is None:
                if tab.primary:
                    context = DocumentContext(
                        None,
                        (self.base_project.output_root / "nml.json").resolve(),
                        self.base_project,
                        empty_document(self.base_project),
                        dict(self.base_project.default_dimensions),
                    )
                else:
                    context = None
            else:
                path = Path(raw_path).resolve()
                if self._input_paths(path) & self._claimed_paths(tab):
                    raise ValueError(f"configuration '{path.name}' is already open")
                if path.suffix.lower() == ".json":
                    document = load_document(path, self.base_project)
                    project = project_for_document(self.base_project, document)
                    json_path = path
                elif path.suffix.lower() == ".nml":
                    project, document = load_namelist_document(
                        path, self.base_project, tab.dimensions()
                    )
                    json_path = path.with_suffix(".json")
                else:
                    raise ValueError("configuration must be a .json or .nml file")
                context = DocumentContext(
                    path,
                    json_path,
                    project,
                    document,
                    document_dimensions(document, self.base_project),
                )
                if self._context_paths(context) & self._claimed_paths(tab):
                    raise ValueError(
                        f"configuration '{path.name}' conflicts with an open document"
                    )
        except (OSError, UnicodeError, ValueError) as exc:
            QMessageBox.critical(self, "Load configuration", str(exc))
            source = previous.source_path if previous is not None else None
            self._populate_configuration_files(tab, source)
            if previous is None and tab.primary:
                tab.context = DocumentContext(
                    None,
                    (self.base_project.output_root / "nml.json").resolve(),
                    self.base_project,
                    empty_document(self.base_project),
                    dict(self.base_project.default_dimensions),
                )
            return

        tab.context = context
        dimensions = (
            context.dimensions
            if context is not None
            else self.base_project.default_dimensions
        )
        self._set_tab_dimensions(tab, dimensions)
        self._sync_profile_controls(tab)
        self._refresh_configuration_files(tab)
        self.tabs.setCurrentWidget(tab)

    def _refresh_configuration_files(
        self, exclude: ProfileConfigTab | None = None
    ) -> None:
        for tab in self.config_tabs:
            if tab is exclude:
                continue
            source = tab.context.source_path if tab.context is not None else None
            self._populate_configuration_files(tab, source)

    def _sync_profile_controls(self, tab: ProfileConfigTab) -> None:
        if not tab.builder:
            return
        project = tab.context.project if tab.context is not None else None
        profile = project.profiles[0] if project and project.profiles else None
        self._set_profile_controls(
            tab,
            profile.name if profile else "",
            profile.default_file if profile else "",
            [page.key for page in profile.pages] if profile else [],
        )

    def _set_profile_controls(
        self,
        tab: ProfileConfigTab,
        name: str,
        default_file: str,
        selected_keys: list[str],
    ) -> None:
        if (
            tab.profile_name is None
            or tab.default_filename is None
            or tab.available_schemas is None
            or tab.selected_schemas is None
        ):
            return
        tab.profile_name.setText(name)
        tab.default_filename.setText(default_file)
        selected = {key.lower() for key in selected_keys}
        tab.available_schemas.clear()
        tab.selected_schemas.clear()
        by_key = {page.key: page for page in self.base_project.namelists}
        for key in selected_keys:
            page = by_key.get(key.lower())
            if page is not None:
                tab.selected_schemas.addItem(self._schema_item(page.name, page.key))
        for page in self.base_project.namelists:
            if page.key not in selected:
                tab.available_schemas.addItem(self._schema_item(page.name, page.key))

    def _prepare_virtual_initial_values(
        self,
        context: DocumentContext,
        initial_values: Mapping[str, Any],
    ) -> None:
        if context.project.profiles or len(initial_values) != 1:
            return
        name, values = next(iter(initial_values.items()))
        if not isinstance(name, str) or not isinstance(values, Mapping):
            return
        context.project = create_virtual_project(
            self.base_project, name, f"{name}.nml", values
        )

    def _browse_configuration(self, tab: ProfileConfigTab) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Load namelist configuration",
            str(self.base_project.output_root),
            "Namelist configuration (*.json *.nml);;JSON files (*.json);;Namelist files (*.nml)",
        )
        if not filename:
            return
        path = Path(filename).resolve()
        self._populate_configuration_files(tab, path)
        self._load_selected_configuration(tab)

    @staticmethod
    def _set_tab_dimensions(
        tab: ProfileConfigTab, dimensions: Mapping[str, int]
    ) -> None:
        for name, box in tab.dimension_boxes.items():
            box.blockSignals(True)
            box.setValue(dimensions[name])
            box.blockSignals(False)

    def _run_configuration(self, tab: ProfileConfigTab | None = None) -> None:
        tab = tab or self.config_tab
        try:
            dimensions = tab.dimensions()
            context = tab.context
            if context is None:
                project = replace(self.base_project, profiles=())
                document = empty_document(self.base_project)
            else:
                project = context.project
                document = context.document
                if (
                    context.source_path is not None
                    and context.source_path.suffix.lower() == ".nml"
                ):
                    project, document = load_namelist_document(
                        context.source_path,
                        self.base_project,
                        dimensions,
                    )

            if tab.builder and not project.profiles:
                assert tab.profile_name is not None
                assert tab.default_filename is not None
                project = append_virtual_profile(
                    project,
                    tab.profile_name.text(),
                    tab.default_filename.text(),
                    tab.schema_keys(),
                    reserved_profiles=self.base_project.profiles,
                )
                if context is None:
                    profile_path = self.base_project.output_root / project.profiles[0].default_file
                    context = DocumentContext(
                        None,
                        profile_path.with_suffix(".json"),
                        project,
                        document,
                        dimensions,
                    )
            if context is None:
                raise ValueError("select a configuration or create a file profile")
            document = merge_initial_dimensions(
                document, dimensions, self.base_project
            )
            context = DocumentContext(
                context.source_path,
                context.json_path,
                project,
                document,
                dimensions,
            )
            if self._context_paths(context) & self._claimed_paths(tab):
                raise ValueError(
                    f"configuration '{context.json_path.name}' conflicts with "
                    "an open document"
                )
            tab.context = context
        except (OSError, UnicodeError, ValueError, KeyError) as exc:
            QMessageBox.critical(self, "Invalid configuration", str(exc))
            return

        added: list[ProfileTab] = []
        for profile in context.project.profiles:
            existing = self._find_profile_tab(context, profile.key)
            if existing is not None:
                continue
            added.append(
                self._add_profile_tab(
                    context,
                    profile,
                    profile_values(context.document, profile),
                    fit_arrays=True,
                )
            )
        self._remove_config_tab(tab)
        self._set_profile_actions_enabled(bool(self.profile_tabs))
        if added:
            self.tabs.setCurrentWidget(added[-1])

    def _remove_config_tab(self, tab: ProfileConfigTab) -> None:
        index = self.tabs.indexOf(tab)
        self.config_tabs.discard(tab)
        if index >= 0:
            self.tabs.removeTab(index)
        tab.deleteLater()
        self._hide_plus_close_button()
        self._refresh_configuration_files()

    def _find_profile_tab(
        self, context: DocumentContext, profile_key: str
    ) -> ProfileTab | None:
        for tab, owner in self.profile_contexts.items():
            if owner is context and tab.profile.key == profile_key:
                return tab
        return None

    def _profile_tab_key(
        self, context: DocumentContext, profile: GuiProfile
    ) -> str:
        if profile.key not in self.profile_tabs:
            return profile.key
        base = f"{profile.key}@{context.json_path}"
        key = base
        index = 2
        while key in self.profile_tabs:
            key = f"{base}#{index}"
            index += 1
        return key

    def _add_profile_tab(
        self,
        context: DocumentContext,
        profile: GuiProfile,
        values: Mapping[str, Any],
        *,
        fit_arrays: bool,
        index: int | None = None,
    ) -> ProfileTab:
        editor = ProfileTab(
            context.project,
            profile,
            values,
            context.dimensions,
            self,
            fit_arrays=fit_arrays,
        )
        editor.cancel.clicked.connect(lambda: self._cancel_profile(editor))
        editor.save.clicked.connect(lambda: self._save_profile(editor))
        if index is None:
            self.tabs.insertTab(self.tabs.indexOf(self.plus_tab), editor, profile.title)
        else:
            self.tabs.insertTab(index, editor, profile.title)
        self.profile_tabs[self._profile_tab_key(context, profile)] = editor
        self.profile_contexts[editor] = context
        self._hide_plus_close_button()
        return editor

    def _forget_profile_tab(self, editor: ProfileTab) -> None:
        self.profile_contexts.pop(editor, None)
        for key, tab in list(self.profile_tabs.items()):
            if tab is editor:
                self.profile_tabs.pop(key)
                break

    def _replace_profile_tab(
        self,
        old: ProfileTab,
        values: Mapping[str, Any],
    ) -> ProfileTab:
        context = self.profile_contexts[old]
        profile = old.profile
        index = self.tabs.indexOf(old)
        self.tabs.removeTab(index)
        self._forget_profile_tab(old)
        old.deleteLater()
        return self._add_profile_tab(
            context,
            profile,
            values,
            fit_arrays=True,
            index=index,
        )

    def _cancel_profile(self, editor: ProfileTab) -> None:
        context = self.profile_contexts[editor]
        replacement = self._replace_profile_tab(
            editor,
            profile_values(context.document, editor.profile),
        )
        self.tabs.setCurrentWidget(replacement)

    def _save_profile(self, editor: ProfileTab) -> None:
        context = self.profile_contexts[editor]
        try:
            context.document = save_profile(
                context.project,
                context.document,
                editor.profile,
                editor.values(),
                context.dimensions,
                context.json_path,
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
            grouped: dict[int, tuple[DocumentContext, dict[str, Any]]] = {}
            for tab in self.profile_tabs.values():
                context = self.profile_contexts[tab]
                values = grouped.setdefault(id(context), (context, {}))[1]
                values[tab.profile.key] = tab.values()
            for context, values in grouped.values():
                context.document = save_profiles(
                    context.project,
                    context.document,
                    values,
                    context.dimensions,
                    context.json_path,
                )
        except (OSError, UnicodeError, ValueError, KeyError) as exc:
            QMessageBox.critical(self, "Save configuration", str(exc))
            return
        self._saved()

    def _saved(self) -> None:
        self._refresh_configuration_files()

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
