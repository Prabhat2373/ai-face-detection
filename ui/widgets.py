# -*- coding: utf-8 -*-
"""Reusable custom widgets for the FaceAgent desktop app.

This module provides a few lightweight widgets used across the UI. The
important change here is `NavButton`: it always sets a QIcon (even a
transparent placeholder) so the text layout remains stable when the
button becomes active. This prevents the label from shifting when the
active left-border is applied by the stylesheet.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QPixmap, QPainter, QFont, QColor


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
    """A sidebar navigation button that supports SVG icons and emoji fallback.

    Behavior:
      - If `icon_path` is provided and loads successfully as a QIcon, that icon
        is used.
      - Otherwise an emoji (explicit or derived from label) is rendered into
        a small pixmap and used as the icon.
      - If both fail, a transparent placeholder pixmap is used so the button
        reserves the icon area and the text will not shift when the button
        becomes active.
    """

    DEFAULT_EMOJI = {
        "live": "📡",
        "dashboard": "📊",
        "employees": "👥",
        "departments": "🏢",
        "cameras": "📷",
        "attendance": "🗓️",
        "alarms": "🔔",
        "settings": "⚙️",
        "access": "🛂",
        "sync": "🔁",
    }

    def __init__(self, text: str, icon_char: str = "", icon_path: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.setProperty("class", "nav-btn")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(38)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip(text)

        icon_size = QSize(18, 18)
        icon_set = False

        # 1) Try explicit SVG/path icon
        if icon_path:
            try:
                qicon = QIcon(icon_path)
                if not qicon.isNull():
                    self.setIcon(qicon)
                    self.setIconSize(icon_size)
                    icon_set = True
            except Exception:
                icon_set = False

        # 2) If no SVG, try emoji fallback (explicit icon_char or derived)
        if not icon_set:
            emoji = (icon_char or "").strip()
            if not emoji:
                lower = (text or "").lower()
                for key, em in self.DEFAULT_EMOJI.items():
                    if key in lower:
                        emoji = em
                        break

            if emoji:
                # Render emoji into pixmap to use as a QIcon so the button icon slot is occupied.
                try:
                    size = icon_size.width()
                    pix = QPixmap(size, size)
                    pix.fill(Qt.transparent)
                    painter = QPainter(pix)
                    try:
                        font = QFont()
                        font.setPointSize(12)
                        painter.setFont(font)
                        painter.setPen(QColor(0, 0, 0))
                        painter.drawText(pix.rect(), Qt.AlignCenter, emoji)
                    finally:
                        painter.end()
                    self.setIcon(QIcon(pix))
                    self.setIconSize(icon_size)
                    icon_set = True
                except Exception:
                    icon_set = False

        # 3) If neither SVG nor emoji available, set a transparent placeholder pixmap
        if not icon_set:
            size = icon_size.width()
            placeholder = QPixmap(size, size)
            placeholder.fill(Qt.transparent)
            self.setIcon(QIcon(placeholder))
            self.setIconSize(icon_size)

        # Set text without extra emoji spacing — icon is always in the icon slot now.
        # Leading spaces are avoided to keep alignment consistent with stylesheet.
        self.setText(text)


class Pill(QFrame):
    """A small colored pill/badge label."""

    COLORS = {
        "running": ("rgba(22, 163, 74, 0.12)", "#15803d"),
        "idle": ("rgba(100, 116, 139, 0.12)", "#475569"),
        "error": ("rgba(220, 38, 38, 0.12)", "#b91c1c"),
        "sync": ("rgba(37, 99, 235, 0.12)", "#1d4ed8"),
        "warning": ("rgba(217, 119, 6, 0.12)", "#a16207"),
        "success": ("rgba(22, 163, 74, 0.12)", "#15803d"),
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


# ── SVG Icons ──────────────────────────────────────────────────────────

EDIT_SVG_TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-square-pen"><path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.375 2.625a1 1 0 0 1 3 3l-9.013 9.014a2 2 0 0 1-.853.505l-2.873.84a.5.5 0 0 1-.62-.62l.84-2.873a2 2 0 0 1 .506-.852z"/></svg>"""

DELETE_SVG_TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-trash"><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>"""


def create_svg_icon(svg_xml: str, color: str = "#ffffff", size: int = 18) -> QIcon:
    """Create a QIcon from an SVG string with custom stroke color and size."""
    from PySide6.QtSvg import QSvgRenderer
    colored_svg = svg_xml.replace('stroke="currentColor"', f'stroke="{color}"').replace('{color}', color)
    renderer = QSvgRenderer(colored_svg.encode('utf-8'))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


def get_edit_icon(color: str = "#ffffff", size: int = 18) -> QIcon:
    """Get Lucide square-pen edit icon."""
    return create_svg_icon(EDIT_SVG_TEMPLATE, color, size)


def get_delete_icon(color: str = "#ffffff", size: int = 18) -> QIcon:
    """Get Lucide trash delete icon."""
    return create_svg_icon(DELETE_SVG_TEMPLATE, color, size)


# ── Table Empty Placeholder & Pagination ────────────────────────────────

