"""Custom-painted controls for the Nocturne UI: segmented mode switch, the
radial hook-type dial, the drag-arc length dial, and the studio progress
ring. None of these have a stock Qt equivalent, so they're built directly
on QPainter, porting the geometry/interaction math from the SVMix.dc.html
redesign spec (SVG shapes + pointer-angle math) to Qt coordinates.
"""

import math

from PySide6.QtCore import Property, QEasingCurve, QPointF, QPropertyAnimation, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from . import theme


class ClickableLabel(QLabel):
    """A QLabel that emits `clicked` on left-click, for text-only links
    (dial quadrant labels, the "Cancel" link, the title-bar SV badge)."""

    clicked = Signal()

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class SegmentedControl(QWidget):
    """A 3-way animated segmented switch, e.g. Normal / Loop / Ultra Mix."""

    changed = Signal(str)

    def __init__(self, options, parent=None):
        # options: list of (key, label)
        super().__init__(parent)
        self._keys = [key for key, _ in options]
        self._current = self._keys[0]
        self.setFixedHeight(38)
        self.setAttribute(Qt.WA_StyledBackground, True)

        self.setStyleSheet(
            f"""
            SegmentedControl {{
                background: {theme.NEUTRAL[900]};
                border: 1px solid {theme.NEUTRAL[800]};
                border-radius: {theme.RADIUS_MD}px;
            }}
            """
        )

        self._highlight = QFrameHighlight(self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._labels = {}
        for key, label in options:
            lbl = ClickableLabel(label)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.clicked.connect(lambda k=key: self.set_current(k))
            layout.addWidget(lbl, 1)
            self._labels[key] = lbl

        self._highlight.lower()
        self._refresh_colors()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_highlight(animate=False)

    def set_current(self, key, emit=True):
        if key == self._current:
            return
        self._current = key
        self._position_highlight(animate=True)
        self._refresh_colors()
        if emit:
            self.changed.emit(key)

    def current(self):
        return self._current

    def _position_highlight(self, animate):
        if self.width() <= 0:
            return
        idx = self._keys.index(self._current)
        n = len(self._keys)
        seg_w = self.width() / n
        x = round(idx * seg_w) + 3
        w = round(seg_w) - 6
        target = QRect(x, 3, w, self.height() - 6)
        if animate:
            anim = QPropertyAnimation(self._highlight, b"geometry", self)
            anim.setDuration(220)
            anim.setStartValue(self._highlight.geometry())
            anim.setEndValue(target)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.start()
            self._anim = anim
        else:
            self._highlight.setGeometry(target)

    def _refresh_colors(self):
        for key, lbl in self._labels.items():
            color = theme.TEXT if key == self._current else theme.NEUTRAL[500]
            lbl.setStyleSheet(
                f"font-size: 12px; font-weight: 600; color: {color}; background: transparent;"
            )


class QFrameHighlight(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"""
            background: {theme.ACCENT_RAMP[900]};
            border: 1px solid {theme.ACCENT};
            border-radius: {theme.RADIUS_SM}px;
            """
        )


class HookDial(QWidget):
    """Radial 4-quadrant hook-type selector with a rotating needle."""

    changed = Signal(str)

    # (key, label, needle angle in degrees)
    _HOOKS = [
        ("normal_hook", "Normal", -45),
        ("melody", "Melody", 45),
        ("dance", "Rock-Dance", 135),
        ("kuthu", "Kuthu", -135),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(240, 240)
        self._current_index = 0
        self._angle = self._HOOKS[0][2]

        self._name_label = QLabel(self)
        self._name_label.setGeometry(45, 94, 150, 20)
        self._name_label.setAlignment(Qt.AlignCenter)
        self._name_label.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {theme.TEXT}; background: transparent;"
        )

        self._sub_label = QLabel("HOOK", self)
        self._sub_label.setGeometry(45, 116, 150, 14)
        self._sub_label.setAlignment(Qt.AlignCenter)
        self._sub_label.setStyleSheet(
            f"font-size: 9px; color: {theme.NEUTRAL[400]}; background: transparent;"
        )

        positions = [
            (0, 34, 108, 18, Qt.AlignLeft | Qt.AlignVCenter),
            (132, 34, 108, 18, Qt.AlignRight | Qt.AlignVCenter),
            (132, 188, 108, 18, Qt.AlignRight | Qt.AlignVCenter),
            (0, 188, 108, 18, Qt.AlignLeft | Qt.AlignVCenter),
        ]
        self._corner_labels = []
        for i, (key, label, _angle) in enumerate(self._HOOKS):
            x, y, w, h, align = positions[i]
            lbl = ClickableLabel(label, self)
            lbl.setGeometry(x, y, w, h)
            lbl.setAlignment(align)
            lbl.clicked.connect(lambda k=key: self.set_current(k))
            self._corner_labels.append(lbl)

        self._name_label.setText(self._HOOKS[0][1])
        self._refresh_colors()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        cx, cy = 120.0, 120.0

        pen = QPen(QColor(theme.NEUTRAL[800]))
        pen.setWidthF(1)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), 96, 96)

        thick_pen = QPen(QColor(theme.ACCENT_RAMP[900]))
        thick_pen.setWidthF(14)
        painter.setPen(thick_pen)
        painter.drawEllipse(QPointF(cx, cy), 96, 96)

        painter.save()
        painter.translate(cx, cy)
        painter.rotate(self._angle)
        needle_pen = QPen(QColor(theme.ACCENT))
        needle_pen.setWidthF(1.5)
        painter.setPen(needle_pen)
        painter.drawLine(QPointF(0, 0), QPointF(0, -89))
        painter.setPen(needle_pen)
        painter.setBrush(QColor(theme.BG))
        painter.drawEllipse(QPointF(0, -96), 7, 7)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.ACCENT))
        painter.drawEllipse(QPointF(0, -96), 2.5, 2.5)
        painter.restore()

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.ACCENT))
        painter.drawEllipse(QPointF(cx, cy), 3, 3)

        painter.setBrush(QColor(theme.NEUTRAL[700]))
        for dx, dy in ((-68, -68), (68, -68), (68, 68), (-68, 68)):
            painter.drawEllipse(QPointF(cx + dx, cy + dy), 2, 2)

    def set_current(self, key, emit=True):
        idx = [h[0] for h in self._HOOKS].index(key)
        if idx == self._current_index:
            return
        self._current_index = idx
        self._animate_to(self._HOOKS[idx][2])
        self._name_label.setText(self._HOOKS[idx][1])
        self._refresh_colors()
        if emit:
            self.changed.emit(key)

    def current(self):
        return self._HOOKS[self._current_index][0]

    def _get_angle(self):
        return self._angle

    def _set_angle(self, value):
        self._angle = value
        self.update()

    angle = Property(float, _get_angle, _set_angle)

    def _animate_to(self, target):
        anim = QPropertyAnimation(self, b"angle", self)
        anim.setDuration(320)
        anim.setStartValue(self._angle)
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        self._anim = anim

    def _refresh_colors(self):
        for i, lbl in enumerate(self._corner_labels):
            selected = i == self._current_index
            color = theme.ACCENT if selected else theme.NEUTRAL[500]
            lbl.setStyleSheet(
                f"font-size: 11px; font-weight: 500; color: {color}; background: transparent;"
            )


