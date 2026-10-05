#!/usr/bin/env python3
"""Compose only after verified native foreground viewport capture is complete.

The full restored reference is input-only. Both panels retain their native pixels.
No source excerpt MP4 is written. Only the paired review MP4 is created.
"""
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
SOURCE = OUT.parent.parent / 'author/halcyon_prone_crawl_r1.blend'
REFERENCE = Path('/workspace/shared/locomotion_reference_media/Modern_Warfare_2022_Movement_Reference.mp4')
SOURCE_SHA256 = '7807f7e16f6fabb2833d9e61ae5a942ee9a57f455a6c3e40e15ed4e03fa153b4'
REFERENCE_SHA256 = '491a1729aa0f32373025d35fff86da76c6c1c8f057c0c553d0fbb5fb6226ff46'
ACTION = 'prone_crawl_enter_r1'
MAP = OUT / 'reference_frame_map.json'
PUB = OUT / 'publication'
VIDEO = PUB / 'prone_crawl_enter.mp4'
FPS, COUNT = 60, 69
QA_INDICES = {0, 4, 12, 24, 36, 48, 56, 63, 68}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def run(args):
    return subprocess.run(args, check=True, text=True, capture_output=True)

def probe(path):
    return json.loads(run(['ffprobe', '-v', 'error', '-show_streams', '-show_format',
                           '-of', 'json', str(path)]).stdout)

