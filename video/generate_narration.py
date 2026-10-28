#!/usr/bin/env python3
"""Generate all narration tracks from the editable chapter text files."""
import argparse
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent
CHAPTERS = ('cover', 'system', 'hardware', 'nominal', 'star', 'dynamic', 'closing')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edge-tts', default=shutil.which('edge-tts') or str(Path.home()/'venv/bin/edge-tts'))
    parser.add_argument('--voice', default='en-US-ChristopherNeural')
    args = parser.parse_args()
    for name in CHAPTERS:
        stem = ROOT/'narration'/name
        if not stem.with_suffix('.txt').is_file():
            raise FileNotFoundError(stem.with_suffix('.txt'))
    for name in CHAPTERS:
        stem = ROOT/'narration'/name
        print(f'Generating {name}: {args.voice}', flush=True)
        subprocess.run([args.edge_tts, '--voice', args.voice, '--file', str(stem.with_suffix('.txt')),
                        '--write-media', str(stem.with_suffix('.mp3')),
                        '--write-subtitles', str(stem.with_suffix('.srt'))], check=True)
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(stem.with_suffix('.mp3')),
                        '-ar', '48000', '-ac', '2', str(stem.with_suffix('.wav'))], check=True)


if __name__ == '__main__':
    main()
