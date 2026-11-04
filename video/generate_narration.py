#!/usr/bin/env python3
"""Generate all narration tracks from the editable chapter text files."""
import argparse
from pathlib import Path
import shutil
import subprocess
from benchmark_evidence import benchmark_evidence

ROOT = Path(__file__).resolve().parent
CHAPTERS = ('cover', 'system', 'hardware', 'benchmark', 'nominal', 'star', 'dynamic', 'closing')


def spoken_integer(value):
    """Spell out benchmark ratios so TTS cannot interpret them as years."""
    if not 0 <= value < 1_000_000:
        raise ValueError('Spoken benchmark ratios must be between 0 and 999999')
    small = ('zero one two three four five six seven eight nine ten eleven twelve '
             'thirteen fourteen fifteen sixteen seventeen eighteen nineteen').split()
    tens = 'zero ten twenty thirty forty fifty sixty seventy eighty ninety'.split()
    if value < 20:
        return small[value]
    if value < 100:
        quotient, remainder = divmod(value, 10)
        return tens[quotient] + ('-' + small[remainder] if remainder else '')
    divisor, label = (100, ' hundred') if value < 1000 else (1000, ' thousand')
    quotient, remainder = divmod(value, divisor)
    joiner = ' and ' if remainder < 100 else ' '
    return spoken_integer(quotient) + label + (joiner + spoken_integer(remainder) if remainder else '')


def narration_values(ratios):
    whole, decimal = f"{ratios['speedup']:.1f}".split('.')
    return {'mcu_speedup': spoken_integer(int(whole)) + ' point ' + spoken_integer(int(decimal)),
            'mcu_edp': spoken_integer(int(f"{ratios['edp_reduction']:.0f}"))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edge-tts', default=shutil.which('edge-tts') or str(Path.home()/'venv/bin/edge-tts'))
    parser.add_argument('--voice', default='en-US-ChristopherNeural')
    parser.add_argument('--chapters', nargs='+', choices=CHAPTERS, default=CHAPTERS,
                        help='Regenerate only selected chapters')
    args = parser.parse_args()
    for name in args.chapters:
        stem = ROOT/'narration'/name
        if not stem.with_suffix('.txt').is_file():
            raise FileNotFoundError(stem.with_suffix('.txt'))
    for name in args.chapters:
        stem = ROOT/'narration'/name
        print(f'Generating {name}: {args.voice}', flush=True)
        content = stem.with_suffix('.txt').read_text()
        ratios = benchmark_evidence()['ratios']['tinympc_e']
        content = content.format(**narration_values(ratios))
        subprocess.run([args.edge_tts, '--voice', args.voice, '--text', content,
                        '--write-media', str(stem.with_suffix('.mp3')),
                        '--write-subtitles', str(stem.with_suffix('.srt'))], check=True)
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(stem.with_suffix('.mp3')),
                        '-ar', '48000', '-ac', '2', str(stem.with_suffix('.wav'))], check=True)


if __name__ == '__main__':
    main()
