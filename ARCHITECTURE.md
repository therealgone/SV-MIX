# SVMixer — Architecture

This document describes how SVMixer is put together, for anyone who needs
to modify or extend it without having to reverse-engineer the code from
scratch. It focuses on **what each piece does and how they're wired
together**, not on styling opinions.

## High-level shape

SVMixer is a 2-screen desktop app: **Setup → Studio**. The user picks
songs and mix settings on the Setup screen; the Studio screen shows live
progress while mixing, then flips in place to a result view (preview
player, skipped-files list, save/restart) once the mix is ready — there's
no separate "processing" screen, just two states of one screen. All the
actual audio analysis and mixing logic is isolated in one dependency-free
module, `pipeline.py`, which knows nothing about Qt — the UI is a thin,
replaceable layer on top of it.

```
┌──────────────────┐              ┌────────────────────────┐
│   SetupScreen     │ ──mix────▶  │      StudioScreen        │
│  (pick files +     │              │  isRunning: progress ring │
│   mode/hook/length) │              │  isReady:   preview/save   │
└──────────────────┘              └────────────────────────┘
        ▲                                            │
        └───────────────── "New mix" ─────────────────┘
```

`MainWindow` (`app/ui/main_window.py`) owns a custom frameless `TitleBar`
plus a `QStackedWidget` holding both screens, and is the only place that
switches between them. Screens never talk to each other directly — they
only emit signals that `MainWindow` listens to and reacts to.

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
rather than silently dropped — shown in the Studio screen's skipped-files
panel.

Both axes are set via plain string constants and companion label dicts
(`MIX_MODES`/`MODE_LABELS`, `HOOK_TYPES`/`HOOK_TYPE_LABELS`) — a redesign
can iterate these to populate any kind of selector without hardcoding the
option list.

### Duration

`estimate_duration_range(num_songs, mode) -> (min_sec, max_sec)` is pure
arithmetic (no audio decoding), so it's cheap to call live as the user
adds/removes files or changes mode — used today to keep the Length dial's
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
it's what feeds the Studio screen's progress ring/status text today.
This function is synchronous and can take anywhere from a few seconds to
over a minute depending on file count/size, which is why the UI always
runs it on a background thread (see below) rather than calling it
directly.

## UI layer (`app/`)

### Threading model (`app/worker.py`)

Qt's UI must never block, so anything slow runs on a `QThread` subclass:

- **`MixWorker(filepaths, mode, target_duration_sec, hook_type)`** — runs
  `pipeline.process_files`. Emits `progress(str, int)` repeatedly,
  then either `finished_ok(dict)` (the result dict above) or
  `failed(str)` on an unexpected exception.
- **`ExportWorker(mix, output_path)`** — runs `pipeline.export_mix`
  (encodes an `AudioSegment` to MP3). Emits `finished_ok(str)` (the output
  path) or `failed(str)`.
