# SV Mix — Microsoft Store listing copy

Paste each block into the matching field in Partner Center →
Store listings → English. Character counts are noted against Microsoft's
limits.

---

## Product name

```
SV Mix
```

---

## Short description
*(Partner Center limit: 1,000 characters — this is ~280)*

```
SV Mix turns a folder of songs into one continuous, crossfaded party mix — automatically. Drop in your tracks and SV Mix analyses each one's tempo and energy, finds the strongest section, snaps the cut points to the beat, and blends everything into a single mix you can preview and export as an MP3. No editing skills needed.
```

---

## Description
*(Partner Center limit: 10,000 characters — this is ~2,900)*

```
SV Mix builds a continuous DJ-style mix out of the songs you already have — no timeline, no manual editing, no experience required.

Add two or more tracks, choose how you want them combined, and SV Mix does the rest. It analyses every song for tempo (BPM) and energy, picks out the strongest section of each one, aligns the cut points to the beat so transitions land musically instead of mid-phrase, and crossfades everything into one seamless mix. Preview it in the app, then export it as an MP3.

HOW IT WORKS

1. Drag in your songs, or browse for them. MP3, WAV and M4A are supported.
2. Pick a mix mode and a hook type, and set how long you want the finished mix to run.
3. Press Mix Songs and watch the progress as each track is analysed.
4. Preview the result, then save it as an MP3.

THREE MIX MODES

Choose how much of each song is used and how long the mix runs.

• Normal Mix — every song is used exactly once, with no repeats. Clean and predictable.
• Loop Mix — every song plays once, then reprises drawn from different sections fill out the rest, so you can build a longer mix from fewer tracks.
• Ultra Mix — a fast, high-energy mashup. Songs are chopped into short interleaved bursts instead of playing end to end.

FOUR HOOK TYPES

Choose which part of each song gets used, independently of the mix mode.

• Normal Hook — the loudest section of the song.
• Melody Hook — the calmest, slowest section, for a more relaxed mix. Songs that stay energetic throughout are skipped rather than forced into a section that isn't really calm.
• Rock-Dance Hook — the loudest and brightest section, tuned to land on drops.
• Kuthu Dance Hook — the loudest, fastest-paced section, tuned for high-energy Tamil kuthu and mass-dance tracks.

BUILT FOR REAL USE

• Beat-aligned transitions. Cut points are snapped to detected beats, so songs join on the beat rather than at an arbitrary timestamp.
• Live preview. Hear the finished mix inside the app before you commit to saving it.
• Clear feedback. If a song is skipped, SV Mix tells you which one and why, rather than silently dropping it.
• Set your own length. A slider controls how long the finished mix should run.
• Export to MP3. Save the mix wherever you want it.

COMPLETELY OFFLINE AND PRIVATE

SV Mix runs entirely on your computer. It makes no network requests, has no accounts or sign-in, and collects no personal data, no analytics and no telemetry. Your music never leaves your device, and nothing about what you mix is recorded or transmitted.

EVERYTHING INCLUDED

SV Mix is fully self-contained. There is nothing extra to install and no separate codec packs or command-line tools to set up — audio support ships inside the app.

GOOD TO KNOW

SV Mix works with the audio files you already own. Analysis quality depends on the source material: cleanly produced tracks with a steady tempo give the most reliable hook detection, while live recordings, spoken word and tracks with heavy tempo changes may produce less predictable cut points. Very short files may be skipped if no section long enough to use can be found.

SV Mix includes FFmpeg, licensed under the LGPL.
```

---

## Product features
*(Limit: 200 characters each, up to 20 — these are all well under)*

```
Automatically builds one continuous, crossfaded mix from your songs
Detects each song's tempo and energy and picks its strongest section
Beat-aligned cut points, so tracks join on the beat
Three mix modes: Normal, Loop and Ultra
Four hook types, including Melody, Rock-Dance and Kuthu Dance
Set how long you want the finished mix to run
Preview the mix in the app before saving
Export your mix as an MP3
Supports MP3, WAV and M4A
Drag and drop, or browse for files
Tells you if a song was skipped, and why
Works fully offline — no account, no telemetry, no data collected
Self-contained: nothing extra to install
```

---

## Search terms
*(Limit: 7 terms, 30 characters each)*

```
music mixer
dj mix maker
party mix
crossfade songs
mashup maker
automatic dj
bpm mixer
```

---

## What's new in this version
*(Limit: 1,500 characters)*

```
First release of SV Mix.

• Automatic mix building from your own audio files, with tempo and energy analysis and beat-aligned transitions.
• Three mix modes (Normal, Loop, Ultra) and four hook types (Normal, Melody, Rock-Dance, Kuthu Dance).
• Adjustable mix length, live preview before saving, and MP3 export.
• Runs fully offline, with audio support included in the app.
```

---

## Additional license terms

```
SV Mix includes FFmpeg (https://ffmpeg.org), licensed under the GNU Lesser General Public License (LGPL). The FFmpeg binaries included with SV Mix are unmodified and are distributed as separate dynamic libraries. Corresponding source code is available from https://git.ffmpeg.org/ffmpeg.git.

SV Mix includes Qt via PySide6, licensed under the LGPL v3, dynamically linked.

Full attribution for all included third-party components is provided in the THIRD-PARTY-NOTICES file installed with the app.
```

---

## Other listing fields

- **Category:** Music → Music creation (or Multimedia design)
- **Privacy policy:** see `PRIVACY.txt`. In Properties, answer **No** to
  "Does this product collect personal information?"
- **Copyright and trademark info:** `© 2026 TRG1. All rights reserved.`
- **Screenshots:** at least one 1366×768 or larger PNG is required. Good
  candidates: the setup screen with songs loaded, the progress ring while
  mixing, and the preview/save screen.

---

## Restricted capability justification — `runFullTrust`

*(Partner Center → Properties → asks why the app needs this capability.)*

```
SV Mix is a traditional Windows desktop application packaged for the Store using the Desktop Bridge. Its manifest declares EntryPoint="Windows.FullTrustApplication", and runFullTrust is the required capability for that application model.

Specifically, the capability is needed for:

1. Native desktop runtime. SV Mix is a Python application using Qt (PySide6) for its interface, together with compiled native extension modules (NumPy, SciPy, librosa) that perform the tempo and energy analysis. These rely on Win32 APIs that are not available inside the UWP app container.

2. Launching bundled FFmpeg as a child process. SV Mix includes FFmpeg (LGPL) in the package and starts ffmpeg.exe and ffprobe.exe as child processes to decode and encode MP3, WAV and M4A audio. Creating child processes requires full trust. FFmpeg is bundled inside the package specifically so the app is self-contained and does not require the user to install anything separately.

3. User-selected file access. The app reads audio files the user explicitly provides, either by drag-and-drop or through the standard file picker, and writes the finished mix only to the location the user chooses in a Save As dialog. It does not scan, index or enumerate the file system on its own.

SV Mix does NOT use this capability to request administrator rights or elevation, modify system or registry settings, install drivers or services, register startup entries or background tasks, access other applications' data, or make any network connection. The application runs entirely offline and collects no user data of any kind.
```
