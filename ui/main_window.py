"""Main application window with sidebar navigation and SVG icons.

This is a self-contained, robust rewrite of the previous `MainWindow`.
It loads sidebar SVG icons from `ui/assets/icons/` (if present) and falls
back to text/emoji if an icon fails to load.

Notes:
- The sidebar width is fixed and nav buttons reserve left-border space so
  activating a button does not shift content.
- Theme toggling is intentionally disabled in the UI; the styles module
  forces the light palette.
"""

from __future__ import annotations

import os
from typing import Dict

from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QFrame,
)
from PySide6.QtCore import Qt, QTimer


# Import page classes (these modules exist in the project)
from .pages.dashboard import DashboardPage
from .pages.live_detection import LiveDetectionPage
from .pages.attendance import AttendancePage
from .pages.employees import EmployeesPage
from .pages.cameras import CamerasPage
from .pages.departments import DepartmentsPage
from .pages.alarms import AlarmsPage

from .widgets import NavButton
from .database import Database


# Navigation metadata: (key, label, group)
NAV_ITEMS = [
    ("live", "Live Detection", "main"),
    ("dashboard", "Dashboard", "overview"),
    ("employees", "Employees", "overview"),
    ("departments", "Departments", "overview"),
    ("cameras", "Cameras", "master"),
    ("attendance", "Attendance", "master"),
    ("alarms", "Alarms", "master"),
]


