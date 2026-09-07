"""Processing screen: progress bar + status label while the mix runs."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget


class ProcessingScreen(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 60, 40, 60)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignCenter)

        title = QLabel("Mixing your songs...")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #2c3e50;")

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(10)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border-radius: 5px;
                background-color: #e1e5ea;
            }
            QProgressBar::chunk {
                border-radius: 5px;
                background-color: #4a90d9;
            }
        """)

        self.status_label = QLabel("Starting...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #5c6b7a; font-size: 13px;")

        layout.addWidget(title)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)

    def set_progress(self, message, percent):
        self.status_label.setText(message)
        self.progress_bar.setValue(percent)

    def reset(self):
        self.progress_bar.setValue(0)
        self.status_label.setText("Starting...")
