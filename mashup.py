"""
CLI entry point for the auto DJ mashup generator.

Drops all songs from INPUT_FOLDER, finds each one's "hook" (and a
reprise section), beat-snaps the cut points, sorts by BPM, crossfades
them together, and exports one continuous mix.

The actual processing logic lives in pipeline.py (shared with the
PySide6 desktop app in app/); this script just points it at a folder
and prints progress to the console.

Requires ffmpeg to be installed and on PATH (used by pydub for
decoding/encoding mp3, wav, and m4a). See requirements.txt.

Tunable constants (crossfade length, hook length, etc.) live at the
top of pipeline.py.
"""

import pipeline

INPUT_FOLDER = "./songs"
OUTPUT_FOLDER = "./output"
OUTPUT_FILENAME = "party_mix.mp3"


def main():
    pipeline.run_cli(INPUT_FOLDER, OUTPUT_FOLDER, OUTPUT_FILENAME)


if __name__ == "__main__":
    main()
