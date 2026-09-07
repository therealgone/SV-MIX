"""Nocturne dark theme: color/spacing/radius tokens and global stylesheet.

Ported from the "Nocturne" design system used in the SVMix UI redesign
brief (SVMix.dc.html / _ds/nocturne-.../styles.css). Values are copied
from that CSS so the two stay visually identical.
"""

import os

from PySide6.QtGui import QFontDatabase

BG = "#161826"
SURFACE = "#232532"
TEXT = "#e9e9ed"
ACCENT = "#9184d9"
ACCENT_2 = "#a7a1db"
DIVIDER = "rgba(233, 233, 237, 0.16)"

NEUTRAL = {
    100: "#f3f5fe",
    200: "#e4e7f5",
    300: "#cfd3e5",
    400: "#b2b6ca",
    500: "#9397ab",
    600: "#75798c",
    700: "#595d6c",
    800: "#3f424d",
    900: "#292b31",
}

ACCENT_RAMP = {
    100: "#f5f4ff",
    200: "#e7e5fe",
    300: "#d2cefd",
    400: "#b5abfc",
    500: "#968ae0",
    600: "#796cbf",
    700: "#5d5294",
    800: "#423a6a",
    900: "#2b2741",
}

SPACE_1, SPACE_2, SPACE_3, SPACE_4, SPACE_6, SPACE_8 = 3, 6, 8, 11, 17, 22
RADIUS_SM, RADIUS_MD, RADIUS_LG = 4, 8, 14

FONT_FAMILY = "Inter"

_FONTS_DIR = os.path.join(os.path.dirname(__file__), "assets", "fonts")


def load_fonts():
    """Registers the bundled Inter font files with Qt so the app matches
    the design system without any runtime network request. Safe to call
    once at startup; silently does nothing if the files aren't present
    (falls back to the system sans-serif stack).
    """
    if not os.path.isdir(_FONTS_DIR):
        return
    for filename in os.listdir(_FONTS_DIR):
        if filename.lower().endswith(".ttf"):
            QFontDatabase.addApplicationFont(os.path.join(_FONTS_DIR, filename))


def stylesheet():
    return f"""
    * {{
        font-family: "{FONT_FAMILY}", sans-serif;
    }}
    QWidget {{
        color: {TEXT};
    }}
    QMainWindow, QWidget#root {{
        background-color: {BG};
    }}
    QLabel {{
        background: transparent;
    }}
    QToolTip {{
        background-color: {SURFACE};
        color: {TEXT};
        border: 1px solid {NEUTRAL[800]};
        padding: 4px 8px;
        border-radius: {RADIUS_SM}px;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {NEUTRAL[700]};
        border-radius: 4px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {NEUTRAL[600]};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QListWidget {{
        background: transparent;
        border: none;
        outline: none;
    }}
    QListWidget::item {{
        border: none;
    }}
    QListWidget::item:selected {{
        background: transparent;
    }}
    QMessageBox {{
        background-color: {SURFACE};
    }}
    QMessageBox QLabel {{
        color: {TEXT};
    }}
    """
