#!/usr/bin/env python3
"""Native same-pose lighting regression: cardinal yaw, pitch, and a reload pose.

Run under xvfb-run on Linux. The actual game renders the level and held mesh;
this script only checks and arranges the resulting unmodified pixels.
"""
import argparse
import json
import math
from pathlib import Path
import subprocess

from PIL import Image, ImageChops, ImageDraw, ImageStat

VIEWS = [('front', -90, 0), ('right', 0, 0), ('back', 90, 0),
         ('left', 180, 0), ('up', -90, 35), ('down', -90, -35)]


def difference(a, b, box):
    diff = ImageChops.difference(a.crop(box), b.crop(box))
    return sum(ImageStat.Stat(diff).mean[:3]) / 3


def verify(folder):
    records = []
    for pose in ['ready', 'reload']:
        images = {name: Image.open(folder / f'{pose}_{name}.png').convert('RGB')
                  for name, _, _ in VIEWS}
        if any(image.size != (960, 540) for image in images.values()):
            raise ValueError('expected native 960x540 viewmodel capture')
        background = images['front'].getpixel((0, 0))
        masks = {name: [p != background for p in image.getdata()]
                 for name, image in images.items()}
        for name, yaw, pitch in VIEWS:
            data = json.loads((folder / f'{pose}_{name}.png.lighting.json').read_text())
            if abs(data['yaw_degrees'] - yaw) > 0.001 or abs(data['pitch_degrees'] - pitch) > 0.001:
                raise ValueError('capture did not use the requested camera direction')
            if data['simulation_time'] != 0:
                raise ValueError('lighting capture changed animation time')
            # Independent closed-form world-to-camera basis, not copied sidecars.
            y, p = math.radians(yaw), math.radians(pitch)
            forward = (math.cos(y)*math.cos(p), math.sin(p), math.sin(y)*math.cos(p))
            right = (-math.sin(y), 0, math.cos(y))
            up = (-math.cos(y)*math.sin(p), math.cos(p), -math.sin(y)*math.sin(p))
            world = [-.3 / math.sqrt(.98), .8 / math.sqrt(.98), .5 / math.sqrt(.98)]
            expected = [sum(a*b for a,b in zip(axis, world)) for axis in [right, up, [-x for x in forward]]]
            if max(abs(a-b) for a,b in zip(expected, data['view_light'])) > 1e-5:
                raise ValueError('view light does not match the fixed world light')
            if max(abs(a-b) for a,b in zip(world, data['world_light'])) > 1e-5:
                raise ValueError('level light rotated with the camera')
            same = sum(a == b for a,b in zip(masks['front'], masks[name])) / (960*540)
            if same < .999:
                raise ValueError(f'{pose}/{name}: pose silhouette changed during a lighting-only capture')
        # Separate skinned-arm and rigid-weapon screen regions in the ready pose.
        # Reload also must change as a whole, without altering its frozen pose.
        boxes = {'model': (250, 220, 960, 540)}
        if pose == 'ready':
            boxes.update(arm=(365, 450, 465, 525), weapon=(660, 370, 820, 460))
        for region, box in boxes.items():
            yaw_delta = difference(images['front'], images['back'], box)
            pitch_delta = difference(images['up'], images['down'], box)
            if min(yaw_delta, pitch_delta) <= 1.0:
                raise ValueError(f'{pose}/{region}: held geometry still looks camera-lit ({yaw_delta}, {pitch_delta})')
            records.append({'pose': pose, 'region': region, 'opposite_yaw_rgb_mean_delta': yaw_delta,
                            'opposite_pitch_rgb_mean_delta': pitch_delta})
    report = {'schema': 'rust-duty-native-lighting-verification/v1', 'passed': True,
              'frames': 12, 'frozen_pose_silhouette': True, 'records': records,
              'scope': 'Directional diffuse plus ambient; no shadows, point lights, or artistic approval.'}
    (folder / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def contact_sheet(folder, pose, suffix=''):
    canvas = Image.new('RGB', (1920, 792), '#17212b')
    draw = ImageDraw.Draw(canvas)
    for i, (name, yaw, pitch) in enumerate(VIEWS):
        image = Image.open(folder / f'{pose}_{name}.png{suffix}').convert('RGB')
        image.thumbnail((640, 360))
        x, y = (i % 3) * 640, (i // 3) * 396
        canvas.paste(image, (x, y + 32))
        draw.text((x+12, y+10), f'{pose} | yaw {yaw:+} deg | pitch {pitch:+} deg', fill='white')
    canvas.save(folder / f'{pose}{"_world" if suffix else ""}_directions.png')


def capture(binary, folder):
    binary = binary.resolve()
    folder = folder.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    root = binary.parent
    for pose, asset, clip, time in [
            ('ready', 'locomotion', 'normal_ready', 0),
            ('reload', 'reload', 'reload_current_wip', 1.4)]:
        for name, yaw, pitch in VIEWS:
            output = folder / f'{pose}_{name}.png'
            command = [str(binary), '--no-update', '--reference-viewport', '--capture-lighting',
                       f'--capture-yaw={yaw}', f'--capture-pitch={pitch}',
                       f'--viewmodel-asset={root}/assets/{asset}/asset.vra',
                       f'--viewmodel-clip={clip}', f'--viewmodel-time={time}', f'--output={output}']
            result = subprocess.run(command, cwd=root, text=True, capture_output=True, timeout=60)
            (folder / f'{pose}_{name}.log').write_text(result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError(f'native capture failed: {pose}/{name}: {result.stderr}')
        contact_sheet(folder, pose)
    contact_sheet(folder, 'ready', '.world.png')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--binary', type=Path)
    args = parser.parse_args()
    if args.binary:
        capture(args.binary, args.folder)
    print(json.dumps(verify(args.folder), indent=2))
