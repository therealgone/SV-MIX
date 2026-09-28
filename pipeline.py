"""
Core audio mashup pipeline: BPM detection, hook extraction (with an
optional reprise section), and crossfade combining.

Video sources (mp4 etc.) go through the exact same audio analysis; the
cut points found in their soundtrack are then applied to the picture as
well (see render_video_mix).

This module has no UI dependencies. It is used by the CLI script
(mashup.py) and by the PySide6 desktop app (app/).
"""

import os
import glob
import shutil
import subprocess
import tempfile
import warnings

import numpy as np
import librosa

import ffmpeg_support

# Point pydub at the bundled LGPL ffmpeg (if this is a packaged build)
# before importing it, so its ffmpeg/ffprobe lookup resolves there rather
# than to whatever may or may not be on the user's PATH.
ffmpeg_support.configure()

from pydub import AudioSegment
from pydub.utils import mediainfo

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

DEFAULT_INPUT_FOLDER = "./songs"
DEFAULT_OUTPUT_FOLDER = "./output"
DEFAULT_OUTPUT_FILENAME = "party_mix.mp3"

CROSSFADE_MS = 3000
EXPORT_BITRATE = "320k"

AUDIO_EXTENSIONS = (".mp3", ".wav", ".m4a")
VIDEO_EXTENSIONS = (".mp4", ".mkv", ".mov", ".webm")

# Media type of a mix: every source in one mix is either audio (mp3 out)
# or video (mp4 out) -- the two are never mixed together.
MEDIA_AUDIO = "audio"
MEDIA_VIDEO = "video"
MEDIA_EXTENSIONS = {
    MEDIA_AUDIO: AUDIO_EXTENSIONS,
    MEDIA_VIDEO: VIDEO_EXTENSIONS,
}
DEFAULT_VIDEO_OUTPUT_FILENAME = "party_mix.mp4"

ANALYSIS_SR = 22050          # sample rate used for BPM/energy analysis
ENERGY_WINDOW_SEC = 1.0      # window size for RMS energy estimation; also
                              # sets the step size hook-window scanning
                              # slides by, so smaller = finer-grained hook
                              # placement (at some extra analysis cost)

# How many seconds around a candidate window's own position to exclude
# when scoring it for "repetition" (see compute_repetition_strength) --
# a window always looks similar to its immediate neighbors just from
# audio continuity, which isn't the same thing as the section recurring
# elsewhere in the song (e.g. the chorus coming back later).
REPETITION_NEIGHBOR_SEC = 6.0

# Hook/segment length is dynamic per song rather than fixed: every song's
# kept hook is somewhere between HOOK_MIN_SEC and HOOK_MAX_SEC, with the
# exact length driven by how strongly that song's detected section fits
# the selected hook type relative to the other songs in the mix (see
# _compute_dynamic_lengths). HOOK_TARGET_SEC is the scan/extraction window
# used during analysis — it's set to the max, since trimming a segment
# down later is easy but you can never lengthen it back up.
HOOK_MIN_SEC = 20.0
HOOK_MAX_SEC = 35.0
HOOK_TARGET_SEC = HOOK_MAX_SEC
INTRO_SKIP_FRACTION = 0.15   # ignore first 15% of the track
OUTRO_SKIP_FRACTION = 0.10   # ignore last 10% of the track

HOOKS_PER_SONG = 2           # extract up to this many non-overlapping hooks
                              # per song, so a track can reappear later in
                              # the mix with a different part (reprise)

# Mix modes: how much of each song is used, and how songs are ordered,
# when the caller supplies a target_duration_sec to process_files().
MODE_NORMAL = "normal"       # every song used exactly once, no repeats
MODE_LOOP = "loop"           # today's reuse behavior, dynamic w/ duration
MODE_ULTRA = "ultra"         # fast interleaved mashup, chopped + reused
MIX_MODES = (MODE_NORMAL, MODE_LOOP, MODE_ULTRA)
MODE_LABELS = {
    MODE_NORMAL: "Normal Mix",
    MODE_LOOP: "Loop Mix",
    MODE_ULTRA: "Ultra Mix",
}

SEGMENT_MIN_SEC = HOOK_MIN_SEC   # shortest a kept hook segment is trimmed to
SEGMENT_MAX_SEC = HOOK_MAX_SEC   # longest a kept hook segment is trimmed to
ULTRA_CHUNK_MIN_SEC = SEGMENT_MIN_SEC / 2.0   # shortest an Ultra Mix interleaved half is
ULTRA_CHUNK_MAX_SEC = SEGMENT_MAX_SEC / 2.0   # longest

# Hook types: which part of each song gets used as the hook, independent
# of the mix mode above.
HOOK_TYPE_NORMAL = "normal_hook"   # today's behavior: loudest window
HOOK_TYPE_MELODY = "melody"        # calmer, less "bright" window
HOOK_TYPE_DANCE = "dance"          # loudest AND brightest window
HOOK_TYPE_KUTHU = "kuthu"          # loudest AND fastest-tempo window
HOOK_TYPES = (HOOK_TYPE_NORMAL, HOOK_TYPE_MELODY, HOOK_TYPE_DANCE, HOOK_TYPE_KUTHU)
HOOK_TYPE_LABELS = {
    HOOK_TYPE_NORMAL: "Normal Hook",
    HOOK_TYPE_MELODY: "Melody Hook",
    HOOK_TYPE_DANCE: "Rock-Dance Hook",
    HOOK_TYPE_KUTHU: "Kuthu Dance Hook",
}

# How flat a song's energy has to be (relative std of RMS in the valid
# region) before it's judged to have no distinct melody/dance section
# at all, and gets skipped for those hook types. This is only meant to
# catch genuinely degenerate tracks (near-silent or completely uniform)
# — a song that's consistently high-energy throughout still has valid
# dance material even without internal contrast, so this floor is kept
# low rather than requiring a strong quiet/loud split.
DISTINCT_DYNAMICS_MIN_RELATIVE_STD = 0.07
# A whole file quieter than this (average dBFS) has no usable audio at
# all -- typically a broken download -- and is skipped even if locked or
# pre-cut, rather than leaving a dead gap in the mix.
SILENT_FILE_DBFS = -60.0
# Melody windows must have at least this much RMS (percentile of the
# song's own RMS distribution) to avoid picking near-silent gaps.
MELODY_RMS_FLOOR_PERCENTILE = 20

# Melody windows must have a local tempo at or below this (BPM) to
# qualify at all. Tamil "melody"/romantic songs run roughly 60-110 BPM,
# while "mass"/dance songs sit at 120+ BPM (per genre convention). A song
# that's fast everywhere has no real melody section and should be
# skipped rather than forced to yield its "least fast" moment, which
# still reads as hyped.
MELODY_MAX_TEMPO_BPM = 115.0

# Local tempo estimates below this (BPM) are treated as half-time beat
# tracker errors and doubled, since these are common for syncopated,
# bass/kick-heavy tracks.
KUTHU_OCTAVE_CORRECTION_BPM = 85.0

# Video mixes: only Normal Mix is offered (Loop/Ultra's short, repeated
# bursts look choppy on screen), and every clip stays at least
# VIDEO_SEGMENT_MIN_SEC long -- anything shorter reads as a jump cut
# rather than a section of the music video. The max is still dynamic per
# song (weighted by hook-type fit) like the audio modes, and is also the
# window the hook search scans with for video (see hook_window_sec), so a
# strong hook really can run the full VIDEO_SEGMENT_MAX_SEC.
VIDEO_SEGMENT_MIN_SEC = 25.0
VIDEO_SEGMENT_MAX_SEC = 45.0
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
VIDEO_FPS = 30
VIDEO_AUDIO_BITRATE = "192k"


# --------------------------------------------------------------------------
# Analysis helpers
# --------------------------------------------------------------------------

def get_audio_files(folder):
    """Return sorted list of audio file paths in folder matching supported extensions."""
    return get_media_files(folder, MEDIA_AUDIO)


def get_media_files(folder, media_type=MEDIA_AUDIO):
    """Return sorted list of file paths in folder for the given media type."""
    files = []
    for ext in MEDIA_EXTENSIONS[media_type]:
        files.extend(glob.glob(os.path.join(folder, f"*{ext}")))
    return sorted(files)


def get_duration_seconds(filepath):
    """Quick metadata-only duration read (no full decode) for display
    purposes, e.g. listing files in a UI before processing. Returns
    None if the duration can't be read.
    """
    try:
        info = mediainfo(filepath)
        return float(info["duration"])
    except Exception:
        return None


def compute_rms_energy(y, sr, window_sec=ENERGY_WINDOW_SEC):
    """Compute short-term RMS energy over fixed-size windows.

    Returns (times, rms) where times[i] is the start time (sec) of the
    window and rms[i] is its RMS energy.
    """
    hop_length = max(int(sr * window_sec), 1)
    frame_length = hop_length * 2
    rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
    times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)
    return times, rms


