"""Custom title bar for the frameless main window: SV badge, wordmark,
breadcrumb, and window controls (minimize / maximize / close), matching
the SVMix redesign's nav bar."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QWidget

from . import theme
from .widgets import ClickableLabel


class TitleBar(QWidget):
    home_clicked = Signal()
    minimize_clicked = Signal()
    maximize_clicked = Signal()
    close_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self.setObjectName("titleBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QWidget#titleBar {{ background-color: {theme.SURFACE}; "
            f"border-bottom: 1px solid {theme.NEUTRAL[800]}; }}"
        )
        self._drag_active = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_4, 0, theme.SPACE_4, 0)
        layout.setSpacing(theme.SPACE_4)

        self.badge = ClickableLabel("SV")
        self.badge.setFixedSize(22, 22)
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setStyleSheet(
            f"""
            border: 1px solid {theme.ACCENT};
            border-radius: {theme.RADIUS_SM}px;
            font-size: 9px;
            font-weight: 600;
            color: {theme.ACCENT};
            """
        )
        self.badge.clicked.connect(self.home_clicked.emit)

        wordmark = ClickableLabel("SVMIX")
        wordmark.setStyleSheet(
            f"font-size: 12px; font-weight: 500; letter-spacing: 2px; color: {theme.NEUTRAL[300]};"
        )
        wordmark.clicked.connect(self.home_clicked.emit)

        divider = QWidget()
        divider.setFixedSize(1, 14)
        divider.setStyleSheet(f"background-color: {theme.NEUTRAL[800]};")

        self.crumb_label = ClickableLabel("Session · untitled")
        self.crumb_label.setStyleSheet(f"font-size: 11px; color: {theme.NEUTRAL[400]};")

        layout.addWidget(self.badge)
        layout.addWidget(wordmark)
        layout.addWidget(divider)
        layout.addWidget(self.crumb_label)
        layout.addStretch(1)

        self.minimize_btn = self._window_button("–")
        self.maximize_btn = self._window_button("□")
        self.close_btn = self._window_button("✕")
        self.minimize_btn.clicked.connect(self.minimize_clicked.emit)
        self.maximize_btn.clicked.connect(self.maximize_clicked.emit)
        self.close_btn.clicked.connect(self.close_clicked.emit)

        layout.addWidget(self.minimize_btn)
        layout.addWidget(self.maximize_btn)
        layout.addWidget(self.close_btn)

    def _window_button(self, glyph):
        btn = ClickableLabel(glyph)
        btn.setFixedSize(24, 24)
        btn.setAlignment(Qt.AlignCenter)
        btn.setStyleSheet(f"font-size: 12px; color: {theme.NEUTRAL[500]};")
        return btn

    def set_crumb(self, text):
        self.crumb_label.setText(text)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.maximize_clicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
