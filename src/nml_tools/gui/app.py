"""Qt application and dialogs for the nml-tools GUI."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from qtpy.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .fields import NamelistForm, _accepted, _exec
from .model import (
    GuiProfile,
    GuiProject,
    discover_json_files,
    document_dimensions,
    empty_document,
    load_document,
    load_project,
    profile_is_saved,
    profile_values,
    render_profile,
    save_profile,
)


class ProfileDialog(QDialog):
    """Modal ordered page editor for one configured file profile."""

    def __init__(
        self,
        project: GuiProject,
        profile: GuiProfile,
        values: dict[str, Any],
        dimensions: dict[str, int],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(profile.title)
        self.resize(850, 650)
        self.profile = profile
        self.project = project
        self.dimensions = dimensions
        self._values: dict[str, Any] | None = None
        sizes = {**project.constants, **dimensions}

        root = QVBoxLayout(self)
        if profile.description:
            description = QLabel(profile.description, self)
            description.setWordWrap(True)
            root.addWidget(description)

        self.selector = QComboBox(self)
        self.stack = QStackedWidget(self)
        self.forms: dict[str, NamelistForm] = {}
        for page in profile.pages:
            title = page.schema.get("title")
            self.selector.addItem(str(title or page.name), page.key)
            form = NamelistForm(page.schema, values.get(page.name), sizes)
            scroll = QScrollArea(self)
            scroll.setWidgetResizable(True)
            scroll.setWidget(form)
            self.stack.addWidget(scroll)
            self.forms[page.name] = form
        self.selector.currentIndexChanged.connect(self.stack.setCurrentIndex)
        root.addWidget(self.selector)
        root.addWidget(self.stack, 1)

        buttons = QHBoxLayout()
        self.back = QPushButton("Back", self)
        self.next = QPushButton("Next", self)
        restore = QPushButton("Restore defaults", self)
        cancel = QPushButton("Cancel", self)
        save = QPushButton("Save", self)
        self.back.clicked.connect(
            lambda: self.selector.setCurrentIndex(self.selector.currentIndex() - 1)
        )
        self.next.clicked.connect(
            lambda: self.selector.setCurrentIndex(self.selector.currentIndex() + 1)
        )
        restore.clicked.connect(self._restore_page)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._accept_values)
        buttons.addWidget(self.back)
        buttons.addWidget(self.next)
        buttons.addStretch(1)
        buttons.addWidget(restore)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)
        self.selector.currentIndexChanged.connect(self._update_navigation)
        self._update_navigation(0)

    @property
    def values(self) -> dict[str, Any]:
        if self._values is None:
            raise RuntimeError("profile dialog has not been accepted")
        return self._values

    def _restore_page(self) -> None:
        page = self.profile.pages[self.selector.currentIndex()]
        self.forms[page.name].reset()

    def _accept_values(self) -> None:
        try:
            values = {
                page.name: self.forms[page.name].values() for page in self.profile.pages
            }
            render_profile(
                self.project,
                self.profile,
                values,
                self.dimensions,
            )
        except (ValueError, KeyError) as exc:
            QMessageBox.critical(self, "Invalid value", str(exc))
            return
        self._values = values
        self.accept()

    def _update_navigation(self, index: int) -> None:
        self.back.setEnabled(index > 0)
        self.next.setEnabled(index < len(self.profile.pages) - 1)


class ConfigurationDialog(QDialog):
    """Project configuration chooser and dynamic file-profile launcher."""

    def __init__(self, project: GuiProject, parent: QWidget | None = None):
        super().__init__(parent)
        self.project = project
        self.document = empty_document(project)
        self.source_path: Path | None = None
        self._loading = False
        self.dimension_boxes: dict[str, QSpinBox] = {}
        self.status_labels: dict[str, QLabel] = {}

        self.setWindowTitle("Namelist configuration")
        self.resize(680, 400)
        root = QVBoxLayout(self)

        configuration = QGroupBox("Namelist configuration", self)
        configuration_layout = QVBoxLayout(configuration)
        source_layout = QHBoxLayout()
        source_layout.addWidget(QLabel("Load configuration", self))
        self.json_combo = QComboBox(self)
        self.browse = QPushButton("Browse…", self)
        source_layout.addWidget(self.json_combo, 1)
        source_layout.addWidget(self.browse)
        configuration_layout.addLayout(source_layout)

        self.dimensions_group = QGroupBox("Runtime dimensions", self)
        self.dimensions_layout = QFormLayout(self.dimensions_group)
        for name, default in project.default_dimensions.items():
            box = QSpinBox(self)
            box.setRange(1, 2_147_483_647)
            box.setValue(default)
            box.valueChanged.connect(self._mark_dirty)
            self.dimensions_layout.addRow(name, box)
            self.dimension_boxes[name] = box
        if self.dimension_boxes:
            configuration_layout.addWidget(self.dimensions_group)
        else:
            self.dimensions_group.hide()

        profiles = QGroupBox("File profiles", self)
        profiles_layout = QFormLayout(profiles)
        for profile in project.profiles:
            button = QPushButton(profile.title, self)
            button.setToolTip(profile.description or profile.default_file)
            button.clicked.connect(lambda _checked=False, item=profile: self._edit_profile(item))
            status = QLabel(self)
            self.status_labels[profile.key] = status
            row = QWidget(self)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(button, 1)
            row_layout.addWidget(status)
            profiles_layout.addRow(profile.name, row)
        configuration_layout.addWidget(profiles)
        root.addWidget(configuration, 1)

        close = QPushButton("Close", self)
        close.clicked.connect(self.accept)
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_row.addWidget(close)
        root.addLayout(close_row)

        self.browse.clicked.connect(self._browse_json)
        self._populate_json_files()
        self.json_combo.currentIndexChanged.connect(self._load_selected_json)
        self._load_selected_json(self.json_combo.currentIndex())

    def _populate_json_files(self, selected: Path | None = None) -> None:
        self._loading = True
        self.json_combo.clear()
        paths = discover_json_files(self.project)
        if not paths:
            self.json_combo.addItem("nml.json (new)", None)
        else:
            for path in paths:
                self.json_combo.addItem(path.name, str(path))
        if selected is not None:
            selected_text = str(selected.resolve())
            index = self.json_combo.findData(selected_text)
            if index < 0:
                label = selected.name if selected.parent == self.project.root else str(selected)
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
            self.document = empty_document(self.project)
        else:
            path = Path(raw_path)
            try:
                document = load_document(path, self.project)
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
                self._refresh_status()
                return
            self.source_path = path
            self.document = document
        self._set_dimensions(document_dimensions(self.document, self.project))
        self._refresh_status()

    def _browse_json(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Load namelist JSON",
            str(self.project.root),
            "JSON files (*.json)",
        )
        if not filename:
            return
        path = Path(filename).resolve()
        self._populate_json_files(path)
        self._load_selected_json(self.json_combo.currentIndex())

    def _set_dimensions(self, dimensions: dict[str, int]) -> None:
        for name, box in self.dimension_boxes.items():
            box.blockSignals(True)
            box.setValue(dimensions[name])
            box.blockSignals(False)

    def _current_dimensions(self) -> dict[str, int]:
        return {name: box.value() for name, box in self.dimension_boxes.items()}

    def _mark_dirty(self, _value: int) -> None:
        self._refresh_status()

    def _refresh_status(self) -> None:
        dimensions_match = self._current_dimensions() == document_dimensions(
            self.document, self.project
        )
        for profile in self.project.profiles:
            self._set_status(
                self.status_labels[profile.key],
                dimensions_match and profile_is_saved(self.project, self.document, profile),
            )

    @staticmethod
    def _set_status(label: QLabel, saved: bool) -> None:
        label.setText("Saved" if saved else "Not saved")
        label.setStyleSheet(f"color: {'#22863a' if saved else '#b31d28'}; font-weight: bold;")

    def _edit_profile(self, profile: GuiProfile) -> None:
        dimensions = self._current_dimensions()
        editor = ProfileDialog(
            self.project,
            profile,
            profile_values(self.document, profile),
            dimensions,
            self,
        )
        if _exec(editor) != _accepted(editor):
            return
        try:
            self.document = save_profile(
                self.project,
                self.document,
                profile,
                editor.values,
                dimensions,
            )
        except (OSError, UnicodeError, ValueError, KeyError) as exc:
            QMessageBox.critical(self, "Save configuration", str(exc))
            return
        self.source_path = self.project.root / "nml.json"
        self._populate_json_files(self.source_path)
        self._refresh_status()


def launch_gui(project_dir: Path | str | None = None) -> int:
    """Launch the GUI for a directory containing ``nml-config.toml``."""
    project = load_project(project_dir)
    application = QApplication.instance()
    owns_application = application is None
    if application is None:
        application = QApplication(sys.argv[:1])
        application.setApplicationName("nml-tools")
    dialog = ConfigurationDialog(project)
    if not owns_application:
        _exec(dialog)
        return 0
    dialog.show()
    method = getattr(application, "exec", None)
    if method is None:
        method = application.exec_
    return int(method())
