"""Reports and analytics dashboard page for the FaceAgent app."""

import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QScrollArea, QGridLayout, QDateEdit, QSpacerItem, QSizePolicy,
    QCalendarWidget,
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtCharts import (
    QChart, QChartView, QPieSeries, QBarSeries,
    QBarSet, QBarCategoryAxis, QValueAxis, QLineSeries,
    QCategoryAxis,
)
from PySide6.QtGui import QPainter

from ..database import Database

class StatCard(QFrame):
    """Simple KPI card widget."""
    def __init__(self, title: str, value: str, parent=None):
        super().__init__(parent)
        self.setProperty("class", "card")
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 16px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(12, 12, 12, 12)

        self.title_lbl = QLabel(title.upper())
        self.title_lbl.setStyleSheet("color: #6b7280; font-size: 11px; font-weight: 700; letter-spacing: 0.5px;")
        
        self.val_lbl = QLabel(value)
        self.val_lbl.setStyleSheet("color: #111827; font-size: 24px; font-weight: 800;")

        layout.addWidget(self.title_lbl)
        layout.addWidget(self.val_lbl)

    def set_value(self, val: str):
        self.val_lbl.setText(val)


def get_am_pm_label(hour: int) -> str:
    """Helper to convert 24 hour integer to AM/PM string."""
    if hour == 0:
        return "12 AM"
    elif hour < 12:
        return f"{hour} AM"
    elif hour == 12:
        return "12 PM"
    else:
        return f"{hour - 12} PM"


