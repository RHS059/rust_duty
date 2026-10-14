#!/usr/bin/env python3
"""Prepare/accept a PRIVATE r6 reconstruction without ever launching Blender.

prepare copies the byte-pinned source-free recipe, omits historical generated
results from the execution copy, and prints three background commands. The r5
BLEND stays in place. A trusted caller must run those commands separately and
supply process_results.json using process_results.template.json. Record actual
start/end time.time_ns(), return codes, combined stdout/stderr log hashes, and
artifact hashes after each successful process. Never fill that template from
historical reports: verify_revision writes results before its final assertion.

accept checks that evidence and writes a NEW local config/sidecar/receipt. It
confirms numerical reconstruction only, never rendering, art, export, or runtime
approval. Process receipts are caller attestations, not proof against a caller
who fabricates execution evidence. No private BLEND is copied or uploaded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import time
import uuid

import export_prone_pair

MANIFEST_SHA256 = '6e8cc99c5f5e607facaa2f0f49ea63d467cdb4da68feca86c770a7885fe667e0'
INPUT_SHA256 = '67cf025fc31d9804cb0259432a91e496d7d8f84d1d4ac6be2b1914a6a98510ad'
HISTORICAL_CANDIDATE = 'bd65f2eb280a6c08d413fd331a19b3b52b0990089cc4f06e802fc02813b85fd8'
HISTORICAL_SIDECAR = '19098b693b94a5a0b2421cff9dd25f5dda949506be87bc76eb84dfe23499fbfa'
CONTRACT_COMMIT = '659fd15ec77a7b4df5018bc7c86a54deace5333e'
INPUT_COMMIT = '9c5da4a2bb9920ce65390abfd7c287116d369e8a'
EXPECTED_ACTIONS = {
    'prone_crawl_enter_r6': '2a860a55decb8f0fa06226f55a2ace85e9629a21b54ff827cb275b244da8d41f',
    'prone_crawl_enter_camera_r6': '7006eeec2a3a9c83ca6eec27290692db81554ecb219afc656f8da413aa311c82',
}
GENERATED = {'frame_map.json', 'camera_motion_samples.json',
             'fresh_reopen_checks.json', 'capture_pair_checks.json'}
CANDIDATE = 'halcyon_prone_crawl_r6.blend'
STAGES = {
    'revise_entry': [CANDIDATE, 'baseline_preservation.json', 'revision_report.json',
                     'contact_precheck.json', 'frame_map.json'],
    'verify_revision': ['fresh_reopen_checks.json', 'camera_motion_samples.json'],
    'test_capture_pair': ['capture_pair_checks.json'],
}
SNAPSHOT = {'actions', 'drivers', 'nla', 'packed_images'}
EXTRA = {'actions_extended', 'actions_metadata', 'armatures', 'cameras',
         'materials', 'meshes', 'objects_and_bindings', 'pose_channel_defaults'}
PRESERVATION = {'snapshot.' + k for k in SNAPSHOT} | {'extra.' + k for k in EXTRA} | {'object_defaults'}
AUTHOR_CHECKS = (SNAPSHOT - {'actions'}) | EXTRA | {
    'all_112_prior_actions', 'camera_animation_unbound', 'object_defaults', 'scene_fields'}
CAPTURE_CHECKS = PRESERVATION | {'scene', 'camera_unbound', 'depth'}
PROBE_FRAMES = [1, 12, 20, 21, 28, 32, 35, 41, 45, 55, 69]
PROBE_OBJECTS = {'Actual arms mesh 0', 'Actual arms mesh 1', 'Actual arms mesh 2',
                 'hk416_magazine', 'hk416_weapon'}


class ReconstructionError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ReconstructionError(message)


def file_hash(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), f'Not a regular local file: {path}')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read_json(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), f'Missing regular JSON: {path}')
    require(path.stat().st_size <= 64 * 1024 * 1024, 'JSON exceeds 64 MiB')
    result = export_prone_pair.read_json(path.read_bytes())
    finite_tree(result)
    return result


def finite_tree(value):
    if isinstance(value, float):
        require(math.isfinite(value), 'Non-finite report value')
    elif isinstance(value, dict):
        for child in value.values():
            finite_tree(child)
    elif isinstance(value, list):
        for child in value:
            finite_tree(child)


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def verify_manifest(directory):
    directory = Path(directory)
    require(directory.is_dir() and not directory.is_symlink(), 'Invalid contract directory')
    require(file_hash(directory / 'SHA256SUMS') == MANIFEST_SHA256, 'Manifest anchor mismatch')
    entries = {}
    for line in (directory / 'SHA256SUMS').read_text().splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9_.-]+)', line)
        require(match is not None, 'Invalid manifest line')
        digest, name = match.groups()
        require(name not in entries and name not in {'.', '..', 'SHA256SUMS'}, 'Duplicate/unsafe manifest entry')
        entries[name] = digest
    require({p.name for p in directory.iterdir()} == set(entries) | {'SHA256SUMS'},
            'Contract has missing or unmanifested entries')
    for name, digest in entries.items():
        require(file_hash(directory / name) == digest, f'Immutable contract bytes changed: {name}')
    return entries


def historical_config(path):
    config = export_prone_pair.validate_config(read_json(path))
    require(config['source_contract_commit'] == CONTRACT_COMMIT, 'Wrong source contract commit')
    require(config['source_sha256'] == HISTORICAL_CANDIDATE, 'Wrong historical candidate pin')
    require(config['camera_sidecar_sha256'] == HISTORICAL_SIDECAR, 'Wrong pristine sidecar byte pin')
    require(config['action_fingerprints'] == EXPECTED_ACTIONS, 'Wrong expected Action pair')
    require(config['action_count'] == 114, 'Expected exactly 114 Actions')
    return config


def commands(work, source, blender):
    recipe = work / 'execution'
    result = []
    for stage in STAGES:
        blend = source if stage == 'revise_entry' else recipe / CANDIDATE
        argv = [str(blender), '--background', '--factory-startup', '--disable-autoexec',
                str(blend), '--python-exit-code', '1', '--python', str(recipe / (stage + '.py'))]
        result.append({'stage': stage, 'argv': argv, 'cwd': str(recipe),
                       'log': str(work / 'logs' / (stage + '.log'))})
    return result


def prepare(contract, source, work, config, blender):
    contract, source, work = (Path(p).absolute() for p in (contract, source, work))
    require(not work.exists() and not work.is_symlink(), 'Working directory already exists')
    require(not source.is_symlink() and source.suffix.lower() == '.blend', 'Use the original local r5 BLEND')
    require(file_hash(source) == INPUT_SHA256, 'Pinned r5 input hash mismatch')
    entries = verify_manifest(contract)
    historical_config(config)
    design = read_json(contract / 'correction_design.json')
    require(design['source_sha256'] == INPUT_SHA256 and design['source_commit'] == INPUT_COMMIT,
            'Input provenance mismatch')
    # Prevent accidentally placing private generated material inside this source tree.
    repo = Path(__file__).resolve().parent.parent
    require(work != repo and repo not in work.resolve().parents, 'Use a private directory outside the source tree')
    require(work != contract and contract not in work.resolve().parents, 'Working directory overlaps contract')
    require(work.parent.is_dir(), 'Working parent directory must already exist')
    work.mkdir(mode=0o700)
    for directory in ('immutable', 'execution', 'logs'):
        (work / directory).mkdir(mode=0o700)
    for name in list(entries) + ['SHA256SUMS']:
        data = (contract / name).read_bytes()
        (work / 'immutable' / name).write_bytes(data)
        if name not in GENERATED:
            (work / 'execution' / name).write_bytes(data)
    (work / 'historical_export_config.json').write_bytes(Path(config).read_bytes())
    verify_manifest(work / 'immutable')
    plan = {'schema': 'rust-duty-prone-reconstruction-plan/v1', 'run_id': str(uuid.uuid4()),
            'prepared_at_ns': time.time_ns(), 'work': str(work), 'source': str(source),
            'input_sha256': INPUT_SHA256, 'manifest_sha256': MANIFEST_SHA256,
            'blender_version': '4.3.2', 'blender': str(blender),
            'historical_config_sha256': file_hash(work / 'historical_export_config.json'),
            'commands': commands(work, source, blender)}
    write_json(work / 'plan.json', plan)
    template = {'schema': 'rust-duty-prone-process-results/v1', 'run_id': plan['run_id'],
                'plan_sha256': file_hash(work / 'plan.json'), 'stages': []}
    for command in plan['commands']:
        template['stages'].append({**command, 'blender_version': '4.3.2',
            'started_at_ns': None, 'finished_at_ns': None, 'returncode': None,
            'log_sha256': None, 'artifacts': {name: None for name in STAGES[command['stage']]}})
    write_json(work / 'process_results.template.json', template)
    lines = ['# Not executed. Use Blender 4.3.2. Record actual process results separately.',
             '# Each stage must succeed before the next. Never reuse reports from another run.']
    for command in plan['commands']:
        lines.append('cd ' + shlex.quote(command['cwd']) + ' && ' + shlex.join(command['argv'])
                     + ' > ' + shlex.quote(command['log']) + ' 2>&1')
    (work / 'commands.txt').write_text('\n'.join(lines) + '\n')
    return plan


def true_checks(value, expected, label):
    require(isinstance(value, dict) and set(value) == expected and
            all(v is True for v in value.values()), f'Missing or failed {label} checks')


def numeric_pair(value, upper, label):
    require(isinstance(value, dict) and set(value) == {'l', 'r'} and
            all(type(v) in (int, float) and math.isfinite(v) and 0 <= v < upper for v in value.values()),
            f'Invalid {label}')


def same_historical(value, historical, hash_key, candidate, label):
    require(value.get(hash_key) == candidate, f'{label} candidate mismatch')
    expected = dict(historical, **{hash_key: candidate})
    # Canonical JSON distinguishes numeric 0/1 from false/true, unlike Python
    # container equality, while allowing harmless whitespace/key-order changes.
    require(json.dumps(value, sort_keys=True, allow_nan=False) ==
            json.dumps(expected, sort_keys=True, allow_nan=False),
            f'{label} differs from historical Action/motion contract')


def validate_reports(recipe, immutable, candidate):
    fm = read_json(recipe / 'frame_map.json')
    sidecar = read_json(recipe / 'camera_motion_samples.json')
    require(fm.get('actions') == sidecar.get('action_fingerprints') == EXPECTED_ACTIONS,
            'Wrong expected Action pair')
    same_historical(fm, read_json(immutable / 'frame_map.json'), 'blend_sha256', candidate, 'Frame map')
    same_historical(sidecar, read_json(immutable / 'camera_motion_samples.json'),
                    'candidate_sha256', candidate, 'Camera sidecar')
    summary_doc = read_json(recipe / 'fresh_reopen_checks.json')
    summary, rows = summary_doc['summary'], summary_doc.get('rows', [])
    require(summary.get('candidate_sha256') == candidate and summary.get('actions') == EXPECTED_ACTIONS,
            'Fresh audit candidate/Action mismatch')
    # Equivalent bounded checks to the historical report_contract.validate;
    # no recipe Python is imported or executed by this helper.
    require(summary.get('all_bone_matrices_finite') is True and
            summary.get('all_drivers_valid') is True, 'Invalid evaluated data')
    require(type(summary.get('min_camera_height_above_ground_m')) in (int, float) and
            .299 < summary['min_camera_height_above_ground_m'] < .301, 'Real camera depth not verified')
    require(type(summary.get('max_optic_projection_error_px')) in (int, float) and
            0 <= summary['max_optic_projection_error_px'] < .002, 'Optic projection not verified')
    require(summary.get('no_render') is True and summary.get('visual_pass') is None,
            'Numerical audit must not claim a render or artistic pass')
    true_checks(summary.get('fresh_reopen_preservation'), PRESERVATION, 'fresh preservation')
    numeric_pair(summary.get('contact_480hz_max_m'), .0001, 'fresh contact residuals')
    require(type(summary.get('protected_f1_to_11_all_bone_max_difference')) in (int, float) and
            summary['protected_f1_to_11_all_bone_max_difference'] == 0, 'Protected poses changed')
    require(summary.get('action_count') == 114 and summary.get('sample_count') == 545 and len(rows) == 545,
            'Require all 114 Actions and 545 fresh samples')
    require(summary.get('wrist_guard_non_regression_pass') is True and
            summary.get('strict_wrist_guard_pass') is False and
            summary.get('strict_wrist_guard_threshold_deg') == .08,
            'The strict wrist failure must remain disclosed')
    for key in ('old_wrist_guard_max_deg', 'new_wrist_guard_max_deg'):
        numeric_pair(summary.get(key), 360.000001, key)
    require(max(summary['new_wrist_guard_max_deg'].values()) <=
            max(.08, max(summary['old_wrist_guard_max_deg'].values()) + .05),
            'Wrist guard changed beyond original allowance')
    increase = summary.get('max_wrist_guard_increase_deg')
    require(isinstance(increase, dict) and set(increase) == {'l', 'r'} and
            all(type(v) in (int, float) and math.isfinite(v) and v <= .05 for v in increase.values()),
            'Missing wrist non-regression measurements')
    require(max(summary['new_wrist_guard_max_deg'].values()) > .08, 'Strict wrist failure was concealed')
    require(summary.get('finite_evaluated_vertex_samples') == 1046760, 'Incomplete finite geometry probes')
    probes = summary.get('ground_intersection_probes', [])
    require([p['frame'] for p in probes] == PROBE_FRAMES and
            all(set(p['counts']) == PROBE_OBJECTS and
                all(type(n) is int and n == 0 for n in p['counts'].values()) for p in probes),
            'Incomplete or failed ground probes')
    for i, (row, motion) in enumerate(zip(rows, sidecar['rows'])):
        require(row['frame'] == 1 + i / 8 and row['camera_world'] == motion['camera_world'] and
                row['common_world_delta'] == motion['common_world_delta'] and
                row['camera_height_above_ground'] == motion['height_above_source_ground_m'] and
                row['camera_z'] == motion['camera_world'][2][3], 'Fresh row differs from motion sample')
        numeric_pair(row.get('wrist_guard_degrees'), 360.000001, 'sample wrist angles')
        require(type(row.get('optic_target_error_px')) in (int, float) and
                0 <= row['optic_target_error_px'] < .002, 'Invalid sample projection check')
        probe = next((p for p in probes if p['frame'] == row['frame']), None)
        if probe is not None:
            require(row.get('onscreen_vertices_below_ground') == probe['counts'], 'Ground probe row mismatch')
    require(summary['new_wrist_guard_max_deg'] == {
        s: max(r['wrist_guard_degrees'][s] for r in rows) for s in ('l', 'r')}, 'Wrist maxima mismatch')
    require(summary['min_camera_height_above_ground_m'] == min(r['camera_height_above_ground'] for r in rows)
            and summary['max_optic_projection_error_px'] == max(r['optic_target_error_px'] for r in rows),
            'Fresh extrema mismatch')
    baseline = read_json(recipe / 'baseline_preservation.json')
    require(set(baseline['snapshot']) == SNAPSHOT and set(baseline['extra']) == EXTRA and
            len(baseline['snapshot']['actions']) == 112 and
            not set(baseline['snapshot']['actions']) & set(EXPECTED_ACTIONS) and
            bool(baseline.get('object_defaults')) and bool(baseline.get('scene')),
            'Incomplete original source baseline')
    report = read_json(recipe / 'revision_report.json')
    require(report.get('source_sha256') == INPUT_SHA256 and report.get('candidate_sha256') == candidate and
            report.get('actions') == list(EXPECTED_ACTIONS) and report.get('rendered') is False and
            report.get('visual_pass') is None and report.get('protected_f1_to_11_all_bone_difference') == 0,
            'Invalid original source revision report')
    true_checks(report.get('checks'), AUTHOR_CHECKS, 'author/source preservation')
    require(len(report.get('rows', [])) == 545, 'Incomplete authoring samples')
    for i, (authored, row) in enumerate(zip(report['rows'], rows)):
        require(authored['frame'] == 1 + i / 8 and len(authored['camera_world']) == 4 and
                all(len(a) == len(b) == 4 and max(abs(x-y) for x, y in zip(a, b)) < 1e-6
                    for a, b in zip(authored['camera_world'], row['camera_world'])),
                'Authored camera disagrees with fresh evaluation')
        require(len(authored['optic_target_pixels']) == len(row['projected_guides']['optic']) == 2 and
                max(abs(a-b) for a, b in zip(authored['optic_target_pixels'], row['projected_guides']['optic'])) < .002,
                'Author/fresh projection mismatch')
    precheck = read_json(recipe / 'contact_precheck.json')
    require(len(precheck.get('rows', [])) == 545, 'Incomplete source contact precheck')
    for i, row in enumerate(precheck['rows']):
        require(row['frame'] == 1 + i / 8, 'Wrong contact sample clock')
        numeric_pair(row.get('error_m'), .0001, 'source contact precheck')
    maxima = {s: max(r['error_m'][s] for r in precheck['rows']) for s in ('l', 'r')}
    require(precheck.get('maxima_m') == report.get('contact_maxima_480hz_m') == maxima,
            'Source contact maxima mismatch')
    capture = read_json(recipe / 'capture_pair_checks.json')
    true_checks(capture.get('checks'), CAPTURE_CHECKS, 'capture/restoration')
    require(capture.get('frames_exercised') == 69 and capture.get('rendered') is False,
            'Require all 69 restoration checks without rendering')
    return summary


def private_mode_ok(mode):
    # Windows chmod does not implement POSIX group/other permission bits.
    return os.name != 'posix' or mode & 0o077 == 0


def accept(work, process_results):
    work = Path(work).absolute()
    require(work.is_dir() and not work.is_symlink() and private_mode_ok(work.stat().st_mode),
            'Working directory must remain private (mode 0700)')
    output = work / 'accepted'
    require(not output.exists() and not output.is_symlink(), 'Accepted output already exists')
    plan = read_json(work / 'plan.json')
    require(plan.get('schema') == 'rust-duty-prone-reconstruction-plan/v1' and
            plan.get('work') == str(work) and plan.get('input_sha256') == INPUT_SHA256 and
            plan.get('manifest_sha256') == MANIFEST_SHA256 and plan.get('blender_version') == '4.3.2',
            'Invalid reconstruction plan')
    source = Path(plan['source'])
    require(file_hash(source) == INPUT_SHA256, 'Original input changed')
    immutable, recipe = work / 'immutable', work / 'execution'
    require(all(p.is_dir() and not p.is_symlink() for p in (immutable, recipe, work / 'logs')),
            'Working subdirectories must not be links')
    entries = verify_manifest(immutable)
    for name, digest in entries.items():
        if name not in GENERATED:
            require(file_hash(recipe / name) == digest, f'Execution recipe changed: {name}')
    require(file_hash(recipe / 'SHA256SUMS') == MANIFEST_SHA256, 'Execution manifest changed')
    config = historical_config(work / 'historical_export_config.json')
    require(file_hash(work / 'historical_export_config.json') == plan['historical_config_sha256'],
            'Historical config changed')
    expected = commands(work, source, plan['blender'])
    require(plan.get('commands') == expected, 'Plan commands changed')
    result = read_json(process_results)
    require(result.get('schema') == 'rust-duty-prone-process-results/v1' and
            result.get('run_id') == plan['run_id'] and result.get('plan_sha256') == file_hash(work / 'plan.json'),
            'Missing or stale process receipt')
    stages = result.get('stages', [])
    require(len(stages) == 3, 'All three successful process results are mandatory')
    previous = plan['prepared_at_ns']
    artifacts = {}
    for stage, command in zip(stages, expected):
        require(all(stage.get(k) == v for k, v in command.items()), 'Process command/cwd/log mismatch')
        require(type(stage.get('returncode')) is int and stage['returncode'] == 0 and
                stage.get('blender_version') == '4.3.2', 'Process did not succeed with Blender 4.3.2')
        start, end = stage.get('started_at_ns'), stage.get('finished_at_ns')
        require(type(start) is int and type(end) is int and previous <= start < end <= time.time_ns(),
                'Stale, out-of-order, or invalid process times')
        log = Path(command['log'])
        require(file_hash(log) == stage.get('log_sha256') and log.stat().st_size > 0 and
                start <= log.stat().st_mtime_ns <= end, 'Missing, changed, or stale process log')
        stage_artifacts = stage.get('artifacts', {})
        require(set(stage_artifacts) == set(STAGES[command['stage']]), 'Missing process artifact hashes')
        for name, digest in stage_artifacts.items():
            path = recipe / name
            require(file_hash(path) == digest and start <= path.stat().st_mtime_ns <= end,
                    f'Changed, stale, or missing process output: {name}')
            artifacts[name] = digest
        previous = end
    candidate = file_hash(recipe / CANDIDATE)
    summary = validate_reports(recipe, immutable, candidate)
    sidecar_bytes = (recipe / 'camera_motion_samples.json').read_bytes()
    local_config = dict(config, source_sha256=candidate,
                        camera_sidecar_sha256=hashlib.sha256(sidecar_bytes).hexdigest())
    export_prone_pair.validate_inputs(local_config, candidate, EXPECTED_ACTIONS, sidecar_bytes)
    receipt = {'schema': 'rust-duty-prone-local-reconstruction/v1', 'status': 'numerical_reconstruction_only',
               'run_id': plan['run_id'], 'source_contract_commit': CONTRACT_COMMIT,
               'input_provenance_commit': INPUT_COMMIT, 'manifest_sha256': MANIFEST_SHA256,
               'input_sha256': INPUT_SHA256, 'candidate_sha256': candidate,
               'action_fingerprints': EXPECTED_ACTIONS, 'camera_sidecar_sha256': local_config['camera_sidecar_sha256'],
               'process_results_sha256': file_hash(process_results), 'artifacts': artifacts,
               'strict_wrist_guard_pass': False, 'strict_wrist_guard_threshold_deg': .08,
               'new_wrist_guard_max_deg': summary['new_wrist_guard_max_deg'],
               'rendered': False, 'art_approved': False, 'runtime_approved': False, 'export_approved': False}
    output.mkdir(mode=0o700)
    write_json(output / 'prone_pair_r6_export.local.json', local_config)
    (output / 'camera_motion_samples.json').write_bytes(sidecar_bytes)
    write_json(output / 'local_reconstruction_receipt.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--contract', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--config', type=Path, default=Path(__file__).with_name('prone_pair_r6_export.json'))
    p.add_argument('--blender', required=True, help='Local Blender 4.3.2 executable; no process is launched')
    p = sub.add_parser('accept')
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--process-results', type=Path, required=True)
    args = vars(parser.parse_args())
    mode = args.pop('mode')
    try:
        result = prepare(**args) if mode == 'prepare' else accept(**args)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(1, f'Reconstruction rejected: {error}\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
