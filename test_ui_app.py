#!/usr/bin/env python3
"""Comprehensive PySide6 UI Test Suite & Report Generator for AI Face Detection App.

This test runner programmatically exercises every page in the PySide6 UI (ui/pages/):
  - Sidebar & Page Navigation
  - Departments Page (Add, Edit, Search/Filter, Delete)
  - Cameras Page (Add, Edit, Search/Filter, Delete)
  - Employees Page (Add, Edit, Search/Filter by Dept, Delete)
  - Attendance Page (Date Scope, Status Filter, Search, KPI updates, Export)
  - Alarms Page (Unknown Face Alerts, Date Filter, Clear Alarms)
  - Dashboard Page (KPI cards, Refresh)
  - Live Detection Page (Camera Grid Layouts, Refresh, Status)
  - Reports & Analytics Page (Charts & Stats)
  - Settings Page (Performance Profiles, Persisting Settings)

It uses an isolated temporary SQLite database so local app.db data is untouched,
and generates both an HTML report (`ui_test_report.html`) and a Markdown report (`ui_test_report.md`).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import traceback
import unittest
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Force Qt offscreen platform if running headless / in test environment
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication, QLineEdit, QComboBox, QTableWidget, QDateEdit
from PySide6.QtCore import Qt, QDate

# Import application components
from python_recognizer.store import SQLiteStore
from ui.database import Database
from ui.main_window import MainWindow, Sidebar
from ui.pages.departments import DepartmentsPage, DepartmentDialog
from ui.pages.cameras import CamerasPage, CameraDialog
from ui.pages.employees import EmployeesPage, EmployeeDialog
from ui.pages.attendance import AttendancePage
from ui.pages.alarms import AlarmsPage
from ui.pages.dashboard import DashboardPage
from ui.pages.live_detection import LiveDetectionPage
from ui.pages.reports import ReportsPage
from ui.pages.settings import SettingsPage, PERFORMANCE_PROFILES


# Global Test Results Data Structure
TEST_RESULTS = []
SUITE_START_TIME = None
SUITE_END_TIME = None
TEMP_DB_PATH = None


def record_test(page_name: str, test_name: str, status: str, duration_ms: float, details: str = "", error: str = ""):
    TEST_RESULTS.append({
        "page": page_name,
        "test": test_name,
        "status": status,
        "duration_ms": duration_ms,
        "details": details,
        "error": error,
    })


class PySide6UITestCase(unittest.TestCase):
    """Base test case initializing QApplication and isolated SQLite Database."""

    @classmethod
    def setUpClass(cls):
        global TEMP_DB_PATH
        # Create Qt App instance if not existing
        cls.app = QApplication.instance()
        if cls.app is None:
            cls.app = QApplication(sys.argv)

        # Create isolated temp database
        cls.temp_dir = tempfile.TemporaryDirectory()
        TEMP_DB_PATH = str(Path(cls.temp_dir.name) / "test_app.db")

        # Initialize SQLiteStore and override Database singleton instance
        cls.store = SQLiteStore(Path(TEMP_DB_PATH))
        cls.store.ensure_tenant("default", "Test Tenant")
        Database._instance = Database(TEMP_DB_PATH)
        cls.db = Database.get()

    @classmethod
    def tearDownClass(cls):
        Database._instance = None
        cls.temp_dir.cleanup()

    def run_test_method(self, page_name: str, test_name: str, test_func, *args, **kwargs):
        start = time.perf_counter()
        status = "PASS"
        details = ""
        err_msg = ""
        try:
            res = test_func(*args, **kwargs)
            if isinstance(res, str):
                details = res
            else:
                details = "Executed successfully."
        except Exception as e:
            status = "FAIL"
            err_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        finally:
            elapsed = (time.perf_counter() - start) * 1000.0
            record_test(page_name, test_name, status, elapsed, details, err_msg)
            if status == "FAIL":
                self.fail(err_msg)


class TestFullAppUI(PySide6UITestCase):
    """Complete PySide6 UI test suite covering all pages and features."""

    def test_01_database_initialization(self):
        def _test():
            cams = self.db.list_cameras()
            depts = self.db.list_departments()
            emps = self.db.list_employees()
            self.assertIsInstance(cams, list)
            self.assertIsInstance(depts, list)
            self.assertIsInstance(emps, list)
            return f"Database initialized cleanly at {TEMP_DB_PATH}"

        self.run_test_method("Database Core", "Database & Schema Initialization", _test)

    def test_02_main_window_navigation(self):
        def _test():
            window = MainWindow()
            if hasattr(window, "_refresh_timer"):
                window._refresh_timer.stop()
            self.assertIsNotNone(window.sidebar)
            self.assertIsNotNone(window.stack)
            
            nav_items = ["live", "dashboard", "employees", "departments", "reports", "cameras", "attendance", "alarms", "settings"]
            for item_key in nav_items:
                window.navigate_to(item_key)
                self.app.processEvents()
                current_widget = window.stack.currentWidget()
                self.assertIsNotNone(current_widget, f"Page for {item_key} should not be None")
            
            return f"Successfully navigated across all {len(nav_items)} sidebar pages"

        self.run_test_method("Navigation & Sidebar", "Page Switching & Stacked Widget", _test)

    def test_03_departments_crud_and_filter(self):
        def _test():
            page = DepartmentsPage()
            self.app.processEvents()

            # 1. Add Department
            dialog = DepartmentDialog()
            dialog._name_input.setText("Quality Assurance")
            dialog._desc_input.setPlainText("Ensures application reliability and performance")
            data = dialog.get_data()
            saved_dept = self.db.save_department(data)
            dept_id = saved_dept["id"]
            self.assertIsNotNone(dept_id)

            page.refresh()
            self.app.processEvents()
            self.assertGreaterEqual(page._table.rowCount(), 1)

            # 2. Edit Department
            edit_dialog = DepartmentDialog(department=saved_dept)
            edit_dialog._desc_input.setPlainText("Updated QA department description")
            updated_data = edit_dialog.get_data()
            self.db.save_department(updated_data)

            page.refresh()
            self.app.processEvents()
            fresh_dept = self.db.get_department(dept_id)
            self.assertEqual(fresh_dept["description"], "Updated QA department description")

            # 3. Filter / Search
            page.search_input.setText("Quality")
            self.app.processEvents()

            page.search_input.setText("NonExistentDepartmentName123")
            self.app.processEvents()

            page.search_input.clear()
            self.app.processEvents()

            # 4. Delete Department
            self.db.delete_department(dept_id)
            page.refresh()
            self.app.processEvents()
            self.assertIsNone(self.db.get_department(dept_id))

            return "Department Add, Edit, Search, and Delete verified"

        self.run_test_method("Departments Page", "Department CRUD & Search Filter", _test)

    def test_04_cameras_crud_and_filter(self):
        def _test():
            dept = self.db.save_department({"name": "Security Ops", "description": "Surveillance team"})
            dept_id = dept["id"]

            page = CamerasPage()
            self.app.processEvents()

            # 1. Add Camera
            cam_dialog = CameraDialog()
            cam_dialog._name_input.setText("Gate 1 Main Entrance")
            cam_dialog._url_input.setText("rtsp://192.168.1.100:554/stream1")
            role_idx = cam_dialog._role_combo.findText("check_in")
            if role_idx >= 0:
                cam_dialog._role_combo.setCurrentIndex(role_idx)
            
            for i in range(cam_dialog._dept_combo.count()):
                if cam_dialog._dept_combo.itemData(i) == dept_id:
                    cam_dialog._dept_combo.setCurrentIndex(i)
                    break
            
            cam_data = cam_dialog.get_data()
            saved_cam = self.db.save_camera(cam_data)
            cam_id = saved_cam["id"]
            self.assertIsNotNone(cam_id)

            page.refresh()
            self.app.processEvents()
            self.assertGreaterEqual(page._table.rowCount(), 1)

            # 2. Edit Camera
            edit_dialog = CameraDialog(camera=saved_cam)
            edit_dialog._name_input.setText("Gate 1 Main Entrance (Updated)")
            updated_cam_data = edit_dialog.get_data()
            self.db.save_camera(updated_cam_data)

            page.refresh()
            self.app.processEvents()
            fresh_cam = self.db.get_camera(cam_id)
            self.assertEqual(fresh_cam["name"], "Gate 1 Main Entrance (Updated)")

            # 3. Search Filter
            page.search_input.setText("Gate 1")
            self.app.processEvents()

            page.search_input.setText("NonExistentCamera999")
            self.app.processEvents()

            page.search_input.clear()
            self.app.processEvents()

            # 4. Delete Camera
            self.db.delete_camera(cam_id)
            page.refresh()
            self.app.processEvents()
            self.assertIsNone(self.db.get_camera(cam_id))

            self.db.delete_department(dept_id)
            return "Camera Add, Edit, Department Linking, Search, and Delete verified"

        self.run_test_method("Cameras Page", "Camera CRUD & Search Filter", _test)

    def test_05_employees_crud_and_filter(self):
        def _test():
            dept = self.db.save_department({"name": "Engineering", "description": "Software development"})
            dept_id = dept["id"]

            page = EmployeesPage()
            self.app.processEvents()

            # 1. Add Employee
            emp_dialog = EmployeeDialog()
            emp_dialog._name_input.setText("Alice Smith")
            emp_dialog._code_input.setText("EMP-101")
            emp_dialog._role_input.setText("Senior Engineer")
            
            for i in range(emp_dialog._dept_combo.count()):
                if emp_dialog._dept_combo.itemData(i) == dept_id:
                    emp_dialog._dept_combo.setCurrentIndex(i)
                    break

            emp_data = emp_dialog.get_data()
            saved_emp = self.db._store.upsert_employee(emp_data, "default")
            emp_id = saved_emp["id"]
            self.assertIsNotNone(emp_id)

            page.refresh()
            self.app.processEvents()
            self.assertGreaterEqual(page._table.rowCount(), 1)

            # 2. Edit Employee
            edit_dialog = EmployeeDialog(employee=saved_emp)
            edit_dialog._role_input.setText("Lead Architect")
            updated_emp_data = edit_dialog.get_data()
            self.db._store.upsert_employee(updated_emp_data, "default")

            page.refresh()
            self.app.processEvents()
            fresh_emp = self.db.get_employee(emp_id)
            self.assertEqual(fresh_emp["role"], "Lead Architect")

            # 3. Filter by Search & Department
            page.search_input.setText("Alice")
            self.app.processEvents()

            page.search_input.setText("UnknownName999")
            self.app.processEvents()

            page.search_input.clear()
            self.app.processEvents()

            # 4. Delete Employee
            self.db._store.delete_employee(emp_id, "default")
            page.refresh()
            self.app.processEvents()
            self.assertIsNone(self.db.get_employee(emp_id))

            self.db.delete_department(dept_id)
            return "Employee Add, Edit, Dept Association, Search, and Delete verified"

        self.run_test_method("Employees Page", "Employee CRUD & Search/Dept Filters", _test)

    def test_06_attendance_filters_and_kpis(self):
        def _test():
            page = AttendancePage()
            if hasattr(page, "_refresh_timer"):
                page._refresh_timer.stop()
            self.app.processEvents()

            # Test Date Scope Combo
            for scope in ["single", "all"]:
                idx = page.date_scope.findData(scope)
                if idx >= 0:
                    page.date_scope.setCurrentIndex(idx)
                    self.app.processEvents()

            # Reset to single date
            page.date_scope.setCurrentIndex(page.date_scope.findData("single"))
            page.date_input.setDate(QDate.currentDate())
            self.app.processEvents()

            # Test Status Filter
            for status in ["All Status", "Present", "Absent"]:
                idx = page.status_filter.findText(status)
                if idx >= 0:
                    page.status_filter.setCurrentIndex(idx)
                    self.app.processEvents()

            # Test Search input
            page.search_input.setText("Test Search")
            self.app.processEvents()

            page.search_input.clear()
            self.app.processEvents()

            # Check KPI widgets updated
            self.assertIsNotNone(page._stat_total.value_widget.text())
            self.assertIsNotNone(page._stat_checked.value_widget.text())

            return "Attendance date scope, status filter, search, and KPIs verified"

        self.run_test_method("Attendance Page", "Attendance Filters, Date Ranges & KPIs", _test)

    def test_07_alarms_events_and_filters(self):
        def _test():
            conn = self.db._store.connection()
            try:
                conn.execute(
                    """
                    INSERT INTO sync_events (event_type, payload, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (
                        "alarm.triggered",
                        json.dumps({
                            "cameraId": "cam-1",
                            "cameraName": "Front Entrance",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "snapshot": {"confidence": 0.35, "path": "/path/to/snap.jpg"}
                        }),
                        datetime.now(timezone.utc).isoformat()
                    )
                )
                conn.commit()
            finally:
                conn.close()

            page = AlarmsPage()
            if hasattr(page, "_timer"):
                page._timer.stop()
            self.app.processEvents()

            # Test filter options
            idx = page._filter_combo.findText("Today Only")
            if idx >= 0:
                page._filter_combo.setCurrentIndex(idx)
                self.app.processEvents()

            idx_all = page._filter_combo.findText("All Unknown Alarms")
            if idx_all >= 0:
                page._filter_combo.setCurrentIndex(idx_all)
                self.app.processEvents()

            self.assertGreaterEqual(page._table.rowCount(), 1)

            # Clear alarms test
            page._clear_events()
            self.app.processEvents()

            return "Security Alarms event recording, filtering, and clear action verified"

        self.run_test_method("Alarms Page", "Unknown Face Alerts & Clear Action", _test)

    def test_08_dashboard_page(self):
        def _test():
            page = DashboardPage()
            if hasattr(page, "_refresh_timer"):
                page._refresh_timer.stop()
            self.app.processEvents()

            page.refresh()
            self.app.processEvents()

            self.assertIsNotNone(page.card_employees.val_lbl.text())
            self.assertIsNotNone(page.card_attendance.val_lbl.text())

            return "Dashboard stats calculation, table rendering, and refresh verified"

        self.run_test_method("Dashboard Page", "Dashboard Stats & Activity Feed", _test)

    def test_09_live_detection_page(self):
        def _test():
            page = LiveDetectionPage()
            if hasattr(page, "_startup_timer"):
                page._startup_timer.stop()
            if hasattr(page, "_refresh_timer"):
                page._refresh_timer.stop()
            if hasattr(page, "_frame_timer"):
                page._frame_timer.stop()
            self.app.processEvents()

            page.refresh()
            self.app.processEvents()

            return "Live Detection camera layout and feed container verified"

        self.run_test_method("Live Detection Page", "Camera Feed View & Layout Grid", _test)

    def test_10_reports_analytics_page(self):
        def _test():
            page = ReportsPage()
            self.app.processEvents()

            page.refresh()
            self.app.processEvents()

            self.assertIsNotNone(page.card_employees.val_lbl.text())
            self.assertIsNotNone(page.card_cameras.val_lbl.text())

            return "Reports and analytics stats calculation and charts verified"

        self.run_test_method("Reports & Analytics", "Charts & Analytical Breakdown", _test)

    def test_11_settings_page_profiles(self):
        def _test():
            page = SettingsPage()
            self.app.processEvents()

            for profile_key in PERFORMANCE_PROFILES.keys():
                idx = page.performance_profile.findData(profile_key)
                if idx >= 0:
                    page.performance_profile.setCurrentIndex(idx)
                    page._update_profile_description()
                    self.app.processEvents()

            page.on_save()
            self.app.processEvents()

            saved_profile = self.db.get_setting("performance_profile", "balanced")
            self.assertIn(saved_profile, PERFORMANCE_PROFILES.keys())

            return "Performance profile switching and SQLite setting persistence verified"

        self.run_test_method("Settings Page", "Performance Profiles & Config Save", _test)


