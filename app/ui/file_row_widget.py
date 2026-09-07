"""A single row in the upload file list: filename, duration, delete button."""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from . import theme


def format_duration(seconds):
    if seconds is None:
        return "--:--"
    total = int(round(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes}:{secs:02d}"


class FileRowWidget(QWidget):
    remove_clicked = Signal(str)  # emits the filepath to remove

    def __init__(self, filepath, duration_seconds, parent=None):
        super().__init__(parent)
        self.filepath = filepath
        self.setObjectName("fileRow")
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 4, 6)
        layout.setSpacing(theme.SPACE_4)

        name_label = QLabel(os.path.basename(filepath))
        name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        name_label.setStyleSheet(f"font-size: 13px; color: {theme.TEXT};")

        self.duration_seconds = duration_seconds
        self.duration_label = QLabel(format_duration(duration_seconds))
        self.duration_label.setStyleSheet(f"color: {theme.NEUTRAL[400]}; font-size: 11px;")

        remove_button = QPushButton("✕")
        remove_button.setFixedSize(22, 22)
        remove_button.setCursor(Qt.PointingHandCursor)
        remove_button.setToolTip("Remove")
        remove_button.setStyleSheet(f"""
            QPushButton {{
                border: none;
                border-radius: 11px;
                color: {theme.NEUTRAL[400]};
                background-color: transparent;
                font-size: 11px;
            }}
            QPushButton:hover {{
                color: {theme.ACCENT_RAMP[300]};
                background-color: {theme.NEUTRAL[800]};
            }}
        """)
        remove_button.clicked.connect(lambda: self.remove_clicked.emit(self.filepath))

        layout.addWidget(name_label)
        layout.addWidget(self.duration_label)
        layout.addWidget(remove_button)

        self.setStyleSheet(f"""
            #fileRow {{
                border-radius: {theme.RADIUS_SM}px;
            }}
            #fileRow:hover {{
                background-color: {theme.NEUTRAL[900]};
            }}
        """)

    def set_duration(self, duration_seconds):
        self.duration_seconds = duration_seconds
        self.duration_label.setText(format_duration(duration_seconds))
