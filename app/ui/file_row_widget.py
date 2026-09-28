"""A single row in the upload file list: filename, duration, delete button,
and the per-track Lock / Pre-cut toggles underneath."""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from . import theme


def format_duration(seconds):
    if seconds is None:
        return "--:--"
    total = int(round(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes}:{secs:02d}"


LOCK_TOOLTIP = (
    "Always use this track. If it has no section matching the selected hook "
    "type, its closest-matching section is used instead of skipping it."
)
PRECUT_TOOLTIP = (
    "You've already cut this file to the part you want. It's added to the mix "
    "whole, exactly as it is: no hook detection, no trimming."
)


class ElidedLabel(QLabel):
    """A QLabel that shortens its text with "…" to fit its width instead of
    forcing the row wider -- song filenames are often very long."""

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self._full_text = text
        self.setToolTip(text)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(40)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setText(self.fontMetrics().elidedText(self._full_text, Qt.ElideRight, self.width()))


def _toggle(text, tooltip):
    box = QCheckBox(text)
    box.setCursor(Qt.PointingHandCursor)
    box.setToolTip(tooltip)
    box.setStyleSheet(f"""
        QCheckBox {{
            font-size: 11px;
            color: {theme.NEUTRAL[400]};
            spacing: 5px;
        }}
        QCheckBox:checked {{
            color: {theme.ACCENT_RAMP[300]};
        }}
        QCheckBox:disabled {{
            color: {theme.NEUTRAL[600]};
        }}
        QCheckBox::indicator {{
            width: 12px;
            height: 12px;
            border: 1px solid {theme.NEUTRAL[600]};
            border-radius: 3px;
            background: transparent;
        }}
        QCheckBox::indicator:hover {{
            border-color: {theme.ACCENT};
        }}
        QCheckBox::indicator:checked {{
            border-color: {theme.ACCENT};
            background: {theme.ACCENT};
        }}
        QCheckBox::indicator:checked:disabled {{
            border-color: {theme.ACCENT_RAMP[700]};
            background: {theme.ACCENT_RAMP[700]};
        }}
    """)
    return box


class FileRowWidget(QWidget):
    remove_clicked = Signal(str)  # emits the filepath to remove
    locked_changed = Signal(str, bool)  # (filepath, locked)
    precut_changed = Signal(str, bool)  # (filepath, pre-cut)

    def __init__(self, filepath, duration_seconds, parent=None):
        super().__init__(parent)
        self.filepath = filepath
        self.setObjectName("fileRow")
        self.setAttribute(Qt.WA_StyledBackground, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 4, 6)
        outer.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(theme.SPACE_4)

        name_label = ElidedLabel(os.path.basename(filepath))
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

        top.addWidget(name_label, 1)
        top.addWidget(self.duration_label)
        top.addWidget(remove_button)
        outer.addLayout(top)

        toggles = QHBoxLayout()
        toggles.setSpacing(theme.SPACE_6)
        self.lock_box = _toggle("Lock", LOCK_TOOLTIP)
        self.lock_box.toggled.connect(lambda on: self.locked_changed.emit(self.filepath, on))
        self.precut_box = _toggle("Pre-cut", PRECUT_TOOLTIP)
        self.precut_box.toggled.connect(self._on_precut_toggled)
        toggles.addWidget(self.lock_box)
        toggles.addWidget(self.precut_box)
        toggles.addStretch(1)
        outer.addLayout(toggles)

        self.setStyleSheet(f"""
            #fileRow {{
                border-radius: {theme.RADIUS_SM}px;
            }}
            #fileRow:hover {{
                background-color: {theme.NEUTRAL[900]};
            }}
        """)

    def _on_precut_toggled(self, on):
        # A pre-cut track is always used by definition, so Lock is implied
        # (shown ticked and greyed out) while Pre-cut is on.
        self.lock_box.setEnabled(not on)
        if on:
            self._lock_before_precut = self.lock_box.isChecked()
            self.lock_box.setChecked(True)
        else:
            self.lock_box.setChecked(getattr(self, "_lock_before_precut", False))
        self.precut_changed.emit(self.filepath, on)

    def set_duration(self, duration_seconds):
        self.duration_seconds = duration_seconds
        self.duration_label.setText(format_duration(duration_seconds))
