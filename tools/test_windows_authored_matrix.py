"""Synthetic fixtures and mocked process orchestration, never native acceptance."""
import contextlib
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import run_windows_authored_matrix as matrix
import test_dx12_authored as authored_fixtures
import test_windows_same_platform_return as return_fixtures


class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def test_original_eight_cases_and_all_frame_counts(self):
        matrix.contract()
        self.assertEqual(list(matrix.COUNTS.values()), [403, 214, 223, 553, 553, 337, 673, 391])
        self.assertEqual(sum(matrix.COUNTS.values()), 3347)
        self.assertEqual(len(matrix.INPUTS), 9)
        changed = matrix.authored.CASES[:-1]
        with patch.object(matrix.authored, 'CASES', changed), self.assertRaises(ValueError): matrix.contract()

    def test_exact_gl_dx12_commands_and_unmodified_default_cadence(self):
        game = self.root / 'same.exe'; offset = self.root / 'offset.cfg'
        for case in matrix.authored.CASES:
            for backend in matrix.BACKENDS.values():
                with self.subTest(case=case.name, backend=backend):
                    command = matrix.capture_command(game, self.root, self.root / 'out', case, offset, backend)
                    self.assertEqual(str(game), command[0])
                    self.assertEqual([x for x in command if x.startswith('--capture-hz=')],
                                     [] if case.hz is None else [f'--capture-hz={case.hz}'])
                    self.assertEqual([x for x in command if x.startswith('--settings=')],
                                     [f'--settings={offset if case.name == "ads-offset" else self.root / "settings.cfg"}'])
                    self.assertIn('--renderer=gl' if backend == 'OpenGl' else '--renderer=dx12', command)
                    self.assertEqual('--force-fallback-adapter' in command, backend == 'Dx12')
                    self.assertNotIn('--procedural-weapon', command)
                    self.assertIn('--no-update', command)

    def test_all_nine_inputs_required_and_duplicate_directory_rejected(self):
        values = []
        for name in matrix.INPUTS:
            path = self.root / name; path.mkdir(); values.append(f'{name}={path}')
        self.assertEqual(set(matrix.parse_inputs(values)), set(matrix.INPUTS))
        for bad in (values[:-1], values + [values[0]], [v.replace('auxiliary=', 'unknown=') for v in values]):
            with self.assertRaises(ValueError): matrix.parse_inputs(bad)
        reused = [f'{name}={self.root}' for name in matrix.INPUTS]
        with self.assertRaisesRegex(ValueError, 'distinct'): matrix.parse_inputs(reused)

    def test_non_windows_and_invalid_case_cannot_start(self):
        with patch.object(matrix.sys, 'platform', 'linux'), self.assertRaisesRegex(ValueError, 'Windows'):
            matrix.capture('reload-return', None, None, None, None, None, None)
        with patch.object(matrix.sys, 'platform', 'win32'), self.assertRaisesRegex(ValueError, 'unknown'):
            matrix.capture('shorter-case', None, None, None, None, None, None)

    def test_existing_evidence_and_bad_budgets_preserved(self):
        output = self.root / 'evidence'; output.mkdir(); (output / 'keep').write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'existing'):
            matrix.Session(self.root, output, 'capture', 1, 1)
        self.assertEqual((output / 'keep').read_bytes(), b'keep')
        for value in (0, -1, True, float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                matrix.Session(self.root, self.root / 'new', 'capture', value, 1)
        self.assertFalse((self.root / 'new').exists())

    def test_budget_exhaustion_stops_before_action(self):
        session = matrix.Session(self.root, self.root/'evidence', 'capture', 1, 1)
        session.started -= 10
        calls = []
        with self.assertRaisesRegex(ValueError, 'budget'):
            session.check('must-not-launch', lambda: calls.append(True))
        self.assertFalse(calls)
        self.assertFalse(session.report['passed'])
        self.assertEqual(session.report['checks'][-1]['passed'], False)

    def lighting_fixture(self):
        fixture = authored_fixtures.AuthoredDx12Tests()
        fixture.setUpClass(); fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        original = fixture.lighting_fixture()
        result = {}
        for label, backend in matrix.BACKENDS.items():
            folder = self.root / label; shutil.copytree(original, folder)
            logs = self.root / (label + '-logs'); logs.mkdir()
            adapter = 'llvmpipe (LLVM 22.1.8, 256 bits)' if label == 'gl' else matrix.authored.WARP
            for path in folder.glob('*.png.json'):
                value = json.loads(path.read_text()); value.update(backend=backend, requested=label, adapter=adapter)
                path.write_text(json.dumps(value))
            for stem in matrix.lighting_stems():
                sub = logs / f'lighting-{stem}'; sub.mkdir()
                (sub/'stdout.log').write_text('')
                (sub/'stderr.log').write_text(f'renderer requested={label} backend={backend} adapter={adapter}\n'
                                             + (matrix.authored.FXC_LOG+'\n' if label == 'dx12' else ''))
            result[label] = (folder, logs)
        return result

    def test_lighting_all_twelve_poses_both_backends_and_idempotent_original_validator(self):
        fixtures = self.lighting_fixture()
        for label, backend in matrix.BACKENDS.items():
            folder, logs = fixtures[label]
            before = matrix.hashes(folder)
            report = matrix.validate_lighting(folder, backend, logs)
            self.assertEqual(report['existing_validator']['frames'], 12)
            self.assertEqual(report['world_images_checked'], 12)
            matrix.validate_lighting(folder, backend, logs)
            after = matrix.hashes(folder, omit_verdict=True)
            self.assertEqual(before, after)
        result = matrix.exact_lighting(fixtures['gl'][0], fixtures['dx12'][0])
        self.assertEqual(result['capture_metadata_files'], 24)

    def test_lighting_tiny_exact_drift_and_missing_world_rejected(self):
        fixtures = self.lighting_fixture()
        gl, dx = fixtures['gl'][0], fixtures['dx12'][0]
        path = dx / 'ready_front.png.lighting.json'
        original = path.read_text()
        path.write_text(original.replace('"ambient": 0.28', '"ambient": 0.280000000000000001'))
        with self.assertRaisesRegex(ValueError, 'ambient'): matrix.exact_lighting(gl, dx)
        path.write_text(original)
        (dx / 'ready_front.png.world.png').unlink()
        with self.assertRaisesRegex(ValueError, 'inventory'):
            matrix.validate_lighting(dx, 'Dx12', fixtures['dx12'][1])

    def test_dirty_or_untracked_current_source_fails_binding(self):
        context = {'source': {'commit': 'a'*40}}
        with patch.object(matrix.build_identity, 'context', return_value=context), \
                patch.object(matrix.subprocess, 'check_output', return_value='a'*40+'\n'), \
                patch.object(matrix.subprocess, 'check_call', side_effect=subprocess.CalledProcessError(1, ['git','diff'])):
            with self.assertRaises(subprocess.CalledProcessError): matrix.current_identity(self.root)
        with patch.object(matrix.build_identity, 'context', return_value=context), \
                patch.object(matrix.subprocess, 'check_output', side_effect=['a'*40+'\n','src/untracked.rs\n']), \
                patch.object(matrix.subprocess, 'check_call', return_value=0):
            with self.assertRaisesRegex(ValueError, 'untracked'): matrix.current_identity(self.root)

    def test_exact_offset_not_just_any_effective_shift(self):
        settings = self.root/'settings.cfg'; settings.write_text('base = unchanged\n')
        offset = self.root/'ads-offset.cfg'
        offset.write_text(settings.read_text()+matrix.OFFSET)
        record = {'offset_settings_sha256':matrix.authored.sha256(offset)}
        matrix.validate_offset(self.root, record, settings)
        offset.write_text(settings.read_text()+matrix.OFFSET.replace('0.20','0.10'))
        record['offset_settings_sha256'] = matrix.authored.sha256(offset)
        with self.assertRaisesRegex(ValueError, 'original XYZ'): matrix.validate_offset(self.root, record, settings)

    def test_original_windows_commands_reconstructed_without_host_path_changes(self):
        record = {'execution_root':r'D:\a\game', 'execution_evidence':r'D:\evidence\jump',
                  'python_executable':r'C:\Python\python.exe'}
        commands = matrix.expected_process_commands('jump-gameplay', record)
        self.assertEqual(commands['gl/capture'][0], r'D:\evidence\jump\runtime\vector-range.exe')
        self.assertIn('--settings=D:\\a\\game\\settings.cfg', commands['gl/capture'])
        self.assertIn('--capture-hz=60', commands['gl/capture'])
        self.assertEqual(len(commands), 6)

    def test_orientation_requires_separate_fixture_embedded_build_identity(self):
        folder = self.root / 'orientation'; folder.mkdir()
        path = folder / 'renderer-contract-report.json'
        path.write_text(json.dumps({'build_version': '1.0', 'build_number': '10.2'}))
        context = {'version': '1.0', 'build_number': '10.2'}
        with patch.object(matrix.authored, 'validate_orientation', return_value={'fixture': True}) as verify:
            matrix.orientation_build_identity(folder, context)
            verify.assert_called_once_with(folder)
            with self.assertRaisesRegex(ValueError, 'embedded build'):
                matrix.orientation_build_identity(folder, {'version': '1.0', 'build_number': '11.2'})


class CaptureOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = return_fixtures.SamePlatformReturnTests()
        self.fixture.setUpClass(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        original_tools = Path(matrix.__file__).parent
        for file in original_tools.glob('*.py'):
            shutil.copyfile(file, self.root / 'tools' / file.name)
        self.fixture_binary = self.root / 'built/renderer_contract.exe'
        self.fixture_binary.write_bytes(b'MZ synthetic separate orientation fixture, never executed')

    def run_capture(self, *, mutate=None, case='reload-return'):
        fixture = self.fixture
        fixture.mutate_capture = mutate
        assets = {'generated_verification': {'synthetic': True}, 'runtime_and_manifest_sha256': matrix.pair.input_hashes(self.root)}
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(matrix.sys, 'platform', 'win32'))
            stack.enter_context(patch.dict(matrix.os.environ, fixture.env))
            stack.enter_context(patch.object(matrix, 'current_identity', side_effect=lambda root: matrix.build_identity.context()))
            stack.enter_context(patch.object(matrix.authored, 'asset_evidence', return_value=assets))
            stack.enter_context(patch.object(matrix.authored, 'execute', side_effect=fixture.fake_execute))
            stack.enter_context(patch.object(matrix.authored, 'verify_png', return_value={'foreground_coverage': 0.1}))
            return matrix.capture(case, fixture.executable, self.fixture_binary, fixture.runtime, fixture.manifest,
                                  self.root, fixture.evidence, timeout=20, run_timeout=120)

    def test_capture_pass_never_claims_aggregate_acceptance(self):
        report = self.run_capture()
        self.assertTrue(report['passed'], report.get('error'))
        self.assertFalse(report['automated_matrix_passed'])
        self.assertFalse(report['acceptance_complete'])
        self.assertEqual(report['pending_gates'], ['mandatory-aggregate'])
        self.assertEqual(report['parity']['gameplay_files'], 391)
        self.assertEqual(report['binding']['game_executable_sha256'], matrix.authored.sha256(self.fixture.executable))
        self.assertNotEqual(report['binding']['game_executable_sha256'], report['binding']['renderer_contract_sha256'])
        captures = [cmd[0] for cmd in self.fixture.commands if '--capture-sequence=gameplay-return' in cmd[0]]
        self.assertEqual(len(captures), 2)
        self.assertEqual(captures[0][0], captures[1][0])
        with patch.object(matrix.pair, 'process_record', wraps=matrix.pair.process_record):
            record = matrix.inspect_shard('reload-return', self.fixture.evidence, matrix.build_identity.context(self.fixture.env))
        self.assertEqual(record['case'], 'reload-return')

    def test_very_small_anchor_difference_stays_failure(self):
        def mutate(folder, backend):
            path = folder/'0101.png.gameplay.json'
            value = '0.012370688' if backend == 'OpenGl' else '0.012370674'
            text = path.read_text().replace('"anchor": [0,', '"anchor": ['+value+',')
            path.write_text(text)
        report = self.run_capture(mutate=mutate)
        self.assertFalse(report['passed'])
        self.assertIn('anchor', report['error'])
        self.assertFalse(report['automated_matrix_passed'])

    def test_wrong_count_stops_before_second_renderer(self):
        def mutate(folder, backend):
            for path in folder.glob('0390.png*'): path.unlink()
        report = self.run_capture(mutate=mutate)
        self.assertFalse(report['passed'])
        self.assertIn('391', report['error'])
        self.assertEqual(sum('--capture-sequence=gameplay-return' in c[0] for c in self.fixture.commands), 1)

    def test_asset_mutation_fails_closed(self):
        def mutate(folder, backend): (self.root/'settings.cfg').write_text('changed')
        report = self.run_capture(mutate=mutate)
        self.assertFalse(report['passed'])
        self.assertIn('assets/settings/tools changed', report['error'])

    def test_retained_shard_payload_and_run_identity_are_required(self):
        report = self.run_capture()
        wrong = matrix.build_identity.context(self.fixture.env)
        wrong['source']['run_attempt'] = 99
        with self.assertRaisesRegex(ValueError, 'run_attempt'):
            matrix.inspect_shard('reload-return', self.fixture.evidence, wrong)
        (self.fixture.evidence/'captures/gl/reload-return/0000.png').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'payload differs'):
            matrix.inspect_shard('reload-return', self.fixture.evidence, matrix.build_identity.context(self.fixture.env))

    def test_missing_process_binding_rejected(self):
        report = self.run_capture()
        del report['processes']['gl/capture']
        matrix.authored.write_json(self.fixture.evidence/matrix.REPORT, report)
        with self.assertRaisesRegex(ValueError, 'process evidence'):
            matrix.inspect_shard('reload-return', self.fixture.evidence, matrix.build_identity.context(self.fixture.env))

    def test_final_capture_hashing_cannot_overrun_budget_and_pass(self):
        clock = [0]
        original = matrix.payload_hashes
        def exhaust(folder):
            value = original(folder)
            clock[0] = 200
            return value
        with patch.object(matrix.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(matrix, 'payload_hashes', side_effect=exhaust):
            report = self.run_capture()
        self.assertFalse(report['passed'])
        self.assertIn('budget exhausted', report['error'])

    def test_auxiliary_captures_all_lighting_and_separate_orientation_and_rechecks_fxc(self):
        helper = authored_fixtures.AuthoredDx12Tests()
        helper.setUpClass(); helper.setUp(); self.addCleanup(helper.doCleanups)
        lighting = helper.lighting_fixture()
        previous = self.fixture.fake_execute
        def auxiliary(command, root, logs, timeout, **kwargs):
            if command[-1] in ('--build-version','--build-label'):
                return previous(command, root, logs, timeout, **kwargs)
            self.fixture.commands.append((command, root, timeout, {}))
            logs.mkdir(parents=True)
            self.fixture.write(logs/'invocation.json', {'command':command,'cwd':str(root),'timeout_seconds':timeout})
            self.fixture.write(logs/'process.json', {'status':'passed','pid':12345,'exit_code':0})
            label = 'gl' if '--renderer=gl' in command else 'dx12'
            backend = matrix.BACKENDS[label]
            adapter = 'llvmpipe (LLVM 22.1.8, 256 bits)' if label == 'gl' else matrix.authored.WARP
            if any(x.startswith('--output-dir=') for x in command):
                output = Path(next(x.split('=',1)[1] for x in command if x.startswith('--output-dir=')))
                helper.orientation(output)
                path = output/'renderer-contract-report.json'
                report = json.loads(path.read_text())
                context = matrix.build_identity.context()
                report.update(build_version=context['version'], build_number=context['build_number'])
                self.fixture.write(path, report)
            else:
                output = Path(next(x.split('=',1)[1] for x in command if x.startswith('--output=')))
                for suffix in ('','.json','.world.png','.world.png.json','.lighting.json'):
                    source = lighting/(output.name+suffix)
                    target = Path(str(output)+suffix)
                    shutil.copyfile(source,target)
                    if suffix in ('.json','.world.png.json'):
                        value = json.loads(target.read_text());value.update(requested=label,backend=backend,adapter=adapter)
                        self.fixture.write(target,value)
            (logs/'stdout.log').write_text('')
            (logs/'stderr.log').write_text(f'renderer requested={label} backend={backend} adapter={adapter}\n'
                                          +(matrix.authored.FXC_LOG+'\n' if label=='dx12' else ''))
            return {'exit_code':0}
        self.fixture.fake_execute = auxiliary
        report = self.run_capture(case='auxiliary')
        self.assertTrue(report['passed'], report.get('error'))
        self.assertEqual(len([p for p in report['processes'].values() if p['native']]),25)
        self.assertEqual(report['parity']['lighting_records'],12)
        context = matrix.build_identity.context(self.fixture.env)
        matrix.inspect_shard('auxiliary', self.fixture.evidence, context)
        path = self.fixture.evidence/'logs/orientation/stderr.log'
        path.write_text(path.read_text().replace('Fxc','Dxc'))
        report['payload_sha256'] = matrix.payload_hashes(self.fixture.evidence)
        matrix.authored.write_json(self.fixture.evidence/matrix.REPORT,report)
        with self.assertRaisesRegex(ValueError,'Fxc'):
            matrix.inspect_shard('auxiliary', self.fixture.evidence, context)

    def test_retained_runtime_receipt_must_match_recorded_hash(self):
        report = self.run_capture()
        (self.fixture.evidence/'runtime/staging-receipt.json').write_text('{}')
        with self.assertRaises(ValueError):
            matrix.inspect_shard('reload-return', self.fixture.evidence, matrix.build_identity.context(self.fixture.env))

    def test_changed_recorded_command_cannot_redefine_capture_contract(self):
        report = self.run_capture()
        command = report['processes']['gl/capture']['command']
        report['processes']['gl/capture']['command'] = [c for c in command if c != '--capture-hz=60']
        matrix.authored.write_json(self.fixture.evidence/matrix.REPORT, report)
        with self.assertRaisesRegex(ValueError, 'original-command'):
            matrix.inspect_shard('reload-return', self.fixture.evidence, matrix.build_identity.context(self.fixture.env))



class AggregateOrchestrationTests(unittest.TestCase):
    """Minimal files mock capture validation; exercise mandatory real gate wiring."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.output = self.root / 'aggregate'
        self.context = {'source': {'commit': 'a'*40, 'run_id': 80, 'run_attempt': 2},
                        'version': '0.1.0', 'display_version': '0.1.0+build.80.2', 'build_number': '80.2'}
        self.assets = {'settings.cfg': 'b'*64}
        self.tools = {'fixture.py': 'c'*64}
        self.binding = {'source': self.context['source'], 'assets': self.assets, 'tool_sha256': self.tools,
                        'game_executable_sha256': 'd'*64, 'renderer_contract_sha256': 'e'*64}
        self.inputs = []
        self.roots = {}
        self.calls = []
        self.fail_gate = None
        self.omit_rate = False
        self.drift_cross_rate = False
        for name in matrix.INPUTS:
            shard = self.root / name; shard.mkdir(); self.roots[name] = shard
            self.inputs.append(f'{name}={shard}')
            for backend in matrix.BACKENDS:
                folder = shard / 'captures' / backend / ('lighting' if name == 'auxiliary' else name)
                folder.mkdir(parents=True)
                (folder/'0000.png').write_bytes(b'synthetic placeholder, image validation mocked')
                row = {'simulation_time': 0, 'pose_crc32': 1, 'walk_weight': 1, 'walk_seconds': 0,
                       'run_weight': 0, 'directional_weights': [1,0,0,0], 'ads_requested': False,
                       'sprinting': False, 'simulation_ads': 0, 'position': [0,0,0], 'velocity': [0,0,0],
                       'ammo': 30, 'shots': 0}
                (folder/'0000.png.gameplay.json').write_text(json.dumps(row))
                (folder/'verification.json').write_text(json.dumps({'schema': 'fixture-report/v1', 'passed': True, 'frames': 1}))
            if name == 'auxiliary':
                (shard/'renderer-contract').mkdir()
                (shard/'renderer-contract/renderer-contract-report.json').write_text(json.dumps({'build_version':'0.1.0','build_number':'80.2'}))
            record = {'schema': matrix.SCHEMA, 'stage': 'capture', 'case': name,
                      'passed': True, 'status': 'passed', 'native_execution': True,
                      'automated_matrix_passed': False, 'binding': self.binding,
                      'payload_sha256': matrix.payload_hashes(shard)}
            matrix.authored.write_json(shard/matrix.REPORT, record)

    def fake_validator(self, session, label, filename, folders):
        self.calls.append((label, filename, list(folders)))
        if self.fail_gate and self.fail_gate in label:
            raise ValueError('unchanged grouped validator rejected synthetic test')
        destination = session.evidence / 'logs' / label / 'stdout.log'
        destination.parent.mkdir(parents=True, exist_ok=True)
        if filename == 'verify_ads_placement_capture.py':
            value = {'schema':'rust-duty-ads-placement-capture/v1','passed':True,'frames':553}
        elif filename == 'verify_layered_locomotion_capture.py':
            captures, rows = [], []
            for rate, folder in zip((30,60), folders):
                report = {'schema': matrix.authored.LAYERED_SCHEMA, 'passed': True, 'frames': 1, 'sampling_hz': rate}
                (folder/'verification.json').write_text(json.dumps(report))
                captures.append(report)
                rows.append([json.loads((folder/'0000.png.gameplay.json').read_text())])
            if self.drift_cross_rate: rows[1][0]['pose_crc32'] += 1
            value = {'captures': captures}
            if not self.omit_rate:
                value['rate_comparison'] = matrix.authored.layered.compare_rates(*rows)
        else:
            value = {'schema':'fixture-report/v1','passed':True,'frames':1}
            (folders[0]/'verification.json').write_text(json.dumps(value))
        destination.write_text(json.dumps(value))
        return destination

    def run_aggregate(self):
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(matrix, 'current_identity', return_value=self.context))
            stack.enter_context(patch.object(matrix, 'inspect_shard', side_effect=lambda name, folder, *args: json.loads((folder/matrix.REPORT).read_text())))
            stack.enter_context(patch.object(matrix, 'tool_hashes', return_value=self.tools))
            stack.enter_context(patch.object(matrix.pair, 'input_hashes', return_value=self.assets))
            stack.enter_context(patch.object(matrix.authored, 'asset_evidence', return_value={'runtime_and_manifest_sha256': self.assets}))
            stack.enter_context(patch.object(matrix, 'orientation_build_identity', return_value={'fixture':True}))
            stack.enter_context(patch.object(matrix, 'validate_sequence', return_value={'synthetic_images':True}))
            stack.enter_context(patch.object(matrix, 'validate_lighting', return_value={'synthetic_lighting':True}))
            stack.enter_context(patch.object(matrix, 'exact_lighting', return_value={'passed':True}))
            stack.enter_context(patch.object(matrix.authored, 'compare_sequence', return_value={'passed':True}))
            stack.enter_context(patch.object(matrix, 'review_outputs', return_value={'status':'open'}))
            stack.enter_context(patch.object(matrix.Session, 'validator', new=lambda session, label, filename, folders: self.fake_validator(session,label,filename,folders)))
            return matrix.aggregate(self.inputs, self.root, self.output, timeout=30, run_timeout=120)

    def test_all_grouped_gates_mandatory_and_exact_totals(self):
        report = self.run_aggregate()
        self.assertTrue(report['passed'], report.get('error'))
        self.assertTrue(report['automated_matrix_passed'])
        self.assertFalse(report['acceptance_complete'])
        self.assertFalse(report['native_execution'])  # Aggregation rendered nothing.
        self.assertEqual(report['frames_per_backend'], 3347)
        self.assertEqual(report['lighting_poses_per_backend'], 12)
        self.assertEqual(set(report['parity']), set(matrix.COUNTS))
        self.assertEqual(report['pending_gates'], [])
        self.assertEqual(len(self.calls), 16)  # Six per-case + two grouped, per backend.
        for backend in matrix.BACKENDS:
            pair_calls = [c for c in self.calls if c[0] == backend+'/layered-cross-rate']
            self.assertEqual(len(pair_calls), 1)
            self.assertEqual([p.name for p in pair_calls[0][2]], ['layered-30','layered-60'])
            placement = [c for c in self.calls if c[0] == backend+'/ads-placement']
            self.assertEqual([p.name for p in placement[0][2]], ['ads-gameplay','ads-offset'])
        checks = {c['name'] for c in report['checks']}
        for required in ('orientation-existing-validator','gl/layered-verdict-binding',
                         'dx12/layered-verdict-binding','gl/lighting-existing-validator',
                         'dx12/lighting-existing-validator','lighting/strict-all-field-parity'):
            self.assertIn(required, checks)

    def test_missing_case_is_not_partial_aggregate_success(self):
        self.inputs.pop()
        with self.assertRaisesRegex(ValueError, 'all eight'): self.run_aggregate()
        self.assertFalse(self.output.exists())

    def test_different_binary_or_source_across_shards_rejected(self):
        path = self.roots['walk-gameplay']/matrix.REPORT
        value = json.loads(path.read_text()); value['binding']['game_executable_sha256'] = 'f'*64
        path.write_text(json.dumps(value))
        report = self.run_aggregate()
        self.assertFalse(report['passed'])
        self.assertIn('game_executable_sha256', report['error'])
        self.assertFalse(self.calls)

    def test_ads_group_failure_cannot_be_skipped(self):
        self.fail_gate = 'ads-placement'
        report = self.run_aggregate()
        self.assertFalse(report['passed'])
        self.assertFalse(report['automated_matrix_passed'])
        self.assertIn('grouped validator', report['error'])

    def test_layered_stdout_must_contain_real_rate_comparison(self):
        self.omit_rate = True
        report = self.run_aggregate()
        self.assertFalse(report['passed'])
        self.assertIn('rate comparison', report['error'])

    def test_unchanged_cross_rate_comparator_rejects_committed_pose_drift(self):
        self.drift_cross_rate = True
        report = self.run_aggregate()
        self.assertFalse(report['passed'])
        self.assertIn('changed committed output', report['error'])

    def test_final_aggregate_retention_hashing_cannot_overrun_budget_and_pass(self):
        clock = [0]
        original = matrix.payload_hashes
        def exhaust(folder):
            value = original(folder)
            clock[0] = 200
            return value
        with patch.object(matrix.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(matrix, 'payload_hashes', side_effect=exhaust):
            report = self.run_aggregate()
        self.assertFalse(report['passed'])
        self.assertFalse(report['automated_matrix_passed'])
        self.assertIn('budget exhausted', report['error'])


if __name__ == '__main__':
    unittest.main()
