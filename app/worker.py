"""Background worker that runs the mashup pipeline off the UI thread."""

from PySide6.QtCore import QThread, Signal

import pipeline


class MixWorker(QThread):
    """Runs pipeline.process_files() on a background thread so the UI
    stays responsive while songs are analyzed and combined.
    """

    progress = Signal(str, int)   # (status message, percent 0-100)
    finished_ok = Signal(dict)    # result dict from pipeline.process_files
    failed = Signal(str)          # unexpected error message

    def __init__(self, filepaths, mode, target_duration_sec, hook_type, parent=None):
        super().__init__(parent)
        self.filepaths = filepaths
        self.mode = mode
        self.target_duration_sec = target_duration_sec
        self.hook_type = hook_type

    def run(self):
        try:
            result = pipeline.process_files(
                self.filepaths,
                mode=self.mode,
                target_duration_sec=self.target_duration_sec,
                hook_type=self.hook_type,
                progress_callback=self._report,
            )
            self.finished_ok.emit(result)
        except Exception as e:
            self.failed.emit(str(e))

    def _report(self, message, percent):
        self.progress.emit(message, percent)


class DurationProbeWorker(QThread):
    """Reads each file's duration (shells out to ffprobe via pydub's
    mediainfo) on a background thread -- doing this on the UI thread for
    a batch of files blocks the event loop long enough that the window
    manager flags the app as "not responding".
    """

    duration_ready = Signal(str, object)  # (filepath, duration_seconds or None)

    def __init__(self, filepaths, parent=None):
        super().__init__(parent)
        self.filepaths = list(filepaths)

    def run(self):
        for path in self.filepaths:
            duration = pipeline.get_duration_seconds(path)
            self.duration_ready.emit(path, duration)


class ExportWorker(QThread):
    """Runs pipeline.export_mix() on a background thread so the UI stays
    responsive while pydub/ffmpeg encodes the mp3.
    """

    finished_ok = Signal(str)   # output path
    failed = Signal(str)        # error message

    def __init__(self, mix, output_path, parent=None):
        super().__init__(parent)
        self.mix = mix
        self.output_path = output_path

    def run(self):
        try:
            pipeline.export_mix(self.mix, self.output_path)
            self.finished_ok.emit(self.output_path)
        except Exception as e:
            self.failed.emit(str(e))
