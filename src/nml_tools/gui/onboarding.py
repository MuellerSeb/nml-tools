# mypy: disable-error-code="attr-defined, import-not-found, misc"
"""Single-step onboarding used by an empty GUI."""

from __future__ import annotations

from typing import Any

from qtpy.QtCore import QEvent, QObject, QPoint, QRect, Qt
from qtpy.QtWidgets import QAbstractButton, QFrame, QLabel, QVBoxLayout, QWidget


class OnboardingTip(QFrame):
    """Show one message beside, and an outline around, a target button."""

    def __init__(self, dialog: QWidget, target: QAbstractButton, text: str) -> None:
        super().__init__(dialog)
        self.dialog = dialog
        self.target = target
        self.setObjectName("onboardingTip")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet(
            "#onboardingTip { background: palette(window); "
            "border: 1px solid palette(highlight); border-radius: 4px; }"
        )
        self.outline = QFrame(dialog)
        self.outline.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.outline.setStyleSheet(
            "border: 2px solid palette(highlight); border-radius: 3px;"
        )
        self.textLabel = QLabel(text, self)
        self.textLabel.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.textLabel)
        target.clicked.connect(lambda _checked=False: self.close())
        dialog.installEventFilter(self)
        target.installEventFilter(self)

    def show_tip(self) -> None:
        """Place and show the message and target outline."""
        self._place()
        self.outline.show()
        self.show()
        self.raise_()

    def _place(self) -> None:
        target = QRect(self.target.mapTo(self.dialog, QPoint(0, 0)), self.target.size())
        self.outline.setGeometry(target.adjusted(-3, -3, 3, 3))
        self.outline.raise_()
        width = max(160, min(300, self.dialog.width() - 32))
        self.setFixedWidth(width)
        self.adjustSize()
        x = max(16, min(target.right() + 8, self.dialog.width() - width - 16))
        y = max(
            8,
            min(
                target.center().y() - self.height() // 2,
                self.dialog.height() - self.height() - 8,
            ),
        )
        self.move(x, y)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Keep the tip attached while its dialog or target changes size."""
        if self.isVisible() and event.type() in (QEvent.Type.Move, QEvent.Type.Resize):
            self._place()
        return bool(super().eventFilter(watched, event))

    def closeEvent(self, event: Any) -> None:
        """Remove the temporary outline and event filters with the tip."""
        self.dialog.removeEventFilter(self)
        self.target.removeEventFilter(self)
        self.outline.close()
        super().closeEvent(event)
