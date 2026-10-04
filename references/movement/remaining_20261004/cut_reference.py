#!/usr/bin/env python3
"""Make exact, unwarped, native-frame excerpts and verify every decoded pixel.

Requires FFmpeg/ffprobe with libx264. Inputs must match the source SHA-256 pin.
No source download, interpolation, optical flow, audio or inferred PTS is used.
"""
import argparse
import hashlib
import json
import subprocess
from fractions import Fraction
from pathlib import Path


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def run(args):
    return subprocess.check_output(args, text=True)


def inspect(path):
    return json.loads(run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_streams', '-show_frames', '-show_entries',
        'stream=width,height,pix_fmt,r_frame_rate,avg_frame_rate,time_base,duration_ts,nb_frames:frame=pts',
        '-of', 'json', str(path)]))


def frame_hashes(path):
    result = run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path), '-map', '0:v:0',
        '-an', '-c:v', 'rawvideo', '-pix_fmt', 'yuv420p', '-f', 'framemd5', '-'])
    return [line.rsplit(',', 1)[-1].strip() for line in result.splitlines()
            if line and not line.startswith('#')]


def validate_pts(probe, count, fps='60/1', time_base='1/15360'):
    stream = probe['streams'][0]
    frames = probe['frames']
    if stream['time_base'] != time_base or Fraction(stream['avg_frame_rate']) != Fraction(fps):
        raise ValueError('Unexpected timebase or average frame rate')
    ticks = Fraction(1, 1) / Fraction(fps) / Fraction(time_base)
    if ticks.denominator != 1:
        raise ValueError('Nonintegral native frame spacing')
    actual = [frame['pts'] for frame in frames]
    expected = [n * int(ticks) for n in range(count)]
    if actual != expected:
        raise ValueError('Decoded frame count or PTS mismatch')
    if int(stream['duration_ts']) != count * int(ticks):
        raise ValueError('Last frame duration is missing or wrong')
    return actual


def validate_cut(cut, count):
    a, b = cut['start_frame'], cut['end_frame_exclusive']
    if not isinstance(a, int) or not isinstance(b, int) or not 0 <= a < b <= count:
        raise ValueError('Invalid half-open cut bounds')
    return a, b


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--manifest', type=Path, default=Path(__file__).with_name('source_map.json'))
    ap.add_argument('--source-id', required=True)
    ap.add_argument('--source', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--only', action='append', help='One or more exact clip IDs')
    args = ap.parse_args()
    manifest = json.loads(args.manifest.read_text())
    spec = manifest['sources'][args.source_id]
    if sha256(args.source) != spec['sha256']:
        raise ValueError('Source SHA-256 mismatch')
    native = inspect(args.source)
    source_pts = validate_pts(native, spec['frame_count'])
    source_hashes = frame_hashes(args.source)
    if len(source_hashes) != spec['frame_count']:
        raise ValueError('Source pixel audit lost frames')
    args.out.mkdir(parents=True, exist_ok=True)
    reports = []
    cuts = [c for c in manifest['clips'] if c['source_id'] == args.source_id
            and (not args.only or c['id'] in args.only)]
    if not cuts:
        raise ValueError('No matching clips')
    for cut in cuts:
        a, b = validate_cut(cut, len(source_pts))
        dest = args.out / (cut['id'] + '.mp4')
        if not dest.exists():
            # Explicit CFR output supplies the final packet duration. Passthrough
            # output can advertise N frames but decode only N-1 in an MP4.
            subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-n', '-i', str(args.source),
                '-map', '0:v:0', '-an', '-vf',
                f'trim=start_frame={a}:end_frame={b},setpts=PTS-STARTPTS',
                '-r', '60', '-fps_mode', 'cfr', '-c:v', 'libx264', '-qp', '0',
                '-preset', 'fast', '-pix_fmt', 'yuv420p', '-video_track_timescale', '15360',
                '-movflags', '+faststart', str(dest)], check=True)
        probe = inspect(dest)
        clip_pts = validate_pts(probe, b - a)
        decoded_hashes = frame_hashes(dest)
        if decoded_hashes != source_hashes[a:b]:
            raise ValueError(f'{cut["id"]}: decoded native pixels differ')
        mapping = [{'clip_frame': n, 'blender_frame_60fps': n + 1,
                    'clip_pts_ticks': pts, 'source_frame': a + n,
                    'source_pts_ticks': source_pts[a + n]}
                   for n, pts in enumerate(clip_pts)]
        report = {'id': cut['id'], 'source_id': args.source_id, 'source_sha256': spec['sha256'],
            'file': dest.name, 'sha256': sha256(dest), 'bytes': dest.stat().st_size,
            'start_frame': a, 'end_frame_exclusive': b, 'decoded_frames': b - a,
            'fps': '60/1', 'time_base': '1/15360', 'duration_rational_seconds': f'{b-a}/60',
            'all_decoded_pixels_equal_source': True, 'pixel_audit_format': 'yuv420p',
            'source_pixel_md5': source_hashes[a:b], 'frame_map': mapping,
            'audio': 'omitted', 'status': 'source-excerpt-verified; not animation approval'}
        sidecar = dest.with_suffix('.verification.json')
        sidecar.write_text(json.dumps(report, indent=2) + '\n')
        reports.append({k: v for k, v in report.items() if k not in ('frame_map', 'source_pixel_md5')})
        print(json.dumps(reports[-1]), flush=True)
    (args.out / f'{args.source_id}_cut_verification.json').write_text(json.dumps(reports, indent=2) + '\n')


if __name__ == '__main__':
    main()
