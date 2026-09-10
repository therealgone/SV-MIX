"""
Core audio mashup pipeline: BPM detection, hook extraction (with an
optional reprise section), and crossfade combining.

This module has no UI dependencies. It is used by the CLI script
(mashup.py) and by the PySide6 desktop app (app/).
"""

import os
import glob
import warnings

import numpy as np
import librosa
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

ANALYSIS_SR = 22050          # sample rate used for BPM/energy analysis
ENERGY_WINDOW_SEC = 1.5      # window size for RMS energy estimation

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


# --------------------------------------------------------------------------
# Analysis helpers
# --------------------------------------------------------------------------

def get_audio_files(folder):
    """Return sorted list of audio file paths in folder matching supported extensions."""
    files = []
    for ext in AUDIO_EXTENSIONS:
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


def find_typed_hook_windows(
    times, rms, centroid, duration, hook_type, num_windows=HOOKS_PER_SONG, local_tempo=None
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
    """
    valid_start = duration * INTRO_SKIP_FRACTION
    valid_end = duration * (1.0 - OUTRO_SKIP_FRACTION)

    if valid_end - valid_start < HOOK_MIN_SEC:
        return []

    valid_mask = (times >= valid_start) & (times <= valid_end)
    valid_indices = np.where(valid_mask)[0]
    if len(valid_indices) == 0:
        return []

    valid_rms = rms[valid_indices]
    mean_rms = float(np.mean(valid_rms))
    if mean_rms <= 0:
        return []
    if hook_type != HOOK_TYPE_KUTHU:
        # Flat-energy songs have no genuine melody/dance contrast — skip
        # them entirely rather than picking an arbitrary window. This
        # doesn't apply to kuthu: a relentlessly loud, non-stop beat
        # *is* the kuthu vibe, not a disqualifying lack of contrast.
        relative_std = float(np.std(valid_rms)) / mean_rms
        if relative_std < DISTINCT_DYNAMICS_MIN_RELATIVE_STD:
            return []

    window_sec = min(HOOK_TARGET_SEC, valid_end - valid_start)
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
            combined = 0.65 * norm_rms + 0.35 * norm_tempo
        elif hook_type == HOOK_TYPE_MELODY:
            if avg_rms < rms_floor:
                continue
            avg_tempo = float(np.mean(local_tempo[idx:end_idx]))
            if avg_tempo > MELODY_MAX_TEMPO_BPM:
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
            combined = 0.5 * norm_rms + 0.5 * norm_centroid

        candidates.append((combined, idx, end_idx))

    if not candidates:
        return []

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


def find_top_hook_windows(times, rms, duration, num_windows=HOOKS_PER_SONG):
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

    window_sec = min(HOOK_TARGET_SEC, valid_end - valid_start)

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


def analyze_track(audio, hook_type=HOOK_TYPE_NORMAL):
    """Analyze a pydub AudioSegment. Returns a dict with bpm, duration,
    and a list of beat-snapped hooks ({"hook_start", "hook_end"}). The
    first hook is the strongest section; any further ones are distinct
    sections usable as a later reprise of the same song.

    hook_type selects which part of the song counts as "the hook" (see
    HOOK_TYPES). For HOOK_TYPE_MELODY/HOOK_TYPE_DANCE/HOOK_TYPE_KUTHU,
    "hooks" may come back empty if the song has no section distinct
    enough to qualify.
    """
    y, sr = audio_segment_to_mono_float(audio)
    duration = librosa.get_duration(y=y, sr=sr)

    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    bpm = float(np.atleast_1d(tempo)[0])
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    times, rms = compute_rms_energy(y, sr)
    if hook_type == HOOK_TYPE_NORMAL:
        raw_windows = find_top_hook_windows(times, rms, duration)
    elif hook_type == HOOK_TYPE_KUTHU:
        local_tempo = compute_local_tempo(times, y, sr)
        raw_windows = find_typed_hook_windows(
            times, rms, None, duration, hook_type, local_tempo=local_tempo
        )
    elif hook_type == HOOK_TYPE_MELODY:
        centroid = compute_spectral_centroid(y, sr)
        local_tempo = compute_local_tempo(times, y, sr)
        raw_windows = find_typed_hook_windows(
            times, rms, centroid, duration, hook_type, local_tempo=local_tempo
        )
    else:
        centroid = compute_spectral_centroid(y, sr)
        raw_windows = find_typed_hook_windows(times, rms, centroid, duration, hook_type)

    hooks = []
    for raw_start, raw_end, score in raw_windows:
        hook_start = snap_to_beat(raw_start, beat_times)
        hook_end = snap_to_beat(raw_end, beat_times)
        # Guard against snapping collapsing the window or reversing order.
        if hook_end <= hook_start:
            hook_end = min(hook_start + HOOK_MIN_SEC, duration)
        hooks.append({"hook_start": hook_start, "hook_end": hook_end, "score": score})

    return {
        "bpm": bpm,
        "duration": duration,
        "hooks": hooks,
    }


# --------------------------------------------------------------------------
# Audio extraction / combination
# --------------------------------------------------------------------------

def extract_hook_segment(audio, hook_start, hook_end):
    """Slice the hook out of an already-loaded pydub AudioSegment."""
    start_ms = int(hook_start * 1000)
    end_ms = int(hook_end * 1000)
    return audio[start_ms:end_ms]


def combine_hooks(hooks, crossfade_ms=CROSSFADE_MS):
    """Crossfade a list of AudioSegments together into one track."""
    mixed = hooks[0]
    for segment in hooks[1:]:
        fade = min(crossfade_ms, len(mixed) - 1, len(segment) - 1)
        fade = max(fade, 0)
        mixed = mixed.append(segment, crossfade=fade)
    return mixed


def export_mix(mix, output_path, bitrate=EXPORT_BITRATE):
    """Export a combined AudioSegment to an mp3 file."""
    mix.export(output_path, format="mp3", bitrate=bitrate)


# --------------------------------------------------------------------------
# Mix modes & duration planning
# --------------------------------------------------------------------------

def estimate_duration_range(num_songs, mode):
    """Return (min_sec, max_sec): the achievable total mix duration for
    num_songs songs in the given mode. Pure arithmetic (no audio
    decoding), so it's cheap enough to call live from the UI as files
    are added/removed or the mode is changed.
    """
    if num_songs <= 0:
        return (0.0, 0.0)

    crossfade_sec = CROSSFADE_MS / 1000.0

    def total_for(segment_count, segment_len):
        return segment_count * segment_len - max(segment_count - 1, 0) * crossfade_sec

    if mode == MODE_NORMAL:
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
    per-song dicts: {"filename", "bpm", "hooks": [result, ...]}, hooks
    sorted by variation (0 = main hook, 1 = reprise).
    """
    songs = []
    by_filename = {}
    for r in results:
        song = by_filename.get(r["filename"])
        if song is None:
            song = {"filename": r["filename"], "bpm": r["bpm"], "hooks": []}
            by_filename[r["filename"]] = song
            songs.append(song)
        song["hooks"].append(r)
    for song in songs:
        song["hooks"].sort(key=lambda r: r["variation"])
    return songs


def _plan_normal_mix(songs, target_duration_sec):
    """Every song's main hook exactly once, ordered by feel (tempo +
    energy) rather than raw BPM, each given a dynamic length in
    [SEGMENT_MIN_SEC, SEGMENT_MAX_SEC] weighted by how strongly it fits
    the selected hook type, scaled to hit target_duration_sec overall.
    """
    n = len(songs)
    if n == 0:
        return []

    ordered_songs = order_by_feel(songs)
    lengths = _compute_dynamic_lengths(
        ordered_songs, target_duration_sec, score_key=lambda s: s["hooks"][0]["score"]
    )
    return [
        trim_segment(s["hooks"][0]["segment"], length)
        for s, length in zip(ordered_songs, lengths)
    ]


def _plan_loop_mix(songs, target_duration_sec):
    """Phase A: every song's main hook once, dynamic length weighted by
    hook-type fit within [SEGMENT_MIN_SEC, SEGMENT_MAX_SEC]. Phase B
    (once phase A maxes out): add reprise hooks, highest-fit song
    first, until the target is reached.
    """
    n = len(songs)
    if n == 0:
        return []

    crossfade_sec = CROSSFADE_MS / 1000.0

    def total_for(segment_count, segment_len):
        return segment_count * segment_len - max(segment_count - 1, 0) * crossfade_sec

    phase_a_max = total_for(n, SEGMENT_MAX_SEC)
    ordered_songs = order_by_feel(songs)

    if target_duration_sec <= phase_a_max or n == 1:
        lengths = _compute_dynamic_lengths(
            ordered_songs, target_duration_sec, score_key=lambda s: s["hooks"][0]["score"]
        )
        return [
            trim_segment(s["hooks"][0]["segment"], length)
            for s, length in zip(ordered_songs, lengths)
        ]

    # Phase B: mains locked at full length, reprises added — highest
    # hook-type fit first — until we reach the target. Which songs to
    # include is chosen greedily off an average length estimate; the
    # included set's actual per-song lengths are then computed
    # dynamically (weighted by fit) to close the remaining gap.
    mains = [trim_segment(s["hooks"][0]["segment"], SEGMENT_MAX_SEC) for s in ordered_songs]

    current_total = phase_a_max
    reprise_candidates = [s for s in songs if len(s["hooks"]) > 1]
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
        trim_segment(s["hooks"][1]["segment"], length)
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
    """
    n = len(songs)
    if n == 0:
        return []

    crossfade_sec = CROSSFADE_MS / 1000.0

    def total_for(segment_count, segment_len):
        return segment_count * segment_len - max(segment_count - 1, 0) * crossfade_sec

    phase_a_max = total_for(2 * n, ULTRA_CHUNK_MAX_SEC)
    ordered_songs = order_by_feel(songs)

    if target_duration_sec <= phase_a_max or n == 1:
        if n == 1:
            full_lengths = [min(max(target_duration_sec, SEGMENT_MIN_SEC), SEGMENT_MAX_SEC)]
        else:
            # 2n halves total with 2n-1 internal crossfades; each
            # song's full (pre-split) length is what _compute_dynamic_lengths
            # weighs by fit, so the "+ n * crossfade_sec" below converts
            # that segment-count crossfade budget into the per-song one
            # the helper expects (n songs, n-1 crossfades).
            adj_target = target_duration_sec + n * crossfade_sec
            full_lengths = _compute_dynamic_lengths(
                ordered_songs, adj_target, score_key=lambda s: s["hooks"][0]["score"]
            )

        halves_a, halves_b = [], []
        for s, length in zip(ordered_songs, full_lengths):
            a, b = split_into_ultra_chunks(s["hooks"][0]["segment"], length / 2.0)
            halves_a.append(a)
            halves_b.append(b)
        return halves_a + halves_b

    # Phase B: main hooks locked at max chunk length, reprise chunk-pairs
    # added — highest hook-type fit first — until target is reached.
    halves_a, halves_b = [], []
    for s in ordered_songs:
        a, b = split_into_ultra_chunks(s["hooks"][0]["segment"], ULTRA_CHUNK_MAX_SEC)
        halves_a.append(a)
        halves_b.append(b)

    current_total = phase_a_max
    reprise_candidates = [s for s in songs if len(s["hooks"]) > 1]
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
    m = len(ordered_reprises)
    remaining_target = target_duration_sec - phase_a_max
    adj_target = remaining_target + (m + 1) * crossfade_sec
    reprise_lengths = _compute_dynamic_lengths(
        ordered_reprises, adj_target, score_key=lambda s: s["hooks"][1]["score"]
    )

    extra_a, extra_b = [], []
    for s, length in zip(ordered_reprises, reprise_lengths):
        a, b = split_into_ultra_chunks(s["hooks"][1]["segment"], length / 2.0)
        extra_a.append(a)
        extra_b.append(b)

    return halves_a + halves_b + extra_a + extra_b


# --------------------------------------------------------------------------
# Orchestration — reusable by both the CLI script and the desktop UI
# --------------------------------------------------------------------------

def process_files(filepaths, mode=MODE_LOOP, target_duration_sec=None, hook_type=HOOK_TYPE_NORMAL, progress_callback=None):
    """Run the full pipeline over an explicit list of audio file paths:
    analyze -> extract hook(s) -> order/combine -> crossfade combine.

    mode is one of MIX_MODES (MODE_NORMAL / MODE_LOOP / MODE_ULTRA) and
    only takes effect when target_duration_sec is given (seconds). With
    target_duration_sec=None, every available hook (main + reprise) is
    used for every song, ordered in alternating BPM passes — this is
    the original, mode-agnostic behavior used by the CLI.

    hook_type is one of HOOK_TYPES, selecting which part of each song is
    used as the hook. A song with no qualifying section for the chosen
    hook_type (HOOK_TYPE_MELODY/HOOK_TYPE_DANCE only) is skipped.

    progress_callback, if given, is called as
    progress_callback(message: str, percent: int) so a caller (CLI or
    UI) can report status without this module knowing how it's shown.

    Returns a dict:
        {
            "mix": AudioSegment or None,
            "processed_filenames": [str, ...],
            "skipped": [(filename, reason), ...],
            "total_hooks": int,
        }
    """
    def report(message, percent):
        if progress_callback:
            progress_callback(message, percent)

    total = len(filepaths)
    results = []
    skipped = []
    processed_filenames = []

    for i, filepath in enumerate(filepaths):
        filename = os.path.basename(filepath)
        # Analysis phase fills the first 80% of the progress range.
        percent = int((i / total) * 80) if total else 0

        try:
            report(f"Analyzing {filename}...", percent)
            audio = AudioSegment.from_file(filepath)
            info = analyze_track(audio, hook_type=hook_type)

            if not info["hooks"]:
                type_label = HOOK_TYPE_LABELS.get(hook_type, hook_type).replace(" Hook", "")
                skipped.append((filename, f"No distinct {type_label.lower()} section found"))
                continue

            report(f"Detecting hook in {filename}...", percent)
            for variation, hook in enumerate(info["hooks"]):
                segment = extract_hook_segment(audio, hook["hook_start"], hook["hook_end"])
                results.append({
                    "filename": filename,
                    "bpm": info["bpm"],
                    "segment": segment,
                    "variation": variation,
                    "score": hook["score"],
                })
            processed_filenames.append(filename)
        except Exception as e:
            skipped.append((filename, str(e)))
            continue

    if not results:
        report("No tracks could be processed.", 100)
        return {
            "mix": None,
            "processed_filenames": processed_filenames,
            "skipped": skipped,
            "total_hooks": 0,
        }

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
        if mode == MODE_NORMAL:
            hooks = _plan_normal_mix(songs, target_duration_sec)
        elif mode == MODE_ULTRA:
            hooks = _plan_ultra_mix(songs, target_duration_sec)
        else:
            hooks = _plan_loop_mix(songs, target_duration_sec)

    report("Combining tracks...", 90)
    final_mix = combine_hooks(hooks, CROSSFADE_MS)

    report("Done.", 100)
    return {
        "mix": final_mix,
        "processed_filenames": processed_filenames,
        "skipped": skipped,
        "total_hooks": len(results),
    }


def run_cli(input_folder=DEFAULT_INPUT_FOLDER, output_folder=DEFAULT_OUTPUT_FOLDER,
            output_filename=DEFAULT_OUTPUT_FILENAME):
    """Command-line entry point: process every audio file in a folder
    and print progress to the console. Used by mashup.py.
    """
    warnings.filterwarnings("ignore")
    os.makedirs(output_folder, exist_ok=True)

    audio_files = get_audio_files(input_folder)
    if not audio_files:
        print(f"No audio files found in {input_folder}")
        return

    print(f"Found {len(audio_files)} audio file(s) in {input_folder}\n")

    def cli_progress(message, percent):
        print(f"[{percent:3d}%] {message}")

    result = process_files(audio_files, progress_callback=cli_progress)

    if result["skipped"]:
        print()
        for filename, reason in result["skipped"]:
            print(f"  WARNING: skipped '{filename}': {reason}")

    if result["mix"] is None:
        print("\nNo tracks were successfully processed. Nothing to mix.")
        return

    output_path = os.path.join(output_folder, output_filename)
    export_mix(result["mix"], output_path)

    duration_sec = len(result["mix"]) / 1000.0
    reprise_count = result["total_hooks"] - len(result["processed_filenames"])
    print(f"\nDone. Successfully mixed {len(result['processed_filenames'])} of {len(audio_files)} songs "
          f"({reprise_count} reprise segment(s), {result['total_hooks']} total hooks).")
    print(f"Output: {output_path}")
    print(f"Final duration: {duration_sec:.1f}s ({duration_sec / 60:.1f} min)")
