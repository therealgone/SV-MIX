"""Locate the ffmpeg that SVMixer should use, preferring a bundled copy.

Packaged builds (the Store MSIX and the Setup.exe installer) ship an LGPL
build of ffmpeg inside the application folder, so the app works without the
user installing anything. Running from source falls back to vendor/ffmpeg/
if it has been fetched (packaging/windows/fetch_ffmpeg.ps1), and finally to
whatever ffmpeg is on PATH.

pydub discovers ffmpeg *and* ffprobe by name via shutil.which, so the
reliable way to redirect it is to put the bundled folder at the front of
this process's PATH. We also set pydub's explicit converter attributes,
which covers the ffmpeg side even if PATH lookup is bypassed.
"""

import os
import shutil
import sys
from pathlib import Path

_EXE = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
_PROBE = "ffprobe.exe" if os.name == "nt" else "ffprobe"

_configured = False


def _candidate_dirs():
    """Folders that may hold a bundled ffmpeg, most specific first."""
    # PyInstaller onefile / onedir unpack location.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        yield Path(meipass) / "ffmpeg"

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        # PyInstaller >= 6 puts collected data under _internal/.
        yield exe_dir / "_internal" / "ffmpeg"
        yield exe_dir / "ffmpeg"

    # Running from source.
    yield Path(__file__).resolve().parent / "vendor" / "ffmpeg" / "bin"


def find_ffmpeg_dir():
    """Return the bundled ffmpeg folder, or None if there isn't one."""
    for d in _candidate_dirs():
        if (d / _EXE).is_file():
            return d
    return None


def configure():
    """Point this process (and pydub) at the bundled ffmpeg, if present.

    Safe to call more than once. Returns the folder used, or None when
    falling back to a system ffmpeg on PATH.
    """
    global _configured
    if _configured:
        return find_ffmpeg_dir()

    d = find_ffmpeg_dir()
    if d is not None:
        # Front of PATH so pydub's shutil.which finds ffprobe too, and so
        # any child process inherits it.
        os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
        try:
            from pydub import AudioSegment

            AudioSegment.converter = str(d / _EXE)
            probe = d / _PROBE
            if probe.is_file():
                AudioSegment.ffprobe = str(probe)
        except Exception:
            # pydub not importable yet; PATH alone is enough for it to work
            # once it is imported.
            pass

    _configured = True
    return d


def ffmpeg_available():
    """True if ffmpeg is usable — bundled or already on the user's PATH."""
    configure()
    return find_ffmpeg_dir() is not None or shutil.which("ffmpeg") is not None
