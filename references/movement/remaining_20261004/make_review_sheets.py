#!/usr/bin/env python3
"""Regenerate labeled visual-review grids; never use grids as scoring input."""
import argparse
import json
import subprocess
from pathlib import Path

from cut_reference import sha256


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-id', required=True)
    ap.add_argument('--source', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--font', type=Path, required=True, help='Existing TTF font path for frame labels')
    ap.add_argument('--only', action='append', help='Optional exact sample group ID')
    args = ap.parse_args()
    here = Path(__file__).parent
    spec = json.loads((here / 'source_map.json').read_text())['sources'][args.source_id]
    if sha256(args.source) != spec['sha256']:
        raise ValueError('Wrong source bytes')
    if not args.font.is_file():
        raise FileNotFoundError(args.font)
    # FFmpeg filter syntax has reserved separators; reject rather than silently
    # interpreting a different filename or allowing an arbitrary filter.
    font = str(args.font.resolve())
    if any(c in font for c in "':,;[]\\"):
        raise ValueError('Use a font path without FFmpeg filter separators')
    samples = json.loads((here / 'review_samples.json').read_text())['samples']
    args.out.mkdir(parents=True, exist_ok=True)
    for s in samples:
        if s['source_id'] != args.source_id or (args.only and s['id'] not in args.only):
            continue
        a, b, step = s['start_frame'], s['end_frame_exclusive'], s['stride_frames']
        vf = (f"drawtext=fontfile={font}:text='f%{{n}}':x=12:y=12:fontsize=48:"
              f"fontcolor=white:box=1:boxcolor=black,"
              f"select='gte(n,{a})*lt(n,{b})*not(mod(n-{a},{step}))',scale=384:216,tile=5x5")
        dest = args.out / (args.source_id + '_' + s['id'] + '_%02d.png')
        subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-n', '-i', str(args.source),
                        '-vf', vf, '-fps_mode', 'vfr', str(dest)], check=True)


if __name__ == '__main__':
    main()
