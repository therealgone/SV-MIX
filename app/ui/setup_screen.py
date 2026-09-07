"""Setup screen: Sources panel (file list) + Session panel (mix mode, hook
type, length, start button). Replaces the old upload_screen.py, restyled
for the Nocturne dark theme and laid out per the SVMix redesign spec."""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

import pipeline
from . import theme
from ..worker import DurationProbeWorker
from .drop_area import DropArea
from .file_row_widget import FileRowWidget, format_duration
from .widgets import ClickableLabel, HookDial, LengthDial, SegmentedControl

MODE_DESCRIPTIONS = {
    pipeline.MODE_NORMAL: "Every song is used exactly once — no repeats.",
    pipeline.MODE_LOOP: "Every song plays once, then reprises fill in the rest for longer mixes.",
    pipeline.MODE_ULTRA: "Fast, hype mashup — songs are chopped into short bursts and interleaved.",
}

HOOK_TYPE_DESCRIPTIONS = {
    pipeline.HOOK_TYPE_NORMAL: "The loudest section of each song.",
    pipeline.HOOK_TYPE_MELODY: "The calmer, quieter section of each song. Songs with no distinct calm section are skipped.",
    pipeline.HOOK_TYPE_DANCE: "The loudest and most upbeat section of each song. Songs with no distinct energetic section are skipped.",
    pipeline.HOOK_TYPE_KUTHU: "The loudest, fastest-tempo section of each song. Songs with no genuinely fast-paced section are skipped.",
}

_MODE_OPTIONS = [
    (pipeline.MODE_NORMAL, "Normal Mix"),
    (pipeline.MODE_LOOP, "Loop Mix"),
    (pipeline.MODE_ULTRA, "Ultra Mix"),
]


def _panel_style():
    # Scoped to #panelBox specifically (not a bare declaration) so it
    # doesn't cascade onto every unstyled child label/widget inside the
    # panel -- see https://doc.qt.io/qt-6/stylesheet-syntax.html on
    # widget-instance style sheets applying to descendants.
    return (
        f"QWidget#panelBox {{ background-color: {theme.SURFACE}; "
        f"border: 1px solid {theme.NEUTRAL[800]}; border-radius: {theme.RADIUS_MD}px; }}"
    )


def _apply_panel_style(panel):
    panel.setObjectName("panelBox")
    panel.setAttribute(Qt.WA_StyledBackground, True)
    panel.setStyleSheet(_panel_style())


def _kicker_style():
    return (
        f"font-size: 11px; font-weight: 500; letter-spacing: 1.5px; "
        f"color: {theme.NEUTRAL[400]}; text-transform: uppercase;"
    )