class Sidebar(QFrame):
    """Left sidebar with grouped navigation buttons and status footer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        # Keep sidebar width consistent with the stylesheet (220px)
        self.setFixedWidth(220)
        self._buttons: Dict[str, QPushButton] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 12)
        layout.setSpacing(0)

        # Header / branding
        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(22, 20, 20, 16)
        header_layout.setSpacing(2)

        brand = QLabel("FaceGuard")
        brand.setObjectName("sidebarTitle")
        header_layout.addWidget(brand)

        subtitle = QLabel("ADMIN PANEL")
        subtitle.setObjectName("sidebarSubtitle")
        header_layout.addWidget(subtitle)

        layout.addWidget(header)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)
        layout.addSpacing(8)

        # Groups and their keys
        sections = [
            ("", ["live"]),
            ("OVERVIEW", ["dashboard", "employees", "departments"]),
            ("MASTER", ["cameras", "attendance", "alarms"]),
            # ("SYSTEM", []),
        ]

        # Map keys -> labels
        item_map = {key: label for key, label, _group in NAV_ITEMS}

        # Icon filenames (relative to ui/assets/icons)
        icon_files = {
            "live": "live.svg",
            "dashboard": "dashboard.svg",
            "employees": "employees.svg",
            "departments": "departments.svg",
            "cameras": "cameras.svg",
            "attendance": "attendance.svg",
            "alarms": "alarms.svg",
            "settings": "settings.svg",
            "access": "access.svg",
            "sync": "sync.svg",
        }

        # Base icons directory (absolute)
        base_dir = os.path.join(os.path.dirname(__file__), "assets", "icons")

        for section_label, keys in sections:
            if section_label:
                nav_label = QLabel(section_label)
                nav_label.setProperty("class", "nav-section")
                nav_label.setContentsMargins(22, 16, 0, 6)
                layout.addWidget(nav_label)

            for key in keys:
                label_text = item_map.get(key, key.title())
                # resolve icon path if exists
                icon_name = icon_files.get(key, "")
                icon_path = os.path.join(base_dir, icon_name) if icon_name else ""
                if icon_path and not os.path.exists(icon_path):
                    # if the icon is missing, pass empty and NavButton will fallback
                    icon_path = ""

                # NavButton accepts: NavButton(text, icon_char="", icon_path="", parent=None)
                # btn = NavButton(label_text, "", icon_path)
                # btn.setProperty("page_key", key)
                # btn.setProperty("class", "nav-btn")
                btn = NavButton(label_text, "", icon_path)
                btn.setCheckable(True)
                btn.setAutoExclusive(True)

                btn.setProperty("page_key", key)
                btn.setProperty("class", "nav-btn")

                btn.clicked.connect(lambda _checked=False, k=key: self._on_nav_clicked(k))
                self._buttons[key] = btn
                # Do not add extra outer left margin here. Alignment is controlled
                # by the stylesheet padding-left so the active left-accent does not
                # cause content to shift. Keep a small right margin for spacing.
                btn.setContentsMargins(0, 0, 8, 0)
                layout.addWidget(btn)

        layout.addStretch()

        # Footer status
        footer = QWidget()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(20, 0, 20, 0)
        footer_layout.setSpacing(4)

        # self._status_indicator = QLabel("● Connected")
        # self._status_indicator.setProperty("class", "muted")
        # footer_layout.addWidget(self._status_indicator)

        # self._model_label = QLabel("● AI Model: Ready")
        # self._model_label.setProperty("class", "muted")
        # footer_layout.addWidget(self._model_label)

        layout.addWidget(footer)

    def _on_nav_clicked(self, page_key: str) -> None:
        """Proxy click handler to let outer code navigate (connected later)."""
        # The MainWindow connects navigation after page creation; this stub is here
        # so buttons are wired even if MainWindow hasn't registered its callbacks yet.
        # MainWindow will override these connections when it initializes pages.
        pass

    @property
    def buttons(self) -> Dict[str, QPushButton]:
        return self._buttons


class MainWindow(QMainWindow):
    """Main application window with sidebar and stacked pages."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("FaceAgent - Face Detection System")
        self.setMinimumSize(1200, 720)
        self.resize(1440, 860)

        # Theme: kept for compatibility but theme toggle is hidden (styles enforce light)
        self._theme = "light"

        # Initialize DB facade
        self.db = Database.get()

        # Central layout: sidebar + content shell
        central = QWidget()
        central.setObjectName("centralWidget")
        central_layout = QHBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        # Sidebar
        self.sidebar = Sidebar()
        central_layout.addWidget(self.sidebar)

        # Content shell with top bar and stacked pages
        content_shell = QWidget()
        content_shell.setObjectName("contentShell")
        content_layout = QVBoxLayout(content_shell)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.top_bar = self._build_top_bar()
        content_layout.addWidget(self.top_bar)

        # Page stack
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background: transparent;")
        content_layout.addWidget(self.stack, 1)
        central_layout.addWidget(content_shell, 1)

        self.setCentralWidget(central)

        # Create pages
        self._pages = {}
        self._create_pages()

        # Connect sidebar buttons to navigation (overwrite stub connections)
        for key, btn in self.sidebar.buttons.items():
            # Safely disconnect any existing handlers. `receivers()` on a SignalInstance
            # is not the correct API; calling disconnect inside a try/except keeps this
            # robust across PySide versions and avoids the TypeError previously seen.
            try:
                btn.clicked.disconnect()
            except Exception:
                # If there were no connections or the Qt binding raises, ignore and continue.
                pass
            btn.clicked.connect(lambda checked=False, k=key: self.navigate_to(k))

        # Navigate to default page
        self.navigate_to("dashboard")

        # Auto-refresh timer (refresh current page)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_current_page)
        self._refresh_timer.start(15000)

    def _build_top_bar(self) -> QWidget:
        """Build the top breadcrumb / status bar."""
        bar = QWidget()
        bar.setObjectName("topBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(24, 10, 24, 10)
        layout.setSpacing(12)

        # Breadcrumb area
        self._breadcrumb = QLabel("FaceGuard > Dashboard")
        self._breadcrumb.setProperty("class", "muted")
        layout.addWidget(self._breadcrumb)
        layout.addStretch()

        # Status pills
        status = QLabel("● System Active")
        status.setStyleSheet(
            "color: #16a34a; font-weight: 800; padding: 8px 14px; "
            "background: rgba(34,197,94,0.12); border-radius: 6px;"
        )
        layout.addWidget(status)

        # offline = QLabel("Offline Mode")
        # offline.setProperty("class", "muted")
        # layout.addWidget(offline)

        # model = QLabel("Model v2.1.4")
        # model.setStyleSheet(
        #     "color: #1a73e8; font-weight: 800; padding: 8px 14px; "
        #     "background: rgba(26,115,232,0.10); border-radius: 6px;"
        # )
        # layout.addWidget(model)

        # Theme toggle intentionally hidden to enforce light-only styling
        self.theme_btn = QPushButton("Theme")
        self.theme_btn.setVisible(False)
        layout.addWidget(self.theme_btn)

        # User details (dynamic company name loaded from license metadata)
        company_name = os.getenv("FACEAGENT_COMPANY_NAME", "").strip()
        display_text = f"Admin User\n{company_name}" if company_name else "Admin User\nHead Office"
        user = QLabel(display_text)
        user.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(user)

        return bar

    def _create_pages(self) -> None:
        """Instantiate pages and add them to the stacked widget."""
        pages_map = {
            "dashboard": DashboardPage,
            "live": LiveDetectionPage,
            "attendance": AttendancePage,
            "employees": EmployeesPage,
            "cameras": CamerasPage,
            "departments": DepartmentsPage,
            "alarms": AlarmsPage,
        }

        for key, page_class in pages_map.items():
            try:
                page = page_class()
            except Exception:
                # If a page fails to instantiate, create a minimal placeholder widget
                page = QWidget()
            self._pages[key] = page
            self.stack.addWidget(page)

    def navigate_to(self, page_key: str) -> None:
        """Switch to a page identified by page_key and trigger refresh."""
        if page_key not in self._pages:
            return

        # Update sidebar button visual state
        # for key, btn in self.sidebar.buttons.items():
        #     checked = (key == page_key)
        #     btn.setChecked(checked)
        #     btn.setProperty("class", "nav-btn active" if checked else "nav-btn")
        #     btn.style().unpolish(btn)
        #     btn.style().polish(btn)
        for key, btn in self.sidebar.buttons.items():
            btn.setChecked(key == page_key)

        # Switch page
        self.stack.setCurrentWidget(self._pages[page_key])
        current_label = next((label for key, label, _group in NAV_ITEMS if key == page_key), page_key.title())
        self._breadcrumb.setText(f"FaceGuard > {current_label}")

        # Refresh page content if it exposes refresh()
        page = self._pages[page_key]
        if hasattr(page, "refresh"):
            try:
                page.refresh()
            except Exception:
                # ignore exceptions during page refresh to keep UI responsive
                pass

    def _refresh_current_page(self) -> None:
        current = self.stack.currentWidget()
        if current and hasattr(current, "refresh"):
            try:
                current.refresh()
            except Exception:
                pass

    def closeEvent(self, event):
        """Ensure any backend or resources are cleaned up by the application (placeholder)."""
        # The main launcher/back-end process is responsible for shutting down the backend.
        super().closeEvent(event)