def compute_spectral_centroid(y, sr, window_sec=ENERGY_WINDOW_SEC):
    """Compute spectral centroid ("brightness") over the same fixed-size
    windows as compute_rms_energy, so the two series align 1:1 by index.
    """
    hop_length = max(int(sr * window_sec), 1)
    frame_length = hop_length * 2
    centroid = librosa.feature.spectral_centroid(
        y=y, sr=sr, n_fft=frame_length, hop_length=hop_length
    )[0]
    return centroid


def compute_repetition_strength(y, sr, times, window_sec=ENERGY_WINDOW_SEC):
    """Score each window (aligned with `times`) by how much its harmonic
    content recurs elsewhere in the song, using a chroma self-similarity
    (recurrence) matrix -- the same idea behind "chorus detection" /
    audio thumbnailing. A section that comes back multiple times (the
    chorus/hook) scores higher than a loud one-off moment (e.g. a bridge
    or instrumental break) that happens to have similar energy.

    Returns an array aligned with `times`; all zeros if the song is too
    short for the self-similarity matrix to be meaningful.
    """
    hop_length = max(int(sr * window_sec), 1)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop_length)
    n = min(chroma.shape[1], len(times))
    if n < 4:
        return np.zeros(len(times))

    band = max(int(round(REPETITION_NEIGHBOR_SEC / window_sec)), 1)
    recurrence = librosa.segment.recurrence_matrix(
        chroma[:, :n], width=band, sym=True, mode="affinity"
    )
    strength = np.asarray(recurrence.sum(axis=1)).flatten()

    full = np.zeros(len(times))
    full[:n] = strength
    return full


def compute_local_tempo(times, y, sr):
    """Compute a local (short-time) tempo estimate for each window in
    `times` (the same grid produced by compute_rms_energy), by taking
    the median of librosa's framewise tempo curve within each window's
    time span. Applies a simple octave correction (doubles estimates
    below KUTHU_OCTAVE_CORRECTION_BPM) since beat trackers commonly
    detect half-time for syncopated, bass/kick-heavy tracks.
    """
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    tempo_curve = librosa.feature.tempo(onset_envelope=onset_env, sr=sr, aggregate=None)
    tempo_times = librosa.times_like(tempo_curve, sr=sr)

    window_sec = times[1] - times[0] if len(times) > 1 else ENERGY_WINDOW_SEC
    local_tempo = np.zeros(len(times))
    for i, t in enumerate(times):
        mask = (tempo_times >= t) & (tempo_times < t + window_sec)
        if np.any(mask):
            local_tempo[i] = np.median(tempo_curve[mask])
        elif len(tempo_curve):
            idx = int(np.argmin(np.abs(tempo_times - t)))
            local_tempo[i] = tempo_curve[idx]

    local_tempo = np.where(
        local_tempo < KUTHU_OCTAVE_CORRECTION_BPM, local_tempo * 2, local_tempo
    )
    return local_tempo


def _whole_track_window(duration, hook_window_sec=HOOK_TARGET_SEC):
    """Last-resort window for a locked song that has no usable hook region
    at all (too short or silent): the valid middle of the track, or the
    whole track if even that is too short.
    """
    valid_start = duration * INTRO_SKIP_FRACTION
    valid_end = duration * (1.0 - OUTRO_SKIP_FRACTION)
    if valid_end - valid_start < HOOK_MIN_SEC:
        valid_start, valid_end = 0.0, duration
    return [(valid_start, min(valid_start + hook_window_sec, valid_end), 0.0)]


def find_typed_hook_windows(
    times, rms, centroid, duration, hook_type, num_windows=HOOKS_PER_SONG,
    local_tempo=None, repetition=None, relaxed=False, hook_window_sec=HOOK_TARGET_SEC
):
    """Like find_top_hook_windows, but ranks candidate windows by a
    combined energy+brightness score instead of energy alone, and can
    return zero windows if the song has no section distinct enough to
    qualify as the requested hook_type.

    hook_type is HOOK_TYPE_MELODY (quietest/darkest, above a minimum RMS
    floor so near-silence is never picked), HOOK_TYPE_DANCE (loudest and
    brightest), or HOOK_TYPE_KUTHU (loudest and fastest local tempo,
    using `local_tempo`, an array aligned with `times`/`rms`). score is
    always stored so "higher = more preferred" holds for every type
    (melody scores are the inverted combined score).

    `repetition`, if given (see compute_repetition_strength, aligned with
    `times`/`rms`), nudges HOOK_TYPE_DANCE/HOOK_TYPE_KUTHU toward
    sections that recur elsewhere in the song (the chorus/hook proper)
    rather than a merely loud/fast one-off moment. Not applied to melody:
    the "calm section" melody is looking for is often a verse/bridge that
    deliberately *doesn't* repeat as much as the chorus, so biasing
    toward repetition there would work against the point of that mode.

    relaxed=True is used for songs the user locked into the mix: the
    "does this song qualify at all" gates (flat dynamics, melody's tempo
    ceiling) are dropped, so the same scoring simply returns whichever
    window comes *closest* to the hook type instead of nothing.
    """
    no_match = _whole_track_window(duration, hook_window_sec) if relaxed else []
    valid_start = duration * INTRO_SKIP_FRACTION
    valid_end = duration * (1.0 - OUTRO_SKIP_FRACTION)

    if valid_end - valid_start < HOOK_MIN_SEC:
        return no_match

    valid_mask = (times >= valid_start) & (times <= valid_end)
    valid_indices = np.where(valid_mask)[0]
    if len(valid_indices) == 0:
        return no_match

    valid_rms = rms[valid_indices]
    mean_rms = float(np.mean(valid_rms))
    if mean_rms <= 0:
        return no_match
    if hook_type != HOOK_TYPE_KUTHU and not relaxed:
        # Flat-energy songs have no genuine melody/dance contrast — skip
        # them entirely rather than picking an arbitrary window. This
        # doesn't apply to kuthu: a relentlessly loud, non-stop beat
        # *is* the kuthu vibe, not a disqualifying lack of contrast.
        relative_std = float(np.std(valid_rms)) / mean_rms
        if relative_std < DISTINCT_DYNAMICS_MIN_RELATIVE_STD:
            return []

    window_sec = min(hook_window_sec, valid_end - valid_start)
    step = times[1] - times[0] if len(times) > 1 else ENERGY_WINDOW_SEC
    frames_per_window = max(int(round(window_sec / step)), 1)

    rms_min, rms_max = float(np.min(valid_rms)), float(np.max(valid_rms))
    rms_range = rms_max - rms_min or 1.0

    if hook_type in (HOOK_TYPE_KUTHU, HOOK_TYPE_MELODY):
        valid_tempo = local_tempo[valid_indices]
        tempo_min, tempo_max = float(np.min(valid_tempo)), float(np.max(valid_tempo))
        tempo_range = tempo_max - tempo_min or 1.0
    if hook_type in (HOOK_TYPE_MELODY, HOOK_TYPE_DANCE):
        valid_centroid = centroid[valid_indices]
        c_min, c_max = float(np.min(valid_centroid)), float(np.max(valid_centroid))
        c_range = c_max - c_min or 1.0

    use_repetition = repetition is not None and hook_type in (HOOK_TYPE_KUTHU, HOOK_TYPE_DANCE)
    if use_repetition:
        valid_repetition = repetition[valid_indices]
        rep_min, rep_max = float(np.min(valid_repetition)), float(np.max(valid_repetition))
        rep_range = rep_max - rep_min or 1.0

    rms_floor = None
    if hook_type == HOOK_TYPE_MELODY:
        rms_floor = float(np.percentile(valid_rms, MELODY_RMS_FLOOR_PERCENTILE))

    candidates = []
    for idx in valid_indices:
        end_idx = idx + frames_per_window
        if end_idx > valid_indices[-1] + 1:
            break
        window_rms = rms[idx:end_idx]
        avg_rms = float(np.mean(window_rms))
        norm_rms = (avg_rms - rms_min) / rms_range

        if hook_type == HOOK_TYPE_KUTHU:
            avg_tempo = float(np.mean(local_tempo[idx:end_idx]))
            norm_tempo = (avg_tempo - tempo_min) / tempo_range
            # Energy-weighted: a loud, relentless section counts as much
            # as raw tempo, since that's what actually reads as "hype"
            # for this genre — tempo alone under- and over-shoots badly.
            if use_repetition:
                avg_rep = float(np.mean(repetition[idx:end_idx]))
                norm_rep = (avg_rep - rep_min) / rep_range
                # Repetition gets real weight but doesn't dominate: a
                # loud, fast, *recurring* section is what "the kuthu
                # part" means, not just whichever moment repeats most.
                combined = 0.5 * norm_rms + 0.2 * norm_tempo + 0.3 * norm_rep
            else:
                combined = 0.65 * norm_rms + 0.35 * norm_tempo
        elif hook_type == HOOK_TYPE_MELODY:
            if avg_rms < rms_floor:
                continue
            avg_tempo = float(np.mean(local_tempo[idx:end_idx]))
            if avg_tempo > MELODY_MAX_TEMPO_BPM and not relaxed:
                continue
            avg_centroid = float(np.mean(centroid[idx:end_idx]))
            norm_centroid = (avg_centroid - c_min) / c_range
            norm_tempo = (avg_tempo - tempo_min) / tempo_range
            # Tempo-led: the "quietest" moment in a mostly upbeat song is
            # often still rhythmically fast (fast hi-hats/percussion under
            # a dip in loudness), which is what made melody picks feel
            # hyped. Weight local tempo heavily so a genuinely slower
            # passage wins even if it isn't the single quietest instant.
            combined_raw = 0.25 * norm_rms + 0.15 * norm_centroid + 0.60 * norm_tempo
            combined = -combined_raw  # higher stored score = more melodic
        else:  # HOOK_TYPE_DANCE
            avg_centroid = float(np.mean(centroid[idx:end_idx]))
            norm_centroid = (avg_centroid - c_min) / c_range
            if use_repetition:
                avg_rep = float(np.mean(repetition[idx:end_idx]))
                norm_rep = (avg_rep - rep_min) / rep_range
                combined = 0.35 * norm_rms + 0.35 * norm_centroid + 0.3 * norm_rep
            else:
                combined = 0.5 * norm_rms + 0.5 * norm_centroid

        candidates.append((combined, idx, end_idx))

    if not candidates:
        return no_match

    candidates.sort(key=lambda c: c[0], reverse=True)
    chosen = []
    used_ranges = []
    for score, idx, end_idx in candidates:
        if len(chosen) >= num_windows:
            break
        overlaps = any(idx < u_end and end_idx > u_start for u_start, u_end in used_ranges)
        if overlaps:
            continue
        chosen.append((times[idx], min(times[idx] + window_sec, valid_end), float(score)))
        used_ranges.append((idx, end_idx))

    chosen.sort(key=lambda w: w[0])
    return chosen


