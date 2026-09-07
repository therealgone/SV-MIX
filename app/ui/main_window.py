"""Main application window: frameless Nocturne-themed chrome hosting the
Setup and Studio screens."""

import os
import shutil
import tempfile
import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox, QStackedWidget, QVBoxLayout, QWidget

import pipeline
from ..worker import ExportWorker, MixWorker
from .setup_screen import SetupScreen
from .studio_screen import StudioScreen
from .title_bar import TitleBar


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SVMixer")
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.resize(1000, 660)
        self.setMinimumSize(860, 580)

        self._worker = None
        self._export_worker = None
        self._current_mix = None
        self._cancelled = False
        self._pending_skipped = []
        self._temp_dir = tempfile.mkdtemp(prefix="mashup_preview_")
        self._preview_path = None

        root = QWidget()
        root.setObjectName("root")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.title_bar = TitleBar()
        self.title_bar.home_clicked.connect(self._on_home_clicked)
        self.title_bar.minimize_clicked.connect(self.showMinimized)
        self.title_bar.maximize_clicked.connect(self._toggle_maximize)
        self.title_bar.close_clicked.connect(self.close)
        root_layout.addWidget(self.title_bar)

        self.setup_screen = SetupScreen()
        self.studio_screen = StudioScreen()

        self.stack = QStackedWidget()
        self.stack.addWidget(self.setup_screen)
        self.stack.addWidget(self.studio_screen)
        root_layout.addWidget(self.stack, 1)

        self.setCentralWidget(root)

        self.setup_screen.mix_requested.connect(self.start_processing)
        self.studio_screen.save_requested.connect(self.save_mix)
        self.studio_screen.new_mix_requested.connect(self.start_new_mix)
        self.studio_screen.cancel_requested.connect(self.cancel_processing)

    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _on_home_clicked(self):
        if self.stack.currentWidget() is self.studio_screen:
            if self._worker is not None:
                self.cancel_processing()
            else:
                self.start_new_mix()

    # ----------------------------------------------------------------
    # Processing
    # ----------------------------------------------------------------

    def start_processing(self, filepaths, mode, target_duration_sec, hook_type):
        self._cancelled = False
        mode_label = pipeline.MODE_LABELS.get(mode, mode)
        hook_label = pipeline.HOOK_TYPE_LABELS.get(hook_type, hook_type).replace(" Hook", "")
        minutes_target = max(1, round(target_duration_sec / 60))
        self.studio_screen.start(mode_label, hook_label, minutes_target, len(filepaths))
        self.title_bar.set_crumb("Session · mixing")
        self.stack.setCurrentWidget(self.studio_screen)

        self._worker = MixWorker(filepaths, mode, target_duration_sec, hook_type)
        self._worker.progress.connect(self.studio_screen.set_progress)
        self._worker.finished_ok.connect(self._on_processing_finished)
        self._worker.failed.connect(self._on_processing_failed)
        self._worker.start()

    def cancel_processing(self):
        self._cancelled = True
        self.studio_screen.stop_playback()
        self.setup_screen.reset()
        self.title_bar.set_crumb("Session · untitled")
        self.stack.setCurrentWidget(self.setup_screen)

    def _on_processing_finished(self, result):
        self._worker = None
        if self._cancelled:
            return

        if result["mix"] is None:
            details = "\n".join(f"- {name}: {reason}" for name, reason in result["skipped"])
            QMessageBox.warning(
                self,
                "Nothing to mix",
                "None of the selected files could be processed.\n\n" + details,
            )
            self.title_bar.set_crumb("Session · untitled")
            self.stack.setCurrentWidget(self.setup_screen)
            return

        self._current_mix = result["mix"]
        self._pending_skipped = result["skipped"]
        self.studio_screen.set_progress("Preparing preview...", 100)

        # A fresh filename each time -- QMediaPlayer can skip reloading if
        # given the same QUrl it already has loaded, so reusing one fixed
        # preview path would silently keep playing a stale/earlier mix.
        self._preview_path = os.path.join(self._temp_dir, f"preview_{uuid.uuid4().hex[:8]}.mp3")
        self._export_worker = ExportWorker(self._current_mix, self._preview_path)
        self._export_worker.finished_ok.connect(self._on_preview_ready)
        self._export_worker.failed.connect(self._on_preview_failed)
        self._export_worker.start()

    def _on_preview_ready(self, preview_path):
        self._export_worker = None
        if self._cancelled:
            return
        duration_seconds = len(self._current_mix) / 1000.0
        n_tracks = getattr(self.studio_screen, "_n_tracks", len(self._pending_skipped))
        self.studio_screen.set_result(preview_path, duration_seconds, self._pending_skipped, n_tracks)
        self.title_bar.set_crumb("Session · mix ready")

    def _on_preview_failed(self, message):
        self._export_worker = None
        if self._cancelled:
            return
        QMessageBox.critical(self, "Error", f"Could not prepare the preview:\n{message}")
        self.title_bar.set_crumb("Session · untitled")
        self.stack.setCurrentWidget(self.setup_screen)

    def _on_processing_failed(self, message):
        self._worker = None
        if self._cancelled:
            return
        QMessageBox.critical(self, "Processing error", f"Something went wrong:\n{message}")
        self.title_bar.set_crumb("Session · untitled")
        self.stack.setCurrentWidget(self.setup_screen)

    # ----------------------------------------------------------------
    # Save / restart
    # ----------------------------------------------------------------

    def save_mix(self):
        if self._current_mix is None:
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Save mix as", "party_mix.mp3", "MP3 Audio (*.mp3)"
        )
        if not path:
            return
        if not path.lower().endswith(".mp3"):
            path += ".mp3"

        self.studio_screen.save_button.setEnabled(False)
        self.studio_screen.save_button.setText("Saving…")

        self._export_worker = ExportWorker(self._current_mix, path)
        self._export_worker.finished_ok.connect(self._on_save_finished)
        self._export_worker.failed.connect(self._on_save_failed)
        self._export_worker.start()

    def _on_save_finished(self, path):
        self._export_worker = None
        self.studio_screen.save_button.setEnabled(True)
        self.studio_screen.save_button.setText("Save mix")
        QMessageBox.information(self, "Saved", f"Mix saved to:\n{path}")

    def _on_save_failed(self, message):
        self._export_worker = None
        self.studio_screen.save_button.setEnabled(True)
        self.studio_screen.save_button.setText("Save mix")
        QMessageBox.critical(self, "Save failed", f"Could not save the file:\n{message}")

    def start_new_mix(self):
        self.studio_screen.stop_playback()
        self._current_mix = None
        self.setup_screen.reset()
        self.title_bar.set_crumb("Session · untitled")
        self.stack.setCurrentWidget(self.setup_screen)

    # ----------------------------------------------------------------
    # Cleanup
    # ----------------------------------------------------------------

    def closeEvent(self, event):
        self._cancelled = True
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait()
        if self._export_worker is not None and self._export_worker.isRunning():
            self._export_worker.wait()
        self.studio_screen.stop_playback()
        shutil.rmtree(self._temp_dir, ignore_errors=True)
        super().closeEvent(event)
