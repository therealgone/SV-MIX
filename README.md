# SVMixer

SVMixer is a desktop app that turns a folder of songs into one continuous,
crossfaded "party mix" automatically. Drop in your songs, pick how they
should be combined, and SVMixer analyzes each track's tempo and energy,
picks out the best section ("hook") of each one, beat-snaps the cut
points, and crossfades everything together into a single exportable
MP3 — no manual editing required.

It ships as both a PySide6 (Qt) desktop GUI and a plain command-line
script, both built on the same analysis engine (`pipeline.py`).

## Features

- **Drag-and-drop** or file-browser song selection, `.mp3` / `.wav` / `.m4a` supported.
- **Automatic hook detection** — every song is analyzed for tempo (BPM) and
  energy, and the strongest section is extracted and beat-aligned, so cuts
  land musically instead of mid-phrase.
- **Three mix modes** (how much of each song is used, and how long the
  final mix runs):
  - **Normal Mix** — every song used exactly once, no repeats.
  - **Loop Mix** — every song plays once, then reprises (a different
    section of the same song) fill in the rest for longer mixes.
  - **Ultra Mix** — a fast, hype mashup: songs are chopped into short
    interleaved bursts instead of played end-to-end.
- **Four hook types** (which part of each song is picked as "the hook"),
  independent of mix mode:
  - **Normal Hook** — the loudest section of the song.
  - **Melody Hook** — the calmest, slowest section (tempo ≤ 115 BPM).
    Songs that never dip below that — i.e. that are "hype" throughout —
    are skipped rather than forced into a fake calm pick.
  - **Rock-Dance Hook** — the loudest *and* brightest ("drop"-like) section.
  - **Kuthu Dance Hook** — the loudest, fastest-paced section, tuned for
    high-energy Tamil "kuthu"/mass-dance style tracks.
- **Live preview** of the finished mix before saving, with a clear list of
  any songs that were skipped and why.
- **Fully offline** — all analysis and audio processing happens locally.
  SVMixer makes no network requests and collects no user data.

## Requirements

- Python 3.9+ (3.13+ also supported — see `requirements.txt`)
- [ffmpeg](https://ffmpeg.org/) installed and available on your system `PATH`
  (used by `pydub` to decode/encode mp3, wav, and m4a files). The GUI will
  warn you on startup if it can't find ffmpeg.
  - **Windows:** download from https://ffmpeg.org/download.html and add it to PATH
  - **macOS:** `brew install ffmpeg`
  - **Linux:** `sudo apt install ffmpeg` (or your distro's package manager)

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### Desktop app

```bash
python run_app.py
```

1. Drag in (or browse for) two or more audio files.
2. Choose a mix mode and hook type, and set the target mix length with the
   slider.
3. Click **Mix Songs**. Progress is shown live while each song is analyzed.
4. Preview the result, then **Save As...** to export it as an MP3, or
   **Start New Mix** to begin again.

### Command-line

Drop audio files into a `songs/` folder next to `mashup.py` (or edit the
`INPUT_FOLDER` constant at the top of the file), then run:

```bash
python mashup.py
```

The mix is written to `output/party_mix.mp3`, using every available hook
for every song (main hook + reprise), ordered by BPM. Progress prints to
the console, and any skipped files are reported with a reason.

## Configuration

All the tunable constants that shape how mixes are built — crossfade
length, hook length, how much of a song's intro/outro is ignored, the
BPM thresholds behind each hook type, etc. — live at the top of
`pipeline.py`, each with an explanatory comment.

## Project structure

```
run_app.py          Desktop app entry point
mashup.py            CLI entry point
pipeline.py          Core analysis/mixing engine (no UI dependencies)
app/
  main.py            QApplication bootstrap, window icon, ffmpeg pre-flight check
  worker.py           Background QThread workers (keep the UI responsive)
  ui/
    main_window.py    Hosts the Setup/Studio screens and wires them together
    title_bar.py      Custom frameless-window chrome (logo, breadcrumb, controls)
    setup_screen.py   File list, mix mode / hook type / length controls
    studio_screen.py  Progress ring while mixing, then preview/save/restart
    widgets.py         Custom-painted controls (segmented switch, dials, ring)
    theme.py            Nocturne color/spacing tokens + global stylesheet
    drop_area.py        Drag-and-drop / browse widget
    file_row_widget.py  File list row (name, duration, remove button)
    assets/              Bundled fonts, logo, and app icon
packaging/
  windows/            PyInstaller spec + Inno Setup script — see BUILD_WINDOWS.md
```

See `ARCHITECTURE.md` for a deeper technical breakdown of how the screens,
workers, and pipeline fit together, and `BUILD_WINDOWS.md` for packaging
SVMixer as a standalone Windows installer.

## Privacy & offline use

SVMixer performs all song analysis and audio processing locally on your
machine. It does not make network requests, does not phone home, and does
not collect, store, or transmit any user data or telemetry.

## Notes for packaging / distribution

- The `songs/` and `output/` folders (if present in a local checkout) are
  personal test data and generated output — they are excluded via
  `.gitignore` and must not be bundled into any packaged/distributed build.
- PySide6 is distributed under LGPLv3 (with a commercial option); if you
  package SVMixer as a compiled/frozen app (e.g. via PyInstaller), keep
  Qt/PySide6 dynamically linked and include the required LGPL attribution
  per Qt's licensing terms.
- See `BUILD_WINDOWS.md` for step-by-step instructions on building a
  standalone `SVMixer-Setup.exe` Windows installer with PyInstaller +
  Inno Setup.
