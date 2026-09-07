"""A single row in the upload file list: filename, duration, delete button."""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget


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

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 6, 4)
        layout.setSpacing(10)

        name_label = QLabel(os.path.basename(filepath))
        name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        name_label.setStyleSheet("font-size: 13px; color: #2c3e50;")

        duration_label = QLabel(format_duration(duration_seconds))
        duration_label.setStyleSheet("color: #7f8c99; font-size: 12px;")

        remove_button = QPushButton("✕")
        remove_button.setFixedSize(24, 24)
        remove_button.setCursor(Qt.PointingHandCursor)
        remove_button.setToolTip("Remove")
        remove_button.setStyleSheet("""
            QPushButton {
                border: none;
                border-radius: 12px;
                color: #b0392a;
                background-color: transparent;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #fbe4e0;
            }
        """)
        remove_button.clicked.connect(lambda: self.remove_clicked.emit(self.filepath))

        layout.addWidget(name_label)
        layout.addWidget(duration_label)
        layout.addWidget(remove_button)
