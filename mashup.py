"""
CLI entry point for the auto DJ mashup generator.

Drops all songs from INPUT_FOLDER, finds each one's "hook" (and a
reprise section), beat-snaps the cut points, sorts by BPM, crossfades
them together, and exports one continuous mix.

With --video, it uses the video files (mp4/mkv/mov/webm) in the folder
instead: each video's soundtrack is analyzed the same way, the picture
is cut at the same points, and the result is an mp4 (Normal Mix).

The actual processing logic lives in pipeline.py (shared with the
PySide6 desktop app in app/); this script just points it at a folder
and prints progress to the console.

Requires ffmpeg to be installed and on PATH (used by pydub for
decoding/encoding mp3, wav, and m4a, and for rendering video mixes).
See requirements.txt.

Tunable constants (crossfade length, hook length, etc.) live at the
top of pipeline.py.
"""

import argparse

import pipeline

INPUT_FOLDER = "./songs"
OUTPUT_FOLDER = "./output"


def main():
    parser = argparse.ArgumentParser(description="Build a crossfaded party mix from a folder of songs.")
    parser.add_argument("--video", action="store_true",
                        help="mix the video files in the folder into an mp4 instead of an mp3")
    parser.add_argument("--hook", choices=pipeline.HOOK_TYPES, default=pipeline.HOOK_TYPE_NORMAL,
                        help="which part of each song to use (default: %(default)s)")
    parser.add_argument("--input", default=INPUT_FOLDER, help="folder of songs (default: %(default)s)")
    args = parser.parse_args()

    media_type = pipeline.MEDIA_VIDEO if args.video else pipeline.MEDIA_AUDIO
    pipeline.run_cli(args.input, OUTPUT_FOLDER, media_type=media_type, hook_type=args.hook)


if __name__ == "__main__":
    main()
