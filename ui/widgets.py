"""Reusable custom widgets for the FaceAgent desktop app."""

from PySide6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
    QSizePolicy,
)
from PySide6.QtCore import Qt


class StatCard(QFrame):
    """A compact stat card showing a label, value, and optional unit."""

    def __init__(self, label: str, value: str = "0", unit: str = "", parent=None):
        super().__init__(parent)
        self.setProperty("class", "stat-card")
        self.setMinimumHeight(100)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        self.label_widget = QLabel(label.upper())
        self.label_widget.setProperty("class", "stat-label")

        value_layout = QHBoxLayout()
        value_layout.setSpacing(4)
        self.value_widget = QLabel(value)
        self.value_widget.setProperty("class", "stat-value")
        value_layout.addWidget(self.value_widget)

        if unit:
            self.unit_widget = QLabel(unit)
            self.unit_widget.setProperty("class", "muted")
            value_layout.addWidget(self.unit_widget, 0, Qt.AlignBottom)
        else:
            self.unit_widget = None

        value_layout.addStretch()
        layout.addWidget(self.label_widget)
        layout.addLayout(value_layout)

    def set_value(self, value: str):
        self.value_widget.setText(value)

    def set_unit(self, unit: str):
        if self.unit_widget is None:
            self.unit_widget = QLabel(unit)
            self.unit_widget.setProperty("class", "muted")
        else:
            self.unit_widget.setText(unit)


class SectionHeader(QWidget):
    """A section header with a title and optional action buttons."""

    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setProperty("class", "section-title")
        text_layout.addWidget(self.title_label)

        if subtitle:
            self.subtitle_label = QLabel(subtitle)
            self.subtitle_label.setProperty("class", "muted")
            text_layout.addWidget(self.subtitle_label)

        layout.addLayout(text_layout)
        layout.addStretch()

    def set_title(self, title: str):
        self.title_label.setText(title)

    def set_subtitle(self, subtitle: str):
        if hasattr(self, "subtitle_label"):
            self.subtitle_label.setText(subtitle)
            self.subtitle_label.show()
            return

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setProperty("class", "muted")
        self.layout().insertWidget(1, self.subtitle_label)


class NavButton(QPushButton):
    """A sidebar navigation button."""

    def __init__(self, text: str, icon_char: str = "", parent=None):
        super().__init__(parent)
        self.setText(f"  {icon_char}  {text}" if icon_char else text)
        self.setProperty("class", "nav-btn")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(38)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)


class Pill(QFrame):
    """A small colored pill/badge label."""

    COLORS = {
        "running": ("rgba(34, 197, 94, 0.15)", "#86efac"),
        "idle": ("rgba(148, 163, 184, 0.15)", "#cbd5e1"),
        "error": ("rgba(248, 113, 113, 0.15)", "#fca5a5"),
        "sync": ("rgba(96, 165, 250, 0.16)", "#bfdbfe"),
        "warning": ("rgba(251, 191, 36, 0.15)", "#fbbf24"),
        "success": ("rgba(34, 197, 94, 0.15)", "#86efac"),
    }

    def __init__(self, text: str = "", state: str = "idle", parent=None):
        super().__init__(parent)
        bg, fg = self.COLORS.get(state, self.COLORS["idle"])
        layout = QHBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(8, 4, 8, 4)
        self.label = QLabel(text)
        self.label.setStyleSheet(f"color: {fg}; font-size: 11px; font-weight: 700; background: transparent;")
        layout.addWidget(self.label)
        self.setStyleSheet(f"background: {bg}; border-radius: 10px;")

    def set_text(self, text: str):
        self.label.setText(text)

    def set_state(self, state: str):
        bg, fg = self.COLORS.get(state, self.COLORS["idle"])
        self.label.setStyleSheet(f"color: {fg}; font-size: 11px; font-weight: 700; background: transparent;")
        self.setStyleSheet(f"background: {bg}; border-radius: 10px;")


class EmptyState(QWidget):
    """A placeholder shown when there's no data."""

    def __init__(self, message: str = "No data available", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        self.label = QLabel(message)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setProperty("class", "muted")
        layout.addWidget(self.label)

    def set_message(self, message: str):
        self.label.setText(message)
