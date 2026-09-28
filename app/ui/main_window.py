"""Main application window: frameless Nocturne-themed chrome hosting the
Setup and Studio screens."""

import os
import shutil
import tempfile
import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox, QStackedWidget, QVBoxLayout, QWidget

import pipeline
from ..worker import ExportWorker, FileCopyWorker, MixWorker
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
        self._stale_workers = []  # cancelled workers still winding down
        self._export_worker = None
        self._current_mix = None
        self._media_type = pipeline.MEDIA_AUDIO
        self._closest_match = []
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

    def start_processing(self, filepaths, mode, target_duration_sec, hook_type,
                         locked_paths=(), precut_paths=(), media_type=pipeline.MEDIA_AUDIO):
        self._cancelled = False
        self._media_type = media_type
        is_video = media_type == pipeline.MEDIA_VIDEO
        mode_label = pipeline.MODE_LABELS.get(mode, mode)
        if is_video:
            mode_label += " · MP4"
        hook_label = pipeline.HOOK_TYPE_LABELS.get(hook_type, hook_type).replace(" Hook", "")
        minutes, secs = divmod(int(target_duration_sec), 60)
        self.studio_screen.start(mode_label, hook_label, f"{minutes}:{secs:02d}", len(filepaths))
        self.title_bar.set_crumb("Session · mixing")
        self.stack.setCurrentWidget(self.studio_screen)

        video_path = (
            os.path.join(self._temp_dir, f"preview_{uuid.uuid4().hex[:8]}.mp4") if is_video else None
        )
        worker = MixWorker(
            filepaths, mode, target_duration_sec, hook_type,
            locked_paths=locked_paths, precut_paths=precut_paths,
            media_type=media_type, video_output_path=video_path,
        )
        # Only the current worker's signals count: a cancelled one may
        # still finish (or fail) after the user has started another mix.
        worker.progress.connect(
            lambda m, p, w=worker: self.studio_screen.set_progress(m, p) if w is self._worker else None
        )
        worker.finished_ok.connect(
            lambda r, w=worker: self._on_processing_finished(r) if w is self._worker else None
        )
        worker.failed.connect(
            lambda m, w=worker: self._on_processing_failed(m) if w is self._worker else None
        )
        self._worker = worker
        worker.start()

    def _retire_worker(self):
        worker, self._worker = self._worker, None
        if worker is None:
            return
        worker.cancel()
        if worker.isRunning():
            # Keep a reference until the thread exits -- a QThread that's
            # garbage-collected while running takes the app down with it.
            self._stale_workers.append(worker)
            worker.finished.connect(
                lambda w=worker: self._stale_workers.remove(w) if w in self._stale_workers else None
            )

    def _discard_preview(self):
        self.studio_screen.release_media()
        if self._preview_path and os.path.exists(self._preview_path):
            try:
                os.remove(self._preview_path)
            except OSError:
                pass  # still locked by the player; the temp dir goes on exit
        self._preview_path = None

    def cancel_processing(self):
        self._cancelled = True
        self._retire_worker()
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
        self._closest_match = result.get("closest_match", [])

        if result.get("video_path"):
            # Video mixes are rendered by the worker itself; that file is
            # the preview, and saving just copies it.
            self._preview_path = result["video_path"]
            self._on_preview_ready(self._preview_path)
            return

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
        self.studio_screen.set_result(
            preview_path, duration_seconds, self._pending_skipped, n_tracks,
            is_video=self._media_type == pipeline.MEDIA_VIDEO,
            closest_match=self._closest_match,
        )
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
        if self._cancelled or message == "Cancelled":
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

        is_video = self._media_type == pipeline.MEDIA_VIDEO
        ext = ".mp4" if is_video else ".mp3"
        file_filter = "MP4 Video (*.mp4)" if is_video else "MP3 Audio (*.mp3)"
        path, _ = QFileDialog.getSaveFileName(self, "Save mix as", f"party_mix{ext}", file_filter)
        if not path:
            return
        if not path.lower().endswith(ext):
            path += ext

        self.studio_screen.save_button.setEnabled(False)
        self.studio_screen.save_button.setText("Saving…")

        if is_video:
            self._export_worker = FileCopyWorker(self._preview_path, path)
        else:
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
        self._discard_preview()
        self._current_mix = None
        self.setup_screen.reset()
        self.title_bar.set_crumb("Session · untitled")
        self.stack.setCurrentWidget(self.setup_screen)

    # ----------------------------------------------------------------
    # Cleanup
    # ----------------------------------------------------------------

    def closeEvent(self, event):
        self._cancelled = True
        self._retire_worker()
        for worker in list(self._stale_workers):
            worker.wait()
        if self._export_worker is not None and self._export_worker.isRunning():
            self._export_worker.wait()
        self.studio_screen.stop_playback()
        shutil.rmtree(self._temp_dir, ignore_errors=True)
        super().closeEvent(event)
