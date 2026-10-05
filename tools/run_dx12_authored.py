#!/usr/bin/env python3
"""Run authored Windows DX12/WARP acceptance with strict same-run legacy parity.

No asset generation or renderer-specific telemetry tolerances. The caller must
supply native-validation's immutable artifacts from the same run and attempt.
An automated pass leaves the measured-pixel landmark/human review gate OPEN.
"""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from PIL import Image, ImageDraw

from package_game import verify_generated
from verify_capture_telemetry import _compare, compare, read_record, validate
from verify_render_capture import verify as verify_png
import verify_lighting_capture as lighting


EXTENT = (960, 540)
BACKGROUND = (36, 48, 61, 255)
WORLD_BACKGROUND = (168, 194, 199, 255)
WARP = 'Microsoft Basic Render Driver'
FXC_LOG = 'renderer dx12_shader_compiler=Fxc'
# Primary capture sidecar fields that name the renderer; every other field is
# presentation state (extent, hfov, ADS weight, reload phase) and must match.
RENDERER_IDENTITY = frozenset({'backend', 'adapter', 'requested'})
LANDMARKS = {'ads': ('rear-aperture center', (480, 270)),
             'hip': ('front-sight guard', (526, 280))}


@dataclass(frozen=True)
class Case:
    name: str
    sequence: str
    hz: int | None
    baseline: str
    validator: str | None


# Match native-validation.yml exactly. None preserves the game's 60000/1001
# default; replacing it with 60 would compare different committed sample ticks.
CASES = (
    Case('jump-gameplay', 'gameplay-jump', 60, 'jump-gameplay', 'verify_jump_capture.py'),
    Case('reload-gameplay', 'gameplay-reload', None, 'reload-gameplay', 'verify_gameplay_capture.py'),
    Case('walk-gameplay', 'gameplay-walk', None, 'walk-gameplay', 'verify_gameplay_walk_capture.py'),
    Case('ads-gameplay', 'gameplay-ads', None, 'ads-gameplay', 'verify_gameplay_ads_capture.py'),
    Case('ads-offset', 'gameplay-ads', None, 'ads-placement/ads-offset', 'verify_gameplay_ads_capture.py'),
    Case('layered-30', 'gameplay-layered', 30, 'layered/layered-30', None),
    Case('layered-60', 'gameplay-layered', 60, 'layered/layered-60', None),
    Case('reload-return', 'gameplay-return', 60, 'reload-return', 'verify_reload_return_capture.py'),
)


def write_json(path, value):
    # A reader (or cancellation) must see either the previous complete report
    # or the new one, never a truncated summary during an in-place write.
    path = Path(path)
    data = json.dumps(value, indent=2, allow_nan=False) + '\n'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=f'.{path.name}.', suffix='.tmp', delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def sha256(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def game_command(executable, root, output, case, offset):
    command = [str(executable), '--renderer=dx12', '--force-fallback-adapter',
               '--no-update', '--reference-viewport',
               f'--animation-manifest={root / "assets/animations.cfg"}',
               f'--capture-sequence={case.sequence}', f'--output={output}']
    if case.hz is not None:
        command.append(f'--capture-hz={case.hz}')
    if case.name == 'ads-offset':
        command.append(f'--settings={offset}')
    return command


def lighting_commands(executable, root, folder):
    # Same poses, clips, native sample times and camera directions as the
    # existing lighting producer; it does not yet forward fallback selection.
    for pose, asset, clip, seconds in (
            ('ready', 'locomotion', 'normal_ready', 0),
            ('reload', 'reload', 'reload_current_wip', 1.4)):
        for name, yaw, pitch in lighting.VIEWS:
            stem = f'{pose}_{name}'
            yield stem, [str(executable), '--renderer=dx12', '--force-fallback-adapter',
                         '--no-update', '--reference-viewport', '--capture-lighting',
                         f'--animation-manifest={root / "assets/animations.cfg"}',
                         f'--capture-yaw={yaw}', f'--capture-pitch={pitch}',
                         f'--viewmodel-asset={root}/assets/{asset}/asset.vra',
                         f'--viewmodel-clip={clip}', f'--viewmodel-time={seconds}',
                         f'--output={folder / (stem + ".png")}']


def renderer_logs(folder):
    lines = []
    for name in ('stdout.log', 'stderr.log'):
        lines.extend((folder / name).read_text(encoding='utf-8', errors='replace').splitlines())
    identities = [line for line in lines if line.startswith('renderer requested=')]
    expected = f'renderer requested=dx12 backend=Dx12 adapter={WARP}'
    if not identities or any(line.casefold() != expected.casefold() for line in identities):
        raise ValueError(f'expected actual DX12 WARP identity, got {identities!r}')
    compiler = [line for line in lines if line.startswith('renderer dx12_shader_compiler=')]
    if not compiler or any(line != FXC_LOG for line in compiler):
        raise ValueError(f'expected exact {FXC_LOG!r}, got {compiler!r}')
    return {'renderer': identities, 'shader_compiler': compiler}


def stop_process_tree(process):
    """Bound cleanup too; retain diagnostics if the OS cannot reap a child."""
    result = {'method': 'taskkill-tree' if os.name == 'nt' else 'kill-process-group'}
    try:
        if os.name == 'nt':
            # Kill descendants while their parent still exists. subprocess.run's
            # timeout kills only its direct child and loses this opportunity.
            cleanup = subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                     capture_output=True, text=True, timeout=10, check=False)
            result.update(exit_code=cleanup.returncode,
                          stdout=cleanup.stdout, stderr=cleanup.stderr)
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    except (OSError, subprocess.TimeoutExpired) as error:
        result['error'] = f'{type(error).__name__}: {error}'
    finally:
        try:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired) as error:
            result['reap_error'] = f'{type(error).__name__}: {error}'
    return result


