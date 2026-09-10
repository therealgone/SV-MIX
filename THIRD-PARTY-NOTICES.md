# Third-party notices

SVMixer redistributes the following third-party components.

## FFmpeg

SVMixer bundles a build of **FFmpeg** (`ffmpeg.exe`, `ffprobe.exe` and the
`libav*` / `libsw*` DLLs), used to decode and encode audio.

- **License:** GNU Lesser General Public License (LGPL), version 2.1 or
  later. The bundled build is compiled **without** `--enable-gpl`, so no
  GPL-only components are included.
- **Full license text:** shipped alongside the binaries as
  `ffmpeg/LICENSE.txt` inside the installed application, and at
  `vendor/ffmpeg/LICENSE.txt` in the source tree.
- **Binary build source:** https://github.com/BtbN/FFmpeg-Builds
  (`ffmpeg-master-latest-win64-lgpl-shared.zip`)
- **Corresponding source code:** https://git.ffmpeg.org/ffmpeg.git —
  the build configuration used is published at
  https://github.com/BtbN/FFmpeg-Builds
- **Modifications:** none. The binaries are redistributed unmodified.

The FFmpeg libraries ship as **separate, dynamically-loadable DLLs** and are
invoked as a **separate process**; they are not linked into SVMixer. A user
may therefore replace them with their own compatible FFmpeg build, which is
what the LGPL requires. `packaging/windows/fetch_ffmpeg.ps1` refuses to
stage any build advertising `--enable-gpl`.

## Qt / PySide6

SVMixer's user interface uses **PySide6** (Qt for Python).

- **License:** GNU Lesser General Public License (LGPL) v3.
- Qt is **dynamically linked** — PyInstaller ships the Qt DLLs as separate
  files rather than statically linking them — so it may be replaced with a
  compatible Qt build.
- **Source:** https://download.qt.io/official_releases/QtForPython/

## Python libraries

The following are bundled under permissive licenses (BSD/MIT/ISC), which
require attribution only:

| Package | License |
| --- | --- |
| librosa | ISC |
| numpy | BSD-3-Clause |
| scipy | BSD-3-Clause |
| numba / llvmlite | BSD-2-Clause |
| scikit-learn | BSD-3-Clause |
| soundfile | BSD-3-Clause |
| audioread, pooch, joblib, decorator | BSD/MIT |
| pydub | MIT |

Each package's full license text is included in its distribution inside the
application folder.
