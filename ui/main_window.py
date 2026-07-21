"""Main application window with sidebar navigation and stacked pages."""

import os

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QStackedWidget, QFrame, QApplication,
)
from PySide6.QtCore import Qt, QTimer

from .pages.dashboard import DashboardPage
from .pages.live_detection import LiveDetectionPage
from .pages.attendance import AttendancePage
from .pages.employees import EmployeesPage
from .pages.cameras import CamerasPage
from .pages.departments import DepartmentsPage
from .pages.alarms import AlarmsPage
from .widgets import NavButton
from .database import Database
from .styles import build_stylesheet


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
    """Sidebar with grouped navigation buttons."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(230)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 12)
        layout.setSpacing(0)

        # Header / branding
        header = QWidget()
        header.setObjectName("sidebarHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(22, 20, 20, 16)
        header_layout.setSpacing(2)

        brand = QLabel("FaceGuard")
        brand.setObjectName("sidebarTitle")
        header_layout.addWidget(brand)

        subtitle = QLabel("ADMIN PANEL")
        subtitle.setObjectName("sidebarSubtitle")
        header_layout.addWidget(subtitle)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        layout.addWidget(header)
        layout.addWidget(separator)

        layout.addSpacing(8)

        self._buttons = {}
        sections = [
            ("", ["live"]),
            ("OVERVIEW", ["dashboard", "employees", "departments"]),
            ("MASTER", ["cameras", "attendance", "alarms"]),
            ("SYSTEM", []),
        ]
        item_map = {key: label for key, label, _group in NAV_ITEMS}
        for section_label, keys in sections:
            if section_label:
                nav_label = QLabel(section_label)
                nav_label.setProperty("class", "nav-section")
                nav_label.setContentsMargins(22, 16, 0, 6)
                layout.addWidget(nav_label)
            for key in keys:
                btn = NavButton(item_map[key])
                btn.setProperty("page_key", key)
                btn.setProperty("class", "nav-btn")
                self._buttons[key] = btn
                layout.addWidget(btn)

        layout.addStretch()

        # Bottom status
        footer = QWidget()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(20, 0, 20, 0)
        footer_layout.setSpacing(4)

        self._status_indicator = QLabel("● Connected")
        self._status_indicator.setProperty("class", "muted")
        footer_layout.addWidget(self._status_indicator)

        model_label = QLabel("● AI Model: Ready")
        model_label.setProperty("class", "muted")
        footer_layout.addWidget(model_label)

        layout.addWidget(footer)

    @property
    def buttons(self) -> dict:
        return self._buttons


class MainWindow(QMainWindow):
    """Main application window with sidebar and page navigation."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("FaceAgent - Face Detection System")
        self.setMinimumSize(1200, 720)
        self.resize(1440, 860)
        self._theme = "dark" if os.getenv("FACEAGENT_THEME", "light").lower() == "dark" else "light"

        # Initialize database
        self.db = Database.get()

        # Central widget
        central = QWidget()
        central.setObjectName("centralWidget")
        central_layout = QHBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        # Sidebar
        self.sidebar = Sidebar()
        central_layout.addWidget(self.sidebar)

        content_shell = QWidget()
        content_shell.setObjectName("contentShell")
        content_layout = QVBoxLayout(content_shell)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.top_bar = self._build_top_bar()
        content_layout.addWidget(self.top_bar)

        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background: transparent;")
        content_layout.addWidget(self.stack, 1)
        central_layout.addWidget(content_shell, 1)

        self.setCentralWidget(central)

        # Create pages
        self._pages = {}
        self._create_pages()

        # Connect nav buttons
        for key, btn in self.sidebar.buttons.items():
            btn.clicked.connect(lambda checked=False, k=key: self.navigate_to(k))

        # Navigate to dashboard by default
        self.navigate_to("dashboard")

        # Auto-refresh timer
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_current_page)
        self._refresh_timer.start(15000)

    def _build_top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("topBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(24, 10, 24, 10)
        layout.setSpacing(12)

        self._breadcrumb = QLabel("FaceGuard > Dashboard")
        self._breadcrumb.setProperty("class", "muted")
        layout.addWidget(self._breadcrumb)
        layout.addStretch()

        status = QLabel("● System Active")
        status.setStyleSheet("color: #16a34a; font-weight: 800; padding: 8px 14px; background: rgba(34,197,94,0.12); border-radius: 6px;")
        layout.addWidget(status)

        offline = QLabel("Offline Mode")
        offline.setProperty("class", "muted")
        layout.addWidget(offline)

        model = QLabel("Model v2.1.4")
        model.setStyleSheet("color: #1a73e8; font-weight: 800; padding: 8px 14px; background: rgba(26,115,232,0.10); border-radius: 6px;")
        layout.addWidget(model)

        self.theme_btn = QPushButton("Dark")
        self.theme_btn.setText("Light" if self._theme == "dark" else "Dark")
        self.theme_btn.setProperty("class", "ghost")
        self.theme_btn.clicked.connect(self.toggle_theme)
        layout.addWidget(self.theme_btn)

        user = QLabel("Admin User\nHead Office")
        user.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(user)
        return bar

    def toggle_theme(self):
        self._theme = "dark" if self._theme == "light" else "light"
        QApplication.instance().setStyleSheet(build_stylesheet(self._theme))
        self.theme_btn.setText("Light" if self._theme == "dark" else "Dark")

    def _create_pages(self):
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
            page = page_class()
            self._pages[key] = page
            self.stack.addWidget(page)

    def navigate_to(self, page_key: str):
        if page_key not in self._pages:
            return

        # Update nav button states – stylesheet handles the visuals
        for key, btn in self.sidebar.buttons.items():
            btn.setChecked(key == page_key)
            btn.setProperty("class", "nav-btn active" if key == page_key else "nav-btn")
            # Force style recalculation
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        self.stack.setCurrentWidget(self._pages[page_key])
        current_label = next((label for key, label, _group in NAV_ITEMS if key == page_key), page_key.title())
        self._breadcrumb.setText(f"FaceGuard > {current_label}")

        # Refresh the page content
        page = self._pages[page_key]
        if hasattr(page, 'refresh'):
            page.refresh()

    def _refresh_current_page(self):
        current = self.stack.currentWidget()
        if current and hasattr(current, 'refresh'):
            current.refresh()
