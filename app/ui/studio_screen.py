"""Studio screen: merges the old processing_screen (progress) and
done_screen (preview/save/restart) into the two sub-states of a single
screen, matching the SVMix redesign's isRunning / isReady split."""

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QVBoxLayout, QWidget

from . import theme
from .widgets import ClickableLabel, ProgressRing


def format_duration(seconds):
    total = int(round(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes}:{secs:02d}"


def _chip_style():
    return (
        f"padding: 4px 11px; border: 1px solid {theme.NEUTRAL[800]}; "
        f"border-radius: 999px; font-size: 11px; color: {theme.NEUTRAL[300]};"
    )


class StudioScreen(QWidget):
    save_requested = Signal()
    new_mix_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)
        self._player.playbackStateChanged.connect(self._on_playback_state_changed)
        self._player.errorOccurred.connect(self._on_player_error)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(56, theme.SPACE_8, 56, theme.SPACE_8)
        outer.setSpacing(theme.SPACE_8)

        outer.addWidget(self._build_ring(), 0, Qt.AlignVCenter)
        outer.addWidget(self._build_info_panel(), 1)

        self._set_running_visible(True)

    # ------------------------------------------------------------------
    # Left: progress ring / play button
    # ------------------------------------------------------------------

    def _build_ring(self):
        wrap = QWidget()
        wrap.setFixedSize(280, 280)

        self.ring = ProgressRing(wrap)
        self.ring.move(0, 0)

        self.percent_label = QLabel("0%", wrap)
        self.percent_label.setGeometry(60, 108, 160, 60)
        self.percent_label.setAlignment(Qt.AlignCenter)
        self.percent_label.setStyleSheet(
            f"font-size: 52px; font-weight: 600; color: {theme.TEXT}; background: transparent;"
        )
        self.percent_label.setAttribute(Qt.WA_TransparentForMouseEvents)

        self.analyzing_caption = QLabel("ANALYZING", wrap)
        self.analyzing_caption.setGeometry(60, 172, 160, 14)
        self.analyzing_caption.setAlignment(Qt.AlignCenter)
        self.analyzing_caption.setStyleSheet(
            f"font-size: 9px; color: {theme.NEUTRAL[500]}; background: transparent;"
        )
        self.analyzing_caption.setAttribute(Qt.WA_TransparentForMouseEvents)

        self.play_button = ClickableLabel("▶", wrap)
        self.play_button.setGeometry(102, 102, 76, 76)
        self.play_button.setAlignment(Qt.AlignCenter)
        self.play_button.setStyleSheet(
            f"""
            border: 1px solid {theme.ACCENT};
            border-radius: 38px;
            font-size: 26px;
            color: {theme.ACCENT};
            background: transparent;
            """
        )
        self.play_button.clicked.connect(self._toggle_playback)

        return wrap

    # ------------------------------------------------------------------
    # Right: kicker/title/status, chips, skipped panel, actions
    # ------------------------------------------------------------------

    def _build_info_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_6)

        heading = QVBoxLayout()
        heading.setSpacing(theme.SPACE_2)
        self.kicker_label = QLabel("WORKING")
        self.kicker_label.setStyleSheet(
            f"font-size: 11px; font-weight: 500; letter-spacing: 1.5px; "
            f"color: {theme.NEUTRAL[500]}; text-transform: uppercase;"
        )
        self.title_label = QLabel("")
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet(f"font-size: 32px; font-weight: 600; color: {theme.TEXT};")
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(20)
        self.status_label.setStyleSheet(f"font-size: 13px; color: {theme.NEUTRAL[500]};")
        heading.addWidget(self.kicker_label)
        heading.addWidget(self.title_label)
        heading.addWidget(self.status_label)
        layout.addLayout(heading)

        chips_row = QHBoxLayout()
        chips_row.setSpacing(theme.SPACE_3)
        self.chip_mode = QLabel("")
        self.chip_hook = QLabel("")
        self.chip_length = QLabel("")
        self.chip_tracks = QLabel("")
        for chip in (self.chip_mode, self.chip_hook, self.chip_length, self.chip_tracks):
            chip.setStyleSheet(_chip_style())
            chips_row.addWidget(chip)
        chips_row.addStretch(1)
        layout.addLayout(chips_row)

        self.skipped_panel = self._build_skipped_panel()
        layout.addWidget(self.skipped_panel)

        self.actions_ready = self._build_ready_actions()
        layout.addWidget(self.actions_ready)

        self.cancel_link = ClickableLabel("Cancel")
        self.cancel_link.setStyleSheet(
            f"font-size: 11px; letter-spacing: 1px; text-transform: uppercase; "
            f"color: {theme.NEUTRAL[400]};"
        )
        self.cancel_link.clicked.connect(self.cancel_requested.emit)
        layout.addWidget(self.cancel_link, 0, Qt.AlignLeft)

        layout.addStretch(1)
        return panel

    def _build_skipped_panel(self):
        panel = QWidget()
        panel.setObjectName("skippedPanel")
        panel.setAttribute(Qt.WA_StyledBackground, True)
        panel.setStyleSheet(
            f"""
            QWidget#skippedPanel {{
                border: 1px solid {theme.ACCENT_RAMP[800]};
                border-radius: {theme.RADIUS_MD}px;
                background: {theme.ACCENT_RAMP[900]};
            }}
            """
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
        layout.setSpacing(theme.SPACE_2)

        self.skipped_label = QLabel("")
        self.skipped_label.setStyleSheet(
            f"font-size: 11px; font-weight: 500; letter-spacing: 1px; "
            f"text-transform: uppercase; color: {theme.ACCENT_RAMP[300]}; background: transparent;"
        )
        layout.addWidget(self.skipped_label)

        self.skipped_list = QListWidget()
        self.skipped_list.setMaximumHeight(90)
        self.skipped_list.setStyleSheet(
            f"""
            QListWidget {{
                background: transparent;
                border: none;
                color: {theme.ACCENT_RAMP[200]};
                font-size: 12px;
            }}
            """
        )
        layout.addWidget(self.skipped_list)

        panel.setVisible(False)
        return panel

    def _build_ready_actions(self):
        wrap = QWidget()
        layout = QHBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_4)

        self.save_button = ClickableLabel("Save mix")
        self.save_button.setFixedHeight(44)
        self.save_button.setAlignment(Qt.AlignCenter)
        self.save_button.setStyleSheet(
            f"""
            border: 1px solid {theme.ACCENT};
            border-radius: {theme.RADIUS_MD}px;
            color: {theme.ACCENT};
            font-size: 12px;
            font-weight: 500;
            letter-spacing: 1px;
            """
        )
        self.save_button.clicked.connect(self.save_requested.emit)

        self.new_mix_button = ClickableLabel("New mix")
        self.new_mix_button.setFixedHeight(44)
        self.new_mix_button.setAlignment(Qt.AlignCenter)
        self.new_mix_button.setStyleSheet(
            f"""
            border: 1px solid {theme.NEUTRAL[800]};
            border-radius: {theme.RADIUS_MD}px;
            color: {theme.NEUTRAL[300]};
            font-size: 12px;
            font-weight: 500;
            letter-spacing: 1px;
            """
        )
        self.new_mix_button.clicked.connect(self._on_new_mix_clicked)

        layout.addWidget(self.save_button, 1)
        layout.addWidget(self.new_mix_button, 1)
        wrap.setMaximumWidth(420)
        return wrap

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def start(self, mode_label, hook_label, minutes_target, n_tracks):
        self.ring.set_percent(0)
        self.percent_label.setText("0%")
        self.kicker_label.setText("WORKING")
        self.title_label.setText(f"Cutting {n_tracks} tracks together")
        self.status_label.setText("Starting…")
        self.chip_mode.setText(mode_label)
        self.chip_hook.setText(f"{hook_label} hook")
        self.chip_length.setText(f"{minutes_target} min target")
        self.chip_tracks.setText(f"{n_tracks} of {n_tracks} tracks")
        self.skipped_panel.setVisible(False)
        self.skipped_list.clear()
        self._n_tracks = n_tracks
        self._set_running_visible(True)

    def set_progress(self, message, percent):
        self.ring.set_percent(percent)
        self.percent_label.setText(f"{percent}%")
        self.status_label.setText(message)

    def set_result(self, preview_path, duration_seconds, skipped, n_tracks):
        self._player.stop()
        self._player.setSource(QUrl())  # force-release any previous media
        self._player.setSource(QUrl.fromLocalFile(preview_path))
        self.play_button.setText("▶")

        self.kicker_label.setText("RESULT")
        self.title_label.setText(f"Mix ready — {format_duration(duration_seconds)}")
        self.status_label.setText("Rendered at 320 kbps. Preview it here, then save the file.")

        n_used = n_tracks - len(skipped)
        self.chip_tracks.setText(f"{n_used} of {n_tracks} used")

        self.skipped_list.clear()
        if skipped:
            self.skipped_panel.setVisible(True)
            self.skipped_label.setText(
                "1 file skipped" if len(skipped) == 1 else f"{len(skipped)} files skipped"
            )
            for filename, reason in skipped:
                self.skipped_list.addItem(f"{filename} — {reason}")
        else:
            self.skipped_panel.setVisible(False)

        self._set_running_visible(False)

    def _set_running_visible(self, running):
        self.ring.set_percent(self.ring.percent() if running else 100)
        self.percent_label.setVisible(running)
        self.analyzing_caption.setVisible(running)
        self.play_button.setVisible(not running)
        self.actions_ready.setVisible(not running)
        self.cancel_link.setVisible(running)

    # ------------------------------------------------------------------
    # Preview playback
    # ------------------------------------------------------------------

    def _toggle_playback(self):
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
        else:
            if (
                self._player.duration() > 0
                and self._player.position() >= self._player.duration()
            ):
                self._player.setPosition(0)
            self._player.play()

    def _on_playback_state_changed(self, state):
        self.play_button.setText("⏸" if state == QMediaPlayer.PlayingState else "▶")

    def _on_player_error(self, error, error_string):
        if error != QMediaPlayer.NoError:
            self.play_button.setText("▶")

    def _on_new_mix_clicked(self):
        self._player.stop()
        self.new_mix_requested.emit()

    def stop_playback(self):
        self._player.stop()
