# Application-wide light-only stylesheet for the FaceAgent desktop app.
# This file intentionally forces the light palette and avoids f-string brace
# interpolation issues by using str.format with doubled CSS braces for literals.

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

# Note: the CSS uses double braces '{{' and '}}' for literal braces because
# .format() is used to substitute color tokens like {text}, {bg}, etc.
_STYLESHEET_TEMPLATE = """
QWidget {{
    font-family: "Helvetica Neue", "Segoe UI", "Inter", sans-serif;
    color: {text};
    background-color: transparent;
    font-size: 14px;
}}

QMainWindow, QDialog, QWidget#centralWidget, QWidget#contentShell {{
    background: {bg};
}}

QWidget#sidebar {{
    background: {sidebar};
    border-right: 1px solid {line};
    min-width: 220px;
    max-width: 220px;
}}

QWidget#topBar {{
    background: {surface};
    border-bottom: 1px solid {line};
}}

/* Hide the theme toggle button (we force light theme) */
QWidget#topBar QPushButton {{
    visibility: hidden;
}}

QLabel#sidebarTitle {{
    color: {text};
    font-size: 18px;
    font-weight: 800;
}}

QLabel#sidebarSubtitle, QLabel[class="muted"], QLabel[class="page-desc"] {{
    color: {muted};
}}

QLabel[class="nav-section"] {{
    color: {muted};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
}}

/* Sidebar nav button: reserve left border so activation doesn't shift content */
QPushButton[class="nav-btn"] {{
	background: transparent;
	border: none;
	border-radius: 0;
	color: {text};
	font-size: 14px;
	font-weight: 600;
	padding: 12px 15px;
	/* Increase internal left padding so text/icons align with section labels
	   and to reserve space for the left accent (border-left). Avoid using
	   external layout margins which can create inconsistent spacing. */

	text-align: left;
	/* Slightly larger reserved accent width for a crisp visual */
	box-sizing: border-box;
	}}

QPushButton[class="nav-btn"]:hover {{
    background: {surface_2};
}}

/* Active nav button: show a left accent without shifting layout.
   The transparent left border is reserved by the base rule, so changing
   the border-left-color here provides the accent without moving content.
   Also give the active background a small radius so the visual matches
   the app's rounded panels. */
QPushButton[class="nav-btn"]:checked,
QPushButton[class="nav-btn active"] {{
	background: {selection};
	color: {primary};
	border-left-color: {primary};
	border-top-left-radius: 6px;
	border-bottom-left-radius: 6px;
}}

QFrame[class="panel"], QFrame[class="stat-card"] {{
    background: {surface};
    border: 1px solid {line};
    border-radius: 8px;
}}

QLabel[class="stat-label"] {{
    color: {muted};
    font-size: 12px;
    font-weight: 700;
}}

QLabel[class="stat-value"] {{
    color: {text};
    font-size: 26px;
    font-weight: 800;
}}

QLabel[class="section-title"], QLabel[class="page-title"] {{
    color: {text};
    font-size: 22px;
    font-weight: 800;
}}

QPushButton {{
    background: {surface_2};
    border: 1px solid {line};
    border-radius: 7px;
    color: {text};
    font-size: 14px;
    font-weight: 700;
    padding: 9px 16px;
    min-height: 22px;
}}

QPushButton:hover {{
    border-color: {primary};
}}

QPushButton:disabled {{
    background: {disabled_bg};
    border-color: {line};
    color: {disabled_text};
}}

QPushButton[class="primary"] {{
    background: {primary};
    border-color: {primary};
    color: #ffffff;
}}

QPushButton[class="primary"]:hover {{
    background: {primary_hover};
}}

QPushButton[class="primary"]:disabled {{
    background: {disabled_bg};
    border-color: {line};
    color: {disabled_text};
}}

QPushButton[class="danger"] {{
    background: rgba(220, 38, 38, 0.12);
    color: {danger};
    border-color: rgba(220, 38, 38, 0.18);
}}

QPushButton[class="ghost"] {{
    background: {surface};
    border-color: {line};
    color: {text};
}}

QPushButton[class="ghost"]:hover {{
    background: {surface_2};
    color: {primary};
}}

QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDateEdit {{
    background: {surface};
    border: 1px solid {line};
    border-radius: 7px;
    color: {text};
    padding: 10px 13px;
    selection-background-color: {primary};
    selection-color: #ffffff;
    min-height: 22px;
}}

QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QComboBox:hover, QSpinBox:hover, QDateEdit:hover {{
    border-color: {input_hover};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QDateEdit:focus {{
    border-color: {primary};
}}

QLineEdit::placeholder {{
    color: {muted};
}}

QComboBox QAbstractItemView {{
    background: {surface};
    border: 1px solid {line};
    color: {text};
    selection-background-color: {selection};
}}

QComboBox::drop-down, QDateEdit::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 28px;
    border-left: 1px solid {line};
    border-top-right-radius: 7px;
    border-bottom-right-radius: 7px;
    background: {surface_2};
}}

QComboBox::down-arrow, QDateEdit::down-arrow {{
    image: none;
    width: 0px;
    height: 0px;
}}

QCalendarWidget,
QCalendarWidget QWidget,
QCalendarWidget QTableView,
QCalendarWidget QAbstractItemView {{
    background-color: #ffffff;
    background: #ffffff;
    color: {text};
}}

QCalendarWidget {{
    border: 1px solid {line};
    border-radius: 10px;
}}

QCalendarWidget QWidget#qt_calendar_navigationbar {{
    background-color: {surface_2};
    background: {surface_2};
    border-bottom: 1px solid {line};
    border-top-left-radius: 9px;
    border-top-right-radius: 9px;
    min-height: 42px;
}}

QCalendarWidget QToolButton {{
    color: {text};
    font-weight: 700;
    font-size: 13px;
    icon-size: 18px;
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 4px 8px;
}}

QCalendarWidget QToolButton:hover {{
    background-color: {selection};
    color: {primary};
}}

QCalendarWidget QToolButton::menu-indicator {{
    image: none;
    width: 0px;
}}

QCalendarWidget QMenu {{
    background-color: #ffffff;
    color: {text};
    border: 1px solid {line};
    border-radius: 6px;
    padding: 4px;
}}

QCalendarWidget QMenu::item:selected {{
    background-color: {primary};
    color: #ffffff;
}}

QCalendarWidget QSpinBox {{
    background-color: #ffffff;
    color: {text};
    border: 1px solid {line};
    border-radius: 6px;
    font-weight: 700;
    padding: 4px 8px;
}}

QCalendarWidget QTableView {{
    background-color: #ffffff;
    border: none;
    border-radius: 0px;
    selection-background-color: {primary};
    selection-color: #ffffff;
    outline: none;
}}

QCalendarWidget QAbstractItemView:enabled {{
    background-color: #ffffff;
    color: {text};
    font-size: 12px;
    font-weight: 500;
    selection-background-color: {primary};
    selection-color: #ffffff;
    outline: none;
    border: none;
    padding: 0px;
    margin: 0px;
}}

QCalendarWidget QAbstractItemView:disabled {{
    color: {muted};
}}

QTableWidget, QTableView {{
    background: {surface};
    border: 1px solid {line};
    border-radius: 8px;
    color: {text};
    gridline-color: {line};
    selection-background-color: {selection};
    selection-color: {text};
    alternate-background-color: {surface_2};
    outline: none;
}}

QTableWidget::item, QTableView::item {{
    padding: 9px 12px;
    border-bottom: 1px solid {line};
}}

QHeaderView::section {{
    background: {table_head};
    color: {muted};
    font-size: 12px;
    font-weight: 800;
    padding: 11px 12px;
    border: none;
    border-bottom: 1px solid {line};
}}

QTableCornerButton::section {{
    background: {table_head};
    border: none;
    border-bottom: 1px solid {line};
}}

QScrollArea {{
    border: none;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 9px;
}}

QScrollBar::handle:vertical {{
    background: {line};
    border-radius: 4px;
    min-height: 28px;
}}

QToolTip {{
    background: {surface};
    color: {text};
    border: 1px solid {line};
    border-radius: 6px;
    padding: 6px 10px;
}}
"""

def build_stylesheet(mode: str = "light") -> str:
    """
    Return the application stylesheet.

    The function intentionally ignores the 'mode' parameter and always returns
    the light theme to avoid popup/rendering inconsistencies across platforms.
    """
    colors = LIGHT
    return _STYLESHEET_TEMPLATE.format(**colors)


# Precompute the stylesheet used by the UI modules.
STYLESHEET = build_stylesheet("light")
