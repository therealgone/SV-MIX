# SVMixer — Architecture

This document describes how SVMixer is put together, for anyone who needs
to modify or redesign it without having to reverse-engineer the code from
scratch (e.g. rebuilding the UI). It focuses on **what each piece does and
how they're wired together**, not on styling opinions — the current visual
design is intentionally simple and is documented at the bottom purely as a
reference for what exists today, not as a constraint on what it should
become.

## High-level shape

SVMixer is a 3-screen desktop wizard: **Upload → Processing → Done**. The
user picks songs and settings on screen 1, watches progress on screen 2,
then previews/saves the result on screen 3 (or goes back to screen 1 to
start over). All the actual audio analysis and mixing logic is isolated
in one dependency-free module, `pipeline.py`, which knows nothing about
Qt — the UI is a thin, replaceable layer on top of it.

```
┌─────────────────┐     ┌──────────────────┐     ┌───────────────┐
│  UploadScreen    │ ──▶ │ ProcessingScreen  │ ──▶ │  DoneScreen    │
│  (pick files +    │     │  (progress bar)    │     │  (preview,     │
│   settings)       │     │                    │     │   save/restart)│
└─────────────────┘     └──────────────────┘     └───────────────┘
        ▲                                                  │
        └──────────────── "Start New Mix" ─────────────────┘
```

`MainWindow` (`app/ui/main_window.py`) owns a `QStackedWidget` holding all
three screens and is the only place that switches between them. Screens
never talk to each other directly — they only emit signals that
`MainWindow` listens to and reacts to.

## Core domain model (`pipeline.py`)

This is the part a UI redesign must accommodate; it's independent of Qt
and unit-testable on its own.

### Two independent axes of control

Every mix is defined by picking one value from each of two independent
enums, plus a target duration:

**Mix mode** — *how much* of each song is used and how the mix is
assembled:
| Mode | Constant | Behavior |
|---|---|---|
| Normal Mix | `MODE_NORMAL` | Every song's hook exactly once, no repeats. |
| Loop Mix | `MODE_LOOP` | Every song once, then reprises (a second, different section of the same song) added to fill out longer target durations. |
| Ultra Mix | `MODE_ULTRA` | Songs chopped into short chunks and interleaved round-robin instead of played end-to-end — fast, choppy, hype. |

**Hook type** — *which part* of each song counts as its hook:
| Hook type | Constant | Behavior |
|---|---|---|
| Normal Hook | `HOOK_TYPE_NORMAL` | The single loudest window in the song. |
| Melody Hook | `HOOK_TYPE_MELODY` | The calmest, slowest window (local tempo ≤ 115 BPM). Songs with no window that slow are **skipped**. |
| Rock-Dance Hook | `HOOK_TYPE_DANCE` | The window that's both loudest and brightest (spectral centroid). Songs with no dynamic contrast are **skipped**. |
| Kuthu Dance Hook | `HOOK_TYPE_KUTHU` | The window that's loudest and fastest-tempo (energy-weighted). Only fails on genuine silence. |

A song can be skipped entirely for a given hook type (see table above);
skipped songs are surfaced to the user as `(filename, reason)` pairs
rather than silently dropped. Any UI needs a way to show this list —
today it's a collapsible panel on the Done screen.

Both axes are set via plain string constants and companion label dicts
(`MIX_MODES`/`MODE_LABELS`, `HOOK_TYPES`/`HOOK_TYPE_LABELS`) — a redesign
can iterate these to populate any kind of selector (dropdown, segmented
control, radio group, etc.) without hardcoding the option list.

### Duration

`estimate_duration_range(num_songs, mode) -> (min_sec, max_sec)` is pure
arithmetic (no audio decoding), so it's cheap to call live as the user
adds/removes files or changes mode — used today to keep a duration slider's
range in sync. The actual duration control is just an integer number of
seconds within that range.

### Processing entry point

Everything funnels through one function:

```python
process_files(filepaths, mode, target_duration_sec, hook_type, progress_callback) -> {
    "mix": AudioSegment | None,
    "processed_filenames": [str, ...],
    "skipped": [(filename, reason), ...],
    "total_hooks": int,
}
```

