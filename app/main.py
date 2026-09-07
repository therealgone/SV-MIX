"""Entry point for the SVMixer desktop app."""

import shutil
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from .ui import theme
from .ui.main_window import MainWindow

ICON_PATH = Path(__file__).parent / "ui" / "assets" / "logo" / "SV.ico"

FFMPEG_MISSING_MESSAGE = (
    "SVMixer uses ffmpeg to read and export audio (mp3/wav/m4a), but it "
    "wasn't found on your system PATH.\n\n"
    "You can still browse the app, but mixing will fail until ffmpeg is "
    "installed:\n"
    "  Windows: download from https://ffmpeg.org/download.html and add it to PATH\n"
    "  macOS:   brew install ffmpeg\n"
    "  Linux:   sudo apt install ffmpeg  (or your distro's package manager)"
)


def main():
    if sys.platform == "win32":
        # Without an explicit AppUserModelID, Windows groups the taskbar
        # icon under python.exe's own icon instead of ours.
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SVMixer.DesktopApp")

    app = QApplication(sys.argv)
    app.setApplicationName("SVMixer")
    app.setWindowIcon(QIcon(str(ICON_PATH)))

    theme.load_fonts()
    app.setStyleSheet(theme.stylesheet())

    window = MainWindow()
    window.setWindowIcon(QIcon(str(ICON_PATH)))
    window.show()

    if shutil.which("ffmpeg") is None:
        QMessageBox.warning(window, "ffmpeg not found", FFMPEG_MISSING_MESSAGE)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