def find_top_hook_windows(times, rms, duration, num_windows=HOOKS_PER_SONG,
                          hook_window_sec=HOOK_TARGET_SEC):
    """Find up to num_windows non-overlapping [start, end, score] windows
    (sec) of sustained high energy, excluding the intro/outro, ranked by
    a rolling-sum of RMS energy over a window sized to the target hook
    length. The first window returned is the strongest (the main hook);
    later ones are weaker but distinct sections usable as a reprise.
    score is the raw RMS-sum used to rank it, so callers can later pick
    the highest-energy hook across many songs (e.g. reprise selection).
    """
    valid_start = duration * INTRO_SKIP_FRACTION
    valid_end = duration * (1.0 - OUTRO_SKIP_FRACTION)

    if valid_end - valid_start < HOOK_MIN_SEC:
        # Track too short for the skip rules to leave a full hook; just
        # use the whole valid region as the single hook.
        return [(valid_start, valid_end, 0.0)]

    window_sec = min(hook_window_sec, valid_end - valid_start)

    valid_mask = (times >= valid_start) & (times <= valid_end)
    valid_indices = np.where(valid_mask)[0]
    if len(valid_indices) == 0:
        return [(valid_start, min(valid_start + window_sec, valid_end), 0.0)]

    step = times[1] - times[0] if len(times) > 1 else ENERGY_WINDOW_SEC
    frames_per_window = max(int(round(window_sec / step)), 1)

    # Score every candidate start index within the valid region.
    candidates = []
    for idx in valid_indices:
        end_idx = idx + frames_per_window
        if end_idx > valid_indices[-1] + 1:
            break
        score = np.sum(rms[idx:end_idx])
        candidates.append((score, idx, end_idx))

    if not candidates:
        return [(valid_start, min(valid_start + window_sec, valid_end), 0.0)]

    # Greedily pick the highest-scoring window, then remove any
    # candidates that overlap it, and repeat until we have enough
    # non-overlapping windows or run out of options.
    candidates.sort(key=lambda c: c[0], reverse=True)
    chosen = []
    used_ranges = []
    for score, idx, end_idx in candidates:
        if len(chosen) >= num_windows:
            break
        overlaps = any(idx < u_end and end_idx > u_start for u_start, u_end in used_ranges)
        if overlaps:
            continue
        chosen.append((times[idx], min(times[idx] + window_sec, valid_end), float(score)))
        used_ranges.append((idx, end_idx))

    # Keep windows in chronological order for readability/logging.
    chosen.sort(key=lambda w: w[0])
    return chosen


def snap_to_beat(time_sec, beat_times):
    """Return the beat timestamp closest to time_sec."""
    if len(beat_times) == 0:
        return time_sec
    idx = int(np.argmin(np.abs(beat_times - time_sec)))
    return beat_times[idx]


def audio_segment_to_mono_float(audio, target_sr=ANALYSIS_SR):
    """Convert a pydub AudioSegment to a mono float32 numpy array at
    target_sr, suitable for librosa analysis.
    """
    audio = audio.set_channels(1).set_frame_rate(target_sr)
    samples = np.array(audio.get_array_of_samples()).astype(np.float32)
    max_val = float(1 << (8 * audio.sample_width - 1))
    samples /= max_val
    return samples, target_sr


def analyze_track(audio, hook_type=HOOK_TYPE_NORMAL, locked=False, hook_window_sec=HOOK_TARGET_SEC):
    """Analyze a pydub AudioSegment. Returns a dict with bpm, duration,
    and a list of beat-snapped hooks ({"hook_start", "hook_end"}). The
    first hook is the strongest section; any further ones are distinct
    sections usable as a later reprise of the same song.

    hook_type selects which part of the song counts as "the hook" (see
    HOOK_TYPES). For HOOK_TYPE_MELODY/HOOK_TYPE_DANCE/HOOK_TYPE_KUTHU,
    "hooks" may come back empty if the song has no section distinct
    enough to qualify -- unless locked=True (the user ticked the song to
    always be used), in which case the closest-matching section is
    returned instead and "closest_match" is set in the result.

    hook_window_sec is how long a section the hook search scans for (and
    so the longest the hook can later be kept at) -- the segment max of
    the mix being built (see segment_bounds).
    """
    y, sr = audio_segment_to_mono_float(audio)
    duration = librosa.get_duration(y=y, sr=sr)

    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    bpm = float(np.atleast_1d(tempo)[0])
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    times, rms = compute_rms_energy(y, sr)
    closest_match = False
    if hook_type == HOOK_TYPE_NORMAL:
        raw_windows = find_top_hook_windows(times, rms, duration, hook_window_sec=hook_window_sec)
    else:
        features = {"centroid": None, "local_tempo": None, "repetition": None}
        if hook_type in (HOOK_TYPE_MELODY, HOOK_TYPE_DANCE):
            features["centroid"] = compute_spectral_centroid(y, sr)
        if hook_type in (HOOK_TYPE_MELODY, HOOK_TYPE_KUTHU):
            features["local_tempo"] = compute_local_tempo(times, y, sr)
        if hook_type in (HOOK_TYPE_DANCE, HOOK_TYPE_KUTHU):
            features["repetition"] = compute_repetition_strength(y, sr, times)

        raw_windows = find_typed_hook_windows(
            times, rms, features["centroid"], duration, hook_type,
            local_tempo=features["local_tempo"], repetition=features["repetition"],
            hook_window_sec=hook_window_sec,
        )
        if not raw_windows and locked:
            raw_windows = find_typed_hook_windows(
                times, rms, features["centroid"], duration, hook_type,
                local_tempo=features["local_tempo"], repetition=features["repetition"],
                relaxed=True, hook_window_sec=hook_window_sec,
            )
            closest_match = True

    hooks = []
    for raw_start, raw_end, score in raw_windows:
        hook_start = snap_to_beat(raw_start, beat_times)
        hook_end = snap_to_beat(raw_end, beat_times)
        # Guard against snapping collapsing the window or reversing order.
        if hook_end <= hook_start:
            hook_end = min(hook_start + HOOK_MIN_SEC, duration)
        # Beats that fall inside this hook, as offsets from the hook's own
        # start -- lets a later dynamic-length trim (_compute_dynamic_lengths
        # / trim_segment_to_beat) cut the segment down on a downbeat instead
        # of at an arbitrary millisecond.
        beat_offsets = [
            float(t - hook_start) for t in beat_times if hook_start <= t <= hook_end
        ]
        hooks.append({
            "hook_start": hook_start,
            "hook_end": hook_end,
            "score": score,
            "beat_offsets": beat_offsets,
        })

    return {
        "bpm": bpm,
        "duration": duration,
        "hooks": hooks,
        "closest_match": closest_match,
    }


# --------------------------------------------------------------------------
# Audio extraction / combination
# --------------------------------------------------------------------------

class SourceClip:
    """A hook's AudioSegment plus where it came from: the source file and
    the second in that file the clip starts at. Slicing it (as the
    trim/split helpers below do) keeps that bookkeeping in step, so after
    planning a mix every final segment still knows exactly which part of
    which file it is -- which is what lets a video mix cut the picture at
    the same points the audio was cut.

    Supports len() (milliseconds) and [start_ms:end_ms] slicing, the two
    AudioSegment operations the planners use.
    """

    def __init__(self, audio, source_path, source_start_sec):
        self.audio = audio
        self.source_path = source_path
        self.source_start_sec = source_start_sec

    def __len__(self):
        return len(self.audio)

    def __getitem__(self, key):
        if not isinstance(key, slice) or key.step is not None:
            raise TypeError("SourceClip only supports [start_ms:end_ms] slicing")
        start_ms = min(max(key.start or 0, 0), len(self.audio))
        return SourceClip(
            self.audio[key], self.source_path, self.source_start_sec + start_ms / 1000.0
        )


