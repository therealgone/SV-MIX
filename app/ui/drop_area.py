"""Drag-and-drop + click-to-browse area for adding audio files."""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QFrame, QLabel, QVBoxLayout

import pipeline


class DropArea(QFrame):
    """A prominent drop zone. Accepts dragged-in audio files and is
    also clickable to open the native file browser.
    """

    files_selected = Signal(list)  # list[str] of file paths

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("dropArea")
        self.setMinimumHeight(160)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(6)

        icon_label = QLabel("\U0001F3B5")
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet("font-size: 32px;")

        title_label = QLabel("Drag & drop audio files here")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setObjectName("dropTitle")

        subtitle_label = QLabel("or click to browse  ·  .mp3, .wav, .m4a")
        subtitle_label.setAlignment(Qt.AlignCenter)
        subtitle_label.setObjectName("dropSubtitle")

        layout.addWidget(icon_label)
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)

        self.setStyleSheet("""
            #dropArea {
                border: 2px dashed #9aa5b1;
                border-radius: 12px;
                background-color: #f7f9fb;
            }
            #dropArea:hover {
                border-color: #4a90d9;
                background-color: #eef5fc;
            }
            #dropTitle {
                font-size: 15px;
                font-weight: 600;
                color: #2c3e50;
            }
            #dropSubtitle {
                font-size: 12px;
                color: #7f8c99;
            }
        """)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._browse()
        super().mousePressEvent(event)

    def _browse(self):
        filters = "Audio Files (*.mp3 *.wav *.m4a)"
        paths, _ = QFileDialog.getOpenFileNames(self, "Select audio files", "", filters)
        if paths:
            self.files_selected.emit(paths)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and self._valid_local_paths(event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = self._valid_local_paths(event.mimeData().urls())
        if paths:
            self.files_selected.emit(paths)
        event.acceptProposedAction()

    @staticmethod
    def _valid_local_paths(urls):
        paths = []
        for url in urls:
            if url.isLocalFile():
                path = url.toLocalFile()
                if os.path.splitext(path)[1].lower() in pipeline.AUDIO_EXTENSIONS:
                    paths.append(path)
        return paths
