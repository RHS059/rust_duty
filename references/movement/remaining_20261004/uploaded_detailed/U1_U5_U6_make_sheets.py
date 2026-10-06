"""Recreate the unwarped source contact sheets for U1/U5/U6 (ffmpeg + Pillow).
Usage: python U1_U5_U6_make_sheets.py --source-repo /path/to/rust_duty --output /tmp/sheets
Input source hashes are mandatory. No video trim or action acceptance is generated.
"""
import argparse
import hashlib
import json
import pathlib
import subprocess
from PIL import Image, ImageDraw

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-repo', required=True, type=pathlib.Path)
    ap.add_argument('--output', required=True, type=pathlib.Path)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for sid in ['U1', 'U5', 'U6']:
        spec = json.loads((pathlib.Path(__file__).parent / (sid + '_annotations.json')).read_text())
        source = args.source_repo / spec['source_path']
        assert hashlib.sha256(source.read_bytes()).hexdigest() == spec['sha256'], source
        stride = spec['review_method']['chronological_stride_frames']
        count = spec['frame_count']
        sample = list(range(0, count, stride))
        if sample[-1] != count - 1:
            sample.append(count - 1)
        batches = [(f'{sid}_{page}', sample[page * 30:(page + 1) * 30], False)
                   for page in range((len(sample) + 29) // 30)]
        for a, b in spec['review_method']['native_every_frame_neighborhoods_half_open']:
            batches.append((f'{sid}_native_{a}_{b}', list(range(a, b)), True))
        for name, frames, native in batches:
            select = '+'.join(f'eq(n\\,{f})' for f in frames)
            raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(source),
                '-vf', 'select=' + select + ',scale=320:180', '-fps_mode', 'passthrough',
                '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-threads', '1', '-'])
            assert len(raw) == len(frames) * 172800
            sheet = Image.new('RGB', (1600, 1400 if native else 1200), '#ddd')
            draw = ImageDraw.Draw(sheet)
            for j, f in enumerate(frames):
                im = Image.frombytes('RGB', (320, 180), raw[j*172800:(j+1)*172800])
                x, y = j % 5 * 320, j // 5 * 200
                sheet.paste(im, (x, y+20))
                label = f'{sid} native f{f} PTS {f*256}' if native else f'{sid} f{f} {f/60:.3f}s'
                draw.text((x+4, y+3), label, fill='black')
            sheet.save(args.output / (name + '.jpg'))

if __name__ == '__main__':
    main()
