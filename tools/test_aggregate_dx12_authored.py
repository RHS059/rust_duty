"""Synthetic aggregation controls. These are never native Windows evidence."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from PIL import Image, ImageDraw

import aggregate_dx12_authored as aggregate
import dx12_authored_shards as shards
import run_dx12_authored as authored
import verify_layered_locomotion_capture as layered
import test_dx12_authored as authored_tests
from test_dx12_authored_shards import make_gl_runtime
from test_capture_frame_witness import marker


ENV = {'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '1234', 'GITHUB_RUN_ATTEMPT': '2'}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + '\n', encoding='utf-8')


def image_bytes(color):
    image = Image.new('RGBA', authored.EXTENT, authored.BACKGROUND)
    ImageDraw.Draw(image).rectangle((200, 100, 700, 420), fill=color)
    output = io.BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


def make_root(root):
    root.mkdir()
    (root / 'Cargo.toml').write_text('[package]\nname="synthetic"\n', encoding='utf-8', newline='\n')
    (root / 'Cargo.lock').write_text('version = 4\n', encoding='utf-8', newline='\n')
    (root / 'settings.cfg').write_text('fov = 90\n')
    target = root / 'assets/authoring/ads/sight_alignment.json'
    target.parent.mkdir(parents=True)
    shutil.copyfile(Path(authored.__file__).parents[1] / 'assets/authoring/ads/sight_alignment.json', target)
    (root / 'tools').mkdir()
    for name in ('verify_layered_locomotion_capture.py', 'verify_ads_placement_capture.py',
                 'verify_capture_frame_witness.py', 'verify_render_capture.py', 'verify_capture_telemetry.py'):
        source = Path(__import__(name[:-3]).__file__)
        shutil.copyfile(source, root / 'tools' / name)
    reference = make_gl_runtime(root)
    binding = {'gl_reference_sha256': shards.gl_reference_digest(reference),
               'source_commit': ENV['GITHUB_SHA'], 'run_id': ENV['GITHUB_RUN_ID'],
               'run_attempt': ENV['GITHUB_RUN_ATTEMPT'], 'executable_sha256': hashlib.sha256(b'synthetic game').hexdigest(),
               'renderer_contract_sha256': 'c' * 64,
               'cargo_manifest_sha256': authored.sha256(root / 'Cargo.toml'),
               'cargo_lock_sha256': authored.sha256(root / 'Cargo.lock'),
               'runtime_and_manifest_sha256': {'settings.cfg': authored.sha256(root / 'settings.cfg'),
                   'assets/authoring/ads/sight_alignment.json': authored.sha256(target)}}
    manifest = {'schema': 'rust-duty-dx12-authored-inputs/v1', 'platform': 'win32',
                'build_selection': {'default_enabled': False, 'features': ['legacy-macroquad', 'wgpu-runtime']},
                'binding': binding, 'gl_reference': reference, 'expected_scenarios': list(shards.SCENARIOS)}
    write(root / 'input-manifest.json', manifest)
    return binding


def make_logs(folder, role, scenario=None, root=None, evidence=None, binding=None):
    folder.mkdir(parents=True)
    identity = ('renderer requested=gl backend=OpenGl adapter=llvmpipe (synthetic unit fixture)' if role == 'windows-legacy'
                else f'renderer requested=dx12 backend=Dx12 adapter={authored.WARP}\n{authored.FXC_LOG}')
    (folder / 'stdout.log').write_text(identity + '\n')
    (folder / 'stderr.log').write_text('')
    count = shards.PROFILES[scenario]['expected_frames'] if scenario else 2 if folder.name == 'renderer-contract' else 1
    timeout = 120 if folder.name == 'windows-legacy-stock-probe' else 900 if role == 'windows-legacy' or not scenario else shards.PROFILES[scenario]['capture_timeout_seconds']
    local_game = (evidence or folder.parent.parent) / 'gl-runtime/vector-range.exe'
    command = [str(local_game)]
    if folder.name == 'windows-legacy-stock-probe':
        command += ['--renderer=gl', '--no-update', '--procedural-weapon', '--reference-viewport', '--capture']
    if scenario:
        command = authored.game_command(local_game, root, evidence / shards.capture_paths(scenario)[role],
                                        aggregate.CASES[scenario], evidence / 'ads-offset.cfg')
        if role == 'windows-legacy':
            command = [argument.replace('--renderer=dx12', '--renderer=gl') for argument in command if argument != '--force-fallback-adapter']
        identity = aggregate.shard_runner.role_witness_identity(binding, scenario, role)
        command.append(f'--capture-frame-witness={identity}')
    write(folder / 'invocation.json', {'command': command, 'cwd': str(root or folder), 'timeout_seconds': timeout})
    write(folder / 'process.json', {'schema': 'rust-duty-capture-process/v1', 'status': 'passed',
                                   'exit_code': 0, 'pid': 42, 'png_files': count,
                                   'timeout_seconds': timeout, 'elapsed_seconds': 1.0})


def make_sequence(folder, scenario, role, binding=None):
    folder.mkdir(parents=True)
    count = shards.PROFILES[scenario]['expected_frames']
    case = aggregate.CASES[scenario]
    hz = case.hz or 60
    metadata = {'backend': 'OpenGl' if role == 'windows-legacy' else 'Dx12',
                'adapter': 'llvmpipe (synthetic unit fixture)' if role == 'windows-legacy' else authored.WARP,
                'requested': 'gl' if role == 'windows-legacy' else 'dx12', 'width': 960, 'height': 540}
    regular = image_bytes((120, 90, 60, 255))
    shifted = image_bytes((90, 120, 60, 255))
    variations = [image_bytes((100 + tick, 90, 60, 255)) for tick in range(8)] if scenario in aggregate.LAYERED else []
    witness_identity = aggregate.shard_runner.role_witness_identity(binding, scenario, role) if binding is not None else None
    for index in range(count):
        tick = index * (120 // hz)
        second = tick // 120
        row = {'simulation_time': tick / 120, 'sampling_hz': hz, 'renderer_failed': False,
               'route': 'ready', 'run_weight': 0, 'walk_weight': 0, 'speed': 0, 'simulation_ads': 0,
               'pose_crc32': tick, 'ads_requested': False, 'sprinting': False,
               'walk_seconds': None, 'directional_weights': None,
               'position': [tick / 120, 0.0, 0.0], 'velocity': [1.0, 0.0, 0.0], 'ammo': 30, 'shots': 0}
        if scenario in ('ads-gameplay', 'ads-offset') and 31 <= index < count - 1:
            row.update(route='ads.hold', simulation_ads=1, ads_requested=True, speed=1 if index < 100 else 0)
        if scenario in aggregate.LAYERED:
            if second < 8:
                direction, kind = divmod(second, 2)
                row.update(segment=f"{('forward', 'backward', 'left', 'right')[direction]}_{('hip', 'ads')[kind]}",
                           route='ads.hold' if kind else 'locomotion', walk_weight=1.0,
                           directional_weights=[1.0 if i == direction else 0.0 for i in range(4)],
                           ads_requested=bool(kind), simulation_ads=kind)
            elif second == 8:
                row.update(segment='rapid_run_interruptions', route='ads.hold', walk_weight=0.5,
                           run_weight=0.5, ads_requested=True, sprinting=True, simulation_ads=1)
            else:
                row['segment'] = 'settle'
        image = folder / f'{index:04}.png'
        raw = variations[index % 8] if variations else shifted if scenario == 'ads-offset' and row['route'] == 'ready' else regular
        record = dict(metadata)
        if witness_identity is None:
            image.write_bytes(raw)
        else:
            with Image.open(io.BytesIO(raw)) as source:
                marked = source.copy()
            marked.paste(marker(index, witness_identity).crop((0, 0, 64, 22)), (0, 0))
            marked.save(image)
            record['frame_witness'] = {'schema': 'rust-duty-capture-frame-witness/v1',
                                       'frame_index': index, 'capture_identity': witness_identity}
        write(Path(f'{image}.json'), record)
        write(Path(f'{image}.time.json'), {'elapsed_seconds': tick / 120, 'sampling_hz': hz})
        write(Path(f'{image}.gameplay.json'), row)
    if scenario in aggregate.LAYERED:
        layered.verify(folder)
    else:
        write(folder / 'verification.json', {'schema': 'synthetic-existing-validator/v1', 'passed': True, 'frames': count})


def summary(folder, scenario, binding):
    reference = make_gl_runtime(folder, runtime=folder/'gl-runtime', manifest=folder/'gl-runtime/windows_gl_reference_lock.json')
    (folder/'gl-runtime/vector-range.exe').write_bytes(b'synthetic game')
    checks = []
    for name in aggregate.local_checks(scenario):
        result = {'synthetic_receipt': True}
        if name in ('validated-inputs', 'inputs-unchanged'):
            result = binding
        elif name.endswith('/existing-validator'):
            result = {'exit_code': 0}
        elif name.endswith('/finite-images'):
            result = {'frames': shards.PROFILES[scenario]['expected_frames'], 'all_images_checked': True}
        elif name == 'layered-pair-deferred-to-aggregate':
            result = {'rates': list(aggregate.LAYERED)}
        checks.append({'name': name, 'passed': True, 'result': result, 'elapsed_seconds': 0.01})
    report = {'schema': 'rust-duty-dx12-authored-shard/v1', 'scenario': scenario, 'binding': binding,
              'platform': 'win32', 'host': {'runner_name': 'synthetic', 'runner_os': 'Windows', 'runner_arch': 'X64'},
              'status': 'passed', 'passed': True, 'acceptance_complete': False, 'automated_landmark_gate': 'open',
              'current_check': None, 'elapsed_seconds': 1.0,
              'run_timeout_seconds': shards.PROFILES[scenario]['run_timeout_seconds'],
              'budget_exhausted': False, 'checks': checks, 'capture_paths': shards.capture_paths(scenario),
              'gl_reference': reference, 'gl_runtime_path':'gl-runtime',
              'app_local_executable':str(folder/'gl-runtime/vector-range.exe'),
              'files': shards.inventory_files(folder)}
    write(folder / 'summary.json', report)
    return report


def make_fixture(base):
    root, incoming, historical = base / 'root', base / 'shards', base / 'historical'
    binding = make_root(root)
    incoming.mkdir()
    historical.mkdir()
    for scenario in shards.SCENARIOS:
        folder = incoming / scenario
        folder.mkdir()
        if scenario in aggregate.CASES:
            for role in aggregate.ROLES:
                make_sequence(folder / shards.capture_paths(scenario)[role], scenario, role, binding)
                make_logs(folder / 'logs' / f'{role}-capture', role, scenario, root, folder, binding)
                validator_logs = folder / 'logs' / f'{role}-validator'
                validator_logs.mkdir(parents=True)
                script = aggregate.CASES[scenario].validator or 'verify_layered_locomotion_capture.py'
                write(validator_logs / 'invocation.json', {'command': ['python', str(root / 'tools' / script),
                      str(folder / shards.capture_paths(scenario)[role])], 'cwd': str(root), 'timeout_seconds': 900})
                write(validator_logs / 'process.json', {'schema': 'rust-duty-capture-process/v1', 'status': 'passed',
                      'exit_code': 0, 'pid': 43, 'png_files': 0, 'timeout_seconds': 900, 'elapsed_seconds': 1.0})
                verdict = json.loads((folder / shards.capture_paths(scenario)[role] / 'verification.json').read_text())
                write(validator_logs / 'stdout.log', {'captures': [verdict]} if scenario in aggregate.LAYERED else verdict)
                (validator_logs / 'stderr.log').write_text('')
            make_sequence(historical / aggregate.CASES[scenario].baseline, scenario, 'windows-legacy')
            stock = folder / 'stock-gl'
            stock.mkdir()
            legacy_frame = folder / shards.capture_paths(scenario)['windows-legacy'] / '0000.png'
            (stock / 'stock-gl.png').write_bytes(image_bytes((120, 90, 60, 255)))
            stock_metadata = json.loads(Path(f'{legacy_frame}.json').read_text())
            stock_metadata.pop('frame_witness')
            write(stock / 'stock-gl.png.json', stock_metadata)
            make_logs(folder / 'logs/windows-legacy-stock-probe', 'windows-legacy')
        else:
            helper = authored_tests.AuthoredDx12Tests(methodName='test_all_frame_finite_and_image_control')
            helper.root = folder
            lighting = helper.lighting_fixture()
            target = folder / shards.capture_paths(scenario)['dx12']
            target.parent.mkdir(parents=True)
            lighting.rename(target)
            authored.validate_lighting(target)
            helper.orientation(folder / 'renderer-contract')
            make_logs(folder / 'logs/renderer-contract', 'dx12')
            for stem, _ in authored.lighting_commands(Path('game'), root, target):
                make_logs(folder / 'logs' / f'lighting-{stem}', 'dx12')
        if scenario == 'ads-offset':
            (folder / 'ads-offset.cfg').write_text('synthetic same settings used by both roles')
        summary(folder, scenario, binding)
    parent = historical / 'layered'
    outputs = [layered.verify(parent / f'layered-{hz}') for hz in (30, 60)]
    write(parent / 'layered-rate-verification.json', {'captures': [output[0] for output in outputs],
                                                    'rate_comparison': layered.compare_rates(outputs[0][1], outputs[1][1])})
    receipt = base / 'historical-manifest.json'
    write(receipt, {'schema': 'rust-duty-dx12-authored-historical/v1',
                    **{key: binding[key] for key in ('source_commit', 'run_id', 'run_attempt')},
                    'files': shards.inventory_files(historical, exclude=())})
    return root, incoming, historical, receipt, binding


class AggregateContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.env = patch.dict(os.environ, ENV)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.root = self.base / 'root'
        self.binding = make_root(self.root)
        self.folder = self.base / 'jump-gameplay'
        self.folder.mkdir()
        (self.folder / 'raw.txt').write_text('synthetic bound evidence')
        self.report = summary(self.folder, 'jump-gameplay', self.binding)

    def read(self):
        return aggregate.read_shard(self.folder, 'jump-gameplay', self.binding)

    def test_lighting_invocation_cannot_bypass_same_binary_by_omitting_renderer_flag(self):
        folder = self.base/'lighting-orientation'; folder.mkdir()
        write(folder/'logs/lighting-ready_front/invocation.json', {'command':['unbound.exe','--capture-lighting']})
        summary(folder,'lighting-orientation',self.binding)
        with self.assertRaisesRegex(ValueError,'same hash-bound app-local game'):
            aggregate.read_shard(folder,'lighting-orientation',self.binding)

    def test_retained_reference_and_copied_binary_are_required_even_after_resealing(self):
        for name in ('opengl32.dll','vector-range.exe'):
            path = self.folder/'gl-runtime'/name; original = path.read_bytes()
            path.write_bytes(original+b'changed')
            report = copy.deepcopy(self.report); report['files'] = shards.inventory_files(self.folder)
            write(self.folder/'summary.json',report)
            with self.subTest(path=name), self.assertRaises(ValueError): self.read()
            path.write_bytes(original)
            write(self.folder/'summary.json',self.report)

    def test_local_check_inventory_matches_real_shard_entrypoint(self):
        for scenario in shards.SCENARIOS:
            self.assertEqual(aggregate.local_checks(scenario), aggregate.shard_runner.required_checks(scenario))

    def test_typed_manifest_and_source_controls(self):
        path = self.root / 'input-manifest.json'
        self.assertEqual(aggregate.validated_manifest(path, self.root), self.binding)
        original = json.loads(path.read_text())
        changes = [('schema', 'invented/v1'), ('platform', 'linux'), ('expected_scenarios', list(reversed(shards.SCENARIOS))),
                   ('build_selection', {'default_enabled': 0, 'features': ['legacy-macroquad', 'wgpu-runtime']})]
        for field, value in changes:
            with self.subTest(field=field):
                write(path, {**original, field: value})
                with self.assertRaises(ValueError):
                    aggregate.validated_manifest(path, self.root)
        write(path, original)
        (self.root / 'settings.cfg').write_text('fov=91\n')
        with self.assertRaises(ValueError):
            aggregate.validated_manifest(path, self.root)

    def test_summary_control_rejects_omission_reorder_duplicate_failure_and_stale_binding(self):
        self.assertTrue(aggregate.shard_pass(self.read())['passed'])
        original = copy.deepcopy(self.report)
        mutations = [lambda d: d['checks'].pop(), lambda d: d['checks'].reverse(),
                     lambda d: d['checks'].append(d['checks'][0]),
                     lambda d: d.update(passed='true'), lambda d: d.update(passed=1),
                     lambda d: d.update(status='failed'), lambda d: d.update(budget_exhausted=True),
                     lambda d: d['binding'].update(run_attempt='1'),
                     lambda d: d['binding'].update(executable_sha256='d' * 64),
                     lambda d: d.update(platform='linux'), lambda d: d['host'].update(runner_os='Linux'),
                     lambda d: d['capture_paths'].update(dx12='wrong'),
                     lambda d: d.update(acceptance_complete=True)]
        for index, mutate in enumerate(mutations):
            report = copy.deepcopy(original)
            mutate(report)
            write(self.folder / 'summary.json', report)
            with self.subTest(mutation=index), self.assertRaises(ValueError):
                aggregate.shard_pass(self.read())

    def test_inventory_rejects_tampering_or_unrecorded_file(self):
        (self.folder / 'raw.txt').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'inventory mismatch'):
            self.read()
        (self.folder / 'raw.txt').write_text('synthetic bound evidence')
        (self.folder / 'extra').write_text('unrecorded')
        with self.assertRaisesRegex(ValueError, 'inventory mismatch'):
            self.read()

    def test_legacy_logs_do_not_accept_requested_flag_or_inconsistent_adapter(self):
        log = self.base / 'logs'
        make_logs(log, 'windows-legacy')
        self.assertEqual(aggregate.legacy_logs(log), 'llvmpipe (synthetic unit fixture)')
        for text in ('--renderer=gl', 'renderer requested=gl backend=Vulkan adapter=GPU',
                     'renderer requested=gl backend=OpenGl adapter= ',
                     'renderer requested=gl backend=OpenGl adapter=A\nrenderer requested=gl backend=OpenGl adapter=B'):
            (log / 'stdout.log').write_text(text)
            with self.subTest(text=text), self.assertRaises(ValueError):
                aggregate.legacy_logs(log)

    def test_recorded_process_must_have_really_finished_with_zero_exit(self):
        logs = self.base / 'process'
        make_logs(logs, 'dx12')
        self.assertEqual(aggregate.process_receipt(logs, 900, 1), [str(logs.parent.parent / 'gl-runtime/vector-range.exe')])
        path = logs / 'process.json'
        original = json.loads(path.read_text())
        for field, value in (('status', 'timed_out'), ('status', 'interrupted'), ('exit_code', False),
                             ('exit_code', 7), ('pid', None), ('png_files', 0),
                             ('timeout_seconds', 901), ('elapsed_seconds', 900)):
            write(path, {**original, field: value})
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                aggregate.process_receipt(logs, 900, 1)
        write(path, original)

    def test_capture_invocation_requires_one_independently_derived_witness_flag(self):
        scenario, role = 'jump-gameplay', 'dx12'
        logs = self.folder / 'logs' / f'{role}-capture'
        make_logs(logs, role, scenario, self.root, self.folder, self.binding)
        expected = aggregate.shard_runner.role_witness_identity(self.binding, scenario, role)
        count = shards.PROFILES[scenario]['expected_frames']
        self.assertIn(f'--capture-frame-witness={expected}',
                      aggregate.capture_invocation(self.folder, scenario, role, count, expected))
        path = logs / 'invocation.json'
        original = json.loads(path.read_text())
        ordinary = [arg for arg in original['command'] if not arg.startswith('--capture-frame-witness')]
        wrong_run = aggregate.shard_runner.role_witness_identity({**self.binding, 'run_id': '1235'}, scenario, role)
        for flags in ([], [f'--capture-frame-witness={wrong_run}'],
                      [f'--capture-frame-witness={expected}'] * 2,
                      ['--capture-frame-witness', expected]):
            with self.subTest(flags=flags):
                write(path, {**original, 'command': ordinary + flags})
                with self.assertRaisesRegex(ValueError, 'exact frame witness identity'):
                    aggregate.capture_invocation(self.folder, scenario, role, count, expected)
        write(path, original)

    def test_local_validator_stdout_must_match_its_recorded_folder_verdict(self):
        logs = self.base / 'validator'
        make_logs(logs, 'dx12')
        state = json.loads((logs / 'process.json').read_text())
        state['png_files'] = 0
        write(logs / 'process.json', state)
        case = aggregate.CASES['jump-gameplay']
        relative = shards.capture_paths(case.name)['dx12']
        write(logs / 'invocation.json', {'command': ['python', '/tools/' + case.validator, '/evidence/' + relative],
                                        'cwd': '/source', 'timeout_seconds': 900})
        verdict = {'schema': 'synthetic/v1', 'passed': True, 'frames': 403}
        write(logs / 'stdout.log', verdict)
        self.assertTrue(aggregate.validator_receipt(logs, case, relative, verdict)['verified_stdout'])
        for changed in ({**verdict, 'passed': False}, {**verdict, 'frames': 402}, {'captures': [verdict]}):
            write(logs / 'stdout.log', changed)
            with self.assertRaises(ValueError):
                aggregate.validator_receipt(logs, case, relative, verdict)

    def test_closed_nine_shard_set_rejects_missing_extra_and_file_entries(self):
        folder = self.base / 'shards'
        folder.mkdir()
        for name in shards.SCENARIOS:
            (folder / name).mkdir()
        self.assertEqual(aggregate.validate_shard_set(folder)['scenarios'], list(shards.SCENARIOS))
        missing = folder / shards.SCENARIOS[0]
        missing.rmdir()
        with self.assertRaises(ValueError):
            aggregate.validate_shard_set(folder)
        missing.write_text('not a directory')
        with self.assertRaises(ValueError):
            aggregate.validate_shard_set(folder)
        missing.unlink()
        missing.mkdir()
        (folder / 'unexpected-scenario').mkdir()
        with self.assertRaises(ValueError):
            aggregate.validate_shard_set(folder)

    def test_missing_inputs_cli_retains_every_required_failure(self):
        evidence = self.base / 'failed'
        with redirect_stdout(io.StringIO()):
            code = aggregate.main(['--root', str(self.root), '--shards', str(self.base / 'absent'),
                                   '--legacy-linux', str(self.base / 'absent-linux'), '--evidence', str(evidence),
                                   '--input-manifest', str(self.base / 'absent-manifest'),
                                   '--historical-manifest', str(self.base / 'absent-receipt')])
        self.assertEqual(code, 1)
        report = json.loads((evidence / 'summary.json').read_text())
        self.assertFalse(report['passed'])
        self.assertEqual(report['status'], 'failed')
        self.assertEqual([row['name'] for row in report['checks']], aggregate.expected_checks())
        self.assertTrue(all(row['passed'] is False for row in report['checks']))

    def test_invalid_budget_retains_complete_failure_report(self):
        output = self.base / 'timeout'
        report = aggregate.run(self.root, self.base / 'absent', self.base / 'linux', output,
                               self.root / 'input-manifest.json', historical_manifest=self.base / 'receipt', run_timeout=0)
        self.assertFalse(report['passed'])
        self.assertEqual(len(report['checks']), len(aggregate.expected_checks()))
        self.assertTrue((output / 'summary.json').is_file())


class AggregateEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temp.name).resolve()
        with patch.dict(os.environ, ENV):
            cls.root, cls.incoming, cls.historical, cls.receipt, cls.binding = make_fixture(cls.base)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def invoke(self, name):
        output = self.base / name
        with patch.dict(os.environ, ENV), redirect_stdout(io.StringIO()):
            report = aggregate.run(self.root, self.incoming, self.historical, output,
                                   self.root / 'input-manifest.json', historical_manifest=self.receipt)
        return output, report

    def test_01_real_pair_validators_strict_wrapper_and_complete_success(self):
        original = shards.inventory_files(self.incoming, exclude=())
        historical_path = self.historical / 'jump-gameplay/0000.png.time.json'
        historical_bytes, receipt_bytes = historical_path.read_bytes(), self.receipt.read_bytes()
        try:
            data = json.loads(historical_bytes)
            data['elapsed_seconds'] = 0.00000001
            write(historical_path, data)
            receipt = json.loads(receipt_bytes)
            receipt['files'] = shards.inventory_files(self.historical, exclude=())
            write(self.receipt, receipt)
            output, report = self.invoke('successful')
        finally:
            historical_path.write_bytes(historical_bytes)
            self.receipt.write_bytes(receipt_bytes)
        diagnostic = next(item for item in report['diagnostics'] if item['scenario'] == 'jump-gameplay')
        self.assertFalse(diagnostic['exact_match'])
        self.assertFalse(diagnostic['acceptance_predicate'])
        failed = [row for row in report['checks'] if not row['passed']]
        self.assertTrue(report['passed'], failed)
        self.assertEqual([row['name'] for row in report['checks']], aggregate.expected_checks())
        self.assertFalse(report['acceptance_complete'])
        self.assertEqual(report['automated_landmark_gate'], 'open')
        for role, parent in (('windows-legacy', 'windows-legacy/layered'), ('dx12', 'dx12')):
            layered_report = json.loads((output / 'assembled' / parent / 'layered-rate-verification.json').read_text())
            self.assertEqual(set(layered_report), {'captures', 'rate_comparison'})
            self.assertEqual({item['sampling_hz'] for item in layered_report['captures']}, {30, 60})
            self.assertEqual(layered_report['rate_comparison']['common_ticks'], 337)
        review = json.loads((output / 'review/landmark-review.json').read_text())
        for row in review['records']:
            role = 'dx12' if row['backend'] == 'dx12' else 'windows-legacy'
            source = self.incoming / 'ads-gameplay' / shards.capture_paths('ads-gameplay')[role] / f'{row["source_frame"]}.json'
            self.assertEqual(source.read_bytes(), (output / 'review' / row['raw_sidecar']).read_bytes())
        self.assertEqual(shards.inventory_files(self.incoming, exclude=()), original)

    def test_03_failed_gl_probe_does_not_suppress_dx12_ads_pair(self):
        originals = {}
        try:
            for scenario in shards.SCENARIOS:
                path = self.incoming / scenario / 'summary.json'
                originals[path] = path.read_bytes()
                report = json.loads(path.read_text())
                report.update(status='failed', passed=False)
                for row in report['checks']:
                    if ((scenario in ('ads-gameplay', 'ads-offset') and row['name'] in ('windows-legacy/stock-probe', 'windows-legacy/capture'))
                            or (scenario not in ('ads-gameplay', 'ads-offset') and row['name'] == 'validated-inputs')):
                        row.pop('result')
                        row.update(passed=False, error='synthetic unrelated failed capture')
                if scenario in ('ads-gameplay', 'ads-offset'):
                    invocation = path.parent / 'logs/windows-legacy-capture/invocation.json'
                    originals[invocation] = invocation.read_bytes()
                    invocation.unlink()
                    report['files'] = shards.inventory_files(path.parent)
                write(path, report)
            _, report = self.invoke('failed-shard')
            self.assertFalse(report['passed'])
            checks = {row['name']: row for row in report['checks']}
            self.assertFalse(checks['jump-gameplay/local-checks']['passed'])
            self.assertTrue(checks['dx12/ads-placement-existing-validator']['passed'])
            self.assertFalse(checks['windows-legacy/ads-placement-existing-validator']['passed'])
            self.assertEqual([row['name'] for row in report['checks']], aggregate.expected_checks())
        finally:
            for path, data in originals.items():
                path.write_bytes(data)

    def test_04_same_windows_type_and_primary_metadata_differences_fail(self):
        folder = self.incoming / 'jump-gameplay'
        with patch.dict(os.environ, ENV):
            report = aggregate.read_shard(folder, 'jump-gameplay', self.binding)
            assembled = self.base / 'parity-controls'
            for role in aggregate.ROLES:
                aggregate.copy_role(folder, report, role, assembled, self.binding)
        baseline, candidate = [assembled / role / 'jump-gameplay' for role in aggregate.ROLES]
        self.assertTrue(aggregate.same_windows_parity(baseline, candidate, 'jump-gameplay', folder)['passed'])
        time_path = candidate / '0000.png.time.json'
        original = time_path.read_bytes()
        write(time_path, {'elapsed_seconds': 0, 'sampling_hz': 60})
        with self.assertRaisesRegex(ValueError, 'type differs'):
            aggregate.same_windows_parity(baseline, candidate, 'jump-gameplay', folder)
        time_path.write_bytes(original)
        path = candidate / '0000.png.json'
        data = json.loads(path.read_text())
        write(path, {**data, 'hfov': 90})
        with self.assertRaisesRegex(ValueError, 'fields differ'):
            aggregate.same_windows_parity(baseline, candidate, 'jump-gameplay', folder)

    @patch.dict(os.environ, ENV)
    def test_06_resealed_cross_run_pixels_and_metadata_do_not_replace_input_binding(self):
        scenario, role = 'reload-gameplay', 'dx12'
        folder = self.incoming / scenario
        capture = folder / shards.capture_paths(scenario)[role]
        summary_path = folder / 'summary.json'
        invocation_path = folder / 'logs' / f'{role}-capture/invocation.json'
        originals = {path: path.read_bytes() for path in capture.glob('*.png*') if path.suffix != '.json' or path.name.endswith('.png.json')}
        originals.update({summary_path: summary_path.read_bytes(), invocation_path: invocation_path.read_bytes()})
        expected = aggregate.shard_runner.role_witness_identity(self.binding, scenario, role)
        other = aggregate.shard_runner.role_witness_identity({**self.binding, 'run_id': '1235'}, scenario, role)
        try:
            for index, path in enumerate(sorted(capture.glob('*.png'))):
                with Image.open(path) as source:
                    image = source.copy()
                image.paste(marker(index, other).crop((0, 0, 64, 22)), (0, 0))
                image.save(path)
                sidecar = Path(str(path) + '.json')
                metadata = json.loads(sidecar.read_text())
                metadata['frame_witness']['capture_identity'] = other
                write(sidecar, metadata)
            invocation = json.loads(invocation_path.read_text())
            invocation['command'] = [arg for arg in invocation['command'] if not arg.startswith('--capture-frame-witness')]
            for suffix, flag_identity, error in (
                ('wrong-invocation', other, 'exact frame witness identity'),
                ('rewritten-metadata', expected, 'metadata capture identity'),
            ):
                write(invocation_path, {**invocation, 'command': invocation['command'] + [f'--capture-frame-witness={flag_identity}']})
                report = json.loads(originals[summary_path])
                report['files'] = shards.inventory_files(folder)
                write(summary_path, report)
                # Re-sealing all artifact hashes is insufficient: derive the
                # expectation from the separately validated input binding.
                checked = aggregate.read_shard(folder, scenario, self.binding)
                with self.subTest(suffix=suffix), self.assertRaisesRegex(ValueError, error):
                    aggregate.copy_role(folder, checked, role, self.base / suffix, self.binding)
        finally:
            for path, data in originals.items():
                path.write_bytes(data)

    def test_05_stale_or_malformed_historical_inputs_fail(self):
        receipt = json.loads(self.receipt.read_text())
        original = self.receipt.read_bytes()
        try:
            receipt['run_attempt'] = '1'
            write(self.receipt, receipt)
            with self.assertRaisesRegex(ValueError, 'value differs'):
                aggregate.load_historical(self.historical, self.base / 'bad-historical-copy', self.binding, self.receipt)
        finally:
            self.receipt.write_bytes(original)
        path = self.historical / 'jump-gameplay/0000.png.gameplay.json'
        original = path.read_bytes()
        try:
            path.write_text('{broken')
            receipt['run_attempt'] = ENV['GITHUB_RUN_ATTEMPT']
            receipt['files'] = shards.inventory_files(self.historical, exclude=())
            write(self.receipt, receipt)
            loaded = aggregate.load_historical(self.historical, self.base / 'malformed-historical-copy', self.binding, self.receipt)
            with self.assertRaises(ValueError):
                aggregate.historical_sequence(loaded['root'] / 'jump-gameplay', 'jump-gameplay')
            self.assertEqual(aggregate.historical_sequence(loaded['root'] / 'ads-gameplay', 'ads-gameplay')['frames'], 553)
        finally:
            path.write_bytes(original)
            receipt['files'] = shards.inventory_files(self.historical, exclude=())
            write(self.receipt, receipt)


if __name__ == '__main__':
    unittest.main()