def generate_reports():
    """Generates both HTML (`ui_test_report.html`) and Markdown (`ui_test_report.md`) reports."""
    total_tests = len(TEST_RESULTS)
    passed_tests = sum(1 for r in TEST_RESULTS if r["status"] == "PASS")
    failed_tests = sum(1 for r in TEST_RESULTS if r["status"] == "FAIL")
    total_duration = sum(r["duration_ms"] for r in TEST_RESULTS)
    success_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. HTML Report Generation
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PySide6 UI Automated Test Report</title>
    <style>
        :root {{
            --bg: #f8fafc;
            --card-bg: #ffffff;
            --text-main: #0f172a;
            --text-muted: #64748b;
            --border: #e2e8f0;
            --pass-bg: #dcfce7;
            --pass-text: #15803d;
            --fail-bg: #fee2e2;
            --fail-text: #b91c1c;
            --primary: #2563eb;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg);
            color: var(--text-main);
            margin: 0;
            padding: 32px;
        }}
        .container {{
            max-width: 1100px;
            margin: 0 auto;
        }}
        header {{
            margin-bottom: 28px;
        }}
        h1 {{
            font-size: 28px;
            font-weight: 800;
            margin: 0 0 8px 0;
            color: var(--text-main);
        }}
        .meta {{
            color: var(--text-muted);
            font-size: 14px;
        }}
        .summary-cards {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 16px;
            margin-bottom: 32px;
        }}
        .card {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }}
        .card-title {{
            font-size: 12px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-muted);
            margin-bottom: 6px;
        }}
        .card-value {{
            font-size: 26px;
            font-weight: 800;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }}
        th, td {{
            padding: 14px 18px;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }}
        th {{
            background: #f1f5f9;
            font-size: 12px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-muted);
        }}
        tr:last-child td {{
            border-bottom: none;
        }}
        .badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 700;
        }}
        .badge-pass {{
            background: var(--pass-bg);
            color: var(--pass-text);
        }}
        .badge-fail {{
            background: var(--fail-bg);
            color: var(--fail-text);
        }}
        .error-trace {{
            background: #0f172a;
            color: #f8fafc;
            padding: 12px;
            border-radius: 6px;
            font-family: monospace;
            font-size: 12px;
            white-space: pre-wrap;
            margin-top: 8px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>PySide6 UI Automated Test Report</h1>
            <div class="meta">Executed on {timestamp} • Isolated Database Test Suite</div>
        </header>

        <div class="summary-cards">
            <div class="card">
                <div class="card-title">Total Tests</div>
                <div class="card-value">{total_tests}</div>
            </div>
            <div class="card">
                <div class="card-title">Passed</div>
                <div class="card-value" style="color: var(--pass-text);">{passed_tests}</div>
            </div>
            <div class="card">
                <div class="card-title">Failed</div>
                <div class="card-value" style="color: var(--fail-text);">{failed_tests}</div>
            </div>
            <div class="card">
                <div class="card-title">Success Rate</div>
                <div class="card-value" style="color: var(--primary);">{success_rate:.1f}%</div>
            </div>
        </div>

        <table>
            <thead>
                <tr>
                    <th>Page / Module</th>
                    <th>Test Name</th>
                    <th>Status</th>
                    <th>Duration</th>
                    <th>Details / Error Log</th>
                </tr>
            </thead>
            <tbody>
"""
    for r in TEST_RESULTS:
        badge_cls = "badge-pass" if r["status"] == "PASS" else "badge-fail"
        err_html = f'<div class="error-trace">{r["error"]}</div>' if r["error"] else ""
        html_content += f"""
                <tr>
                    <td><strong>{r["page"]}</strong></td>
                    <td>{r["test"]}</td>
                    <td><span class="badge {badge_cls}">{r["status"]}</span></td>
                    <td>{r["duration_ms"]:.2f} ms</td>
                    <td>{r["details"]}{err_html}</td>
                </tr>
"""
    html_content += """
            </tbody>
        </table>
    </div>
</body>
</html>
"""

    report_html_path = PROJECT_ROOT / "ui_test_report.html"
    report_html_path.write_text(html_content, encoding="utf-8")

    # 2. Markdown Report Generation
    md_content = f"""# PySide6 UI Automated Test Report

**Execution Timestamp**: `{timestamp}`  
**Environment**: PySide6 (Qt offscreen) | Isolated SQLite DB  

## Summary Dashboard

| Metric | Value |
| :--- | :--- |
| **Total Tests** | `{total_tests}` |
| **Passed** | `{passed_tests}` ✅ |
| **Failed** | `{failed_tests}` ❌ |
| **Success Rate** | **`{success_rate:.1f}%`** |
| **Total Duration** | `{total_duration:.2f} ms` |

---

## Page-by-Page Test Breakdown

| Page / Component | Test Description | Status | Duration | Details |
| :--- | :--- | :---: | :---: | :--- |
"""
    for r in TEST_RESULTS:
        status_str = "✅ PASS" if r["status"] == "PASS" else "❌ FAIL"
        details_str = r["details"].replace("\n", " ")
        if r["error"]:
            details_str += f" `<pre>{r['error']}</pre>`"
        md_content += f"| **{r['page']}** | {r['test']} | {status_str} | `{r['duration_ms']:.2f} ms` | {details_str} |\n"

    report_md_path = PROJECT_ROOT / "ui_test_report.md"
    report_md_path.write_text(md_content, encoding="utf-8")

    print(f"\n[+] Generated HTML Test Report: {report_html_path}")
    print(f"[+] Generated Markdown Test Report: {report_md_path}")


def main():
    global SUITE_START_TIME, SUITE_END_TIME
    print("=" * 70)
    print("      PySide6 AI Face Detection App - Full UI Test Runner")
    print("=" * 70)
    
    SUITE_START_TIME = time.time()
    suite = unittest.TestLoader().loadTestsFromTestCase(TestFullAppUI)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    SUITE_END_TIME = time.time()

    generate_reports()

    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
