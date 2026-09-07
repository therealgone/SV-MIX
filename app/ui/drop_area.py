"""Drag-and-drop + click-to-browse area for adding audio files."""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QFrame, QLabel, QVBoxLayout

import pipeline

from . import theme


class DropArea(QFrame):
    """A prominent drop zone. Accepts dragged-in audio files and is
    also clickable to open the native file browser.
    """

    files_selected = Signal(list)  # list[str] of file paths

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("dropArea")
        self.setFixedHeight(104)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(6)

        icon_label = QLabel("≈")
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet(f"font-size: 22px; color: {theme.ACCENT};")

        title_label = QLabel("Drop audio here")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setObjectName("dropTitle")

        subtitle_label = QLabel("or click to browse  ·  mp3  wav  m4a")
        subtitle_label.setAlignment(Qt.AlignCenter)
        subtitle_label.setObjectName("dropSubtitle")

        layout.addWidget(icon_label)
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)

        self.setStyleSheet(f"""
            #dropArea {{
                border: 1px dashed {theme.NEUTRAL[700]};
                border-radius: {theme.RADIUS_MD}px;
                background-color: {theme.NEUTRAL[900]};
            }}
            #dropArea:hover {{
                border-color: {theme.ACCENT};
                background-color: {theme.ACCENT_RAMP[900]};
            }}
            #dropTitle {{
                font-size: 13px;
                font-weight: 500;
                color: {theme.TEXT};
            }}
            #dropSubtitle {{
                font-size: 11px;
                color: {theme.NEUTRAL[400]};
            }}
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