class SetupScreen(QWidget):
    # (filepaths, mode, target_duration_sec, hook_type)
    mix_requested = Signal(list, str, int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.filepaths = []  # de-duplicated, preserves add order
        self._rows = {}  # filepath -> FileRowWidget
        self._durations = {}  # filepath -> seconds (or None), filled in as probes complete
        self._duration_workers = []

        outer = QHBoxLayout(self)
        outer.setContentsMargins(theme.SPACE_6, theme.SPACE_6, theme.SPACE_6, theme.SPACE_6)
        outer.setSpacing(theme.SPACE_6)

        outer.addWidget(self._build_sources_panel())
        outer.addWidget(self._build_session_panel(), 1)

        self.reset()

    # ------------------------------------------------------------------
    # Sources panel
    # ------------------------------------------------------------------

    def _build_sources_panel(self):
        panel = QWidget()
        panel.setFixedWidth(340)
        _apply_panel_style(panel)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(theme.SPACE_6, theme.SPACE_6, theme.SPACE_6, theme.SPACE_4)
        sources_label = QLabel("SOURCES")
        sources_label.setStyleSheet(_kicker_style())
        self.count_label = QLabel("0 tracks")
        self.count_label.setStyleSheet(f"font-size: 11px; color: {theme.NEUTRAL[400]};")
        header.addWidget(sources_label)
        header.addStretch(1)
        header.addWidget(self.count_label)
        layout.addLayout(header)

        drop_wrap = QVBoxLayout()
        drop_wrap.setContentsMargins(theme.SPACE_6, 0, theme.SPACE_6, 0)
        self.drop_area = DropArea()
        self.drop_area.files_selected.connect(self.add_files)
        drop_wrap.addWidget(self.drop_area)
        layout.addLayout(drop_wrap)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("QListWidget { background: transparent; border: none; }")
        self.list_widget.setContentsMargins(
            theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, 0
        )

        self.empty_label = QLabel(
            "Two tracks minimum — SVMix needs something to cut between."
        )
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setStyleSheet(
            f"font-size: 12px; color: {theme.NEUTRAL[500]}; padding: {theme.SPACE_8}px {theme.SPACE_4}px;"
        )

        layout.addWidget(self.list_widget, 1)
        layout.addWidget(self.empty_label)

        footer = QHBoxLayout()
        footer.setContentsMargins(theme.SPACE_6, theme.SPACE_4, theme.SPACE_6, theme.SPACE_4)
        footer_icon = QLabel("⏱")
        footer_icon.setStyleSheet(f"font-size: 13px; color: {theme.NEUTRAL[400]};")
        self.source_total_label = QLabel("Nothing loaded")
        self.source_total_label.setStyleSheet(f"font-size: 11px; color: {theme.NEUTRAL[400]};")
        footer.addWidget(footer_icon)
        footer.addWidget(self.source_total_label)
        footer.addStretch(1)

        footer_wrap = QWidget()
        footer_wrap.setObjectName("sourcesFooter")
        footer_wrap.setAttribute(Qt.WA_StyledBackground, True)
        footer_wrap.setStyleSheet(
            f"QWidget#sourcesFooter {{ border-top: 1px solid {theme.NEUTRAL[800]}; }}"
        )
        footer_wrap.setLayout(footer)
        layout.addWidget(footer_wrap)

        return panel

    # ------------------------------------------------------------------
    # Session panel
    # ------------------------------------------------------------------

    def _build_session_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_6)

        heading = QVBoxLayout()
        heading.setSpacing(2)
        session_label = QLabel("SESSION")
        session_label.setStyleSheet(
            f"font-size: 11px; font-weight: 500; letter-spacing: 1.5px; "
            f"color: {theme.NEUTRAL[500]}; text-transform: uppercase;"
        )
        title_label = QLabel("Set the cut")
        title_label.setStyleSheet(f"font-size: 25px; font-weight: 600; color: {theme.TEXT};")
        heading.addWidget(session_label)
        heading.addWidget(title_label)
        layout.addLayout(heading)

        mode_wrap = QVBoxLayout()
        mode_wrap.setSpacing(theme.SPACE_3)
        self.mode_control = SegmentedControl(_MODE_OPTIONS)
        self.mode_control.changed.connect(self._on_mode_changed)
        self.mode_desc_label = QLabel("")
        self.mode_desc_label.setWordWrap(True)
        self.mode_desc_label.setStyleSheet(f"font-size: 11px; color: {theme.NEUTRAL[500]};")
        mode_wrap.addWidget(self.mode_control)
        mode_wrap.addWidget(self.mode_desc_label)
        layout.addLayout(mode_wrap)

        dials_row = QHBoxLayout()
        dials_row.setSpacing(theme.SPACE_6)
        dials_row.addWidget(self._build_hook_panel(), 1)
        dials_row.addWidget(self._build_length_panel(), 1)
        layout.addLayout(dials_row, 1)

        self.mix_button = ClickableLabel("Add at least two tracks")
        self.mix_button.setAlignment(Qt.AlignCenter)
        self.mix_button.setFixedHeight(46)
        self.mix_button.clicked.connect(self._on_mix_clicked)
        layout.addWidget(self.mix_button)
        self._refresh_mix_button()

        return panel

    def _build_hook_panel(self):
        panel = QWidget()
        _apply_panel_style(panel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_6)
        layout.setSpacing(theme.SPACE_2)
        layout.setAlignment(Qt.AlignHCenter)

        label = QLabel("HOOK")
        label.setStyleSheet(_kicker_style())
        row = QHBoxLayout()
        row.addWidget(label)
        row.addStretch(1)
        layout.addLayout(row)

        self.hook_dial = HookDial()
        self.hook_dial.changed.connect(self._on_hook_changed)
        dial_row = QHBoxLayout()
        dial_row.addStretch(1)
        dial_row.addWidget(self.hook_dial)
        dial_row.addStretch(1)
        layout.addLayout(dial_row)

        self.hook_desc_label = QLabel("")
        self.hook_desc_label.setWordWrap(True)
        self.hook_desc_label.setAlignment(Qt.AlignCenter)
        self.hook_desc_label.setMinimumHeight(32)
        self.hook_desc_label.setStyleSheet(f"font-size: 11px; color: {theme.NEUTRAL[500]};")
        layout.addWidget(self.hook_desc_label)

        return panel

    def _build_length_panel(self):
        panel = QWidget()
        _apply_panel_style(panel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_6)
        layout.setSpacing(theme.SPACE_2)
        layout.setAlignment(Qt.AlignHCenter)

        label = QLabel("LENGTH")
        label.setStyleSheet(_kicker_style())
        row = QHBoxLayout()
        row.addWidget(label)
        row.addStretch(1)
        layout.addLayout(row)

        self.length_dial = LengthDial()
        self.length_dial.changed.connect(self._on_length_changed)

        overlay = QWidget()
        overlay.setFixedSize(240, 240)
        self.length_dial.setParent(overlay)
        self.length_dial.move(0, 0)

        self.minutes_label = QLabel("0", overlay)
        self.minutes_label.setGeometry(30, 78, 180, 60)
        self.minutes_label.setAlignment(Qt.AlignCenter)
        self.minutes_label.setStyleSheet(
            f"font-size: 52px; font-weight: 600; color: {theme.TEXT}; background: transparent;"
        )
        self.minutes_label.setAttribute(Qt.WA_TransparentForMouseEvents)

        minutes_caption = QLabel("MINUTES", overlay)
        minutes_caption.setGeometry(30, 140, 180, 14)
        minutes_caption.setAlignment(Qt.AlignCenter)
        minutes_caption.setStyleSheet(
            f"font-size: 9px; color: {theme.NEUTRAL[500]}; background: transparent;"
        )
        minutes_caption.setAttribute(Qt.WA_TransparentForMouseEvents)

        self.range_label = QLabel("0 min — 0 min", overlay)
        self.range_label.setGeometry(0, 188, 240, 16)
        self.range_label.setAlignment(Qt.AlignCenter)
        self.range_label.setStyleSheet(
            f"font-size: 10px; color: {theme.NEUTRAL[500]}; background: transparent;"
        )
        self.range_label.setAttribute(Qt.WA_TransparentForMouseEvents)

        dial_row = QHBoxLayout()
        dial_row.addStretch(1)
        dial_row.addWidget(overlay)
        dial_row.addStretch(1)
        layout.addLayout(dial_row)

        self.length_desc_label = QLabel("Add tracks to open up the range.")
        self.length_desc_label.setWordWrap(True)
        self.length_desc_label.setAlignment(Qt.AlignCenter)
        self.length_desc_label.setMinimumHeight(32)
        self.length_desc_label.setStyleSheet(f"font-size: 11px; color: {theme.NEUTRAL[500]};")
        layout.addWidget(self.length_desc_label)

        return panel

    # ------------------------------------------------------------------
    # File list
    # ------------------------------------------------------------------

    def add_files(self, paths):
        added_any = False
        new_paths = []
        for path in paths:
            if path in self.filepaths:
                continue
            ext = os.path.splitext(path)[1].lower()
            if ext not in pipeline.AUDIO_EXTENSIONS:
                continue
            self.filepaths.append(path)
            self._add_row(path, self._durations.get(path))
            new_paths.append(path)
            added_any = True

        if added_any:
            self._update_empty_state()
            self._update_length_range()
            self._refresh_mix_button()

        # Reading duration shells out to ffprobe per file, which is slow
        # enough on a batch of files to block the UI thread and trigger a
        # "not responding" window-manager prompt -- probe off-thread and
        # patch each row/total in as results arrive instead.
        if new_paths:
            worker = DurationProbeWorker(new_paths, self)
            worker.duration_ready.connect(self._on_duration_ready)
            worker.finished.connect(lambda w=worker: self._duration_workers.remove(w))
            self._duration_workers.append(worker)
            worker.start()

    def _on_duration_ready(self, path, duration):
        self._durations[path] = duration
        row = self._rows.get(path)
        if row is not None:
            row.set_duration(duration)
        self._update_empty_state()

    def _add_row(self, path, duration):
        item = QListWidgetItem()
        row = FileRowWidget(path, duration)
        row.remove_clicked.connect(self._remove_file)
        item.setSizeHint(row.sizeHint())
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, row)
        self._rows[path] = row

    def _remove_file(self, filepath):
        if filepath in self.filepaths:
            self.filepaths.remove(filepath)
        self._rows.pop(filepath, None)
        self._durations.pop(filepath, None)

        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            widget = self.list_widget.itemWidget(item)
            if widget is not None and widget.filepath == filepath:
                self.list_widget.takeItem(i)
                break

        self._update_empty_state()
        self._update_length_range()
        self._refresh_mix_button()

    def _update_empty_state(self):
        n = len(self.filepaths)
        has_files = n > 0
        self.list_widget.setVisible(has_files)
        self.empty_label.setVisible(not has_files)
        self.count_label.setText("1 track" if n == 1 else f"{n} tracks")

        total = sum(self._durations.get(p) or 0 for p in self.filepaths)
        self.source_total_label.setText(
            f"{format_duration(total)} of source audio" if n else "Nothing loaded"
        )

    # ------------------------------------------------------------------
    # Mode / hook / length state
    # ------------------------------------------------------------------

    def _on_mode_changed(self, mode):
        self.mode_desc_label.setText(MODE_DESCRIPTIONS.get(mode, ""))
        self._update_length_range()

    def _on_hook_changed(self, hook_type):
        self.hook_desc_label.setText(HOOK_TYPE_DESCRIPTIONS.get(hook_type, ""))

    def _on_length_changed(self, frac):
        self._refresh_minutes_label()

    def _update_length_range(self):
        mode = self.mode_control.current()
        n = len(self.filepaths)
        lo, hi = pipeline.estimate_duration_range(n, mode)
        lo_m = max(1, int(lo // 60))
        hi_m = max(lo_m + 1, -(-int(hi) // 60))  # ceil division

        self._range_lo_m = lo_m
        self._range_hi_m = hi_m
        self.range_label.setText(f"{lo_m} min — {hi_m} min")

        can_mix = n >= 2
        if can_mix:
            mode_label = pipeline.MODE_LABELS.get(mode, mode)
            self.length_desc_label.setText(f"Reachable with {n} tracks in {mode_label}.")
        else:
            self.length_desc_label.setText("Add tracks to open up the range.")

        self._refresh_minutes_label()

    def _refresh_minutes_label(self):
        lo_m = getattr(self, "_range_lo_m", 1)
        hi_m = getattr(self, "_range_hi_m", 2)
        frac = self.length_dial.fraction()
        minutes = lo_m + round(frac * (hi_m - lo_m))
        self.minutes_label.setText(str(minutes))

    def _current_minutes(self):
        lo_m = getattr(self, "_range_lo_m", 1)
        hi_m = getattr(self, "_range_hi_m", 2)
        frac = self.length_dial.fraction()
        return lo_m + round(frac * (hi_m - lo_m))

    # ------------------------------------------------------------------
    # Mix button
    # ------------------------------------------------------------------

    def _refresh_mix_button(self):
        can_mix = len(self.filepaths) >= 2
        n = len(self.filepaths)
        text = f"Mix {n} tracks" if can_mix else "Add at least two tracks"
        border = theme.ACCENT if can_mix else theme.NEUTRAL[800]
        color = theme.ACCENT if can_mix else theme.NEUTRAL[500]
        cursor = Qt.PointingHandCursor if can_mix else Qt.ArrowCursor
        self.mix_button.setText(text.upper())
        self.mix_button.setCursor(cursor)
        self.mix_button.setStyleSheet(
            f"""
            border: 1px solid {border};
            border-radius: {theme.RADIUS_MD}px;
            color: {color};
            font-size: 13px;
            font-weight: 500;
            letter-spacing: 1.5px;
            background: transparent;
            """
        )
        self._can_mix = can_mix

    def _on_mix_clicked(self):
        if len(self.filepaths) >= 2:
            mode = self.mode_control.current()
            hook_type = self.hook_dial.current()
            target_duration_sec = self._current_minutes() * 60
            self.mix_requested.emit(list(self.filepaths), mode, target_duration_sec, hook_type)

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self):
        self.filepaths = []
        self._rows = {}
        self._durations = {}
        self.list_widget.clear()
        self.mode_control.set_current(pipeline.MODE_LOOP, emit=False)
        self.hook_dial.set_current(pipeline.HOOK_TYPE_NORMAL, emit=False)
        self.length_dial.set_fraction(0.5, emit=False)
        self._on_mode_changed(self.mode_control.current())
        self._on_hook_changed(self.hook_dial.current())
        self._update_empty_state()
        self._update_length_range()
        self._refresh_mix_button()