def extract_hook_segment(audio, hook_start, hook_end):
    """Slice the hook out of an already-loaded pydub AudioSegment."""
    start_ms = int(hook_start * 1000)
    end_ms = int(hook_end * 1000)
    return audio[start_ms:end_ms]


def crossfade_lengths(segment_lengths_ms, crossfade_ms=CROSSFADE_MS):
    """Per-boundary crossfade length (ms) for segments joined in order --
    one entry per join, i.e. len(segment_lengths_ms) - 1. Shared by the
    audio combine and the video render so both place every transition at
    exactly the same moment.
    """
    fades = []
    mixed_len = segment_lengths_ms[0] if segment_lengths_ms else 0
    for seg_len in segment_lengths_ms[1:]:
        fade = max(min(crossfade_ms, mixed_len - 1, seg_len - 1), 0)
        fades.append(fade)
        mixed_len += seg_len - fade
    return fades


def combine_hooks(hooks, crossfade_ms=CROSSFADE_MS):
    """Crossfade a list of AudioSegments together into one track."""
    fades = crossfade_lengths([len(h) for h in hooks], crossfade_ms)
    mixed = hooks[0]
    for segment, fade in zip(hooks[1:], fades):
        mixed = mixed.append(segment, crossfade=fade)
    return mixed


def export_mix(mix, output_path, bitrate=EXPORT_BITRATE):
    """Export a combined AudioSegment to an mp3 file."""
    mix.export(output_path, format="mp3", bitrate=bitrate)


# --------------------------------------------------------------------------
# Video rendering
# --------------------------------------------------------------------------

class RenderCancelled(Exception):
    """Raised by render_video_mix when should_cancel() asks it to stop."""


def _ffmpeg_exe():
    converter = getattr(AudioSegment, "converter", None)
    if converter and os.path.isfile(converter):
        return converter
    return shutil.which("ffmpeg") or "ffmpeg"


def _subprocess_flags():
    # Keep a console window from flashing up behind the GUI on Windows.
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


_video_encoder_args = None


def _pick_video_encoder():
    """H.264 encoder args for whatever this ffmpeg build has: libx264 on
    full (GPL) builds, Windows' Media Foundation H.264 on the LGPL build
    packaged releases bundle, and plain MPEG-4 as a last resort.
    """
    global _video_encoder_args
    if _video_encoder_args is not None:
        return _video_encoder_args
    try:
        out = subprocess.run(
            [_ffmpeg_exe(), "-hide_banner", "-encoders"],
            capture_output=True, text=True, creationflags=_subprocess_flags(),
        ).stdout
    except OSError:
        out = ""
    if " libx264 " in out:
        args = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
    elif " h264_mf " in out:
        args = ["-c:v", "h264_mf", "-b:v", "8M"]
    else:
        args = ["-c:v", "mpeg4", "-q:v", "3"]
    _video_encoder_args = args
    return args


def _video_filter_graph(clips, fades):
    """Build the filter_complex that normalizes every clip to one frame
    size/rate (letterboxing as needed, and holding the last frame if a
    video track ends before its audio does) and then crossfades them at
    the same offsets combine_hooks used for the audio.
    """
    size = f"{VIDEO_WIDTH}:{VIDEO_HEIGHT}"
    parts = []
    for i, clip in enumerate(clips):
        dur = len(clip) / 1000.0
        parts.append(
            f"[{i}:v]fps={VIDEO_FPS},"
            f"scale={size}:force_original_aspect_ratio=decrease,"
            f"pad={size}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,format=yuv420p,"
            f"tpad=stop_mode=clone:stop_duration={dur:.3f},"
            f"trim=duration={dur:.3f},setpts=PTS-STARTPTS,settb=AVTB[v{i}]"
        )

    prev = "v0"
    elapsed_ms = len(clips[0])
    for i, fade in enumerate(fades, start=1):
        out = f"x{i}"
        if fade >= 40:  # at least ~one frame, or xfade has nothing to blend
            offset = (elapsed_ms - fade) / 1000.0
            parts.append(
                f"[{prev}][v{i}]xfade=transition=fade:"
                f"duration={fade / 1000.0:.3f}:offset={offset:.3f}[{out}]"
            )
        else:
            parts.append(f"[{prev}][v{i}]concat=n=2:v=1:a=0[{out}]")
        elapsed_ms += len(clips[i]) - fade
        prev = out

    parts.append(f"[{prev}]format=yuv420p[vout]")
    return ";".join(parts)


def render_video_mix(clips, audio_mix, output_path, progress_callback=None,
                     should_cancel=None, crossfade_ms=CROSSFADE_MS):
    """Render a video mix: each SourceClip's picture is cut from its source
    video at the same timestamps as its audio, the clips are crossfaded
    with the same per-boundary fades as the audio mix, and the already-
    mixed audio (audio_mix, from combine_hooks) is laid underneath -- so
    what you hear is identical to the mp3 version of the same mix.

    progress_callback(message, percent) reports 0-100 across the encode.
    should_cancel(), if given, is polled during the encode; returning True
    stops ffmpeg and raises RenderCancelled.
    """
    if not clips:
        raise ValueError("No clips to render")

    fades = crossfade_lengths([len(c) for c in clips], crossfade_ms)
    total_sec = len(audio_mix) / 1000.0
    work_dir = tempfile.mkdtemp(prefix="svmix_render_")
    stderr_path = os.path.join(work_dir, "ffmpeg.log")
    try:
        audio_path = os.path.join(work_dir, "mix.wav")
        audio_mix.export(audio_path, format="wav")

        cmd = [_ffmpeg_exe(), "-y", "-hide_banner", "-nostats", "-progress", "pipe:1"]
        for clip in clips:
            cmd += [
                "-ss", f"{clip.source_start_sec:.3f}",
                "-t", f"{len(clip) / 1000.0 + 0.5:.3f}",
                "-i", clip.source_path,
            ]
        cmd += ["-i", audio_path]
        cmd += [
            "-filter_complex", _video_filter_graph(clips, fades),
            "-map", "[vout]", "-map", f"{len(clips)}:a",
            *_pick_video_encoder(),
            "-pix_fmt", "yuv420p", "-r", str(VIDEO_FPS),
            "-c:a", "aac", "-b:a", VIDEO_AUDIO_BITRATE,
            "-t", f"{total_sec:.3f}",
            "-movflags", "+faststart",
            output_path,
        ]

        with open(stderr_path, "w", encoding="utf-8", errors="replace") as err:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=err, text=True,
                creationflags=_subprocess_flags(),
            )
            try:
                for line in proc.stdout:
                    if should_cancel and should_cancel():
                        proc.kill()
                        proc.wait()
                        raise RenderCancelled()
                    key, _, value = line.strip().partition("=")
                    if key == "out_time_us" and progress_callback and total_sec > 0:
                        try:
                            done_sec = int(value) / 1_000_000
                        except ValueError:
                            continue
                        percent = int(min(max(done_sec / total_sec, 0.0), 1.0) * 100)
                        progress_callback("Rendering video...", percent)
                proc.wait()
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()

        if proc.returncode != 0:
            with open(stderr_path, encoding="utf-8", errors="replace") as err:
                tail = err.read().strip().splitlines()[-8:]
            raise RuntimeError("ffmpeg could not render the video:\n" + "\n".join(tail))
    except RenderCancelled:
        if os.path.exists(output_path):
            os.remove(output_path)
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    return output_path


# --------------------------------------------------------------------------
# Mix modes & duration planning
# --------------------------------------------------------------------------

def segment_bounds(media_type=MEDIA_AUDIO):
    """(min_sec, max_sec) a kept hook segment is trimmed to, per media type."""
    if media_type == MEDIA_VIDEO:
        return (VIDEO_SEGMENT_MIN_SEC, VIDEO_SEGMENT_MAX_SEC)
    return (SEGMENT_MIN_SEC, SEGMENT_MAX_SEC)


def estimate_duration_range(num_songs, mode, media_type=MEDIA_AUDIO, precut_durations=()):
    """Return (min_sec, max_sec): the achievable total mix duration for
    num_songs songs in the given mode. Pure arithmetic (no audio
    decoding), so it's cheap enough to call live from the UI as files
    are added/removed or the mode is changed. Video mixes are always
    Normal Mix, with their own segment bounds (see segment_bounds).

    precut_durations lists the lengths (sec) of any pre-cut songs among
    the num_songs: they're used whole, once, so they add a fixed amount
    to both ends of the range instead of stretching with it.
    """
    if num_songs <= 0:
        return (0.0, 0.0)

    crossfade_sec = CROSSFADE_MS / 1000.0
    precut_count = min(len(precut_durations), num_songs)
    precut_total = float(sum(precut_durations))
    num_songs -= precut_count

    def total_for(segment_count, segment_len):
        pieces = segment_count + precut_count
        return segment_count * segment_len + precut_total - max(pieces - 1, 0) * crossfade_sec

    if media_type == MEDIA_VIDEO:
        seg_min, seg_max = segment_bounds(MEDIA_VIDEO)
        lo = total_for(num_songs, seg_min)
        hi = total_for(num_songs, seg_max)
    elif mode == MODE_NORMAL:
        lo = total_for(num_songs, SEGMENT_MIN_SEC)
        hi = total_for(num_songs, SEGMENT_MAX_SEC)
    elif mode == MODE_ULTRA:
        lo = total_for(num_songs * 2, ULTRA_CHUNK_MIN_SEC)
        hi = total_for(num_songs * 4, ULTRA_CHUNK_MAX_SEC)
    else:  # MODE_LOOP
        lo = total_for(num_songs, SEGMENT_MIN_SEC)
        hi = total_for(num_songs * 2, SEGMENT_MAX_SEC)

    return (max(lo, 0.0), max(hi, lo))


