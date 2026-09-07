"""Done screen: preview the finished mix, see skipped files, save or restart."""

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


def format_duration(seconds):
    total = int(round(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes}:{secs:02d}"


class DoneScreen(QWidget):
    save_requested = Signal()
    new_mix_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)
        self._player.playbackStateChanged.connect(self._on_playback_state_changed)
        self._player.errorOccurred.connect(self._on_player_error)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignTop)

        title = QLabel("Your mix is ready!")
        title.setStyleSheet("font-size: 20px; font-weight: 700; color: #2c3e50;")

        self.duration_label = QLabel("")
        self.duration_label.setStyleSheet("color: #5c6b7a; font-size: 13px;")

        self.play_button = QPushButton("▶  Play preview")
        self.play_button.setFixedHeight(40)
        self.play_button.setCursor(Qt.PointingHandCursor)
        self.play_button.clicked.connect(self._toggle_playback)

        self.skipped_toggle = QToolButton()
        self.skipped_toggle.setCheckable(True)
        self.skipped_toggle.setArrowType(Qt.RightArrow)
        self.skipped_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.skipped_toggle.setCursor(Qt.PointingHandCursor)
        self.skipped_toggle.setStyleSheet("QToolButton { border: none; color: #b0392a; }")
        self.skipped_toggle.toggled.connect(self._on_skipped_toggled)
        self.skipped_toggle.setVisible(False)

        self.skipped_list = QListWidget()
        self.skipped_list.setVisible(False)
        self.skipped_list.setMaximumHeight(120)
        self.skipped_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #f0d4cf;
                border-radius: 6px;
                background-color: #fdf6f5;
                color: #7a3229;
                font-size: 12px;
            }
        """)

        self.save_button = QPushButton("Save As...")
        self.save_button.setFixedHeight(44)
        self.save_button.setCursor(Qt.PointingHandCursor)
        self.save_button.setStyleSheet("""
            QPushButton {
                background-color: #4a90d9;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #3b7bc4;
            }
        """)
        self.save_button.clicked.connect(self.save_requested.emit)

        self.new_mix_button = QPushButton("Start New Mix")
        self.new_mix_button.setFixedHeight(44)
        self.new_mix_button.setCursor(Qt.PointingHandCursor)
        self.new_mix_button.setStyleSheet("""
            QPushButton {
                background-color: #eef1f4;
                color: #2c3e50;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #e1e5ea;
            }
        """)
        self.new_mix_button.clicked.connect(self._on_new_mix_clicked)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        button_row.addWidget(self.save_button)
        button_row.addWidget(self.new_mix_button)

        layout.addWidget(title)
        layout.addWidget(self.duration_label)
        layout.addWidget(self.play_button)
        layout.addWidget(self.skipped_toggle)
        layout.addWidget(self.skipped_list)
        layout.addStretch(1)
        layout.addLayout(button_row)

    def set_result(self, preview_path, duration_seconds, skipped):
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(preview_path))
        self.play_button.setText("▶  Play preview")
        self.duration_label.setText(f"Total duration: {format_duration(duration_seconds)}")

        self.skipped_list.clear()
        if skipped:
            self.skipped_toggle.setVisible(True)
            self.skipped_toggle.setChecked(False)
            self.skipped_toggle.setArrowType(Qt.RightArrow)
            self.skipped_toggle.setText(f"{len(skipped)} file(s) skipped")
            self.skipped_list.setVisible(False)
            for filename, reason in skipped:
                self.skipped_list.addItem(f"{filename} — {reason}")
        else:
            self.skipped_toggle.setVisible(False)
            self.skipped_list.setVisible(False)

    def _on_skipped_toggled(self, checked):
        self.skipped_list.setVisible(checked)
        self.skipped_toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)

    def _toggle_playback(self):
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _on_playback_state_changed(self, state):
        if state == QMediaPlayer.PlayingState:
            self.play_button.setText("⏸  Pause preview")
        else:
            self.play_button.setText("▶  Play preview")

    def _on_player_error(self, error, error_string):
        if error != QMediaPlayer.NoError:
            self.play_button.setText("▶  Play preview")

    def _on_new_mix_clicked(self):
        self._player.stop()
        self.new_mix_requested.emit()

    def stop_playback(self):
        self._player.stop()
