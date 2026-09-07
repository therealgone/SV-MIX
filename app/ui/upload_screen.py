"""Upload screen: drag-and-drop / browse for files, review list, start mix."""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

import pipeline
from .drop_area import DropArea
from .file_row_widget import FileRowWidget, format_duration

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


class UploadScreen(QWidget):
    # (filepaths, mode, target_duration_sec, hook_type)
    mix_requested = Signal(list, str, int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.filepaths = []  # de-duplicated, preserves add order

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        title = QLabel("SVMixer")
        title.setStyleSheet("font-size: 20px; font-weight: 700; color: #2c3e50;")

        self.drop_area = DropArea()
        self.drop_area.files_selected.connect(self.add_files)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("""
            QListWidget {
                border: 1px solid #e1e5ea;
                border-radius: 8px;
                background-color: white;
            }
            QListWidget::item {
                border-bottom: 1px solid #f0f2f5;
            }
        """)

        self.empty_label = QLabel("No files added yet")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("color: #9aa5b1; padding: 12px;")

        self.mode_combo = QComboBox()
        for mode in pipeline.MIX_MODES:
            self.mode_combo.addItem(pipeline.MODE_LABELS[mode], mode)
        self.mode_combo.setCurrentIndex(pipeline.MIX_MODES.index(pipeline.MODE_LOOP))
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)

        self.mode_description = QLabel("")
        self.mode_description.setWordWrap(True)
        self.mode_description.setStyleSheet("color: #5c6b7a; font-size: 12px;")

        self.hook_type_combo = QComboBox()
        for hook_type in pipeline.HOOK_TYPES:
            self.hook_type_combo.addItem(pipeline.HOOK_TYPE_LABELS[hook_type], hook_type)
        self.hook_type_combo.setCurrentIndex(pipeline.HOOK_TYPES.index(pipeline.HOOK_TYPE_NORMAL))
        self.hook_type_combo.currentIndexChanged.connect(self._on_hook_type_changed)

        self.hook_type_description = QLabel("")
        self.hook_type_description.setWordWrap(True)
        self.hook_type_description.setStyleSheet("color: #5c6b7a; font-size: 12px;")

        self.duration_label = QLabel("")
        self.duration_label.setStyleSheet("color: #5c6b7a; font-size: 12px;")

        self.duration_slider = QSlider(Qt.Horizontal)
        self.duration_slider.valueChanged.connect(self._on_duration_changed)

        self.mix_button = QPushButton("Mix Songs")
        self.mix_button.setEnabled(False)
        self.mix_button.setFixedHeight(44)
        self.mix_button.setCursor(Qt.PointingHandCursor)
        self.mix_button.setStyleSheet("""
            QPushButton {
                background-color: #4a90d9;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 15px;
                font-weight: 600;
            }
            QPushButton:disabled {
                background-color: #d5d9dd;
                color: #f0f2f5;
            }
            QPushButton:hover:!disabled {
                background-color: #3b7bc4;
            }
        """)
        self.mix_button.clicked.connect(self._on_mix_clicked)

        layout.addWidget(title)
        layout.addWidget(self.drop_area)
        layout.addWidget(self.list_widget, 1)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.mode_combo)
        layout.addWidget(self.mode_description)
        layout.addWidget(self.hook_type_combo)
        layout.addWidget(self.hook_type_description)
        layout.addWidget(self.duration_label)
        layout.addWidget(self.duration_slider)
        layout.addWidget(self.mix_button)

        self._update_empty_state()
        self._on_mode_changed(self.mode_combo.currentIndex())
        self._on_hook_type_changed(self.hook_type_combo.currentIndex())

    def add_files(self, paths):
        added_any = False
        for path in paths:
            if path in self.filepaths:
                continue
            ext = os.path.splitext(path)[1].lower()
            if ext not in pipeline.AUDIO_EXTENSIONS:
                continue
            self.filepaths.append(path)
            duration = pipeline.get_duration_seconds(path)
            self._add_row(path, duration)
            added_any = True

        if added_any:
            self._update_empty_state()
            self._update_mix_button()
            self._update_duration_range()

    def _add_row(self, path, duration):
        item = QListWidgetItem()
        row = FileRowWidget(path, duration)
        row.remove_clicked.connect(self._remove_file)
        item.setSizeHint(row.sizeHint())
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, row)

    def _remove_file(self, filepath):
        if filepath in self.filepaths:
            self.filepaths.remove(filepath)

        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            widget = self.list_widget.itemWidget(item)
            if widget is not None and widget.filepath == filepath:
                self.list_widget.takeItem(i)
                break

        self._update_empty_state()
        self._update_mix_button()
        self._update_duration_range()

    def _update_empty_state(self):
        has_files = len(self.filepaths) > 0
        self.list_widget.setVisible(has_files)
        self.empty_label.setVisible(not has_files)

    def _update_mix_button(self):
        enabled = len(self.filepaths) >= 2
        self.mix_button.setEnabled(enabled)
        self.mode_combo.setEnabled(enabled)
        self.hook_type_combo.setEnabled(enabled)
        self.duration_slider.setEnabled(enabled)

    def _on_mode_changed(self, index):
        mode = self.mode_combo.currentData()
        self.mode_description.setText(MODE_DESCRIPTIONS.get(mode, ""))
        self._update_duration_range()

    def _on_hook_type_changed(self, index):
        hook_type = self.hook_type_combo.currentData()
        self.hook_type_description.setText(HOOK_TYPE_DESCRIPTIONS.get(hook_type, ""))

    def _on_duration_changed(self, value):
        self._refresh_duration_label()

    def _update_duration_range(self):
        mode = self.mode_combo.currentData()
        lo, hi = pipeline.estimate_duration_range(len(self.filepaths), mode)
        lo_i, hi_i = int(round(lo)), max(int(round(hi)), int(round(lo)) + 1)

        self.duration_slider.blockSignals(True)
        self.duration_slider.setRange(lo_i, hi_i)
        self.duration_slider.setValue((lo_i + hi_i) // 2)
        self.duration_slider.blockSignals(False)

        self._duration_min = lo_i
        self._duration_max = hi_i
        self._refresh_duration_label()

    def _refresh_duration_label(self):
        target = self.duration_slider.value()
        lo = getattr(self, "_duration_min", target)
        hi = getattr(self, "_duration_max", target)
        self.duration_label.setText(
            f"Target length: {format_duration(target)}  "
            f"(min {format_duration(lo)} – max {format_duration(hi)})"
        )

    def _on_mix_clicked(self):
        if len(self.filepaths) >= 2:
            mode = self.mode_combo.currentData()
            hook_type = self.hook_type_combo.currentData()
            target_duration_sec = self.duration_slider.value()
            self.mix_requested.emit(list(self.filepaths), mode, target_duration_sec, hook_type)

    def reset(self):
        self.filepaths = []
        self.list_widget.clear()
        self.mode_combo.setCurrentIndex(pipeline.MIX_MODES.index(pipeline.MODE_LOOP))
        self.hook_type_combo.setCurrentIndex(pipeline.HOOK_TYPES.index(pipeline.HOOK_TYPE_NORMAL))
        self._update_empty_state()
        self._update_mix_button()
        self._update_duration_range()