class LengthDial(QWidget):
    """Circular drag-arc control for choosing the mix length fraction."""

    changed = Signal(float)  # fraction 0..1, emitted on user drag

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(240, 240)
        self.setCursor(Qt.OpenHandCursor)
        self._frac = 0.5
        self._dragging = False

    def set_fraction(self, frac, emit=False):
        frac = max(0.0, min(1.0, frac))
        if frac == self._frac:
            return
        self._frac = frac
        self.update()
        if emit:
            self.changed.emit(frac)

    def fraction(self):
        return self._frac

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        cx, cy = 120.0, 120.0

        dash_pen = QPen(QColor(theme.NEUTRAL[800]))
        dash_pen.setWidthF(6)
        dash_pen.setDashPattern([0.5, 4.4])
        dash_pen.setCapStyle(Qt.FlatCap)
        painter.setPen(dash_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), 112, 112)

        rect = QRectF(cx - 96, cy - 96, 192, 192)
        track_pen = QPen(QColor(theme.NEUTRAL[800]))
        track_pen.setWidthF(8)
        track_pen.setCapStyle(Qt.FlatCap)
        painter.setPen(track_pen)
        painter.drawArc(rect, int(-135 * 16), int(-270 * 16))

        if self._frac > 0:
            accent_pen = QPen(QColor(theme.ACCENT))
            accent_pen.setWidthF(8)
            accent_pen.setCapStyle(Qt.RoundCap)
            painter.setPen(accent_pen)
            painter.drawArc(rect, int(-135 * 16), int(-270 * 16 * self._frac))

        angle_deg = 135 + self._frac * 270
        angle_rad = math.radians(angle_deg)
        hx = cx + 96 * math.cos(angle_rad)
        hy = cy + 96 * math.sin(angle_rad)
        painter.setPen(QPen(QColor(theme.ACCENT), 1.5))
        painter.setBrush(QColor(theme.SURFACE))
        painter.drawEllipse(QPointF(hx, hy), 9, 9)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.ACCENT))
        painter.drawEllipse(QPointF(hx, hy), 3, 3)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self.setCursor(Qt.ClosedHandCursor)
            self._update_from_pos(event.position())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._update_from_pos(event.position())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            self.setCursor(Qt.OpenHandCursor)

    def _update_from_pos(self, pos):
        cx, cy = self.width() / 2.0, self.height() / 2.0
        dx = pos.x() - cx
        dy = pos.y() - cy
        deg = math.degrees(math.atan2(dy, dx))
        # Offset from the arc's start (135deg) going clockwise, normalized
        # into [0, 360). The valid arc spans [0, 270]; the remaining 90deg
        # is the visual gap at the bottom of the dial, split at its midpoint
        # so the pointer always snaps to whichever end it's closer to.
        rel = (deg - 135) % 360
        if rel > 270:
            rel = 270.0 if rel < 315 else 0.0
        frac = max(0.0, min(1.0, rel / 270.0))
        self.set_fraction(frac, emit=True)


