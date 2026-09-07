"""Main application window: hosts the three screens and wires them together."""

import os
import shutil
import tempfile

from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox, QStackedWidget

from ..worker import ExportWorker, MixWorker
from .done_screen import DoneScreen
from .processing_screen import ProcessingScreen
from .upload_screen import UploadScreen


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SVMixer")
        self.resize(480, 640)
        self.setMinimumSize(400, 520)

        self._worker = None
        self._export_worker = None
        self._current_mix = None
        self._temp_dir = tempfile.mkdtemp(prefix="mashup_preview_")
        self._preview_path = os.path.join(self._temp_dir, "preview.mp3")

        self.upload_screen = UploadScreen()
        self.processing_screen = ProcessingScreen()
        self.done_screen = DoneScreen()

        self.stack = QStackedWidget()
        self.stack.addWidget(self.upload_screen)
        self.stack.addWidget(self.processing_screen)
        self.stack.addWidget(self.done_screen)
        self.setCentralWidget(self.stack)

        self.upload_screen.mix_requested.connect(self.start_processing)
        self.done_screen.save_requested.connect(self.save_mix)
        self.done_screen.new_mix_requested.connect(self.start_new_mix)

    # ----------------------------------------------------------------
    # Processing
    # ----------------------------------------------------------------

    def start_processing(self, filepaths, mode, target_duration_sec, hook_type):
        self.processing_screen.reset()
        self.stack.setCurrentWidget(self.processing_screen)

        self._worker = MixWorker(filepaths, mode, target_duration_sec, hook_type)
        self._worker.progress.connect(self.processing_screen.set_progress)
        self._worker.finished_ok.connect(self._on_processing_finished)
        self._worker.failed.connect(self._on_processing_failed)
        self._worker.start()

    def _on_processing_finished(self, result):
        self._worker = None

        if result["mix"] is None:
            details = "\n".join(f"- {name}: {reason}" for name, reason in result["skipped"])
            QMessageBox.warning(
                self,
                "Nothing to mix",
                "None of the selected files could be processed.\n\n" + details,
            )
            self.stack.setCurrentWidget(self.upload_screen)
            return

        self._current_mix = result["mix"]
        self._pending_skipped = result["skipped"]
        self.processing_screen.set_progress("Preparing preview...", 100)

        self._export_worker = ExportWorker(self._current_mix, self._preview_path)
        self._export_worker.finished_ok.connect(self._on_preview_ready)
        self._export_worker.failed.connect(self._on_preview_failed)
        self._export_worker.start()

    def _on_preview_ready(self, preview_path):
        self._export_worker = None
        duration_seconds = len(self._current_mix) / 1000.0
        self.done_screen.set_result(preview_path, duration_seconds, self._pending_skipped)
        self.stack.setCurrentWidget(self.done_screen)

    def _on_preview_failed(self, message):
        self._export_worker = None
        QMessageBox.critical(self, "Error", f"Could not prepare the preview:\n{message}")
        self.stack.setCurrentWidget(self.upload_screen)

    def _on_processing_failed(self, message):
        self._worker = None
        QMessageBox.critical(self, "Processing error", f"Something went wrong:\n{message}")
        self.stack.setCurrentWidget(self.upload_screen)

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

        self.done_screen.save_button.setEnabled(False)
        self.done_screen.save_button.setText("Saving...")

        self._export_worker = ExportWorker(self._current_mix, path)
        self._export_worker.finished_ok.connect(self._on_save_finished)
        self._export_worker.failed.connect(self._on_save_failed)
        self._export_worker.start()

    def _on_save_finished(self, path):
        self._export_worker = None
        self.done_screen.save_button.setEnabled(True)
        self.done_screen.save_button.setText("Save As...")
        QMessageBox.information(self, "Saved", f"Mix saved to:\n{path}")

    def _on_save_failed(self, message):
        self._export_worker = None
        self.done_screen.save_button.setEnabled(True)
        self.done_screen.save_button.setText("Save As...")
        QMessageBox.critical(self, "Save failed", f"Could not save the file:\n{message}")

    def start_new_mix(self):
        self.done_screen.stop_playback()
        self._current_mix = None
        self.upload_screen.reset()
        self.stack.setCurrentWidget(self.upload_screen)

    # ----------------------------------------------------------------
    # Cleanup
    # ----------------------------------------------------------------

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait()
        if self._export_worker is not None and self._export_worker.isRunning():
            self._export_worker.wait()
        self.done_screen.stop_playback()
        shutil.rmtree(self._temp_dir, ignore_errors=True)
        super().closeEvent(event)