def execute(command, root, logs, timeout, *, renderer=False, progress_interval=30):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('timeout must be finite and positive')
    if not math.isfinite(progress_interval) or progress_interval <= 0:
        raise ValueError('progress interval must be finite and positive')
    logs.mkdir(parents=True, exist_ok=False)
    write_json(logs / 'invocation.json', {'command': command, 'cwd': str(root),
                                        'timeout_seconds': timeout})
    started = time.monotonic()
    state = {'schema': 'rust-duty-capture-process/v1', 'status': 'starting',
             'started_at': datetime.now(timezone.utc).isoformat(),
             'pid': None, 'exit_code': None, 'timeout_seconds': timeout,
             'elapsed_seconds': 0.0, 'output_path': None, 'png_files': 0}
    output = next((argument.split('=', 1)[1] for argument in command
                   if argument.startswith(('--output=', '--output-dir='))), None)
    if output:
        output = Path(output)
        if not output.is_absolute():
            output = root / output
        state['output_path'] = str(output)

    def progress():
        state['elapsed_seconds'] = round(time.monotonic() - started, 6)
        state['updated_at'] = datetime.now(timezone.utc).isoformat()
        # File counts are progress only, never evidence of completeness/validity.
        if output is not None:
            state['png_files'] = (sum(1 for path in output.glob('*.png') if path.is_file())
                                  if output.is_dir() else int(output.is_file()))
        for stream in ('stdout', 'stderr'):
            path = logs / f'{stream}.log'
            state[f'{stream}_bytes'] = path.stat().st_size if path.exists() else 0
        write_json(logs / 'process.json', state)

    process = None
    progress()
    try:
        with (logs / 'stdout.log').open('wb') as stdout, (logs / 'stderr.log').open('wb') as stderr:
            options = ({'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt'
                       else {'start_new_session': True})
            process = subprocess.Popen(command, cwd=root, stdout=stdout, stderr=stderr, **options)
            state.update(status='running', pid=process.pid)
            progress()
            print(f'[process {logs.name}] started pid={process.pid} timeout={timeout}s logs={logs}', flush=True)
            while True:
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                try:
                    process.wait(timeout=min(progress_interval, remaining))
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() - started >= timeout:
                        raise subprocess.TimeoutExpired(command, timeout) from None
                    progress()
                    print(f'[process {logs.name}] still running elapsed={state["elapsed_seconds"]:.1f}s '
                          f'png_files={state["png_files"]} logs={logs}', flush=True)
        state['exit_code'] = process.returncode
        if process.returncode:
            raise ValueError(f'process exited {process.returncode}; see {logs}')
        result = renderer_logs(logs) if renderer else {'exit_code': process.returncode}
    except BaseException as error:
        # Interruptions must keep partial files and kill only this invocation's
        # isolated children. Never continue silently after a KeyboardInterrupt.
        if process is not None and (isinstance(error, subprocess.TimeoutExpired) or process.poll() is None):
            state['cleanup'] = stop_process_tree(process)
        state['exit_code'] = process.poll() if process is not None else None
        state['status'] = ('timed_out' if isinstance(error, subprocess.TimeoutExpired)
                           else 'failed' if isinstance(error, Exception) else 'interrupted')
        state['error'] = f'{type(error).__name__}: {error}'
        progress()
        raise
    state['status'] = 'passed'
    progress()
    return result


def capture_metadata(path, backend='Dx12'):
    record = read_record(Path(f'{path}.json'))
    if record.get('backend') != backend or not isinstance(record.get('adapter'), str) or not record['adapter'].strip():
        raise ValueError(f'{path}: missing or wrong actual renderer identity')
    if backend == 'Dx12' and (record.get('requested') != 'dx12' or record['adapter'].casefold() != WARP.casefold()):
        raise ValueError(f'{path}: expected requested dx12 on {WARP}')
    if any(type(record.get(field)) is not int for field in ('width', 'height')):
        raise ValueError(f'{path}: extent must use integer width/height')
    return record


def sequence_inventory(folder, backend):
    finite = validate(folder, expected_backend=backend)
    images = sorted(folder.glob('*.png'))
    if not images or [p.name for p in images] != [f'{i:04}.png' for i in range(len(images))]:
        raise ValueError(f'{folder}: missing or noncontiguous zero-based captures')
    expected = {image.name + suffix for image in images
                for suffix in ('', '.json', '.time.json', '.gameplay.json')}
    actual = {path.name for path in folder.iterdir()}
    # Existing native validators write this report after successful inspection.
    if actual - {'verification.json'} != expected:
        raise ValueError(f'{folder}: missing/orphan/unexpected image or sidecar')
    for image in images:
        metadata = capture_metadata(image, backend)
        if (metadata['width'], metadata['height']) != EXTENT:
            raise ValueError(f'{image}: reference capture must be {EXTENT}')
    return images, finite


def validate_sequence(folder):
    images, finite = sequence_inventory(folder, 'Dx12')
    coverage = []
    for image in images:
        result = verify_png(image, EXTENT, BACKGROUND, 0.01, 8, None)
        coverage.append(result['foreground_coverage'])
    return {'frames': len(images), 'finite_json': finite,
            'all_images_checked': True, 'minimum_foreground_coverage': min(coverage)}


def baseline_verdicts(baseline, images):
    """Require the existing validators' successful reports for a legacy baseline.

    Native validation writes verification.json into each scenario folder, except
    the ADS offset run, whose placement report sits beside its folder. Layered
    rates also carry a cross-rate report. A frame count, when reported, must
    match this folder so a report cannot vouch for a different capture.
    """
    reports = []
    if (baseline / 'verification.json').exists():
        reports.append((baseline / 'verification.json', True))
    elif baseline.name == 'ads-offset':
        reports.append((baseline.parent / 'ads-offset-verification.json', True))
    else:
        raise ValueError(f'{baseline}: missing legacy validator verdict')
    if baseline.name in ('layered-30', 'layered-60'):
        reports.append((baseline.parent / 'layered-rate-verification.json', False))
    checked = []
    for path, per_folder in reports:
        report = read_record(path)
        if report.get('passed') is not True or not isinstance(report.get('schema'), str):
            raise ValueError(f'{path}: legacy validator verdict is not a successful report')
        frames = report.get('frames')
        if per_folder and frames is not None and (type(frames) is not int or frames != len(images)):
            raise ValueError(f'{path}: verdict covers {frames!r} frames, folder has {len(images)}')
        checked.append(path.name)
    return checked


def compare_capture_metadata(baseline, candidate, images):
    """Compare primary capture sidecars, excluding only renderer identity."""
    for image in images:
        before = read_record(baseline / f'{image.name}.json')
        after = read_record(candidate / f'{image.name}.json')
        _compare({k: v for k, v in before.items() if k not in RENDERER_IDENTITY},
                 {k: v for k, v in after.items() if k not in RENDERER_IDENTITY},
                 f'{image.name}.json')
    return len(images)


def compare_sequence(baseline, candidate):
    # The legacy renderer identity is checked independently of the comparison;
    # gameplay/time files are compared with EVERY field and exact types, and
    # primary sidecars with every field except renderer identity.
    images, _ = sequence_inventory(baseline, 'OpenGl')
    verdicts = baseline_verdicts(baseline, images)
    result = compare(baseline, candidate)
    result['capture_metadata_files'] = compare_capture_metadata(baseline, candidate, images)
    result['baseline_verdicts'] = verdicts
    return result


def validate_lighting_record(path):
    """Require the complete emitted schema before zip-based legacy comparisons."""
    record = read_record(path)
    scalars = ('yaw_degrees', 'pitch_degrees', 'ambient', 'diffuse', 'simulation_time')
    vectors = ('world_light', 'view_light')
    if set(record) != {'schema', *scalars, *vectors} or record.get('schema') != 'rust-duty-lighting-capture/v1':
        raise ValueError(f'{path}: unsupported or incomplete lighting schema')
    # read_record already rejects nonfinite values. Exact numeric types exclude
    # booleans, strings and null while preserving its lossless Decimal parser.
    for field in scalars:
        if type(record[field]) not in (int, Decimal):
            raise ValueError(f'{path}: {field} must be a finite JSON number')
    for field in vectors:
        value = record[field]
        if not isinstance(value, list) or len(value) != 3:
            raise ValueError(f'{path}: {field} must contain exactly three components')
        if any(type(component) not in (int, Decimal) for component in value):
            raise ValueError(f'{path}: {field} components must be finite JSON numbers')
    return record


def validate_lighting(folder):
    finite = validate(folder, expected_backend='Dx12')
    expected = {f'{pose}_{name}.png{suffix}'
                for pose in ('ready', 'reload') for name, _, _ in lighting.VIEWS
                for suffix in ('', '.json', '.world.png', '.world.png.json', '.lighting.json')}
    actual = {path.name for path in folder.iterdir()}
    if actual != expected:
        raise ValueError('lighting capture set is missing or contains unexpected files')
    for pose in ('ready', 'reload'):
        for name, _, _ in lighting.VIEWS:
            image = folder / f'{pose}_{name}.png'
            validate_lighting_record(Path(f'{image}.lighting.json'))
            metadata = capture_metadata(image)
            if (metadata['width'], metadata['height']) != EXTENT:
                raise ValueError('lighting viewmodel must be 960x540')
            verify_png(image, EXTENT, BACKGROUND, 0.01, 8, None)
            world = folder / f'{pose}_{name}.png.world.png'
            metadata = capture_metadata(world)
            size = (metadata['width'], metadata['height'])
            if min(size) <= 0:
                raise ValueError('world capture extent must be positive')
            verify_png(world, size, WORLD_BACKGROUND, 0.01, 8, None)
    # Unchanged existing silhouette/lighting thresholds, including fixed-region
    # arm and weapon deltas. A failure needs investigation, never relaxation.
    report = lighting.verify(folder)
    for pose in ('ready', 'reload'):
        lighting.contact_sheet(folder, pose)
    lighting.contact_sheet(folder, 'ready', '.world.png')
    return {'finite_json': finite, 'existing_validator': report,
            'world_images_checked': 12, 'viewmodel_images_checked': 12}


def validate_orientation(folder):
    finite = validate(folder, expected_backend='Dx12')
    report = read_record(folder / 'renderer-contract-report.json')
    adapter = report.get('adapter')
    if (report.get('status') != 'passed' or report.get('native_execution') is not True
            or report.get('platform') != 'windows' or report.get('requested') != 'dx12'
            or report.get('backend') != 'Dx12' or not isinstance(adapter, str)
            or adapter.casefold() != WARP.casefold()
            or report.get('force_fallback_adapter') is not True):
        raise ValueError('renderer contract is not a passing native Windows DX12 WARP run')
    results = []
    for name, extent in (('quadrant.png', (96, 64)), ('readback-width-65.png', (65, 49))):
        metadata = capture_metadata(folder / name)
        if (metadata['width'], metadata['height']) != extent:
            raise ValueError('orientation sidecar has wrong extent')
        results.append(verify_png(folder / name, extent, (0, 0, 0, 255), 0.01, 8, 'quadrants-v1'))
    return {'finite_json': finite, 'orientation': results,
            'scope': 'Native asymmetric fixture/readback; authored image orientation still needs visual review'}


def review_guides(candidate, baseline, output, source_root):
    output.mkdir(parents=True, exist_ok=False)
    rows = [(path, read_record(path)) for path in sorted(candidate.glob('*.gameplay.json'))]

    def exactly(value, target):
        # Booleans compare equal to 0/1; require an actual finite JSON number.
        return type(value) in (int, Decimal) and value == target

    hip = next((path for path, row in rows if row.get('route') == 'ready'), None)
    ads = next((path for path, row in rows if row.get('route') == 'ads.hold'
                and exactly(row.get('run_weight'), 0) and exactly(row.get('speed'), 0)
                and exactly(row.get('simulation_ads'), 1)), None)
    if hip is None or ads is None:
        raise ValueError('review needs actual ready and stationary fully held ADS frames')
    records = []
    for pose, telemetry in (('hip', hip), ('ads', ads)):
        filename = telemetry.name.removesuffix('.gameplay.json')
        feature, (x, y) = LANDMARKS[pose]
        for label, source in (('dx12', candidate), ('legacy', baseline)):
            raw = source / filename
            expected_backend = 'Dx12' if label == 'dx12' else 'OpenGl'
            metadata = capture_metadata(raw, expected_backend)
            if (metadata['width'], metadata['height']) != EXTENT:
                raise ValueError(f'{raw}: review source metadata must identify {EXTENT}')
            raw_copy = output / f'{label}-{pose}-raw.png'
            sidecar = Path(f'{raw}.json')
            sidecar_copy = Path(f'{raw_copy}.json')
            # Copy the exact primary sidecar from this source frame. Do not
            # synthesize metadata for renamed raw images or for guide overlays.
            shutil.copyfile(raw, raw_copy)
            shutil.copyfile(sidecar, sidecar_copy)
            with Image.open(raw) as original:
                if original.size != EXTENT:
                    raise ValueError('landmark guides require unscaled 960x540 pixels')
                image = original.convert('RGB')
            draw = ImageDraw.Draw(image)
            draw.rectangle((x - 4, y - 4, x + 4, y + 4), outline='#ffcf40', width=1)
            draw.line((x - 16, y, x - 7, y), fill='#ffcf40')
            draw.line((x + 7, y, x + 16, y), fill='#ffcf40')
            draw.line((x, y - 16, x, y - 7), fill='#ffcf40')
            draw.line((x, y + 7, x, y + 16), fill='#ffcf40')
            draw.rectangle((0, 0, 960, 42), fill='#17212b')
            draw.text((8, 6), f'GUIDE ONLY / UNMEASURED | {label} {pose} | {feature} ({x},{y}) +/-4 px', fill='white')
            draw.text((8, 23), f'Raw frame: {filename} | No pixel detection or projected-anchor assertion', fill='white')
            guide = output / f'{label}-{pose}-guide.png'
            image.save(guide)
            records.append({'backend': label, 'pose': pose, 'source_frame': filename,
                            'source_role': 'dx12-under-review' if label == 'dx12' else 'legacy-comparison-only',
                            'actual_backend': metadata['backend'], 'source_sidecar': sidecar.name,
                            'raw': raw_copy.name, 'raw_sha256': sha256(raw_copy),
                            'raw_sidecar': sidecar_copy.name, 'raw_sidecar_sha256': sha256(sidecar_copy),
                            'guide': guide.name, 'feature': feature,
                            'calibrated_center': [x, y], 'tolerance_px': 4,
                            'measured_center': None, 'projected_center': None})
    projection_path = source_root / 'assets/authoring/ads/sight_alignment.json'
    source_projection = read_record(projection_path)
    shutil.copyfile(projection_path, output / 'historical-source-sight-alignment.json')
    historical = []
    for feature, witness in source_projection['measured_landmark_evidence'].items():
        pixels = witness['pixel_1280x720']
        historical.append({'source_feature': feature,
                           'source_projection_1280x720': [float(value) for value in pixels],
                           'scaled_source_projection_960x540': [float(value) * 0.75 for value in pixels]})
    report = {'status': 'open', 'automated_landmark_gate': 'open',
              'reason': 'No supported measured-pixel detector or live sight projection witness in current DX12 sidecars.',
              'historical_projection_context': {
                  'evidence_type': 'Historical source geometry projection, not current DX12 measured pixels',
                  'source': projection_path.relative_to(source_root).as_posix(),
                  'source_sha256': sha256(projection_path),
                  'artifact_file': 'historical-source-sight-alignment.json',
                  'source_geometry_sha256': source_projection['source_geometry_sha256'],
                  'landmark_method': source_projection['landmark_method'],
                  'current_runtime_geometry_match_verified': False,
                  'records': historical},
              'calibration_source': 'docs/VISUAL_REFERENCE_MATCH.md',
              'records': records,
              'required_review': 'Measure both features in raw pixels, record reviewer and coordinates/deltas; inspect orientation, grips, transitions and lighting.'}
    write_json(output / 'landmark-review.json', report)
    return report


def asset_evidence(root):
    generated = verify_generated(root)
    for name in ('walk', 'ads', 'directional', 'jump'):
        if name not in generated:
            raise ValueError(f'authored acceptance requires source-validated {name} companions')
    files = {path.relative_to(root).as_posix(): sha256(path)
             for path in sorted((root / 'assets').rglob('*'))
             if path.is_file() and path.suffix in ('.vra', '.vrs', '.vrm', '.json', '.cfg')}
    files['settings.cfg'] = sha256(root / 'settings.cfg')
    return {'generated_verification': generated, 'runtime_and_manifest_sha256': files}


def run(executable, fixture, root, evidence, legacy, timeout, *, run_timeout=90 * 60):
    executable, fixture, root, evidence, legacy = [Path(path).resolve()
                                                 for path in (executable, fixture, root, evidence, legacy)]
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('timeout must be finite and positive')
    if not math.isfinite(run_timeout) or run_timeout <= 0:
        raise ValueError('run timeout must be finite and positive')
    for binary in (executable, fixture):
        if not binary.is_file():
            raise ValueError(f'executable missing: {binary}')
    if not root.is_dir() or not legacy.is_dir():
        raise ValueError('working directory or matched legacy baseline missing')
    # Never overwrite or merge output from an earlier run.
    evidence.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = {'schema': 'rust-duty-dx12-authored-acceptance/v1', 'passed': False,
              'acceptance_complete': False, 'automated_landmark_gate': 'open',
              'status': 'running', 'current_check': None, 'elapsed_seconds': 0.0,
              'run_timeout_seconds': run_timeout, 'budget_exhausted': False,
              'started_at': datetime.now(timezone.utc).isoformat(),
              'source_commit': os.environ.get('GITHUB_SHA'), 'run_id': os.environ.get('GITHUB_RUN_ID'),
              'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
              'platform': sys.platform, 'executable_sha256': sha256(executable),
              'renderer_contract_sha256': sha256(fixture), 'checks': []}
    summary = evidence / 'summary.json'
    write_json(summary, report)

    def execute_bounded(command, cwd, logs, per_process_timeout, **kwargs):
        remaining = run_timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise RuntimeError('whole-run time budget exhausted before subprocess launch')
        return execute(command, cwd, logs, min(per_process_timeout, remaining), **kwargs)

    def check(name, action):
        if report['budget_exhausted']:
            return False
        check_started = time.monotonic()
        report.update(current_check=name, elapsed_seconds=round(check_started - started, 6))
        write_json(summary, report)
        print(f'[{name}] running', flush=True)
        try:
            if time.monotonic() - started >= run_timeout:
                raise RuntimeError('whole-run time budget exhausted; check was not attempted')
            result = action()
            row = {'name': name, 'passed': True, 'result': result}
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
            row = {'name': name, 'passed': False, 'error': str(error)}
        except BaseException as error:
            # Preserve which check was active when interrupted; do not report an
            # interrupted process or unexpected exception as completed evidence.
            report['checks'].append({'name': name, 'passed': False,
                                     'error': f'{type(error).__name__}: {error}',
                                     'elapsed_seconds': round(time.monotonic() - check_started, 6)})
            report.update(status='interrupted', elapsed_seconds=round(time.monotonic() - started, 6))
            write_json(summary, report)
            raise
        completed = time.monotonic()
        row['elapsed_seconds'] = round(completed - check_started, 6)
        if completed - started >= run_timeout:
            # Cooperative only: in-process image/parity validators cannot be
            # interrupted here. The workflow's outer 95-minute step timeout is
            # still required. No further check or subprocess may be started.
            report.update(budget_exhausted=True, status='failed')
            if row['passed']:
                row.update(passed=False, error='check completed after whole-run time budget was exhausted')
        report['checks'].append(row)
        report.update(current_check=None, elapsed_seconds=round(completed - started, 6))
        write_json(summary, report)
        print(f'[{name}] {"passed" if row["passed"] else row["error"]}', flush=True)
        return row['passed']

    if not check('validated-same-run-companions', lambda: asset_evidence(root)):
        report['status'] = 'failed'
        write_json(summary, report)
        return report
    offset = evidence / 'ads-offset.cfg'
    offset.write_text((root / 'settings.cfg').read_text(encoding='utf-8')
                      + '\nviewmodel_x = 0.20\nviewmodel_y = -0.20\nviewmodel_z = 0.20\n', encoding='utf-8')
    logs = evidence / 'logs'
    captures = evidence / 'captures'
    captures.mkdir()

    def orientation():
        folder = evidence / 'renderer-contract'
        execution = execute_bounded([str(fixture), '--renderer=dx12', '--force-fallback-adapter',
                             f'--output-dir={folder}'], root, logs / 'renderer-contract', timeout, renderer=True)
        if time.monotonic() - started >= run_timeout:
            raise RuntimeError('whole-run time budget exhausted before orientation validation')
        return {'logs': execution, **validate_orientation(folder)}

    check('orientation-renderer-contract', orientation)
    captured = set()
    for case in CASES:
        if report['budget_exhausted']:
            break
        folder = captures / case.name
        if check(f'{case.name}/capture', lambda case=case, folder=folder: execute_bounded(
                game_command(executable, root, folder, case, offset), root,
                logs / case.name, timeout, renderer=True)):
            captured.add(case.name)
            check(f'{case.name}/finite-images', lambda folder=folder: validate_sequence(folder))
            if case.validator:
                check(f'{case.name}/existing-validator', lambda case=case, folder=folder: execute_bounded(
                    [sys.executable, str(root / 'tools' / case.validator), str(folder)], root,
                    logs / f'{case.name}-validator', timeout))
            check(f'{case.name}/strict-gameplay-time-parity', lambda case=case, folder=folder:
                  compare_sequence(legacy / case.baseline, folder))

    if {'ads-gameplay', 'ads-offset'} <= captured:
        check('ads-placement-existing-validator', lambda: execute_bounded(
            [sys.executable, str(root / 'tools/verify_ads_placement_capture.py'),
             str(captures / 'ads-gameplay'), str(captures / 'ads-offset')], root,
            logs / 'ads-placement-validator', timeout))
    if {'layered-30', 'layered-60'} <= captured:
        check('layered-rates-existing-validator', lambda: execute_bounded(
            [sys.executable, str(root / 'tools/verify_layered_locomotion_capture.py'),
             str(captures / 'layered-30'), str(captures / 'layered-60')], root,
            logs / 'layered-rates-validator', timeout))

    light = captures / 'lighting'
    if not report['budget_exhausted']:
        light.mkdir()
        for stem, command in lighting_commands(executable, root, light):
            if report['budget_exhausted']:
                break
            check(f'lighting/{stem}', lambda stem=stem, command=command:
                  execute_bounded(command, root, logs / f'lighting-{stem}', timeout, renderer=True))
    check('lighting-existing-validator-and-images', lambda: validate_lighting(light))
    if 'ads-gameplay' in captured:
        check('landmark-guides-not-a-landmark-pass', lambda: review_guides(
            captures / 'ads-gameplay', legacy / 'ads-gameplay', evidence / 'review', root))
    report['passed'] = not report['budget_exhausted'] and all(item['passed'] for item in report['checks'])
    report.update(status='passed' if report['passed'] else 'failed',
                  elapsed_seconds=round(time.monotonic() - started, 6))
    report['scope'] = ('Automated authored DX12 WARP capture/validator/parity checks only; '
                       'measured landmark gate, human visual review and real-GPU playtest remain open.')
    write_json(summary, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--renderer-contract', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--legacy', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=900)
    args = parser.parse_args(argv)
    try:
        if sys.platform != 'win32':
            raise ValueError('authored DX12 WARP acceptance requires actual Windows execution')
        report = run(args.executable, args.renderer_contract, args.root, args.evidence, args.legacy, args.timeout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f'authored DX12 validation failed: {error}', file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
