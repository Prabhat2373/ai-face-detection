import os
import sys
import json
import urllib.request
import tempfile
import subprocess
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QTextBrowser, QMessageBox
)

def compare_versions(v1, v2):
    """Compares version strings. Returns >0 if v1 > v2, <0 if v1 < v2, 0 if equal."""
    p1 = [int(x) for x in str(v1).split(".") if x.isdigit()]
    p2 = [int(x) for x in str(v2).split(".") if x.isdigit()]
    # Normalize length
    for _ in range(max(len(p1), len(p2)) - len(p1)):
        p1.append(0)
    for _ in range(max(len(p1), len(p2)) - len(p2)):
        p2.append(0)
    for a, b in zip(p1, p2):
        if a != b:
            return a - b
    return 0

class UpdateCheckWorker(QThread):
    update_available = Signal(dict)  # Emits update details dict

    def __init__(self, current_version, update_url):
        super().__init__()
        self.current_version = current_version
        self.update_url = update_url

    def run(self):
        if not self.update_url:
            return
        try:
            req = urllib.request.Request(
                self.update_url,
                headers={"User-Agent": "FaceAgent-Updater"}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    latest_version = data.get("version")
                    if latest_version and compare_versions(latest_version, self.current_version) > 0:
                        self.update_available.emit(data)
        except Exception:
            # Silently ignore connection errors during background checks
            pass

class UpdateDialog(QDialog):
    def __init__(self, parent=None, update_info=None):
        super().__init__(parent)
        self.info = update_info or {}
        self.setWindowTitle("Update Available")
        self.setMinimumWidth(450)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet("""
            QDialog {
                background: #f4f6fb;
                color: #111827;
            }
            QLabel {
                color: #111827;
            }
            QPushButton {
                background: #ffffff;
                color: #111827;
                border: 1px solid #cbd5e1;
                border-radius: 7px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #f1f5f9;
                border-color: #1a73e8;
            }
            QPushButton[class="primary"] {
                background: #1a73e8;
                color: #ffffff;
                border: 1px solid #1a73e8;
            }
            QPushButton[class="primary"]:hover {
                background: #1765cc;
            }
            QProgressBar {
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                background: #ffffff;
                text-align: center;
                color: #111827;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #1a73e8;
                border-radius: 3px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        title = QLabel("New Version Available!")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #1a73e8;")
        layout.addWidget(title)

        ver_layout = QHBoxLayout()
        v_current = self.info.get("current_version", "1.0.0")
        v_latest = self.info.get("version", "Unknown")
        lbl_ver = QLabel(f"Current Version: <b>{v_current}</b> &nbsp;&nbsp;|&nbsp;&nbsp; Latest Version: <b>{v_latest}</b>")
        lbl_ver.setStyleSheet("font-size: 13px;")
        ver_layout.addWidget(lbl_ver)
        layout.addLayout(ver_layout)

        notes = self.info.get("notes")
        if notes:
            lbl_notes = QLabel("Release Notes:")
            lbl_notes.setStyleSheet("font-weight: bold;")
            layout.addWidget(lbl_notes)

            self.notes_browser = QTextBrowser()
            self.notes_browser.setPlainText(notes)
            self.notes_browser.setStyleSheet("background: #ffffff; color: #111827; border: 1px solid #cbd5e1; border-radius: 6px; padding: 8px;")
            self.notes_browser.setMaximumHeight(150)
            layout.addWidget(self.notes_browser)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #4b5563; font-size: 12px;")
        layout.addWidget(self.status_label)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_skip = QPushButton("Remind Me Later")
        self.btn_skip.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_skip)

        self.btn_update = QPushButton("Update Now")
        self.btn_update.setProperty("class", "primary")
        self.btn_update.clicked.connect(self._start_download)
        btn_layout.addWidget(self.btn_update)

        layout.addLayout(btn_layout)

    def _start_download(self):
        download_url = None
        platforms = self.info.get("platforms")
        if isinstance(platforms, dict):
            if sys.platform == "win32":
                download_url = platforms.get("windows")
            elif sys.platform == "darwin":
                download_url = platforms.get("macos")
            else:
                download_url = platforms.get("linux")

        if not download_url:
            download_url = self.info.get("url")

        if not download_url:
            QMessageBox.warning(self, "Error", "Download URL for your operating system was not found in the update manifest.")
            return

        self.btn_update.setEnabled(False)
        self.btn_skip.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("Downloading update...")

        # Run download in worker thread to prevent freezing UI
        self.downloader = DownloaderThread(download_url)
        self.downloader.progress.connect(self._on_progress)
        self.downloader.finished.connect(self._on_finished)
        self.downloader.error.connect(self._on_error)
        self.downloader.start()

    def _on_progress(self, percentage):
        self.progress_bar.setValue(percentage)

    def _on_error(self, err_msg):
        QMessageBox.critical(self, "Download Error", f"Failed to download update:\n{err_msg}")
        self.btn_update.setEnabled(True)
        self.btn_skip.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText("")

    def _on_finished(self, filepath):
        self.status_label.setText("Download complete! Launching package...")
        try:
            if sys.platform == "win32":
                os.startfile(filepath)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", filepath])
            else:
                subprocess.Popen(["xdg-open", filepath])
            QMessageBox.information(self, "Install Update", "The update package has been downloaded. Please install it to finish updating.")
            self.accept()
            sys.exit(0)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open download: {e}\nFile saved at: {filepath}")
            self.btn_update.setEnabled(True)
            self.btn_skip.setEnabled(True)

class DownloaderThread(QThread):
    progress = Signal(int)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            filename = self.url.split("/")[-1] or "update.zip"
            if not filename.endswith((".zip", ".dmg", ".exe", ".pkg", ".tar.gz")):
                filename = "FaceAgentUpdate" + os.path.splitext(filename)[1] or ".zip"
            
            temp_dir = tempfile.gettempdir()
            dest_path = os.path.join(temp_dir, filename)

            req = urllib.request.Request(
                self.url,
                headers={"User-Agent": "FaceAgent-Updater"}
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                total_size = int(response.info().get('Content-Length', 0))
                bytes_so_far = 0
                block_size = 8192

                with open(dest_path, "wb") as f:
                    while True:
                        chunk = response.read(block_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        bytes_so_far += len(chunk)
                        if total_size > 0:
                            percent = int((bytes_so_far / total_size) * 100)
                            self.progress.emit(percent)

            self.finished.emit(dest_path)
        except Exception as e:
            self.error.emit(str(e))
