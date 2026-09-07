"""Entry point for the SVMixer desktop app."""

import shutil
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from .ui.main_window import MainWindow

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
    app = QApplication(sys.argv)
    app.setApplicationName("SVMixer")

    window = MainWindow()
    window.show()

    if shutil.which("ffmpeg") is None:
        QMessageBox.warning(window, "ffmpeg not found", FFMPEG_MISSING_MESSAGE)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