class ProgressRing(QWidget):
    """Non-interactive ring used on the Studio screen: a dashed outer tick
    ring plus a solid track + accent progress arc, matching the mockup's
    circular progress indicator (and, when ready, hosting the play button
    as an overlay child placed by the caller)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(280, 280)
        self._percent = 0

    def set_percent(self, percent):
        percent = max(0, min(100, int(percent)))
        if percent == self._percent:
            return
        self._percent = percent
        self.update()

    def percent(self):
        return self._percent

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        cx, cy = 140.0, 140.0

        dash_pen = QPen(QColor(theme.NEUTRAL[800]))
        dash_pen.setWidthF(6)
        dash_pen.setDashPattern([0.5, 5.1])
        dash_pen.setCapStyle(Qt.FlatCap)
        painter.setPen(dash_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), 130, 130)

        rect = QRectF(cx - 112, cy - 112, 224, 224)
        track_pen = QPen(QColor(theme.NEUTRAL[800]))
        track_pen.setWidthF(10)
        painter.setPen(track_pen)
        painter.drawEllipse(rect)

        if self._percent > 0:
            accent_pen = QPen(QColor(theme.ACCENT))
            accent_pen.setWidthF(10)
            accent_pen.setCapStyle(Qt.RoundCap)
            painter.setPen(accent_pen)
            span = -int(360 * 16 * (self._percent / 100.0))
            painter.drawArc(rect, 90 * 16, span)
