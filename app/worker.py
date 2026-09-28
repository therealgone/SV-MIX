"""Background worker that runs the mashup pipeline off the UI thread."""

import shutil

from PySide6.QtCore import QThread, Signal

import pipeline


class MixWorker(QThread):
    """Runs pipeline.process_files() on a background thread so the UI
    stays responsive while songs are analyzed and combined. For a video
    mix it then also renders the mp4 to video_output_path (the analysis
    fills the first part of the progress range, the encode the rest) and
    adds it to the result as "video_path".
    """

    progress = Signal(str, int)   # (status message, percent 0-100)
    finished_ok = Signal(dict)    # result dict from pipeline.process_files
    failed = Signal(str)          # unexpected error message

    # Share of the progress bar the analysis gets in a video mix; the
    # encode is usually the longer half.
    _VIDEO_ANALYSIS_SHARE = 0.45

    def __init__(self, filepaths, mode, target_duration_sec, hook_type,
                 locked_paths=(), media_type=pipeline.MEDIA_AUDIO,
                 video_output_path=None, precut_paths=(), parent=None):
        super().__init__(parent)
        self.filepaths = filepaths
        self.mode = mode
        self.target_duration_sec = target_duration_sec
        self.hook_type = hook_type
        self.locked_paths = list(locked_paths)
        self.precut_paths = list(precut_paths)
        self.media_type = media_type
        self.video_output_path = video_output_path
        self._cancelled = False

    def cancel(self):
        """Stop an in-progress video render (the analysis itself runs to
        completion, but its result is then ignored by the caller)."""
        self._cancelled = True

    def run(self):
        is_video = self.media_type == pipeline.MEDIA_VIDEO
        share = self._VIDEO_ANALYSIS_SHARE if is_video else 1.0
        try:
            result = pipeline.process_files(
                self.filepaths,
                mode=self.mode,
                target_duration_sec=self.target_duration_sec,
                hook_type=self.hook_type,
                progress_callback=lambda m, p: self._report(m, int(p * share)),
                locked_paths=self.locked_paths,
                media_type=self.media_type,
                precut_paths=self.precut_paths,
            )
            if is_video and result["mix"] is not None and not self._cancelled:
                base = int(share * 100)
                pipeline.render_video_mix(
                    result["clips"],
                    result["mix"],
                    self.video_output_path,
                    progress_callback=lambda m, p: self._report(m, base + int(p * (100 - base) / 100)),
                    should_cancel=lambda: self._cancelled,
                )
                result["video_path"] = self.video_output_path
            self.finished_ok.emit(result)
        except pipeline.RenderCancelled:
            self.failed.emit("Cancelled")
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


class FileCopyWorker(QThread):
    """Copies an already-rendered file (a video mix's preview) to where
    the user chose to save it, off the UI thread -- these can be hundreds
    of MB.
    """

    finished_ok = Signal(str)   # output path
    failed = Signal(str)        # error message

    def __init__(self, source_path, output_path, parent=None):
        super().__init__(parent)
        self.source_path = source_path
        self.output_path = output_path

    def run(self):
        try:
            shutil.copyfile(self.source_path, self.output_path)
            self.finished_ok.emit(self.output_path)
        except Exception as e:
            self.failed.emit(str(e))


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