class ReportsPage(QWidget):
    """Analytics and Reports Dashboard Page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = Database.get()
        self._last_stats = None
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(24)

        # Header
        header = QWidget()
        hdr_layout = QHBoxLayout(header)
        hdr_layout.setContentsMargins(0, 0, 0, 0)
        
        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        title = QLabel("Reports & Analytics")
        title.setStyleSheet("font-size: 24px; font-weight: 800; color: #111827;")
        desc = QLabel("Visual statistics and activity logs")
        desc.setStyleSheet("font-size: 14px; color: #6b7280;")
        text_col.addWidget(title)
        text_col.addWidget(desc)
        hdr_layout.addLayout(text_col)
        layout.addWidget(header)

        # KPI row
        self.kpis_layout = QHBoxLayout()
        self.kpis_layout.setSpacing(16)
        self.card_employees = StatCard("Registered Employees", "0")
        self.card_cameras = StatCard("Active Cameras", "0")
        self.card_attendance = StatCard("Total Check-ins", "0")
        self.card_alarms = StatCard("Total Alarms", "0")

        self.kpis_layout.addWidget(self.card_employees)
        self.kpis_layout.addWidget(self.card_cameras)
        self.kpis_layout.addWidget(self.card_attendance)
        self.kpis_layout.addWidget(self.card_alarms)
        layout.addLayout(self.kpis_layout)

        # Charts Grid
        self.grid = QGridLayout()
        self.grid.setSpacing(20)
        
        # 1. Pie Chart - Detection Share
        self.pie_chart_view = QChartView()
        self.pie_chart_view.setRenderHint(QPainter.Antialiasing)
        self.pie_chart_view.setStyleSheet("background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; min-height: 300px;")
        self.pie_chart = QChart()
        self.pie_chart.setTitle("Detections Breakdown (Known vs Alarms)")
        self.pie_chart.legend().setAlignment(Qt.AlignRight)
        self.pie_chart.setAnimationOptions(QChart.SeriesAnimations)
        self.pie_chart_view.setChart(self.pie_chart)
        self.grid.addWidget(self.pie_chart_view, 0, 0)

        # 2. Bar Chart - Attendance by Department
        self.bar_chart_view = QChartView()
        self.bar_chart_view.setRenderHint(QPainter.Antialiasing)
        self.bar_chart_view.setStyleSheet("background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; min-height: 300px;")
        self.bar_chart = QChart()
        self.bar_chart.setTitle("Attendance by Department")
        self.bar_chart.setAnimationOptions(QChart.SeriesAnimations)
        self.bar_chart_view.setChart(self.bar_chart)
        self.grid.addWidget(self.bar_chart_view, 0, 1)

        # 3. Line Chart Container with Date Picker Header
        timeline_container = QFrame()
        timeline_container.setStyleSheet("background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px;")
        timeline_layout = QVBoxLayout(timeline_container)
        timeline_layout.setContentsMargins(16, 16, 16, 16)
        timeline_layout.setSpacing(12)

        # Control row header (Title + Date Picker)
        control_row = QHBoxLayout()
        timeline_title = QLabel("Hourly Check-in Timeline")
        timeline_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #111827;")
        
        self.date_picker = QDateEdit()
        self.date_picker.setCalendarPopup(True)
        self.date_picker.setDate(QDate.currentDate())
        self.date_picker.dateChanged.connect(self._on_date_changed)
        self.date_picker.setStyleSheet("""
            QDateEdit {
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                padding: 6px 12px;
                color: #111827;
                font-weight: 500;
                min-width: 120px;
            }
        """)
        # Explicitly style the calendar popup to ensure readable colors for dates and months
        cal = self.date_picker.calendarWidget()
        if cal is not None:
            cal.setAutoFillBackground(True)
            cal.setStyleSheet(
                "QCalendarWidget, QCalendarWidget QWidget, QCalendarWidget QTableView, QCalendarWidget QAbstractItemView { "
                "background-color: #ffffff !important; background: #ffffff !important; color: #111827 !important; }"
            )
            cal.setMinimumSize(380, 310)
            cal.setHorizontalHeaderFormat(QCalendarWidget.ShortDayNames)
            cal.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
            cal.setGridVisible(False)

        control_row.addWidget(timeline_title)
        control_row.addStretch()
        control_row.addWidget(self.date_picker)
        timeline_layout.addLayout(control_row)

        self.line_chart_view = QChartView()
        self.line_chart_view.setRenderHint(QPainter.Antialiasing)
        self.line_chart_view.setStyleSheet("border: none; min-height: 280px;")
        self.line_chart = QChart()
        # Title handled by control row
        self.line_chart.legend().setVisible(True)
        self.line_chart.legend().setAlignment(Qt.AlignBottom)
        self.line_chart.setAnimationOptions(QChart.SeriesAnimations)
        self.line_chart_view.setChart(self.line_chart)
        timeline_layout.addWidget(self.line_chart_view)

        self.grid.addWidget(timeline_container, 1, 0, 1, 2)

        layout.addLayout(self.grid)

        scroll.setWidget(container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def _on_date_changed(self, qdate):
        # Force a refresh to pull data for the new date
        self._last_stats = None
        self.refresh()

    def refresh(self):
        # 1. Update KPI Values
        stats = self.db.dashboard_stats()
        self.card_employees.set_value(str(stats.get("active_employees", 0)))
        self.card_cameras.set_value(str(stats.get("active_cameras", 0)))
        self.card_attendance.set_value(str(stats.get("total_attendance", 0)))
        
        date_str = self.date_picker.date().toString("yyyy-MM-dd")
        report_stats = self.db.get_reports_stats(date_str)
        self.card_alarms.set_value(str(report_stats.get("alarms_count", 0)))

        # Compare stats to avoid redundant redraws / animations
        current_stats = {
            "stats": stats,
            "reports": report_stats,
            "date": date_str
        }
        if self._last_stats == current_stats:
            return
        self._last_stats = current_stats

        # 2. Render Pie Chart
        self._render_pie_chart(report_stats)

        # 3. Render Bar Chart
        self._render_bar_chart(report_stats)

        # 4. Render Line Chart
        self._render_line_chart(report_stats)

    def _render_pie_chart(self, stats: dict):
        chart = self.pie_chart
        chart.removeAllSeries()

        series = QPieSeries()
        known = stats.get("known_faces_count", 0)
        alarms = stats.get("alarms_count", 0)

        if known == 0 and alarms == 0:
            series.append("No Data", 1)
        else:
            slice_known = series.append(f"Known ({known})", known)
            slice_known.setColor(Qt.GlobalColor.blue)
            slice_alarms = series.append(f"Alarms ({alarms})", alarms)
            slice_alarms.setColor(Qt.GlobalColor.red)

        chart.addSeries(series)

    def _render_bar_chart(self, stats: dict):
        chart = self.bar_chart
        chart.removeAllSeries()
        for axis in chart.axes():
            chart.removeAxis(axis)

        dept_data = stats.get("department_attendance") or {}
        
        series = QBarSeries()
        bar_set = QBarSet("Check-ins")
        
        categories = []
        if not dept_data:
            bar_set.append(0)
            categories.append("None")
        else:
            for name, count in dept_data.items():
                bar_set.append(count)
                categories.append(name)
        
        series.append(bar_set)
        chart.addSeries(series)

        axis_x = QBarCategoryAxis()
        axis_x.append(categories)
        chart.addAxis(axis_x, Qt.AlignBottom)
        series.attachAxis(axis_x)

        axis_y = QValueAxis()
        max_val = max(list(dept_data.values()) + [5])
        axis_y.setRange(0, max_val)
        chart.addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_y)

    def _render_line_chart(self, stats: dict):
        chart = self.line_chart
        chart.removeAllSeries()
        for axis in chart.axes():
            chart.removeAxis(axis)

        hourly_data = stats.get("hourly_attendance") or {}
        
        series = QLineSeries()
        series.setName("Check-in Activity")

        for hour in range(24):
            count = hourly_data.get(hour, 0)
            series.append(hour, count)

        chart.addSeries(series)

        axis_x = QCategoryAxis()
        axis_x.setRange(0, 23)
        
        # Populate with AM/PM format
        for hour in range(24):
            if hour % 2 == 0 or hour == 23:
                axis_x.append(get_am_pm_label(hour), hour)
                
        chart.addAxis(axis_x, Qt.AlignBottom)
        series.attachAxis(axis_x)

        axis_y = QValueAxis()
        max_val = max(list(hourly_data.values()) + [5])
        axis_y.setRange(0, max_val)
        chart.addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_y)
