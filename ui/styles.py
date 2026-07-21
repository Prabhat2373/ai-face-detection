"""Application-wide light and dark styles for the FaceAgent desktop app."""

from __future__ import annotations


LIGHT = {
    "bg": "#f4f6fb",
    "surface": "#ffffff",
    "surface_2": "#f8fafc",
    "sidebar": "#ffffff",
    "line": "#e5e7eb",
    "text": "#111827",
    "muted": "#6b7280",
    "soft": "#eef4ff",
    "primary": "#1a73e8",
    "primary_hover": "#1765cc",
    "danger": "#dc2626",
    "success": "#16a34a",
    "warning": "#d97706",
    "table_head": "#f1f3f8",
    "selection": "#e8f0fe",
    "disabled_bg": "#eef2f7",
    "disabled_text": "#94a3b8",
    "input_hover": "#d5dce8",
}

DARK = {
    "bg": "#0b1220",
    "surface": "#111827",
    "surface_2": "#162033",
    "sidebar": "#0f172a",
    "line": "#263244",
    "text": "#e5edf8",
    "muted": "#9aa6b7",
    "soft": "#172554",
    "primary": "#3b82f6",
    "primary_hover": "#60a5fa",
    "danger": "#ef4444",
    "success": "#22c55e",
    "warning": "#f59e0b",
    "table_head": "#182235",
    "selection": "#1e3a5f",
    "disabled_bg": "#1f2937",
    "disabled_text": "#64748b",
    "input_hover": "#3a465a",
}