`progress_callback(message: str, percent: int)` is invoked repeatedly
during processing — this is the only progress-reporting mechanism, and
it's what feeds the Processing screen's progress bar/status text today.
This function is synchronous and can take anywhere from a few seconds to
over a minute depending on file count/size, which is why the UI always
runs it on a background thread (see below) rather than calling it
directly.

## UI layer (`app/`)

### Threading model (`app/worker.py`)

Qt's UI must never block, and `process_files` / MP3 export are both slow,
so both run on `QThread` subclasses:

- **`MixWorker(filepaths, mode, target_duration_sec, hook_type)`** — runs
  `pipeline.process_files`. Emits `progress(str, int)` repeatedly,
  then either `finished_ok(dict)` (the result dict above) or
  `failed(str)` on an unexpected exception.
- **`ExportWorker(mix, output_path)`** — runs `pipeline.export_mix`
  (encodes an `AudioSegment` to MP3). Emits `finished_ok(str)` (the output
  path) or `failed(str)`.

Any UI redesign should keep this split: kick off a worker, show a
busy/progress state, and react to its signals — never call `pipeline`
functions directly from the main thread for anything that touches whole
files.

### `MainWindow` (`app/ui/main_window.py`)

Owns the `QStackedWidget` and both worker instances. Key methods:

- `start_processing(filepaths, mode, target_duration_sec, hook_type)` —
  switches to the Processing screen and starts a `MixWorker`.
- `_on_processing_finished(result)` — if `result["mix"]` is `None`
  (nothing could be processed), shows a warning dialog listing why every
  file was skipped and returns to Upload. Otherwise stashes the mix and
  kicks off an `ExportWorker` to render a temp-file preview.
- `_on_preview_ready(preview_path)` — switches to the Done screen.
- `save_mix()` — opens a native "Save As" dialog, then runs a second
  `ExportWorker` against the chosen path.
- `start_new_mix()` — resets Upload screen state and switches back to it.
- `closeEvent` — waits for any in-flight worker, stops playback, and
  deletes the temp preview directory.

A temp directory (`tempfile.mkdtemp`) is created once per app session for
the preview MP3; it's cleaned up on window close.

### `UploadScreen` (`app/ui/upload_screen.py`)

Responsible for: file selection, both mode/hook-type selectors, the
duration slider, and kicking off a mix.

State: `self.filepaths` — an ordered, de-duplicated list of absolute file
paths (order = the order files were added, not display order).

Key widgets and what they map to:
- `DropArea` (drag-and-drop / click-to-browse) → calls `add_files(paths)`.
- `QListWidget` of `FileRowWidget` rows → one per file, each with a remove
  (✕) button.
- `mode_combo` (`QComboBox`) → populated from `pipeline.MIX_MODES` /
  `MODE_LABELS`; a `mode_description` label under it shows freeform text
  from a local `MODE_DESCRIPTIONS` dict (UI-only, not in `pipeline.py`).
- `hook_type_combo` → same pattern, from `pipeline.HOOK_TYPES` /
  `HOOK_TYPE_LABELS`, with `HOOK_TYPE_DESCRIPTIONS` for the helper text.
- `duration_slider` (`QSlider`) → range recalculated on every file-list or
  mode change via `pipeline.estimate_duration_range`; a label shows the
  current target plus the achievable min/max.
- `mix_button` → disabled until ≥2 files are present; emits the screen's
  one public signal.

Public signal (the entire contract other screens/MainWindow rely on):
```python
mix_requested = Signal(list, str, int, str)
# (filepaths: list[str], mode: str, target_duration_sec: int, hook_type: str)
```

`reset()` clears the file list and puts both combos back to their
defaults (Loop Mix / Normal Hook) — called when the user starts a new mix.

### `ProcessingScreen` (`app/ui/processing_screen.py`)

Stateless display only: a `QProgressBar` (0–100) and a status `QLabel`,
driven entirely by `set_progress(message, percent)` calls forwarded from
`MixWorker.progress`. `reset()` puts both back to their initial state.

### `DoneScreen` (`app/ui/done_screen.py`)

- `QMediaPlayer` + `QAudioOutput` for in-app preview playback of the
  temp-file MP3, toggled by one play/pause button.