- **`DurationProbeWorker(filepaths)`** — reads each file's duration via
  `pipeline.get_duration_seconds` (shells out to `ffprobe` through
  pydub's `mediainfo`) one at a time, emitting `duration_ready(path,
  seconds)` per file. Doing this synchronously on the UI thread for a
  batch of files was slow enough to freeze the event loop and trigger a
  "not responding" OS prompt during file upload — this worker exists so
  `SetupScreen.add_files` can insert rows immediately and patch durations
  in as they resolve.

Any UI redesign should keep this split: kick off a worker, show a
busy/progress state, and react to its signals — never call `pipeline`
functions (or `get_duration_seconds` in bulk) directly from the main
thread for anything that touches whole files.

### `MainWindow` (`app/ui/main_window.py`)

Owns the `TitleBar`, the `QStackedWidget`, and all worker instances. Key
methods:

- `start_processing(filepaths, mode, target_duration_sec, hook_type)` —
  switches to the Studio screen (running state) and starts a `MixWorker`.
- `_on_processing_finished(result)` — if `result["mix"]` is `None`
  (nothing could be processed), shows a warning dialog listing why every
  file was skipped and returns to Setup. Otherwise stashes the mix and
  kicks off an `ExportWorker` to render a temp-file preview, under a
  **freshly generated filename each time** (`preview_<uuid>.mp3`) — reusing
  one fixed path across mixes in a session caused `QMediaPlayer` to skip
  reloading a changed file, since it can short-circuit `setSource()` on an
  identical `QUrl`.
- `_on_preview_ready(preview_path)` — flips the Studio screen to its ready
  state.
- `save_mix()` — opens a native "Save As" dialog, then runs a second
  `ExportWorker` against the chosen path.
- `start_new_mix()` — resets Setup screen state and switches back to it.
- `closeEvent` — waits for any in-flight worker, stops playback, and
  deletes the temp preview directory.

A temp directory (`tempfile.mkdtemp`) is created once per app session for
preview MP3s; it's cleaned up on window close.

### `TitleBar` (`app/ui/title_bar.py`)

Custom chrome for the frameless main window: SV badge + wordmark (both
clickable → `home_clicked`, used as a "back to Setup" shortcut), a
breadcrumb label (`set_crumb(text)`, e.g. "Session · mixing"), and
minimize/maximize/close buttons. Handles its own window-drag
(`startSystemMove()`) and double-click-to-maximize.

### `SetupScreen` (`app/ui/setup_screen.py`)

Responsible for: file selection, the mode/hook-type/length selectors, and
kicking off a mix. Two side-by-side panels: **Sources** (file list) and
**Session** (mix mode, hook dial, length dial, start button).

State:
- `self.filepaths` — an ordered, de-duplicated list of absolute file
  paths (order = the order files were added).
- `self._durations` — `{filepath: seconds|None}` cache, filled in
  asynchronously by `DurationProbeWorker` (see threading model above).
  `_update_empty_state()` sums from this cache rather than re-reading
  durations from disk, so it stays cheap no matter how often it's called.
- `self._rows` — `{filepath: FileRowWidget}` for O(1) row lookup when a
  duration probe result comes back.

Key widgets and what they map to:
- `DropArea` (drag-and-drop / click-to-browse) → calls `add_files(paths)`.
- `QListWidget` of `FileRowWidget` rows → one per file, each showing
  `--:--` until its duration probe resolves, with a remove (✕) button.
- `mode_control` (`SegmentedControl`, from `widgets.py`) → populated from
  a local `_MODE_OPTIONS` list mirroring `pipeline.MIX_MODES` /
  `MODE_LABELS`; `mode_desc_label` shows freeform text from a local
  `MODE_DESCRIPTIONS` dict (UI-only, not in `pipeline.py`).
- `hook_dial` (`HookDial`, from `widgets.py`) → a 4-quadrant radial
  selector over `pipeline.HOOK_TYPES`, with `HOOK_TYPE_DESCRIPTIONS` for
  the helper text.
- `length_dial` (`LengthDial`, from `widgets.py`) → a drag-arc control;
  its `0..1` fraction is mapped into `[range_lo_m, range_hi_m]` minutes,
  recalculated on every file-list or mode change via
  `pipeline.estimate_duration_range`.
- `mix_button` → disabled until ≥2 files are present; emits the screen's
  one public signal.

Public signal (the entire contract other screens/`MainWindow` rely on):
```python
mix_requested = Signal(list, str, int, str)
# (filepaths: list[str], mode: str, target_duration_sec: int, hook_type: str)
```

`reset()` clears the file list and both dials/segmented control back to
their defaults (Loop Mix / Normal Hook) — called when the user starts a
new mix.

### `StudioScreen` (`app/ui/studio_screen.py`)

One screen, two visual states toggled by `_set_running_visible(bool)`:

- **Running** — a `ProgressRing` (from `widgets.py`) plus percent/status
  labels, driven by `set_progress(message, percent)` calls forwarded from
  `MixWorker.progress`. A "Cancel" link is visible only in this state.
- **Ready** — `set_result(preview_path, duration_seconds, skipped,
  n_tracks)` swaps in the finished-mix view: a play/pause button over the
  ring, chips (mode/hook/length/tracks used), a collapsible skipped-files
  panel, and **Save mix** / **New mix** actions.

Playback: `QMediaPlayer` + `QAudioOutput`, toggled by `_toggle_playback()`.
Two defensive behaviors worth knowing about if touching this code:
- `set_result` explicitly clears the player's source (`setSource(QUrl())`)
  before loading the new preview, rather than relying on `setSource()`
  alone, since Qt Multimedia can otherwise no-op a same-looking reload.
- `_toggle_playback` resets position to `0` before calling `play()` if the
  player had already reached end-of-media — some backends don't restart
  from the beginning automatically once `PlaybackState` is `Stopped` at
  end-of-stream.

`stop_playback()` is called externally (by `MainWindow`) whenever the
screen is being left or the window is closing, so audio doesn't keep
playing in the background.

### `DropArea` (`app/ui/drop_area.py`)

Self-contained drag-and-drop target that also opens a native file picker
on click. Filters dropped/selected paths by extension
(`pipeline.AUDIO_EXTENSIONS`) before emitting `files_selected = Signal(list)`.

### `FileRowWidget` (`app/ui/file_row_widget.py`)

One row: filename (elided/expanding), formatted duration, remove button.
`set_duration(seconds)` updates the duration label in place once an
async probe resolves (initial duration may be `None` → shows `--:--`).
Emits `remove_clicked = Signal(str)` with the filepath so the parent list
can drop it from `SetupScreen.filepaths`.

### `widgets.py` — custom-painted controls

None of these have a stock Qt equivalent; they're built directly on
`QPainter`, porting geometry/interaction math from the Nocturne design
spec (SVG shapes + pointer-angle math) to Qt coordinates:

- **`ClickableLabel`** — a `QLabel` that emits `clicked` on left-click.
- **`SegmentedControl`** — animated N-way switch (e.g. Normal/Loop/Ultra
  Mix); an internal `QFrameHighlight` child slides between segments via
  `QPropertyAnimation` on its `geometry`.
- **`HookDial`** — 4-quadrant radial selector with a rotating needle
  (`angle` is a Qt `Property` so it can be animated).
- **`LengthDial`** — drag-arc control. Pointer position maps to an angle
  via `atan2`, then to a `0..1` fraction via
  `rel = (deg - 135) % 360` (normalized modulo-360 offset from the arc's
  135° start point, clamped into the valid 270° sweep) — this specific
  formulation matters because a naive un-normalized version mishandles
  the wraparound near the end of the arc and causes the last ~25% of the
  range to snap straight to the maximum instead of interpolating.
- **`ProgressRing`** — non-interactive dashed-tick ring + progress arc
  used behind the Studio screen's play button.

### `theme.py` — Nocturne design tokens

Color/spacing/radius constants (`BG`, `SURFACE`, `TEXT`, `ACCENT`,
`NEUTRAL`/`ACCENT_RAMP` ramps, `SPACE_*`, `RADIUS_*`) plus
`stylesheet()` (global `QApplication`-level rules) and `load_fonts()`
(registers the bundled Inter `.ttf` files so the app doesn't depend on
the font being installed system-wide).

**Qt stylesheet gotcha worth knowing before touching any panel/container
style:** a widget-instance `setStyleSheet(...)` call using *bare*
(unscoped) property declarations — e.g. `"border: 1px solid red;"` — leaks
onto every descendant widget that doesn't set its own override for that
property, per Qt's documented (non-CSS-standard) cascading behavior. Every
panel/container in this codebase scopes its stylesheet to an
`objectName`-based ID selector instead (`QWidget#panelBox { ... }`) to
avoid this. Relatedly, a plain `QWidget` subclass needs
`setAttribute(Qt.WA_StyledBackground, True)` for its own
`background`/`border` stylesheet properties to actually paint at all —
easy to forget when adding a new custom container.