def main():
    assert sha(SOURCE) == SOURCE_SHA256
    assert sha(REFERENCE) == REFERENCE_SHA256
    mapping = json.loads(MAP.read_text())
    assert mapping['source_sha256'] == SOURCE_SHA256
    assert mapping['reference_sha256'] == REFERENCE_SHA256
    assert mapping['fps'] == FPS and mapping['native_samples'] == COUNT
    assert mapping['native_reference_half_open'] == [2241, 2310]
    assert mapping['action_frame_range_inclusive'] == [1, 69]
    rows = mapping['frames']
    assert len(rows) == COUNT
    for i, row in enumerate(rows):
        assert row['output_index'] == i and row['source_frame'] == 2241 + i
        assert row['action'] == ACTION and row['action_frame'] == 1 + i
        assert row['source_pts_ticks'] == (2241 + i) * 256
        assert row['output_pts_ticks'] == i * 256
    proof_path = OUT / 'viewport_process_proof.json'
    proof = json.loads(proof_path.read_text())
    assert proof['completed'] is True and proof['background'] is False
    assert proof['source_sha256'] == SOURCE_SHA256
    assert proof['engine'] == 'BLENDER_EEVEE_NEXT'
    assert proof['operator'] == 'bpy.ops.render.opengl'
    assert proof['operator_arguments'] == {'animation': True, 'view_context': True,
                                          'render_keyed_only': False, 'sequencer': False}
    assert proof['viewport_shading'] == 'RENDERED' and proof['camera_view'] == 'CAMERA'
    assert proof['camera']['name'] == 'RD First Person Review'
    assert proof['source_saved'] is False
    assert proof['regular_offline_render_operator_used'] is False
    for key in ('source_bytes_unchanged', 'camera_unchanged', 'world_root_unchanged',
                'action_curves_unchanged', 'source_structure_unchanged', 'companions_unchanged'):
        assert proof[key] is True
    assert len(proof['actions']) == 1
    capture = proof['actions'][0]
    assert capture['action'] == ACTION and capture['native_frames'] == COUNT
    assert capture['operator_result'] == ['FINISHED']
    assert len(capture['output_files']) == COUNT
    native_paths = []
    for i, record in enumerate(capture['output_files']):
        path = OUT / 'frames' / ACTION / f'f{i+1:04d}.png'
        assert path.resolve() == Path(record['path']).resolve()
        assert sha(path) == record['sha256']
        native_paths.append(path)
    assert not VIDEO.exists(), 'Refuse to replace an existing review identity'
    PUB.mkdir(exist_ok=True)
    reference_dir, paired_dir, qa_dir = OUT / 'reference_native', OUT / 'paired_native', OUT / 'qa'
    for directory in (reference_dir, paired_dir, qa_dir):
        directory.mkdir(exist_ok=True)
    assert not list(reference_dir.glob('*.png')) and not list(paired_dir.glob('*.png'))
    original_probe = probe(REFERENCE)
    original_stream = next(stream for stream in original_probe['streams'] if stream['codec_type'] == 'video')
    assert (original_stream['width'], original_stream['height']) == (1280, 720)
    assert original_stream['avg_frame_rate'] == '60/1'
    assert original_stream['time_base'] == '1/15360'
    pts_probe = json.loads(run(['ffprobe', '-v', 'error', '-read_intervals', '36%40',
        '-select_streams', 'v:0', '-show_frames', '-show_entries', 'frame=pts',
        '-of', 'json', str(REFERENCE)]).stdout)
    pts = {frame['pts'] for frame in pts_probe['frames']}
    assert all(row['source_pts_ticks'] in pts for row in rows)
    run(['ffmpeg', '-v', 'error', '-i', str(REFERENCE), '-vf',
         'trim=start_frame=2241:end_frame=2310', '-fps_mode', 'passthrough',
         '-start_number', '0', str(reference_dir / 'f%04d.png')])
    assert len(list(reference_dir.glob('*.png'))) == COUNT
    regular = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    mono = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'
    title_font = ImageFont.truetype(regular, 28)
    label_font = ImageFont.truetype(regular, 23)
    small_font = ImageFont.truetype(mono, 17)
    tiny_font = ImageFont.truetype(mono, 14)
    panel_checks = []
    for i, row in enumerate(rows):
        ref = Image.open(reference_dir / f'f{i:04d}.png').convert('RGB')
        model = Image.open(native_paths[i]).convert('RGB')
        assert ref.size == model.size == (1280, 720)
        canvas = Image.new('RGB', (1280, 1760), '#151923')
        canvas.paste(ref, (0, 96))
        canvas.paste(model, (0, 928))
        draw = ImageDraw.Draw(canvas)
        draw.text((22, 12), 'Prone entry r1 | COD reference / Eevee retarget | WIP', font=title_font, fill='white')
        draw.text((22, 51), f'COD R3  source n{row["source_frame"]}  t={row["source_time_seconds"]:.6f}s  PTS={row["source_pts_ticks"]}/15360', font=small_font, fill='#dce4ef')
        draw.text((22, 827), 'Eevee Viewport Render Animation | fixed review camera | native 1x', font=label_font, fill='white')
        draw.text((22, 866), f'{ACTION}  frame {row["action_frame"]:02d}/69  action t={row["action_time_seconds"]:.6f}s', font=small_font, fill='#dce4ef')
        draw.text((22, 897), 'Top: recorded world/camera motion   Bottom: held-rig motion only', font=small_font, fill='#dce4ef')
        draw.text((22, 1656), 'BLEND SHA256 ' + SOURCE_SHA256, font=tiny_font, fill='#ccd6e3')
        draw.text((22, 1678), 'REF   SHA256 ' + REFERENCE_SHA256, font=tiny_font, fill='#ccd6e3')
        draw.text((22, 1703), 'Different geometry; optic-region 2D fit; depth/roll inferred from one view', font=small_font, fill='#dce4ef')
        draw.text((22, 1732), '69 native samples / 60 fps | no retiming | independent artistic review pending', font=small_font, fill='#dce4ef')
        assert canvas.crop((0, 96, 1280, 816)).tobytes() == ref.tobytes()
        assert canvas.crop((0, 928, 1280, 1648)).tobytes() == model.tobytes()
        output = paired_dir / f'f{i:04d}.png'
        canvas.save(output)
        panel_checks.append({'output_index': i, 'reference_pixel_preservation': True,
                             'model_pixel_preservation': True, 'paired_png_sha256': sha(output)})
        if i in QA_INDICES:
            canvas.save(qa_dir / f'paired_{i:04d}.png')
    run(['ffmpeg', '-v', 'error', '-framerate', '60', '-start_number', '0',
         '-i', str(paired_dir / 'f%04d.png'), '-frames:v', str(COUNT), '-an',
         '-c:v', 'libx264', '-threads', '4', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
         '-video_track_timescale', '15360', '-movflags', '+faststart', str(VIDEO)])
    encoded = probe(VIDEO)
    stream = next(stream for stream in encoded['streams'] if stream['codec_type'] == 'video')
    assert (stream['width'], stream['height']) == (1280, 1760)
    assert stream['avg_frame_rate'] == stream['r_frame_rate'] == '60/1'
    assert int(stream['nb_frames']) == COUNT and stream['time_base'] == '1/15360'
    assert abs(float(stream['duration']) - COUNT/FPS) < 1e-6
    assert VIDEO.stat().st_size < 25_000_000
    run(['ffmpeg', '-v', 'error', '-i', str(VIDEO), '-f', 'null', '-'])
    output_pts = json.loads(run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_frames', '-show_entries', 'frame=pts', '-of', 'json', str(VIDEO)]).stdout)
    assert [frame['pts'] for frame in output_pts['frames']] == [i*256 for i in range(COUNT)]
    assert sha(SOURCE) == SOURCE_SHA256 and sha(REFERENCE) == REFERENCE_SHA256
    shutil.copyfile(MAP, PUB / 'prone_crawl_enter_author_map.json')
    shutil.copyfile(proof_path, PUB / 'prone_crawl_enter_viewport_process_proof.json')
    with (PUB / 'prone_crawl_enter_frame_map.csv').open('w') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (PUB / 'prone_crawl_enter_mapping_preservation.json').write_text(json.dumps(panel_checks, indent=2)+'\n')
    manifest = {'schema': 'rust-duty-paired-prone-entry-review/v1', 'revision': 'r1',
        'video': VIDEO.name, 'sha256': sha(VIDEO), 'bytes': VIDEO.stat().st_size,
        'frames': COUNT, 'fps': FPS, 'duration_seconds': COUNT/FPS, 'resolution': [1280, 1760],
        'source_sha256': SOURCE_SHA256, 'reference_sha256': REFERENCE_SHA256,
        'source_commit': '99a804349c3a5ca7d7a9fa64f0c4f213d01e9b35',
        'reference_frames_half_open': [2241, 2310], 'action': ACTION,
        'action_frames_inclusive': [1, 69], 'full_decode_passed': True,
        'native_pts_verified': True, 'panel_pixel_preservation_before_encoding': True,
        'source_bytes_unchanged': True, 'reference_bytes_unchanged': True,
        'capture': 'Genuine foreground Eevee Viewport Render Animation',
        'workflow_reconstruction': proof['reconstruction'],
        'manual_artifact_check': 'pending', 'artistic_review': 'pending',
        'scope': 'WIP optic-region 2D retarget with inferred depth/roll; fixed model camera',
        'source_probe': original_probe, 'output_probe': encoded}
    (PUB / 'prone_crawl_enter_manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    files = sorted(path for path in PUB.iterdir() if path.is_file() and path.name != 'SHA256SUMS')
    (PUB / 'SHA256SUMS').write_text(''.join(f'{sha(path)}  {path.name}\n' for path in files))
    print(json.dumps({key:manifest[key] for key in ('video','sha256','bytes','frames','fps','manual_artifact_check')},indent=2))

if __name__ == '__main__':
    main()