def trim_segment(segment, target_len_sec):
    """Return segment trimmed to its first target_len_sec seconds, or
    the whole segment if it's already shorter than that.
    """
    target_ms = int(target_len_sec * 1000)
    if target_ms <= 0 or target_ms >= len(segment):
        return segment
    return segment[:target_ms]


def split_into_ultra_chunks(segment, chunk_len_sec):
    """Split segment into two consecutive chunks of chunk_len_sec each,
    for Ultra Mix's interleaved halves. Shrinks chunk_len_sec if the
    segment is too short to hold two full chunks. Returns (chunk_a, chunk_b).
    """
    chunk_ms = int(chunk_len_sec * 1000)
    available = len(segment)
    if chunk_ms * 2 > available:
        chunk_ms = max(available // 2, 1)
    return segment[:chunk_ms], segment[chunk_ms:chunk_ms * 2]


# How far (seconds) a dynamically-shortened hook's cut point is allowed to
# drift from the requested length in order to land on a beat instead.
# Beyond this, hitting the user's requested duration matters more than
# landing exactly on a downbeat, so it falls back to a plain cut.
TRIM_BEAT_SNAP_TOLERANCE_SEC = 1.5


def _nearest_beat_sec(target_sec, beat_offsets, tolerance_sec=TRIM_BEAT_SNAP_TOLERANCE_SEC):
    """Return the beat offset (seconds, relative to a hook's own start --
    see analyze_track) closest to target_sec, or None if none fall within
    tolerance_sec of it.
    """
    if not beat_offsets:
        return None
    candidates = [b for b in beat_offsets if abs(b - target_sec) <= tolerance_sec]
    if not candidates:
        return None
    return min(candidates, key=lambda b: abs(b - target_sec))


def trim_segment_to_beat(segment, target_len_sec, beat_offsets=None):
    """Like trim_segment, but snaps the cut point to the nearest beat
    inside the segment (beat_offsets: seconds relative to the segment's
    own start, from analyze_track) instead of an arbitrary millisecond --
    a dynamically-shortened hook then still ends on a downbeat rather
    than mid-phrase. Falls back to a plain trim if no beat lands close
    enough to the requested length.
    """
    target_ms = int(target_len_sec * 1000)
    if target_ms <= 0 or target_ms >= len(segment):
        return segment
    nearest = _nearest_beat_sec(target_len_sec, beat_offsets)
    if nearest is None:
        return segment[:target_ms]
    nearest_ms = int(nearest * 1000)
    if nearest_ms <= 0 or nearest_ms >= len(segment):
        return segment[:target_ms]
    return segment[:nearest_ms]


def split_into_ultra_chunks_to_beat(segment, chunk_len_sec, beat_offsets=None):
    """Beat-aware version of split_into_ultra_chunks: the boundary between
    the two halves (and the end of the second half) each snap to the
    nearest beat within tolerance, same rationale as trim_segment_to_beat.
    """
    available = len(segment)
    chunk_ms = int(chunk_len_sec * 1000)
    if chunk_ms * 2 > available:
        chunk_ms = max(available // 2, 1)

    split_sec = chunk_ms / 1000.0
    nearest_split = _nearest_beat_sec(split_sec, beat_offsets)
    split_ms = int(nearest_split * 1000) if nearest_split is not None else chunk_ms
    split_ms = max(1, min(split_ms, available - 1))

    end_sec = (2 * chunk_ms) / 1000.0
    nearest_end = _nearest_beat_sec(end_sec, beat_offsets)
    end_ms = int(nearest_end * 1000) if nearest_end is not None else 2 * chunk_ms
    end_ms = max(split_ms + 1, min(end_ms, available))

    return segment[:split_ms], segment[split_ms:end_ms]


def _nearest_neighbor_chain(items, bpm_key, score_key, descending=False):
    """Order items by nearest-neighbor chaining in normalized
    (bpm, score) space, so every transition lands on whichever
    remaining item feels closest in tempo *and* energy/brightness —
    tighter than a plain BPM sort, since two items at the same tempo
    can still feel very different in intensity. This is what makes the
    crossfade between them read as a deliberate, seamless transition
    rather than an arbitrary cut, no matter which mix mode is active.

    descending=True starts the chain from the highest-BPM item instead
    of the lowest — used to continue an ascending pass with a matching
    "wave back down" for a later reprise section.
    """
    n = len(items)
    if n <= 1:
        return list(items)

    bpms = [bpm_key(it) for it in items]
    scores = [score_key(it) for it in items]
    bpm_lo, bpm_hi = min(bpms), max(bpms)
    score_lo, score_hi = min(scores), max(scores)
    bpm_range = (bpm_hi - bpm_lo) or 1.0
    score_range = (score_hi - score_lo) or 1.0
    features = [
        ((b - bpm_lo) / bpm_range, (sc - score_lo) / score_range)
        for b, sc in zip(bpms, scores)
    ]

    remaining = list(range(n))
    start = (max if descending else min)(remaining, key=lambda i: features[i][0])
    order = [start]
    remaining.remove(start)
    while remaining:
        cur = features[order[-1]]
        nxt = min(
            remaining,
            key=lambda i: (features[i][0] - cur[0]) ** 2 + (features[i][1] - cur[1]) ** 2,
        )
        order.append(nxt)
        remaining.remove(nxt)
    return [items[i] for i in order]


def order_by_feel(songs, score_key=lambda s: s["hooks"][0]["score"], descending=False):
    """Order per-song dicts (see _group_by_song) so consecutive songs in
    the final mix feel alike — similar tempo and energy — using
    _nearest_neighbor_chain. Applied the same way regardless of mix
    mode, since the "does the next song fit" question is universal.
    """
    return _nearest_neighbor_chain(
        songs, bpm_key=lambda s: s["bpm"], score_key=score_key, descending=descending
    )


def _fit_ratios(songs, score_key):
    """Normalize each song's hook score to [0, 1] relative to the other
    songs being mixed — 1.0 is the strongest fit for the selected hook
    type in this batch, 0.0 the weakest. All songs equal -> 0.5 each.
    """
    scores = [score_key(s) for s in songs]
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-9:
        return [0.5] * len(songs)
    return [(sc - lo) / (hi - lo) for sc in scores]


def _scale_lengths_to_target(lengths, fit, target_total, min_sec, max_sec):
    """Redistribute `lengths` (already fit-weighted, one per song) so
    they sum to target_total, without breaking the [min_sec, max_sec]
    bounds. Extra time is handed mostly to the highest-fit songs first,
    since they best represent the selected hook mode; time taken away
    comes mostly from the lowest-fit songs first. Priority order set by
    `fit` survives the correction for the user's requested duration —
    a low-fit song is only ever leaned on less, never dropped.
    """
    lengths = list(lengths)
    n = len(lengths)
    if n == 0:
        return lengths

    for _ in range(60):
        diff = target_total - sum(lengths)
        if abs(diff) < 0.05:
            break
        if diff > 0:
            idxs = [i for i in range(n) if lengths[i] < max_sec - 1e-6]
            weights = [fit[i] + 0.05 for i in idxs]
        else:
            idxs = [i for i in range(n) if lengths[i] > min_sec + 1e-6]
            weights = [(1.0 - fit[i]) + 0.05 for i in idxs]
        if not idxs:
            break
        wsum = sum(weights)
        for i, w in zip(idxs, weights):
            lengths[i] = min(max_sec, max(min_sec, lengths[i] + diff * (w / wsum)))
    return lengths


def _compute_dynamic_lengths(songs, target_duration_sec, score_key,
                              min_sec=SEGMENT_MIN_SEC, max_sec=SEGMENT_MAX_SEC):
    """Per-song hook length in [min_sec, max_sec] seconds. A song whose
    detected hook scores higher for the selected hook type (relative to
    the other songs in this mix) gets a length closer to max_sec; a
    weaker match gets pulled toward min_sec — leaned on less, never
    dropped. This is what "priority to the selected mode" means in
    practice: the song that's most *oriented* to Kuthu/Melody/Dance/etc.
    gets more seconds of its hook in the final mix than one that only
    weakly qualifies.

    When target_duration_sec is given, lengths are then nudged
    (respecting the same bounds and the same priority order) so the
    mix lands close to the user's requested overall duration.
    """
    n = len(songs)
    if n == 0:
        return []

    fit = _fit_ratios(songs, score_key)
    base_lengths = [min_sec + f * (max_sec - min_sec) for f in fit]

    if target_duration_sec is None:
        return base_lengths
    if n == 1:
        return [min(max(target_duration_sec, min_sec), max_sec)]

    crossfade_sec = CROSSFADE_MS / 1000.0
    target_total = target_duration_sec + (n - 1) * crossfade_sec
    return _scale_lengths_to_target(base_lengths, fit, target_total, min_sec, max_sec)


def _group_by_song(results):
    """Group process_files' flat per-hook results back into a list of
    per-song dicts: {"filename", "bpm", "precut", "hooks": [result, ...]},
    hooks sorted by variation (0 = main hook, 1 = reprise).
    """
    songs = []
    by_path = {}
    for r in results:
        # Keyed by full path, not filename: two different files can share
        # a basename (same song name in two folders).
        song = by_path.get(r["filepath"])
        if song is None:
            song = {
                "filename": r["filename"],
                "bpm": r["bpm"],
                "precut": r.get("precut", False),
                "hooks": [],
            }
            by_path[r["filepath"]] = song
            songs.append(song)
        song["hooks"].append(r)
    for song in songs:
        song["hooks"].sort(key=lambda r: r["variation"])
    return songs


def _main_score(song):
    return song["hooks"][0]["score"]


def _main_segment(song, length_sec):
    """A song's main hook trimmed (on a beat) to length_sec -- or, for a
    pre-cut song, the user's own cut exactly as it is.
    """
    hook = song["hooks"][0]
    if song["precut"]:
        return hook["segment"]
    return trim_segment_to_beat(hook["segment"], length_sec, hook.get("beat_offsets"))


def _fit_around_precut(ordered_songs, target_duration_sec, min_sec, max_sec, segments_per_song=1):
    """Main-hook length (sec) for each song in ordered_songs. A pre-cut
    song's is its own full length, fixed; every other song gets a dynamic
    length in [min_sec, max_sec] (see _compute_dynamic_lengths), sized so
    the mix as a whole -- pre-cut songs included -- still lands on
    target_duration_sec. segments_per_song is how many crossfaded pieces
    each adjustable song ends up as (Ultra Mix splits each into two);
    pre-cut songs are always a single piece.
    """
    crossfade_sec = CROSSFADE_MS / 1000.0
    lengths = [
        len(s["hooks"][0]["segment"]) / 1000.0 if s["precut"] else None for s in ordered_songs
    ]
    adjustable = [s for s in ordered_songs if not s["precut"]]
    if not adjustable:
        return lengths

    m = len(adjustable)
    p = len(ordered_songs) - m
    fixed_total = sum(length for length in lengths if length is not None)
    adj_target = None
    if target_duration_sec is not None:
        # mix total = sum(all pieces) - (pieces - 1) * crossfade, and
        # _compute_dynamic_lengths already adds (m - 1) crossfades itself.
        pieces = p + segments_per_song * m
        adj_target = (
            target_duration_sec + (pieces - 1) * crossfade_sec - fixed_total - (m - 1) * crossfade_sec
        )
    adj_lengths = iter(
        _compute_dynamic_lengths(adjustable, adj_target, _main_score, min_sec=min_sec, max_sec=max_sec)
    )
    return [length if length is not None else next(adj_lengths) for length in lengths]


def _plan_normal_mix(songs, target_duration_sec,
                     min_sec=SEGMENT_MIN_SEC, max_sec=SEGMENT_MAX_SEC):
    """Every song's main hook exactly once, ordered by feel (tempo +
    energy) rather than raw BPM, each given a dynamic length in
    [min_sec, max_sec] weighted by how strongly it fits the selected
    hook type, scaled to hit target_duration_sec overall. Pre-cut songs
    are used whole, and the others are sized around them.
    """
    if not songs:
        return []
    ordered_songs = order_by_feel(songs)
    lengths = _fit_around_precut(ordered_songs, target_duration_sec, min_sec, max_sec)
    return [_main_segment(s, length) for s, length in zip(ordered_songs, lengths)]


# How much each aspect of a transition counts when choosing the running
# order of a video mix (see _transition_cost). Each aspect is first scaled
# so that 1.0 means "clearly noticeable": a TRANSITION_TEMPO_STEP tempo
# gap, a TRANSITION_LOUDNESS_STEP_DB loudness jump, or a
# TRANSITION_HARMONY_STEP drop in chroma similarity.
TRANSITION_TEMPO_WEIGHT = 0.45
TRANSITION_LOUDNESS_WEIGHT = 0.25
TRANSITION_HARMONY_WEIGHT = 0.30
TRANSITION_TEMPO_STEP = 0.08          # 8% tempo difference
TRANSITION_LOUDNESS_STEP_DB = 6.0
TRANSITION_HARMONY_STEP = 0.2
# Half/double-time matches (e.g. 80 vs 160 BPM) still lock together on
# the beat, but not quite as naturally as the same tempo does.
TRANSITION_OCTAVE_PENALTY = 0.35


def _clip_tempo(clip, beat_offsets, fallback_bpm):
    """Tempo (BPM) of the part of a hook that actually made it into the
    clip, from the beats analyze_track found inside it; the song's overall
    BPM if there aren't enough of them (e.g. a pre-cut file)."""
    clip_sec = len(clip) / 1000.0
    beats = [b for b in (beat_offsets or []) if b <= clip_sec]
    if len(beats) >= 4:
        interval = float(np.median(np.diff(beats)))
        if interval > 0:
            return 60.0 / interval
    return fallback_bpm


def _edge_features(audio):
    """Loudness (dBFS) and normalized mean chroma of a short stretch of
    audio -- what's audible during one side of a crossfade."""
    y, sr = audio_segment_to_mono_float(audio)
    loudness = audio.dBFS if audio.rms > 0 else -90.0
    if len(y) < 2048:
        return loudness, np.zeros(12)
    chroma = librosa.feature.chroma_stft(y=y, sr=sr).mean(axis=1)
    norm = float(np.linalg.norm(chroma))
    return loudness, (chroma / norm if norm > 0 else chroma)


def _transition_profile(song, clip):
    """Everything needed to judge how well this clip hands over to, or
    takes over from, another: its tempo, plus loudness and harmony of its
    first and last crossfade-length stretch (the parts that overlap the
    neighbouring clips)."""
    edge_ms = min(CROSSFADE_MS, len(clip))
    head_db, head_chroma = _edge_features(clip.audio[:edge_ms])
    tail_db, tail_chroma = _edge_features(clip.audio[-edge_ms:])
    return {
        "tempo": _clip_tempo(clip, song["hooks"][0].get("beat_offsets"), song["bpm"]),
        "head_db": head_db, "head_chroma": head_chroma,
        "tail_db": tail_db, "tail_chroma": tail_chroma,
    }


def _transition_cost(out_profile, in_profile):
    """How rough the crossfade from one clip into the next would sound:
    0 is seamless, ~1 is a clearly noticeable change. Weighs tempo match
    (half/double time allowed), the loudness jump across the overlap, and
    how well the harmony at the end of the outgoing clip fits the start
    of the incoming one."""
    t_out, t_in = out_profile["tempo"], in_profile["tempo"]
    tempo_cost = 1.0
    if t_out > 0 and t_in > 0:
        octaves = abs(np.log2(t_in / t_out))
        off_octave = abs(octaves - round(octaves))
        tempo_cost = off_octave / np.log2(1 + TRANSITION_TEMPO_STEP)
        if round(octaves) != 0:
            tempo_cost += TRANSITION_OCTAVE_PENALTY
    loudness_cost = abs(out_profile["tail_db"] - in_profile["head_db"]) / TRANSITION_LOUDNESS_STEP_DB
    similarity = float(np.dot(out_profile["tail_chroma"], in_profile["head_chroma"]))
    harmony_cost = max(0.0, 1.0 - similarity) / TRANSITION_HARMONY_STEP
    return (
        TRANSITION_TEMPO_WEIGHT * min(tempo_cost, 3.0)
        + TRANSITION_LOUDNESS_WEIGHT * min(loudness_cost, 3.0)
        + TRANSITION_HARMONY_WEIGHT * min(harmony_cost, 3.0)
    )


def _best_transition_order(cost):
    """Order indices 0..n-1 to minimize the summed cost[a][b] of every
    consecutive a -> b hand-off. Exact for small mixes; for bigger ones,
    the best greedy chain from every starting song, polished with 2-opt
    segment reversals."""
    n = len(cost)
    if n <= 2:
        if n == 2 and cost[1][0] < cost[0][1]:
            return [1, 0]
        return list(range(n))

    def path_cost(order):
        return sum(cost[a][b] for a, b in zip(order, order[1:]))

    if n <= 10:
        # Held-Karp over subsets: best[(mask, last)] = (cost, previous).
        best = {(1 << i, i): (0.0, None) for i in range(n)}
        for mask in range(1, 1 << n):
            for last in range(n):
                entry = best.get((mask, last))
                if entry is None:
                    continue
                for nxt in range(n):
                    if mask & (1 << nxt):
                        continue
                    key = (mask | (1 << nxt), nxt)
                    c = entry[0] + cost[last][nxt]
                    if key not in best or c < best[key][0]:
                        best[key] = (c, last)
        full = (1 << n) - 1
        last = min(range(n), key=lambda i: best[(full, i)][0])
        order, mask = [], full
        while last is not None:
            order.append(last)
            prev = best[(mask, last)][1]
            mask &= ~(1 << last)
            last = prev
        return order[::-1]

    best_order = None
    for start in range(n):
        order, remaining = [start], set(range(n)) - {start}
        while remaining:
            nxt = min(remaining, key=lambda j: cost[order[-1]][j])
            order.append(nxt)
            remaining.remove(nxt)
        improved = True
        while improved:
            improved = False
            for i in range(0, n - 1):
                for j in range(i + 1, n):
                    candidate = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                    if path_cost(candidate) + 1e-9 < path_cost(order):
                        order, improved = candidate, True
        if best_order is None or path_cost(order) < path_cost(best_order):
            best_order = order
    return best_order


def _plan_video_mix(songs, target_duration_sec,
                    min_sec=VIDEO_SEGMENT_MIN_SEC, max_sec=VIDEO_SEGMENT_MAX_SEC):
    """Normal Mix for video, in two steps. First, every song's cut is
    settled: its strongest hook (see process_files), trimmed to a dynamic
    length exactly as _plan_normal_mix would (pre-cut songs whole). Only
    then is the running order chosen, from the finished clips themselves:
    each possible hand-off is scored on how the end of one clip meets the
    start of the next (_transition_cost), and the order with the smoothest
    transitions overall wins.
    """
    if not songs:
        return []
    lengths = _fit_around_precut(songs, target_duration_sec, min_sec, max_sec)
    clips = [_main_segment(s, length) for s, length in zip(songs, lengths)]
    profiles = [_transition_profile(s, c) for s, c in zip(songs, clips)]
    cost = [
        [0.0 if a == b else _transition_cost(profiles[a], profiles[b]) for b in range(len(clips))]
        for a in range(len(clips))
    ]
    return [clips[i] for i in _best_transition_order(cost)]


def _plan_loop_mix(songs, target_duration_sec):
    """Phase A: every song's main hook once, dynamic length weighted by
    hook-type fit within [SEGMENT_MIN_SEC, SEGMENT_MAX_SEC] (pre-cut songs
    whole). Phase B (once phase A maxes out): add reprise hooks, highest-
    fit song first, until the target is reached. Pre-cut songs have no
    reprise -- the user's cut is the only part of them there is.
    """
    n = len(songs)
    if n == 0:
        return []

    crossfade_sec = CROSSFADE_MS / 1000.0
    ordered_songs = order_by_feel(songs)
    main_max = [
        len(s["hooks"][0]["segment"]) / 1000.0 if s["precut"] else SEGMENT_MAX_SEC
        for s in ordered_songs
    ]
    phase_a_max = sum(main_max) - (n - 1) * crossfade_sec

    if target_duration_sec <= phase_a_max or n == 1:
        return _plan_normal_mix(songs, target_duration_sec)

    # Phase B: mains locked at full length, reprises added — highest
    # hook-type fit first — until we reach the target. Which songs to
    # include is chosen greedily off an average length estimate; the
    # included set's actual per-song lengths are then computed
    # dynamically (weighted by fit) to close the remaining gap.
    mains = [_main_segment(s, SEGMENT_MAX_SEC) for s in ordered_songs]

    current_total = phase_a_max
    reprise_candidates = [s for s in songs if len(s["hooks"]) > 1 and not s["precut"]]
    reprise_candidates.sort(key=lambda s: s["hooks"][1]["score"], reverse=True)

    avg_len = (SEGMENT_MIN_SEC + SEGMENT_MAX_SEC) / 2.0
    used_songs = []
    for s in reprise_candidates:
        if current_total >= target_duration_sec:
            break
        used_songs.append(s)
        current_total += avg_len - crossfade_sec

    if not used_songs:
        return mains

    # Reprises ordered by feel, starting from the high-BPM end: a wave
    # back down, echoing the ascending-then-descending pass style of
    # the original mix logic. Each new segment crossfades against the
    # one before it (including the first reprise against the last
    # main), hence the "+ crossfade_sec".
    ordered_reprises = order_by_feel(
        used_songs, score_key=lambda s: s["hooks"][1]["score"], descending=True
    )
    remaining_target = target_duration_sec - phase_a_max + crossfade_sec
    lengths = _compute_dynamic_lengths(
        ordered_reprises, remaining_target, score_key=lambda s: s["hooks"][1]["score"]
    )
    extras = [
        trim_segment_to_beat(s["hooks"][1]["segment"], length, s["hooks"][1].get("beat_offsets"))
        for s, length in zip(ordered_reprises, lengths)
    ]
    return mains + extras


def _plan_ultra_mix(songs, target_duration_sec):
    """Fast interleaved mashup. Phase A: every song's main hook gets a
    dynamic length (weighted by hook-type fit, like the other modes),
    split into two consecutive halves played round-robin (all "A"
    halves in feel order, then all "B" halves) instead of finishing one
    song before the next. Phase B (once phase A maxes out): songs
    progressively also contribute their reprise hook, split the same
    way and appended as two more rounds, highest-fit song first.

    Pre-cut songs aren't chopped: each plays whole, in the "A" round at
    its place in the feel order, and has no "B" half or reprise.
    """
    n = len(songs)
    if n == 0:
        return []

    crossfade_sec = CROSSFADE_MS / 1000.0
    ordered_songs = order_by_feel(songs)
    precut_total = sum(len(s["hooks"][0]["segment"]) / 1000.0 for s in ordered_songs if s["precut"])
    m = sum(1 for s in ordered_songs if not s["precut"])
    p = n - m
    phase_a_max = precut_total + 2 * m * ULTRA_CHUNK_MAX_SEC - (p + 2 * m - 1) * crossfade_sec

    def split_round(lengths_for_split):
        halves_a, halves_b = [], []
        for s, chunk_len in zip(ordered_songs, lengths_for_split):
            if s["precut"]:
                halves_a.append(s["hooks"][0]["segment"])
                continue
            a, b = split_into_ultra_chunks_to_beat(
                s["hooks"][0]["segment"], chunk_len, s["hooks"][0].get("beat_offsets")
            )
            halves_a.append(a)
            halves_b.append(b)
        return halves_a, halves_b

    if target_duration_sec <= phase_a_max or n == 1:
        full_lengths = _fit_around_precut(
            ordered_songs, target_duration_sec, SEGMENT_MIN_SEC, SEGMENT_MAX_SEC, segments_per_song=2
        )
        halves_a, halves_b = split_round([length / 2.0 for length in full_lengths])
        return halves_a + halves_b

    # Phase B: main hooks locked at max chunk length, reprise chunk-pairs
    # added — highest hook-type fit first — until target is reached.
    halves_a, halves_b = split_round([ULTRA_CHUNK_MAX_SEC] * n)

    current_total = phase_a_max
    reprise_candidates = [s for s in songs if len(s["hooks"]) > 1 and not s["precut"]]
    reprise_candidates.sort(key=lambda s: s["hooks"][1]["score"], reverse=True)

    avg_chunk = (ULTRA_CHUNK_MIN_SEC + ULTRA_CHUNK_MAX_SEC) / 2.0
    used_songs = []
    for s in reprise_candidates:
        if current_total >= target_duration_sec:
            break
        used_songs.append(s)
        current_total += 2 * avg_chunk - 2 * crossfade_sec

    if not used_songs:
        return halves_a + halves_b

    ordered_reprises = order_by_feel(
        used_songs, score_key=lambda s: s["hooks"][1]["score"], descending=True
    )
    r = len(ordered_reprises)
    remaining_target = target_duration_sec - phase_a_max
    adj_target = remaining_target + (r + 1) * crossfade_sec
    reprise_lengths = _compute_dynamic_lengths(
        ordered_reprises, adj_target, score_key=lambda s: s["hooks"][1]["score"]
    )

    extra_a, extra_b = [], []
    for s, length in zip(ordered_reprises, reprise_lengths):
        a, b = split_into_ultra_chunks_to_beat(
            s["hooks"][1]["segment"], length / 2.0, s["hooks"][1].get("beat_offsets")
        )
        extra_a.append(a)
        extra_b.append(b)

    return halves_a + halves_b + extra_a + extra_b


# --------------------------------------------------------------------------
# Orchestration — reusable by both the CLI script and the desktop UI
# --------------------------------------------------------------------------

def _path_key(path):
    return os.path.normcase(os.path.abspath(path))


def analyze_precut(audio):
    """BPM of a pre-cut file (the user's own finished cut), for ordering
    it among the other songs -- no hook search, since the whole file is
    what gets used.
    """
    y, sr = audio_segment_to_mono_float(audio)
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    return float(np.atleast_1d(tempo)[0])


def process_files(filepaths, mode=MODE_LOOP, target_duration_sec=None, hook_type=HOOK_TYPE_NORMAL,
                  progress_callback=None, locked_paths=None, media_type=MEDIA_AUDIO,
                  precut_paths=None):
    """Run the full pipeline over an explicit list of audio file paths:
    analyze -> extract hook(s) -> order/combine -> crossfade combine.

    mode is one of MIX_MODES (MODE_NORMAL / MODE_LOOP / MODE_ULTRA) and
    only takes effect when target_duration_sec is given (seconds). With
    target_duration_sec=None, every available hook (main + reprise) is
    used for every song, ordered in alternating BPM passes — this is
    the original, mode-agnostic behavior used by the CLI.

    hook_type is one of HOOK_TYPES, selecting which part of each song is
    used as the hook. A song with no qualifying section for the chosen
    hook_type (HOOK_TYPE_MELODY/HOOK_TYPE_DANCE only) is skipped --
    unless its path is in locked_paths, in which case its closest-
    matching section is used instead (see analyze_track).

    Files in precut_paths are the user's own finished cuts: no hook
    detection or trimming, the whole file goes into the mix once (in its
    place in the tempo/energy order) and the other songs' lengths are
    sized around it.

    media_type MEDIA_VIDEO analyzes each video's soundtrack exactly like
    an audio file, but always plans a Normal Mix with the video segment
    bounds (see segment_bounds); the returned "clips" then feed
    render_video_mix.

    progress_callback, if given, is called as
    progress_callback(message: str, percent: int) so a caller (CLI or
    UI) can report status without this module knowing how it's shown.

    Returns a dict:
        {
            "mix": AudioSegment or None,
            "clips": [SourceClip, ...],   # the mix's segments, in order
            "media_type": str,
            "processed_filenames": [str, ...],
            "skipped": [(filename, reason), ...],
            "closest_match": [filename, ...],  # locked songs that didn't
                                               # match the hook type
            "total_hooks": int,
        }
    """
    def report(message, percent):
        if progress_callback:
            progress_callback(message, percent)

    locked = {_path_key(p) for p in (locked_paths or [])}
    precut = {_path_key(p) for p in (precut_paths or [])}
    if media_type == MEDIA_VIDEO:
        mode = MODE_NORMAL
        if target_duration_sec is None:
            # No target: give every video its longest cut.
            target_duration_sec = estimate_duration_range(len(filepaths), MODE_NORMAL, MEDIA_VIDEO)[1]

    total = len(filepaths)
    results = []
    skipped = []
    processed_filenames = []
    closest_match = []

    for i, filepath in enumerate(filepaths):
        filename = os.path.basename(filepath)
        # Analysis phase fills the first 80% of the progress range.
        percent = int((i / total) * 80) if total else 0

        try:
            report(f"Analyzing {filename}...", percent)
            audio = AudioSegment.from_file(filepath)
            if len(audio) == 0 or audio.dBFS < SILENT_FILE_DBFS:
                skipped.append((filename, "Audio is silent (the file may be damaged)"))
                continue
            if _path_key(filepath) in precut:
                results.append({
                    "filename": filename,
                    "filepath": filepath,
                    "bpm": analyze_precut(audio),
                    "segment": SourceClip(audio, filepath, 0.0),
                    "variation": 0,
                    "score": None,  # filled in below, once other songs are scored
                    "beat_offsets": [],
                    "precut": True,
                })
                processed_filenames.append(filename)
                continue

            info = analyze_track(
                audio, hook_type=hook_type, locked=_path_key(filepath) in locked,
                hook_window_sec=segment_bounds(media_type)[1],
            )

            if not info["hooks"]:
                type_label = HOOK_TYPE_LABELS.get(hook_type, hook_type).replace(" Hook", "")
                skipped.append((filename, f"No distinct {type_label.lower()} section found"))
                continue
            if info["closest_match"]:
                closest_match.append(filename)

            report(f"Detecting hook in {filename}...", percent)
            hooks = info["hooks"]
            if media_type == MEDIA_VIDEO:
                # analyze_track returns hooks in time order, and a mix uses
                # hooks[0] -- for video, make that the strongest-scoring
                # section instead of just the earliest of the candidates.
                hooks = sorted(hooks, key=lambda h: h["score"], reverse=True)
            for variation, hook in enumerate(hooks):
                start_ms = int(hook["hook_start"] * 1000)
                segment = extract_hook_segment(audio, hook["hook_start"], hook["hook_end"])
                results.append({
                    "filename": filename,
                    "filepath": filepath,
                    "bpm": info["bpm"],
                    "segment": SourceClip(segment, filepath, start_ms / 1000.0),
                    "variation": variation,
                    "score": hook["score"],
                    "beat_offsets": hook.get("beat_offsets", []),
                })
            processed_filenames.append(filename)
        except Exception as e:
            skipped.append((filename, str(e)))
            continue

    if not results:
        report("No tracks could be processed.", 100)
        return {
            "mix": None,
            "clips": [],
            "media_type": media_type,
            "processed_filenames": processed_filenames,
            "skipped": skipped,
            "closest_match": closest_match,
            "total_hooks": 0,
        }

    # A pre-cut song has no hook score of its own (nothing was searched);
    # give it the batch's median so it sits neutrally in feel ordering.
    scored = sorted(r["score"] for r in results if r["score"] is not None and r["variation"] == 0)
    neutral_score = scored[len(scored) // 2] if scored else 0.0
    for r in results:
        if r["score"] is None:
            r["score"] = neutral_score

    report("Ordering by feel...", 85)

    if target_duration_sec is None:
        # Original, mode-agnostic behavior: use every available hook
        # (main + reprise) for every song. Group entries into passes by
        # variation index: pass 0 is every song's main hook, pass 1 is
        # the reprise for songs that have one. Each pass is chained by
        # tempo+energy feel rather than raw BPM, alternating direction
        # (ascending, then descending) so the mix ramps up then back
        # down like a wave, with every hand-off landing on whichever
        # remaining song feels closest to the one before it.
        max_variation = max(r["variation"] for r in results)
        ordered = []
        for pass_idx in range(max_variation + 1):
            pass_entries = [r for r in results if r["variation"] == pass_idx]
            pass_entries = _nearest_neighbor_chain(
                pass_entries,
                bpm_key=lambda r: r["bpm"],
                score_key=lambda r: r["score"],
                descending=(pass_idx % 2 == 1),
            )
            ordered.extend(pass_entries)
        hooks = [r["segment"] for r in ordered]
    else:
        songs = _group_by_song(results)
        if media_type == MEDIA_VIDEO:
            report("Matching transitions...", 87)
            hooks = _plan_video_mix(songs, target_duration_sec)
        elif mode == MODE_NORMAL:
            hooks = _plan_normal_mix(songs, target_duration_sec)
        elif mode == MODE_ULTRA:
            hooks = _plan_ultra_mix(songs, target_duration_sec)
        else:
            hooks = _plan_loop_mix(songs, target_duration_sec)

    report("Combining tracks...", 90)
    final_mix = combine_hooks([clip.audio for clip in hooks], CROSSFADE_MS)

    report("Done.", 100)
    return {
        "mix": final_mix,
        "clips": hooks,
        "media_type": media_type,
        "processed_filenames": processed_filenames,
        "skipped": skipped,
        "closest_match": closest_match,
        "total_hooks": len(results),
    }


def run_cli(input_folder=DEFAULT_INPUT_FOLDER, output_folder=DEFAULT_OUTPUT_FOLDER,
            output_filename=None, media_type=MEDIA_AUDIO, hook_type=HOOK_TYPE_NORMAL):
    """Command-line entry point: process every audio (or video) file in a
    folder and print progress to the console. Used by mashup.py.
    """
    warnings.filterwarnings("ignore")
    os.makedirs(output_folder, exist_ok=True)
    if output_filename is None:
        output_filename = (
            DEFAULT_VIDEO_OUTPUT_FILENAME if media_type == MEDIA_VIDEO else DEFAULT_OUTPUT_FILENAME
        )

    kind = "video" if media_type == MEDIA_VIDEO else "audio"
    audio_files = get_media_files(input_folder, media_type)
    if not audio_files:
        print(f"No {kind} files found in {input_folder}")
        return

    print(f"Found {len(audio_files)} {kind} file(s) in {input_folder}\n")

    def cli_progress(message, percent):
        print(f"[{percent:3d}%] {message}")

    result = process_files(
        audio_files, hook_type=hook_type, progress_callback=cli_progress, media_type=media_type
    )

    if result["skipped"]:
        print()
        for filename, reason in result["skipped"]:
            print(f"  WARNING: skipped '{filename}': {reason}")

    if result["mix"] is None:
        print("\nNo tracks were successfully processed. Nothing to mix.")
        return

    output_path = os.path.join(output_folder, output_filename)
    if media_type == MEDIA_VIDEO:
        render_video_mix(result["clips"], result["mix"], output_path, progress_callback=cli_progress)
    else:
        export_mix(result["mix"], output_path)

    duration_sec = len(result["mix"]) / 1000.0
    reprise_count = len(result["clips"]) - len(result["processed_filenames"])
    print(f"\nDone. Successfully mixed {len(result['processed_filenames'])} of {len(audio_files)} songs "
          f"({reprise_count} reprise segment(s), {len(result['clips'])} segments in the mix).")
    print(f"Output: {output_path}")
    print(f"Final duration: {duration_sec:.1f}s ({duration_sec / 60:.1f} min)")