## Full signal/slot wiring map

For a redesign to preserve behavior, these connections need to exist in
some form (widget structure/styling can change freely, this contract
shouldn't):

```
DropArea.files_selected(list[str])
    → SetupScreen.add_files
DurationProbeWorker.duration_ready(str, object)
    → SetupScreen._on_duration_ready

FileRowWidget.remove_clicked(str)
    → SetupScreen._remove_file

SetupScreen.mix_requested(list[str], str, int, str)
    → MainWindow.start_processing

MixWorker.progress(str, int)
    → StudioScreen.set_progress
MixWorker.finished_ok(dict)
    → MainWindow._on_processing_finished
MixWorker.failed(str)
    → MainWindow._on_processing_failed

ExportWorker.finished_ok(str)
    → MainWindow._on_preview_ready  (first run, for the preview)
    → MainWindow._on_save_finished  (second run, for Save As)
ExportWorker.failed(str)
    → MainWindow._on_preview_failed / _on_save_failed

StudioScreen.save_requested()
    → MainWindow.save_mix
StudioScreen.new_mix_requested()
    → MainWindow.start_new_mix
StudioScreen.cancel_requested()
    → MainWindow.cancel_processing

TitleBar.home_clicked() → MainWindow._on_home_clicked
TitleBar.minimize_clicked() → MainWindow.showMinimized
TitleBar.maximize_clicked() → MainWindow._toggle_maximize
TitleBar.close_clicked() → MainWindow.close
```

## Validation / edge-case rules the UI encodes today

- Mixing requires **≥ 2 files** (`mix_button` stays disabled below that).
- Only `.mp3` / `.wav` / `.m4a` are accepted, both via drop and browse
  (`pipeline.AUDIO_EXTENSIONS`); anything else is silently filtered out.
- Duplicate file paths are ignored on add (`SetupScreen.filepaths`
  dedupes).
- If **every** selected file gets skipped (`result["mix"] is None`), the
  user sees a warning dialog with per-file reasons and is returned to the
  Setup screen rather than proceeding to an empty Studio screen.
- ffmpeg availability is checked once at app startup (`app/main.py`); if
  missing, a non-blocking warning explains the app will still open but
  mixing will fail, with install instructions per OS.

## App icon

`app/ui/assets/logo/SV.ico` is a multi-resolution Windows icon (16–256px,
covering the standard Win32 small/taskbar/large/jumbo sizes) generated
from `SV.png`. `app/main.py` sets it as both the `QApplication` and
`MainWindow` window icon, and — on Windows only — calls
`SetCurrentProcessExplicitAppUserModelID` before creating the
`QApplication`, since without it Windows groups the taskbar icon under
`python.exe`'s own icon instead of SVMixer's when run unfrozen. If you
regenerate the logo, rebuild `SV.ico` the same way (`Pillow`,
`Image.save(..., format="ICO", sizes=[(s, s) for s in SIZES])`) rather
than hand-editing it.