def render_empty_table_placeholder(table, col_count: int, message: str = "No data found"):
    """Render a clean centered 'No data found' row spanning all table columns."""
    from PySide6.QtWidgets import QTableWidgetItem
    from PySide6.QtGui import QBrush, QColor, QFont
    table.clearSpans()
    table.setRowCount(1)
    table.setRowHeight(0, 90)
    table.clearContents()
    item = QTableWidgetItem(f"⚠️  {message}")
    item.setTextAlignment(Qt.AlignCenter)
    item.setFlags(Qt.NoItemFlags)
    item.setForeground(QBrush(QColor("#9badc8")))
    font = QFont()
    font.setPointSize(13)
    font.setBold(True)
    item.setFont(font)
    table.setItem(0, 0, item)
    table.setSpan(0, 0, 1, col_count)


class PaginationWidget(QWidget):
    """Reusable pagination control widget for data tables."""

    def __init__(self, parent=None, page_sizes: list[int] | None = None, on_page_change=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QComboBox
        self.on_page_change = on_page_change
        self.page_sizes = page_sizes or [10, 25, 50, 100]
        self.current_page = 1
        self.page_size = self.page_sizes[0]
        self.total_items = 0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(12)

        # Count summary e.g. "Showing 1–10 of 42 records"
        self.summary_label = QLabel("No records found")
        self.summary_label.setStyleSheet("color: #6b7d9a; font-size: 13px; font-weight: 500;")
        layout.addWidget(self.summary_label)

        layout.addStretch()

        # Page Size Selector
        page_size_layout = QHBoxLayout()
        page_size_layout.setSpacing(6)
        lbl_show = QLabel("Rows per page:")
        lbl_show.setStyleSheet("color: #475569; font-size: 13px;")
        self.size_combo = QComboBox()
        self.size_combo.setStyleSheet("""
            QComboBox {
                background: #ffffff;
                color: #111827;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 4px 8px;
                min-width: 60px;
                font-size: 12px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #ffffff;
                color: #111827;
                border: 1px solid #cbd5e1;
                selection-background-color: #1a73e8;
                selection-color: #ffffff;
            }
        """)
        for size in self.page_sizes:
            self.size_combo.addItem(str(size), size)
        self.size_combo.currentIndexChanged.connect(self._on_size_changed)
        page_size_layout.addWidget(lbl_show)
        page_size_layout.addWidget(self.size_combo)
        layout.addLayout(page_size_layout)

        # Nav Buttons
        nav_layout = QHBoxLayout()
        nav_layout.setSpacing(6)

        btn_style = """
            QPushButton {
                background: #ffffff;
                color: #111827;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 4px 14px;
                font-weight: 600;
                font-size: 12px;
                min-width: 60px;
                min-height: 28px;
            }
            QPushButton:hover:enabled {
                background: #f1f5f9;
                border-color: #1a73e8;
                color: #1a73e8;
            }
            QPushButton:disabled {
                background: #f8fafc;
                color: #94a3b8;
                border-color: #e2e8f0;
            }
        """

        self.btn_prev = QPushButton("◀ Prev")
        self.btn_prev.setStyleSheet(btn_style)
        self.btn_prev.setCursor(Qt.PointingHandCursor)
        self.btn_prev.clicked.connect(self.prev_page)
        nav_layout.addWidget(self.btn_prev)

        self.page_label = QLabel("Page 1 of 1")
        self.page_label.setStyleSheet("color: #111827; font-weight: bold; font-size: 13px; padding: 0 8px;")
        nav_layout.addWidget(self.page_label)

        self.btn_next = QPushButton("Next ▶")
        self.btn_next.setStyleSheet(btn_style)
        self.btn_next.setCursor(Qt.PointingHandCursor)
        self.btn_next.clicked.connect(self.next_page)
        nav_layout.addWidget(self.btn_next)

        layout.addLayout(nav_layout)

    def total_pages(self) -> int:
        if self.total_items == 0:
            return 1
        return max(1, (self.total_items + self.page_size - 1) // self.page_size)

    def update_state(self, total_items: int):
        self.total_items = total_items
        max_p = self.total_pages()
        if self.current_page > max_p:
            self.current_page = max_p
        if self.current_page < 1:
            self.current_page = 1

        if self.total_items == 0:
            self.summary_label.setText("No records found")
            self.page_label.setText("Page 0 of 0")
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
        else:
            start_idx = (self.current_page - 1) * self.page_size + 1
            end_idx = min(self.current_page * self.page_size, self.total_items)
            self.summary_label.setText(f"Showing {start_idx}–{end_idx} of {self.total_items} records")
            self.page_label.setText(f"Page {self.current_page} of {max_p}")
            self.btn_prev.setEnabled(self.current_page > 1)
            self.btn_next.setEnabled(self.current_page < max_p)

    def get_slice(self, items: list) -> list:
        self.update_state(len(items))
        if not items:
            return []
        start_idx = (self.current_page - 1) * self.page_size
        end_idx = start_idx + self.page_size
        return items[start_idx:end_idx]

    def prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            if self.on_page_change:
                self.on_page_change()

    def next_page(self):
        if self.current_page < self.total_pages():
            self.current_page += 1
            if self.on_page_change:
                self.on_page_change()

    def _on_size_changed(self, index: int):
        self.page_size = self.size_combo.itemData(index) or 10
        self.current_page = 1
        if self.on_page_change:
            self.on_page_change()
