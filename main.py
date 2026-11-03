from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QSettings
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QAction
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget, QDialog, QPlainTextEdit, QDialogButtonBox, QLineEdit,
    QProgressBar, QHeaderView
)

from filebutler.organizer import apply_sort_plan, build_sort_plan, has_undo, undo_last_sort
from filebutler.rules import load_rules, save_rules
from filebutler.scanner import find_duplicates, scan_folder

APP_STYLE = """
QMainWindow, QWidget { background: #101319; color: #e8edf5; font-family: Segoe UI; font-size: 10pt; }
QLabel#title { font-size: 25pt; font-weight: 750; color: #ffffff; }
QLabel#muted { color: #9aa6b7; }
QLineEdit { background: #171d26; border: 1px solid #394557; border-radius: 8px; padding: 9px 12px; color: #f2f5fa; }
QPushButton { background: #252d3a; border: 1px solid #394557; border-radius: 8px; padding: 9px 14px; }
QPushButton:hover { background: #303b4c; }
QPushButton:disabled { color: #667080; background: #1b2029; }
QPushButton#primary { background: #5578e8; border: none; font-weight: 600; }
QPushButton#primary:hover { background: #6688f2; }
QTableWidget { background: #171d26; alternate-background-color: #1b2330; border: 1px solid #303a49; gridline-color: #303a49; border-radius: 8px; }
QHeaderView::section { background: #202936; color: #b9c5d5; padding: 8px; border: none; }
QCheckBox { spacing: 8px; color: #b9c5d5; }
QPlainTextEdit { background: #171d26; color: #e8edf5; border: 1px solid #394557; border-radius: 8px; padding: 8px; font-family: Consolas; }
QProgressBar { background: #202936; border: 0; border-radius: 5px; height: 10px; text-align: center; }
QProgressBar::chunk { background: #5578e8; border-radius: 5px; }
"""

class ScanWorker(QThread):
    progress = Signal(int, str)
    completed = Signal(object, bool)
    failed = Signal(str)

    def __init__(self, folder: Path, recursive: bool):
        super().__init__()
        self.folder = folder
        self.recursive = recursive
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        try:
            files = scan_folder(
                self.folder,
                self.recursive,
                cancel_check=lambda: self._cancel_requested,
                progress_callback=lambda count, path: self.progress.emit(count, path.name),
            )
            self.completed.emit(files, self._cancel_requested)
        except Exception as error:
            self.failed.emit(str(error))


class DuplicateWorker(QThread):
    progress = Signal(int, str)
    completed = Signal(object, bool)
    failed = Signal(str)

    def __init__(self, files: list[dict]):
        super().__init__()
        self.files = files
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        try:
            groups = find_duplicates(
                self.files,
                cancel_check=lambda: self._cancel_requested,
                progress_callback=lambda count, path: self.progress.emit(count, path.name),
            )
            self.completed.emit(groups, self._cancel_requested)
        except Exception as error:
            self.failed.emit(str(error))


class RulesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sorting rules")
        self.resize(560, 520)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Edit extension → destination folder rules as JSON. Example: .psd → Design"))
        self.editor = QPlainTextEdit()
        self.editor.setPlainText(json.dumps(load_rules(), indent=2, ensure_ascii=False))
        layout.addWidget(self.editor, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        try:
            save_rules(json.loads(self.editor.toPlainText()))
        except (json.JSONDecodeError, ValueError, OSError) as error:
            QMessageBox.warning(self, "Invalid rules", str(error))
            return
        super().accept()


class DuplicateDialog(QDialog):
    def __init__(self, groups: dict[str, list[Path]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Duplicate Manager")
        self.resize(850, 500)
        layout = QVBoxLayout(self)
        total = sum(len(paths) for paths in groups.values())
        layout.addWidget(QLabel(f"Found {len(groups)} duplicate groups ({total} files). No files will be deleted."))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["SHA-256", "File", "Location"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        for digest, paths in groups.items():
            for path in paths:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(digest[:16] + "…"))
                self.table.setItem(row, 1, QTableWidgetItem(path.name))
                self.table.setItem(row, 2, QTableWidgetItem(str(path.parent)))
        layout.addWidget(self.table, 1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        layout.addWidget(close)


class FileButlerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FileButler")
        self.setWindowIconText("FileButler")
        self.settings = QSettings("FileButler", "FileButler")
        self.resize(1180, 760)
        saved_geometry = self.settings.value("window/geometry")
        if saved_geometry:
            self.restoreGeometry(saved_geometry)
        self.setAcceptDrops(True)
        self.folder: Path | None = None
        self.files: list[dict] = []
        self.visible_files: list[dict] = []
        self.plan: list[tuple[Path, Path]] = []
        self.worker: ScanWorker | None = None
        self.duplicate_worker: DuplicateWorker | None = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(13)

        title = QLabel("FileButler")
        title.setObjectName("title")
        subtitle = QLabel("A calmer place for your files. Local, private, and under your control.")
        subtitle.setObjectName("muted")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        controls = QHBoxLayout()
        self.choose_btn = QPushButton("Choose folder")
        self.choose_btn.clicked.connect(self.choose_folder)
        self.scan_btn = QPushButton("Scan folder")
        self.scan_btn.clicked.connect(self.start_scan)
        self.scan_btn.setEnabled(False)
        self.recursive = QCheckBox("Include subfolders")
        self.recursive.setChecked(self.settings.value("scan/recursive", True, type=bool))
        self.recursive.toggled.connect(lambda value: self.settings.setValue("scan/recursive", value))
        self.rules_btn = QPushButton("Sorting rules")
        self.rules_btn.clicked.connect(self.edit_rules)
        controls.addWidget(self.choose_btn)
        controls.addWidget(self.scan_btn)
        controls.addWidget(self.recursive)
        controls.addWidget(self.rules_btn)
        controls.addStretch()
        layout.addLayout(controls)

        self.path_label = QLabel("No folder selected — or drag a folder into this window")
        self.path_label.setObjectName("muted")
        layout.addWidget(self.path_label)

        self.summary = QLabel("Choose a folder to inspect its files.")
        layout.addWidget(self.summary)

        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by filename, extension or category…")
        self.search.textChanged.connect(self.filter_table)
        search_row.addWidget(self.search, 1)
        self.clear_search = QPushButton("Clear")
        self.clear_search.clicked.connect(self.search.clear)
        search_row.addWidget(self.clear_search)
        layout.addLayout(search_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["File", "Category", "Size", "Current location"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.duplicates_btn = QPushButton("Duplicate Manager")
        self.duplicates_btn.clicked.connect(self.show_duplicates)
        self.export_btn = QPushButton("Export report")
        self.export_btn.clicked.connect(self.export_report)
        self.preview_btn = QPushButton("Preview sorting")
        self.preview_btn.clicked.connect(self.preview_sorting)
        self.undo_btn = QPushButton("Undo last sorting")
        self.undo_btn.clicked.connect(self.undo_sorting)
        self.undo_btn.setEnabled(False)
        self.cancel_btn = QPushButton("Cancel scan")
        self.cancel_btn.clicked.connect(self.cancel_scan)
        self.cancel_btn.hide()
        self.apply_btn = QPushButton("Apply sorting")
        self.apply_btn.setObjectName("primary")
        self.apply_btn.clicked.connect(self.apply_sorting)
        for button in (self.duplicates_btn, self.export_btn, self.preview_btn, self.undo_btn):
            footer.addWidget(button)
        footer.addStretch()
        footer.addWidget(self.cancel_btn)
        footer.addWidget(self.apply_btn)
        layout.addLayout(footer)
        self.statusBar().showMessage("Ready")
        self._create_menus()
        last_folder = self.settings.value("folder/last", "", type=str)
        if last_folder and Path(last_folder).is_dir():
            self.set_folder(Path(last_folder))

    def _create_menus(self):
        file_menu = self.menuBar().addMenu("&File")
        choose_action = QAction("Choose folder…", self)
        choose_action.triggered.connect(self.choose_folder)
        file_menu.addAction(choose_action)
        export_action = QAction("Export report…", self)
        export_action.triggered.connect(self.export_report)
        file_menu.addAction(export_action)
        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        help_menu = self.menuBar().addMenu("&Help")
        about_action = QAction("About FileButler", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def show_about(self):
        QMessageBox.about(
            self, "About FileButler",
            "<h2>FileButler 1.0.0</h2>"
            "<p>A local-first file organizer for Windows.</p>"
            "<p>Scan, review, and organize files with a preview before moving. "
            "Duplicate detection only reports matches; it never deletes files.</p>"
            "<p><b>Privacy:</b> file processing stays on this computer.</p>"
        )

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            if url.isLocalFile():
                path = Path(url.toLocalFile())
                if path.is_dir():
                    self.set_folder(path)
                    self.start_scan()
                    event.acceptProposedAction()
                    return
                if path.is_file():
                    self.set_folder(path.parent)
                    self.start_scan()
                    event.acceptProposedAction()
                    return

    def set_folder(self, folder: Path):
        self.folder = folder.expanduser().resolve()
        self.settings.setValue("folder/last", str(self.folder))
        self.path_label.setText(str(self.folder))
        self.scan_btn.setEnabled(True)
        self.files, self.visible_files, self.plan = [], [], []
        self.table.setRowCount(0)
        self.summary.setText("Folder selected. Scan it to see a file overview.")
        self.refresh_undo_state()

    def choose_folder(self):
        selected = QFileDialog.getExistingDirectory(self, "Choose a folder")
        if selected:
            self.set_folder(Path(selected))

    def set_scanning(self, scanning: bool):
        self.scan_btn.setEnabled(not scanning and self.folder is not None)
        self.choose_btn.setEnabled(not scanning)
        self.rules_btn.setEnabled(not scanning)
        self.duplicates_btn.setEnabled(not scanning)
        self.preview_btn.setEnabled(not scanning and bool(self.files))
        self.apply_btn.setEnabled(not scanning and bool(self.plan))
        self.cancel_btn.setVisible(scanning)
        self.progress.setVisible(scanning)

    def start_scan(self):
        if not self.folder or (self.worker and self.worker.isRunning()):
            return
        self.plan = []
        self.apply_btn.setEnabled(False)
        self.preview_btn.setEnabled(False)
        self.worker = ScanWorker(self.folder, self.recursive.isChecked())
        self.worker.progress.connect(self.on_scan_progress)
        self.worker.completed.connect(self.on_scan_completed)
        self.worker.failed.connect(self.on_scan_failed)
        self.set_scanning(True)
        self.statusBar().showMessage("Scanning folder…")
        self.worker.start()

    def cancel_scan(self):
        active = self.worker if self.worker and self.worker.isRunning() else None
        duplicate_active = self.duplicate_worker if self.duplicate_worker and self.duplicate_worker.isRunning() else None
        if active:
            active.cancel()
            self.cancel_btn.setEnabled(False)
            self.statusBar().showMessage("Stopping scan…")
        elif duplicate_active:
            duplicate_active.cancel()
            self.cancel_btn.setEnabled(False)
            self.statusBar().showMessage("Stopping duplicate scan…")

    def on_scan_progress(self, count: int, filename: str):
        self.progress.setFormat(f"Scanned {count} files — {filename}")

    def on_scan_completed(self, files: list, cancelled: bool):
        self.files = files
        self.set_scanning(False)
        self.cancel_btn.setEnabled(True)
        rules = load_rules()
        for item in self.files:
            item["category"] = rules.get(item["suffix"], item["category"])
        self.filter_table()
        total_bytes = sum(item["size"] for item in self.files)
        state = "Scan cancelled" if cancelled else "Scan complete"
        self.statusBar().showMessage(f"{state}: {len(self.files)} files")
        self.preview_btn.setEnabled(bool(self.files))
        self.refresh_undo_state()

    def on_scan_failed(self, message: str):
        self.set_scanning(False)
        self.cancel_btn.setEnabled(True)
        self.preview_btn.setEnabled(bool(self.files))
        QMessageBox.warning(self, "Scan failed", message)
        self.statusBar().showMessage("Scan failed")

    def filter_table(self):
        query = self.search.text().strip().casefold()
        if query:
            self.visible_files = [
                item for item in self.files
                if query in item["name"].casefold()
                or query in item["suffix"].casefold()
                or query in item["category"].casefold()
                or query in str(item["path"].parent).casefold()
            ]
        else:
            self.visible_files = list(self.files)

        self.table.setRowCount(len(self.visible_files))
        for row, item in enumerate(self.visible_files):
            values = [item["name"], item["category"], self.format_size(item["size"]), str(item["path"].parent)]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if col == 3:
                    cell.setToolTip(value)
                self.table.setItem(row, col, cell)
        total_bytes = sum(item["size"] for item in self.files)
        self.summary.setText(
            f"{len(self.files)} files · {self.format_size(total_bytes)} · "
            f"Showing {len(self.visible_files)}"
        )

    def edit_rules(self):
        if RulesDialog(self).exec() == QDialog.DialogCode.Accepted:
            self.plan = []
            if self.folder:
                self.start_scan()

    def preview_sorting(self):
        if not self.folder or not self.files:
            QMessageBox.information(self, "Nothing to preview", "Scan a folder first.")
            return
        self.plan = build_sort_plan(self.files, self.folder, load_rules())
        if not self.plan:
            QMessageBox.information(self, "Already organized", "No files need sorting.")
            return
        lines = [f"{src.name}  →  {dst.parent.name}/{dst.name}" for src, dst in self.plan[:35]]
        if len(self.plan) > 35:
            lines.append(f"... and {len(self.plan) - 35} more")
        QMessageBox.information(self, f"Sorting preview ({len(self.plan)} files)", "No files have been moved yet.\n\n" + "\n".join(lines))
        self.apply_btn.setEnabled(True)

    def apply_sorting(self):
        if not self.plan or not self.folder:
            QMessageBox.information(self, "Preview first", "Scan a folder and preview sorting first.")
            return
        answer = QMessageBox.question(
            self, "Confirm sorting",
            f"Move {len(self.plan)} files into category folders?\n\nFileButler will not delete files or overwrite existing files.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            moved = apply_sort_plan(self.plan)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            QMessageBox.warning(self, "Sorting partially stopped", f"Some files may already have moved. The operation journal was retained where possible.\n\n{error}")
            self.start_scan()
            return
        self.statusBar().showMessage(f"Moved {len(moved)} files")
        self.start_scan()

    def undo_sorting(self):
        if not self.folder:
            return
        answer = QMessageBox.question(
            self, "Undo last sorting",
            "Restore files to their original locations? FileButler will refuse to overwrite files or restore files whose contents changed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            restored = undo_last_sort(self.folder)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            QMessageBox.warning(self, "Undo stopped", str(error))
            self.start_scan()
            return
        QMessageBox.information(self, "Undo complete", f"Restored {len(restored)} files.")
        self.start_scan()

    def refresh_undo_state(self):
        self.undo_btn.setEnabled(bool(self.folder and has_undo(self.folder)))

    def show_duplicates(self):
        if not self.files:
            QMessageBox.information(self, "Scan first", "Scan a folder before checking duplicates.")
            return
        if self.duplicate_worker and self.duplicate_worker.isRunning():
            return
        self.duplicate_worker = DuplicateWorker(list(self.files))
        self.duplicate_worker.progress.connect(self.on_duplicate_progress)
        self.duplicate_worker.completed.connect(self.on_duplicates_completed)
        self.duplicate_worker.failed.connect(self.on_duplicates_failed)
        self.duplicates_btn.setEnabled(False)
        self.scan_btn.setEnabled(False)
        self.choose_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("Cancel check")
        self.cancel_btn.show()
        self.progress.setRange(0, 0)
        self.progress.show()
        self.statusBar().showMessage("Checking duplicate content…")
        self.duplicate_worker.start()

    def on_duplicate_progress(self, count: int, filename: str):
        self.progress.setFormat(f"Hashed {count} files — {filename}")

    def on_duplicates_completed(self, groups: dict, cancelled: bool):
        self.progress.hide()
        self.progress.setFormat("")
        self.duplicates_btn.setEnabled(True)
        self.scan_btn.setEnabled(self.folder is not None)
        self.choose_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("Cancel scan")
        self.cancel_btn.hide()
        self.statusBar().showMessage("Duplicate scan cancelled" if cancelled else "Duplicate scan complete")
        if cancelled:
            return
        if not groups:
            QMessageBox.information(self, "No duplicates", "No identical files were found.")
            return
        DuplicateDialog(groups, self).exec()

    def on_duplicates_failed(self, message: str):
        self.progress.hide()
        self.duplicates_btn.setEnabled(True)
        self.scan_btn.setEnabled(self.folder is not None)
        self.choose_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("Cancel scan")
        self.cancel_btn.hide()
        QMessageBox.warning(self, "Duplicate scan failed", message)
        self.statusBar().showMessage("Duplicate scan failed")

    def export_report(self):
        if not self.files:
            QMessageBox.information(self, "Nothing to export", "Scan a folder first.")
            return
        target, _ = QFileDialog.getSaveFileName(self, "Save scan report", "filebutler-report.json", "JSON files (*.json)")
        if not target:
            return
        report = [{
            "name": item["name"], "path": str(item["path"]),
            "category": item["category"], "size_bytes": item["size"],
            "modified_timestamp": item["modified"]
        } for item in self.files]
        try:
            output = Path(target)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except OSError as error:
            QMessageBox.warning(self, "Export failed", f"Could not save the report.\n\n{error}")
            return
        self.statusBar().showMessage(f"Report saved: {target}")

    @staticmethod
    def format_size(size: int) -> str:
        value = float(size)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if value < 1024 or unit == "TB":
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} TB"

    def closeEvent(self, event):
        self.settings.setValue("window/geometry", self.saveGeometry())
        for worker in (self.worker, self.duplicate_worker):
            if worker and worker.isRunning():
                worker.cancel()
                worker.wait()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("FileButler")
    app.setOrganizationName("FileButler")
    app.setApplicationVersion("1.0.0-rc.2")
    app.setStyleSheet(APP_STYLE)
    window = FileButlerWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