- `set_result(preview_path, duration_seconds, skipped)` — loads the
  preview, updates the duration label, and populates a collapsible
  skipped-files list (`QToolButton` + `QListWidget`) — hidden entirely if
  nothing was skipped.
- Two action buttons: **Save As...** (`save_requested` signal, no
  payload — `MainWindow` owns the actual mix data) and **Start New
  Mix** (`new_mix_requested` signal).
- `stop_playback()` — called externally (by `MainWindow`) whenever the
  screen is being left or the window is closing, so audio doesn't keep
  playing in the background.

### `DropArea` (`app/ui/drop_area.py`)

Self-contained drag-and-drop target that also opens a native file picker
on click. Filters dropped/selected paths by extension
(`pipeline.AUDIO_EXTENSIONS`) before emitting `files_selected = Signal(list)`.

### `FileRowWidget` (`app/ui/file_row_widget.py`)

One row: filename (elided/expanding), formatted duration, remove button.
Emits `remove_clicked = Signal(str)` with the filepath so the parent list
can drop it from `UploadScreen.filepaths`.

## Full signal/slot wiring map

For a redesign to preserve behavior, these connections need to exist in
some form (widget structure/styling can change freely, this contract
shouldn't):

```
DropArea.files_selected(list[str])
    → UploadScreen.add_files

FileRowWidget.remove_clicked(str)
    → UploadScreen._remove_file

UploadScreen.mix_requested(list[str], str, int, str)
    → MainWindow.start_processing

MixWorker.progress(str, int)
    → ProcessingScreen.set_progress
MixWorker.finished_ok(dict)
    → MainWindow._on_processing_finished
MixWorker.failed(str)
    → MainWindow._on_processing_failed

ExportWorker.finished_ok(str)
    → MainWindow._on_preview_ready  (first run, for the preview)
    → MainWindow._on_save_finished  (second run, for Save As)
ExportWorker.failed(str)
    → MainWindow._on_preview_failed / _on_save_failed

DoneScreen.save_requested()
    → MainWindow.save_mix
DoneScreen.new_mix_requested()
    → MainWindow.start_new_mix
```

## Validation / edge-case rules the UI encodes today

- Mixing requires **≥ 2 files** (`mix_button` stays disabled below that).
- Only `.mp3` / `.wav` / `.m4a` are accepted, both via drop and browse
  (`pipeline.AUDIO_EXTENSIONS`); anything else is silently filtered out.
- Duplicate file paths are ignored on add (`UploadScreen.filepaths`
  dedupes).
- If **every** selected file gets skipped (`result["mix"] is None`), the
  user sees a warning dialog with per-file reasons and is returned to the
  Upload screen rather than proceeding to an empty Done screen.
- ffmpeg availability is checked once at app startup (`app/main.py`); if
  missing, a non-blocking warning explains the app will still open but
  mixing will fail, with install instructions per OS.

## Current visual design (reference only)

There is no shared stylesheet or theme module today — every widget sets
its own inline `setStyleSheet(...)` string. This is the full palette in
use, extracted directly from the code, if a redesign wants a starting
point or a clean break:

| Hex | Rough usage today |
|---|---|
| `#2c3e50` | Primary text / titles |
| `#5c6b7a` | Secondary/help text |
| `#7f8c99` | Tertiary text (durations, subtitles) |
| `#9aa5b1` | Borders (drop area, disabled states) |
| `#4a90d9` | Primary action color (buttons, progress fill, focus) |
| `#3b7bc4` | Primary action hover |
| `#eef5fc` | Primary-tinted hover background (drop area) |
| `#d5d9dd` / `#f0f2f5` | Disabled button bg / text |
| `#eef1f4` / `#e1e5ea` | Secondary button bg / hover, panel borders |
| `#f7f9fb` | Drop area default background |
| `#b0392a` / `#7a3229` | Error/warning/destructive text (skipped files, remove button) |
| `#fbe4e0` / `#fdf6f5` / `#f0d4cf` | Error/warning tinted backgrounds |

Typography is plain system default font, sized inline per label (13–20px
range, titles bolded at weight 600–700). There's no icon set beyond a
couple of Unicode glyphs (🎵 drop icon, ▶/⏸ playback, ✕ remove, ▶/▼ arrow
for the collapsible skipped-list toggle) — a redesign is free to replace
these with a real icon set.