def build_stylesheet(mode: str = "light") -> str:
    colors = DARK if mode == "dark" else LIGHT
    return f"""
QWidget {{
    font-family: "Helvetica Neue", "Segoe UI", "Inter", sans-serif;
    color: {colors["text"]};
    background-color: transparent;
    font-size: 14px;
}}

QMainWindow, QDialog, QWidget#centralWidget, QWidget#contentShell {{
    background: {colors["bg"]};
}}

QWidget#sidebar {{
    background: {colors["sidebar"]};
    border-right: 1px solid {colors["line"]};
    min-width: 220px;
    max-width: 220px;
}}

QWidget#topBar {{
    background: {colors["surface"]};
    border-bottom: 1px solid {colors["line"]};
}}

QLabel#sidebarTitle {{
    color: {colors["text"]};
    font-size: 18px;
    font-weight: 800;
}}

QLabel#sidebarSubtitle, QLabel[class="muted"], QLabel[class="page-desc"] {{
    color: {colors["muted"]};
}}

QLabel[class="nav-section"] {{
    color: {colors["muted"]};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
}}

QPushButton[class="nav-btn"] {{
    background: transparent;
    border: none;
    border-radius: 0;
    color: {colors["text"]};
    font-size: 14px;
    font-weight: 600;
    padding: 12px 18px;
    text-align: left;
}}

QPushButton[class="nav-btn"]:hover {{
    background: {colors["surface_2"]};
}}

QPushButton[class="nav-btn"]:checked,
QPushButton[class="nav-btn active"] {{
    background: {colors["selection"]};
    color: {colors["primary"]};
    border-left: 3px solid {colors["primary"]};
}}

QFrame[class="panel"], QFrame[class="stat-card"] {{
    background: {colors["surface"]};
    border: 1px solid {colors["line"]};
    border-radius: 8px;
}}

QLabel[class="stat-label"] {{
    color: {colors["muted"]};
    font-size: 12px;
    font-weight: 700;
}}

QLabel[class="stat-value"] {{
    color: {colors["text"]};
    font-size: 26px;
    font-weight: 800;
}}

QLabel[class="section-title"], QLabel[class="page-title"] {{
    color: {colors["text"]};
    font-size: 22px;
    font-weight: 800;
}}

QPushButton {{
    background: {colors["surface_2"]};
    border: 1px solid {colors["line"]};
    border-radius: 7px;
    color: {colors["text"]};
    font-size: 14px;
    font-weight: 700;
    padding: 9px 16px;
    min-height: 22px;
}}

QPushButton:hover {{
    border-color: {colors["primary"]};
}}

QPushButton:disabled {{
    background: {colors["disabled_bg"]};
    border-color: {colors["line"]};
    color: {colors["disabled_text"]};
}}

QPushButton[class="primary"] {{
    background: {colors["primary"]};
    border-color: {colors["primary"]};
    color: #ffffff;
}}

QPushButton[class="primary"]:hover {{
    background: {colors["primary_hover"]};
}}

QPushButton[class="primary"]:disabled {{
    background: {colors["disabled_bg"]};
    border-color: {colors["line"]};
    color: {colors["disabled_text"]};
}}

QPushButton[class="danger"] {{
    background: rgba(220, 38, 38, 0.12);
    color: {colors["danger"]};
    border-color: rgba(220, 38, 38, 0.18);
}}

QPushButton[class="ghost"] {{
    background: {colors["surface"]};
    border-color: {colors["line"]};
    color: {colors["text"]};
}}

QPushButton[class="ghost"]:hover {{
    background: {colors["surface_2"]};
    color: {colors["primary"]};
}}

QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDateEdit {{
    background: {colors["surface"]};
    border: 1px solid {colors["line"]};
    border-radius: 7px;
    color: {colors["text"]};
    padding: 10px 13px;
    selection-background-color: {colors["primary"]};
    selection-color: #ffffff;
    min-height: 22px;
}}

QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QComboBox:hover, QSpinBox:hover, QDateEdit:hover {{
    border-color: {colors["input_hover"]};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QDateEdit:focus {{
    border-color: {colors["primary"]};
}}

QLineEdit::placeholder {{
    color: {colors["muted"]};
}}

QComboBox QAbstractItemView {{
    background: {colors["surface"]};
    border: 1px solid {colors["line"]};
    color: {colors["text"]};
    selection-background-color: {colors["selection"]};
}}

QComboBox::drop-down, QDateEdit::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 28px;
    border-left: 1px solid {colors["line"]};
    border-top-right-radius: 7px;
    border-bottom-right-radius: 7px;
    background: {colors["surface_2"]};
}}

QComboBox::down-arrow, QDateEdit::down-arrow {{
    image: none;
    width: 0px;
    height: 0px;
}}

QCalendarWidget, QCalendarWidget QWidget {{
    background: {colors["surface"]};
    color: {colors["text"]};
}}

QCalendarWidget QToolButton {{
    background: {colors["surface_2"]};
    border: 1px solid {colors["line"]};
    border-radius: 6px;
    color: {colors["text"]};
    padding: 6px 10px;
}}

QCalendarWidget QToolButton:hover {{
    border-color: {colors["primary"]};
    color: {colors["primary"]};
}}

QCalendarWidget QMenu {{
    background: {colors["surface"]};
    border: 1px solid {colors["line"]};
    color: {colors["text"]};
}}

QCalendarWidget QSpinBox {{
    background: {colors["surface_2"]};
    color: {colors["text"]};
    border: 1px solid {colors["line"]};
    border-radius: 6px;
    padding: 4px 8px;
}}

QCalendarWidget QAbstractItemView {{
    background: {colors["surface"]};
    alternate-background-color: {colors["surface_2"]};
    color: {colors["text"]};
    selection-background-color: {colors["primary"]};
    selection-color: #ffffff;
    outline: none;
}}

QTableWidget, QTableView {{
    background: {colors["surface"]};
    border: 1px solid {colors["line"]};
    border-radius: 8px;
    color: {colors["text"]};
    gridline-color: {colors["line"]};
    selection-background-color: {colors["selection"]};
    selection-color: {colors["text"]};
    alternate-background-color: {colors["surface_2"]};
    outline: none;
}}

QTableWidget::item, QTableView::item {{
    padding: 9px 12px;
    border-bottom: 1px solid {colors["line"]};
}}

QHeaderView::section {{
    background: {colors["table_head"]};
    color: {colors["muted"]};
    font-size: 12px;
    font-weight: 800;
    padding: 11px 12px;
    border: none;
    border-bottom: 1px solid {colors["line"]};
}}

QTableCornerButton::section {{
    background: {colors["table_head"]};
    border: none;
    border-bottom: 1px solid {colors["line"]};
}}

QScrollArea {{
    border: none;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 9px;
}}

QScrollBar::handle:vertical {{
    background: {colors["line"]};
    border-radius: 4px;
    min-height: 28px;
}}

QToolTip {{
    background: {colors["surface"]};
    color: {colors["text"]};
    border: 1px solid {colors["line"]};
    border-radius: 6px;
    padding: 6px 10px;
}}
"""


STYLESHEET = build_stylesheet("light")
