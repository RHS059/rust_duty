"""Paired shard controls using synthetic bytes and mocked native processes only.

No test runs Cargo or either renderer. Image/identity/input checks use their real
validators; orchestration tests mock image generation and existing validators so
that these controls cannot be mistaken for native Windows acceptance evidence.
"""

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

import dx12_authored_shards as shared
import run_dx12_authored as authored
import run_dx12_authored_shard as shard
from test_dx12_authored_shards import make_gl_runtime


ENV = {
    'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '1234', 'GITHUB_RUN_ATTEMPT': '2',
    'RUNNER_NAME': 'synthetic-windows-runner', 'RUNNER_OS': 'Windows', 'RUNNER_ARCH': 'X64',
}
GL_ADAPTER = 'llvmpipe (synthetic unit fixture)'


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=False) + '\n', encoding='utf-8')


def png_bytes(*, extent=authored.EXTENT, uniform=False, sparse=False):
    image = Image.new('RGBA', extent, authored.BACKGROUND)
    if not uniform:
        rectangle = (1, 1, 2, 2) if sparse else (extent[0] // 4, extent[1] // 4,
                                                 extent[0] * 3 // 4, extent[1] * 3 // 4)
        ImageDraw.Draw(image).rectangle(rectangle, fill=(120, 90, 60, 255))
    stream = io.BytesIO()
    image.save(stream, format='PNG')
    return stream.getvalue()


def make_sequence(folder, role, count=3):
    """Small synthetic fixtures for real role validation, never authored replays."""
    folder.mkdir(parents=True)
    image = png_bytes()
    for index in range(count):
        target = folder / f'{index:04}.png'
        target.write_bytes(image)
        write_json(Path(f'{target}.json'), {
            'backend': 'OpenGl' if role == 'windows-legacy' else 'Dx12',
            'requested': 'gl' if role == 'windows-legacy' else 'dx12',
            'adapter': GL_ADAPTER if role == 'windows-legacy' else authored.WARP,
            'width': 960, 'height': 540,
        })
        write_json(Path(f'{target}.time.json'), {'elapsed_seconds': index / 60, 'sampling_hz': 60})
        write_json(Path(f'{target}.gameplay.json'), {'simulation_time': index / 60, 'renderer_failed': False})
    return folder


def write_logs(folder, identity, extra=''):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'stdout.log').write_text('synthetic process\n' + identity + '\n', encoding='utf-8')
    (folder / 'stderr.log').write_text(extra, encoding='utf-8')
    return folder


class FixtureCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / 'root'
        self.root.mkdir()
        (self.root / 'assets').mkdir()
        (self.root / 'assets/animations.cfg').write_text('synthetic manifest\n', encoding='utf-8')
        (self.root / 'settings.cfg').write_text('fov = 90\n', encoding='utf-8')
        (self.root / 'Cargo.toml').write_text('[package]\nname = "synthetic"\n', encoding='utf-8')
        (self.root / 'Cargo.lock').write_text('version = 4\n', encoding='utf-8')
        self.executable = self.root / 'game.exe'
        self.fixture = self.root / 'renderer-contract.exe'
        self.executable.write_bytes(b'synthetic dual-runtime binary')
        self.fixture.write_bytes(b'synthetic renderer fixture binary')
        self.evidence = self.base / 'evidence'
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, ENV))
        self.stack.enter_context(patch.object(authored, 'asset_evidence', side_effect=self.asset_evidence))
        make_gl_runtime(self.root)
        self.manifest = shared.make_input_manifest(self.executable, self.fixture, self.root)
        self.manifest_path = self.base / 'input-manifest.json'
        write_json(self.manifest_path, self.manifest)

    @staticmethod
    def asset_evidence(root):
        # Replace only the expensive committed generated-asset verifier. Shared
        # manifest hashing, schema, typing and before/after verification stay real.
        paths = [root / 'settings.cfg', *sorted((root / 'assets').rglob('*'))]
        return {'runtime_and_manifest_sha256': {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths if path.is_file()
        }}

    def windows(self):
        return patch.object(shard.sys, 'platform', 'win32')

    def saved_report(self):
        return json.loads((self.evidence / 'summary.json').read_text(encoding='utf-8'))


class RoleCommandTests(FixtureCase):
    def test_gl_is_exact_existing_command_with_explicit_renderer_and_no_fallback(self):
        offset = self.evidence / 'ads-offset.cfg'
        for case in authored.CASES:
            with self.subTest(scenario=case.name):
                folder = self.evidence / shared.capture_paths(case.name)['windows-legacy']
                expected = authored.game_command(self.executable, self.root, folder, case, offset)
                expected[expected.index('--renderer=dx12')] = '--renderer=gl'
                expected.remove('--force-fallback-adapter')
                command = shard.role_command(self.executable, self.root, folder, case, offset, 'windows-legacy')
                self.assertEqual(command, expected)
                self.assertEqual(command.count('--renderer=gl'), 1)
                self.assertNotIn('--force-fallback-adapter', command)
                self.assertNotIn('--renderer=dx12', command)

    def test_dx12_command_and_sample_rate_default_omissions_are_unchanged(self):
        for case in authored.CASES:
            with self.subTest(scenario=case.name):
                folder = self.evidence / shared.capture_paths(case.name)['dx12']
                offset = self.evidence / 'ads-offset.cfg'
                command = shard.role_command(self.executable, self.root, folder, case, offset, 'dx12')
                self.assertEqual(command, authored.game_command(self.executable, self.root, folder, case, offset))
                self.assertIn('--force-fallback-adapter', command)
                rates = [argument for argument in command if argument.startswith('--capture-hz=')]
                self.assertEqual(rates, [] if case.hz is None else [f'--capture-hz={case.hz}'])
                self.assertEqual([a for a in command if a.startswith('--settings=')],
                                 [f'--settings={offset}'] if case.name == 'ads-offset' else [])

    def test_renderer_rewrite_preserves_paths_containing_renderer_flag_text(self):
        executable = self.root / 'game--renderer=dx12.exe'
        root = self.root / 'assets--renderer=dx12'
        output = self.evidence / 'capture--renderer=dx12'
        offset = self.evidence / 'settings--renderer=dx12.cfg'
        case = next(case for case in authored.CASES if case.name == 'ads-offset')
        expected = authored.game_command(executable, root, output, case, offset)
        expected[expected.index('--renderer=dx12')] = '--renderer=gl'
        expected.remove('--force-fallback-adapter')
        self.assertEqual(shard.role_command(executable, root, output, case, offset, 'windows-legacy'), expected)

    def test_unknown_role_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'role'):
            shard.role_command(self.executable, self.root, self.evidence, authored.CASES[0], self.evidence, 'auto')

    def test_timeout_profiles_retain_full_frames_and_twenty_minute_headroom(self):
        expected = {
            'jump-gameplay': (403, 2100, 3300), 'reload-gameplay': (214, 1200, 2400),
            'walk-gameplay': (223, 1500, 2700), 'ads-gameplay': (553, 3000, 4200),
            'ads-offset': (553, 3000, 4200), 'layered-30': (337, 2100, 3300),
            'layered-60': (673, 3900, 5100), 'reload-return': (391, 1800, 3000),
        }
        for scenario, values in expected.items():
            with self.subTest(scenario=scenario):
                profile = shared.PROFILES[scenario]
                self.assertEqual(tuple(profile[key] for key in
                                       ('expected_frames', 'capture_timeout_seconds', 'run_timeout_seconds')), values)
                self.assertEqual(profile['run_timeout_seconds'] - profile['capture_timeout_seconds'], 20 * 60)
        self.assertEqual((shard.LEGACY_TIMEOUT, shard.STOCK_TIMEOUT, shard.VALIDATOR_TIMEOUT), (900, 120, 900))

    def test_required_checks_are_exact_closed_and_ordered(self):
        for case in authored.CASES:
            expected = ['validated-inputs', 'windows-legacy/stock-probe']
            expected += [f'{role}/{stage}' for role in ('windows-legacy', 'dx12')
                         for stage in ('capture', 'finite-images', 'existing-validator')]
            expected += ['layered-pair-deferred-to-aggregate' if case.name.startswith('layered-')
                         else 'same-windows-strict-parity', 'inputs-unchanged']
            with self.subTest(scenario=case.name):
                self.assertEqual(shard.required_checks(case.name), expected)
        stems = [stem for stem, _ in authored.lighting_commands(self.executable, self.root, self.evidence)]
        self.assertEqual(len(stems), 12)
        self.assertEqual(shard.required_checks('lighting-orientation'),
                         ['validated-inputs', 'orientation-renderer-contract'] +
                         [f'lighting/{stem}' for stem in stems] +
                         ['lighting-existing-validator-and-images', 'inputs-unchanged'])


class RoleValidationTests(FixtureCase):
    def test_legacy_logs_accept_real_nonblank_consistent_adapter_from_both_streams(self):
        identity = f'renderer requested=gl backend=OpenGl adapter={GL_ADAPTER}'
        logs = write_logs(self.base / 'logs', identity, identity + '\n')
        result = shard.legacy_renderer_logs(logs)
        self.assertEqual(result['adapter'], GL_ADAPTER)
        self.assertEqual(result['renderer'], [identity, identity])

    def test_legacy_logs_reject_missing_invented_or_inconsistent_identity(self):
        good = f'renderer requested=gl backend=OpenGl adapter={GL_ADAPTER}'
        cases = ('', 'renderer requested=auto backend=OpenGl adapter=GPU',
                 'renderer requested=gl backend=Vulkan adapter=GPU',
                 'renderer requested=gl backend=OpenGl adapter=   ',
                 good + '\nrenderer requested=gl backend=OpenGl adapter=Another GPU',
                 good + '\nrenderer requested=dx12 backend=Dx12 adapter=' + authored.WARP)
        for number, identity in enumerate(cases):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                shard.legacy_renderer_logs(write_logs(self.base / f'logs-{number}', identity))

    def test_real_role_validators_check_every_frame(self):
        for role in shard.ROLES:
            with self.subTest(role=role):
                folder = make_sequence(self.base / role, role)
                result = shard.validate_role_images(folder, role, 3)
                self.assertEqual(result['frames'], 3)
                self.assertIs(result['all_images_checked'], True)
                self.assertGreater(result['minimum_foreground_coverage'], 0.01)
                self.assertEqual(result['adapter'], GL_ADAPTER if role == 'windows-legacy' else authored.WARP)

    def test_exact_positive_integer_frame_count_is_required(self):
        folder = make_sequence(self.base / 'frames', 'windows-legacy')
        for expected in (0, -1, True, 3.0, '3', 2, 4):
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                shard.validate_role_images(folder, 'windows-legacy', expected)
        with self.assertRaisesRegex(ValueError, 'role'):
            shard.validate_role_images(folder, 'gl', 3)

    def test_role_metadata_request_backend_adapter_and_extent_are_strict(self):
        for role in shard.ROLES:
            folder = make_sequence(self.base / role, role)
            path = folder / '0001.png.json'
            original = path.read_bytes()
            mutations = [('requested', 'auto'), ('backend', 'Vulkan'), ('adapter', ' '),
                         ('width', 1), ('width', 960.0), ('height', True)]
            if role == 'windows-legacy':
                mutations.append(('adapter', 'Different actual OpenGL adapter'))
            else:
                mutations.append(('adapter', 'Discrete hardware adapter'))
            for field, value in mutations:
                with self.subTest(role=role, field=field, value=value):
                    row = json.loads(original)
                    row[field] = value
                    write_json(path, row)
                    with self.assertRaises(ValueError):
                        shard.validate_role_images(folder, role, 3)
                    path.write_bytes(original)

    def test_missing_sidecars_orphan_frames_and_nonfinite_json_fail(self):
        folder = make_sequence(self.base / 'capture', 'windows-legacy')
        for suffix in ('', '.json', '.time.json', '.gameplay.json'):
            path = folder / f'0001.png{suffix}'
            original = path.read_bytes()
            path.unlink()
            with self.subTest(missing=suffix), self.assertRaises(ValueError):
                shard.validate_role_images(folder, 'windows-legacy', 3)
            path.write_bytes(original)
        for name in ('9999.png.gameplay.json', 'unexpected.txt'):
            path = folder / name
            path.write_text('{"synthetic":true}', encoding='utf-8')
            with self.subTest(unexpected=name), self.assertRaises(ValueError):
                shard.validate_role_images(folder, 'windows-legacy', 3)
            path.unlink()
        path = folder / '0001.png.gameplay.json'
        for raw in ('{"value":NaN}', '{"value":1e9999}', '{"value":1,"value":1}'):
            path.write_text(raw, encoding='utf-8')
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                shard.validate_role_images(folder, 'windows-legacy', 3)

    def test_unsampled_middle_png_corruption_uniform_sparse_and_wrong_extent_fail(self):
        folder = make_sequence(self.base / 'capture', 'windows-legacy')
        path = folder / '0001.png'
        cases = (png_bytes()[:-1], png_bytes(uniform=True), png_bytes(sparse=True),
                 png_bytes(extent=(480, 270)))
        for number, data in enumerate(cases):
            path.write_bytes(data)
            with self.subTest(control=number), self.assertRaises(ValueError):
                shard.validate_role_images(folder, 'windows-legacy', 3)

    def stock_fixture(self):
        folder = self.base / 'stock'
        folder.mkdir()
        (folder / 'stock-gl.png').write_bytes(png_bytes())
        write_json(folder / 'stock-gl.png.json', {
            'backend': 'OpenGl', 'requested': 'gl', 'adapter': GL_ADAPTER, 'width': 960, 'height': 540,
        })
        return folder

    def test_stock_probe_requires_explicit_gl_log_sidecar_agreement_and_image_guard(self):
        folder = self.stock_fixture()
        self.assertEqual(shard.validate_stock_probe(folder, GL_ADAPTER)['adapter'], GL_ADAPTER)
        with self.assertRaisesRegex(ValueError, 'adapters differ'):
            shard.validate_stock_probe(folder, 'Different logged adapter')
        path = folder / 'stock-gl.png.json'
        original = path.read_bytes()
        for field, value in [('requested', 'auto'), ('backend', 'Dx12'), ('width', 480), ('adapter', '')]:
            row = json.loads(original)
            row[field] = value
            write_json(path, row)
            with self.subTest(field=field), self.assertRaises(ValueError):
                shard.validate_stock_probe(folder)
            path.write_bytes(original)
        (folder / 'stock-gl.png').write_bytes(png_bytes(uniform=True))
        with self.assertRaisesRegex(ValueError, 'uniform'):
            shard.validate_stock_probe(folder)


class PreparationTests(FixtureCase):
    def test_platform_gate_precedes_any_preparation_or_run_work(self):
        with patch.object(shard.sys, 'platform', 'linux'), \
                patch.object(shared, 'make_input_manifest') as make, \
                patch.object(shard, 'Journal') as journal:
            with self.assertRaisesRegex(ValueError, 'Windows'):
                shard.prepare(self.executable, self.fixture, self.root, self.base / 'historical', self.evidence)
            with self.assertRaisesRegex(ValueError, 'Windows'):
                shard.run_shard(self.executable, self.fixture, self.root, self.evidence, self.manifest, 'jump-gameplay')
            make.assert_not_called()
            journal.assert_not_called()
            self.assertFalse(self.evidence.exists())

    def test_preparation_binds_shared_inputs_and_historical_receipt(self):
        historical = {'schema': 'rust-duty-dx12-authored-historical/v1', **shared.context(), 'files': {'raw': 'b' * 64}}
        with self.windows(), patch.object(shard, 'historical_manifest', return_value=historical) as historical_check:
            result = shard.prepare(self.executable, self.fixture, self.root, self.base / 'historical', self.evidence)
        self.assertEqual(result, self.manifest)
        self.assertEqual(json.loads((self.evidence / 'input-manifest.json').read_text()), self.manifest)
        self.assertEqual(json.loads((self.evidence / 'historical-manifest.json').read_text()), historical)
        historical_check.assert_called_once_with(self.base / 'historical')
        self.assertFalse((self.evidence / 'failure.json').exists())

    def test_existing_preparation_is_never_overwritten(self):
        self.evidence.mkdir()
        sentinel = self.evidence / 'original.txt'
        sentinel.write_bytes(b'keep')
        with self.windows(), patch.object(shared, 'make_input_manifest') as make:
            with self.assertRaisesRegex(ValueError, 'existing'):
                shard.prepare(self.executable, self.fixture, self.root, self.base / 'historical', self.evidence)
        make.assert_not_called()
        self.assertEqual(list(self.evidence.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_bytes(), b'keep')

    def test_preparation_error_and_interruption_leave_durable_failure(self):
        for number, error in enumerate((ValueError('bad historical input'), KeyboardInterrupt('cancelled'))):
            evidence = self.base / f'failed-{number}'
            with self.windows(), patch.object(shard, 'historical_manifest', side_effect=error):
                with self.subTest(error=type(error).__name__), self.assertRaises(type(error)):
                    shard.prepare(self.executable, self.fixture, self.root, self.base / 'historical', evidence)
            row = json.loads((evidence / 'failure.json').read_text())
            self.assertIs(row['passed'], False)
            self.assertIn(type(error).__name__, row['error'])

    def test_historical_receipt_requires_every_full_sequence_and_existing_verdict(self):
        historical = self.base / 'historical'
        historical.mkdir()
        (historical / 'bound.txt').write_text('source artifact bytes', encoding='utf-8')
        calls = []

        def sequence(folder, backend):
            case = next(case for case in authored.CASES if folder == historical / case.baseline)
            calls.append((case.name, backend))
            return [folder / f'{i:04}.png' for i in range(shared.PROFILES[case.name]['expected_frames'])], {}

        with patch.object(authored, 'sequence_inventory', side_effect=sequence), \
                patch.object(authored, 'baseline_verdicts', return_value=['verification.json']) as verdicts:
            result = shard.historical_manifest(historical)
        self.assertEqual(calls, [(case.name, 'OpenGl') for case in authored.CASES])
        self.assertEqual(verdicts.call_count, len(authored.CASES))
        self.assertEqual(result, {'schema': 'rust-duty-dx12-authored-historical/v1', **shared.context(),
                                  'files': shared.inventory_files(historical, exclude=())})
        with patch.object(authored, 'sequence_inventory', return_value=([Path('0000.png')], {})), \
                patch.object(authored, 'baseline_verdicts') as verdicts:
            with self.assertRaisesRegex(ValueError, 'incomplete baseline frame count'):
                shard.historical_manifest(historical)
            verdicts.assert_not_called()


class JournalTests(FixtureCase):
    def make_journal(self, budget=10):
        self.evidence.mkdir()
        self.clock = [0.0]
        self.stack.enter_context(patch.object(shard.time, 'monotonic', side_effect=lambda: self.clock[0]))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        report = {'run_timeout_seconds': budget, 'checks': [], 'status': 'running',
                  'current_check': None, 'budget_exhausted': False}
        return shard.Journal(self.evidence, report)

    def test_check_writes_current_work_before_call_and_final_result_after(self):
        journal = self.make_journal()

        def action():
            saved = self.saved_report()
            self.assertEqual(saved['current_check'], 'test-check')
            self.assertEqual(saved['checks'], [])
            self.clock[0] = 2
            return {'synthetic': True}

        row = journal.check('test-check', action)
        self.assertIs(row['passed'], True)
        self.assertEqual(row['elapsed_seconds'], 2)
        self.assertIsNone(self.saved_report()['current_check'])
        self.assertEqual(self.saved_report()['checks'], [row])

    def test_failed_check_records_exception_without_stopping_independent_work(self):
        journal = self.make_journal()
        first = journal.check('bad', Mock(side_effect=ValueError('bad data')))
        second = journal.check('independent', lambda: 7)
        self.assertIs(first['passed'], False)
        self.assertIn('ValueError: bad data', first['error'])
        self.assertIs(second['passed'], True)
        self.assertEqual([row['name'] for row in self.saved_report()['checks']], ['bad', 'independent'])

    def test_blocked_check_does_not_run(self):
        journal = self.make_journal()
        action = Mock()
        row = journal.check('blocked', action, ready=False)
        action.assert_not_called()
        self.assertIs(row['passed'], False)
        self.assertIn('blocked', row['error'])

    def test_exhausted_budget_never_launches_a_new_check(self):
        journal = self.make_journal()
        self.clock[0] = 10
        action = Mock()
        row = journal.check('late', action)
        action.assert_not_called()
        self.assertIs(row['passed'], False)
        self.assertIs(self.saved_report()['budget_exhausted'], True)
        self.assertIn('deadline exhausted', row['error'])

    def test_completion_at_or_after_deadline_is_not_a_pass(self):
        journal = self.make_journal()

        def action():
            self.clock[0] = 10
            return {'looks_successful': True}

        row = journal.check('late-result', action)
        self.assertIs(row['passed'], False)
        self.assertIn('after whole-shard deadline', row['error'])
        self.assertIs(self.saved_report()['budget_exhausted'], True)

    def test_execute_clamps_timeout_to_remaining_whole_shard_budget(self):
        journal = self.make_journal()
        self.clock[0] = 7
        with patch.object(authored, 'execute', return_value={'exit_code': 0}) as execute:
            result = journal.execute(['native'], self.root, self.evidence / 'logs', 900, renderer=True)
            execute.assert_called_once_with(['native'], self.root, self.evidence / 'logs', 3, renderer=True)
            self.assertEqual(result, {'exit_code': 0})
            self.clock[0] = 10
            with self.assertRaisesRegex(ValueError, 'deadline exhausted'):
                journal.execute(['native'], self.root, self.evidence / 'logs', 900)
            self.assertEqual(execute.call_count, 1)

    def test_interruption_is_saved_and_propagated(self):
        journal = self.make_journal()
        with self.assertRaises(KeyboardInterrupt):
            journal.check('interrupted', Mock(side_effect=KeyboardInterrupt('stop')))
        saved = self.saved_report()
        self.assertEqual(saved['status'], 'interrupted')
        self.assertEqual(saved['checks'][0]['name'], 'interrupted')
        self.assertIs(saved['checks'][0]['passed'], False)
        self.assertIn('KeyboardInterrupt', saved['checks'][0]['error'])


class ShardRunTests(FixtureCase):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(self.windows())
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.calls = []
        self.failures = {}
        self.after_process = None
        self.stack.enter_context(patch.object(authored, 'execute', side_effect=self.native_process_double))
        self.stock = self.stack.enter_context(patch.object(shard, 'validate_stock_probe',
                                      return_value={'adapter': GL_ADAPTER, 'image': {'passed': True}}))
        self.images = self.stack.enter_context(patch.object(shard, 'validate_role_images', side_effect=self.images_double))
        self.parity = self.stack.enter_context(patch.object(authored, 'compare_sequence', return_value={'passed': True}))
        self.orientation = self.stack.enter_context(patch.object(authored, 'validate_orientation', return_value={'passed': True}))
        self.lighting = self.stack.enter_context(patch.object(authored, 'validate_lighting', return_value={'passed': True}))

    def native_process_double(self, command, root, logs, timeout, *, renderer=False):
        """Retain synthetic execution receipts; intentionally generate no native captures."""
        self.calls.append({'command': command, 'root': root, 'logs': logs,
                           'timeout': timeout, 'renderer': renderer})
        gl = '--renderer=gl' in command
        identity = f'renderer requested=gl backend=OpenGl adapter={GL_ADAPTER}' if gl else \
            f'renderer requested=dx12 backend=Dx12 adapter={authored.WARP}'
        write_logs(logs, identity, '' if gl else authored.FXC_LOG + '\n')
        write_json(logs / 'invocation.json', {'command': command, 'cwd': str(root), 'timeout_seconds': timeout})
        write_json(logs / 'process.json', {'schema': 'synthetic-process-only/v1', 'status': 'passed', 'exit_code': 0})
        if self.after_process:
            self.after_process(logs.name)
        if logs.name in self.failures:
            raise self.failures[logs.name]
        return {'exit_code': 0, **(authored.renderer_logs(logs) if renderer else {})}

    @staticmethod
    def images_double(folder, role, expected_frames):
        return {'frames': expected_frames, 'all_images_checked': True,
                'adapter': GL_ADAPTER if role == 'windows-legacy' else authored.WARP}

    def run_case(self, scenario='jump-gameplay', **kwargs):
        return shard.run_shard(self.executable, self.fixture, self.root, self.evidence,
                               kwargs.pop('manifest', self.manifest_path), scenario, **kwargs)

    @staticmethod
    def by_name(report):
        return {row['name']: row for row in report['checks']}

    def assert_closed(self, report, scenario):
        self.assertEqual([row['name'] for row in report['checks']], shard.required_checks(scenario))
        self.assertIs(report['acceptance_complete'], False)
        self.assertEqual(report['automated_landmark_gate'], 'open')
        self.assertIsNone(report['current_check'])
        self.assertEqual(report, self.saved_report())
        self.assertEqual(report['files'], shared.inventory_files(self.evidence))
        self.assertNotIn('summary.json', report['files'])

    def test_full_pair_uses_stock_first_separate_native_budgets_and_exact_contract(self):
        report = self.run_case()
        self.assertIs(report['passed'], True)
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['binding'], self.manifest['binding'])
        self.assertEqual(report['platform'], 'win32')
        self.assertEqual(report['host'], {'runner_name': ENV['RUNNER_NAME'], 'runner_os': 'Windows', 'runner_arch': 'X64'})
        self.assertEqual(report['run_timeout_seconds'], 3300)
        self.assert_closed(report, 'jump-gameplay')
        self.assertEqual([(row['logs'].name, row['timeout'], row['renderer']) for row in self.calls], [
            ('windows-legacy-stock-probe', 120, False), ('windows-legacy-capture', 900, False),
            ('windows-legacy-validator', 900, False), ('dx12-capture', 2100, True), ('dx12-validator', 900, False),
        ])
        self.assertEqual(self.calls[0]['command'], [str(self.evidence / 'gl-runtime/vector-range.exe'), '--renderer=gl', '--no-update',
            '--procedural-weapon', '--reference-viewport', '--capture', f'--output={self.evidence / "stock-gl/stock-gl.png"}'])
        self.stock.assert_called_once_with(self.evidence / 'stock-gl', GL_ADAPTER)
        self.assertEqual([call.args[2] for call in self.images.call_args_list], [403, 403])
        paths = shared.capture_paths('jump-gameplay')
        self.parity.assert_called_once_with(self.evidence / paths['windows-legacy'], self.evidence / paths['dx12'])
        for call in self.calls:
            self.assertEqual(call['root'], self.root)
            self.assertFalse(any('headless' in str(argument) for argument in call['command']))

    def test_native_environment_is_scoped_and_runtime_mutation_cannot_pass(self):
        observed = []
        def mutate(log_name):
            observed.append({key: os.environ.get(key) for key in shared.GL_ENVIRONMENT})
            if log_name == 'dx12-capture':
                (self.evidence/'gl-runtime/opengl32.dll').write_bytes(b'changed')
        self.after_process = mutate
        with patch.dict(os.environ, {'GALLIUM_DRIVER':'previous','LIBGL_ALWAYS_SOFTWARE':'previous'}):
            report = self.run_case()
            self.assertEqual(os.environ['GALLIUM_DRIVER'],'previous')
            self.assertEqual(os.environ['LIBGL_ALWAYS_SOFTWARE'],'previous')
        self.assertTrue(observed)
        self.assertTrue(all(row == shared.GL_ENVIRONMENT for row in observed))
        self.assertFalse(report['passed'])
        self.assertFalse(self.by_name(report)['inputs-unchanged']['passed'])

    def test_runtime_inventory_sealing_cannot_exceed_whole_run_budget_and_pass(self):
        clock = [0.0]
        original = shared.inventory_files
        def inventory(folder, *args, **kwargs):
            result = original(folder,*args,**kwargs)
            if folder == self.evidence: clock[0] = 11
            return result
        with patch.object(shard.time,'monotonic',side_effect=lambda:clock[0]), \
                patch.object(shared,'inventory_files',side_effect=inventory):
            report = self.run_case(run_timeout=10)
        self.assertFalse(report['passed'])
        self.assertTrue(report['budget_exhausted'])

    def test_both_ads_roles_use_identical_offset_file_and_no_rate_override(self):
        self.run_case('ads-offset')
        capture_calls = [row for row in self.calls if row['logs'].name.endswith('-capture')]
        expected_offset = self.evidence / 'ads-offset.cfg'
        self.assertEqual(expected_offset.read_text(),
                         (self.root / 'settings.cfg').read_text() +
                         '\nviewmodel_x = 0.20\nviewmodel_y = -0.20\nviewmodel_z = 0.20\n')
        for row in capture_calls:
            self.assertEqual([a for a in row['command'] if a.startswith('--settings=')], [f'--settings={expected_offset}'])
            self.assertFalse(any(a.startswith('--capture-hz=') for a in row['command']))
        self.assertEqual([call.args[2] for call in self.images.call_args_list], [553, 553])
        self.assertEqual([row['timeout'] for row in capture_calls], [900, 3000])

    def test_layered_single_rate_only_defers_cross_rate_parity_to_aggregate(self):
        report = self.run_case('layered-60')
        self.assert_closed(report, 'layered-60')
        self.assertIs(report['passed'], True)
        row = self.by_name(report)['layered-pair-deferred-to-aggregate']
        self.assertEqual(row['result'], {'rates': ['layered-30', 'layered-60']})
        self.parity.assert_not_called()
        self.assertEqual([call.args[2] for call in self.images.call_args_list], [673, 673])
        validators = [row for row in self.calls if row['logs'].name.endswith('-validator')]
        self.assertEqual(len(validators), 2)
        for row in validators:
            self.assertEqual(Path(row['command'][1]).name, 'verify_layered_locomotion_capture.py')
            self.assertEqual(len(row['command']), 3)

    def test_stock_failure_blocks_legacy_but_still_attempts_independent_dx12(self):
        self.failures['windows-legacy-stock-probe'] = RuntimeError('native GL unavailable')
        report = self.run_case()
        self.assert_closed(report, 'jump-gameplay')
        self.assertIs(report['passed'], False)
        rows = self.by_name(report)
        self.assertFalse(rows['windows-legacy/stock-probe']['passed'])
        for stage in ('capture', 'finite-images', 'existing-validator'):
            self.assertFalse(rows[f'windows-legacy/{stage}']['passed'])
            self.assertTrue(rows[f'dx12/{stage}']['passed'])
        self.assertFalse(rows['same-windows-strict-parity']['passed'])
        self.assertTrue(rows['inputs-unchanged']['passed'])
        self.assertEqual([row['logs'].name for row in self.calls],
                         ['windows-legacy-stock-probe', 'dx12-capture', 'dx12-validator'])
        self.parity.assert_not_called()

    def test_stock_image_validation_failure_still_allows_independent_dx12(self):
        self.stock.side_effect = ValueError('stock PNG is blank')
        report = self.run_case()
        self.assert_closed(report, 'jump-gameplay')
        rows = self.by_name(report)
        self.assertFalse(report['passed'])
        self.assertIn('stock PNG is blank', rows['windows-legacy/stock-probe']['error'])
        self.assertFalse(rows['windows-legacy/capture']['passed'])
        self.assertTrue(rows['dx12/existing-validator']['passed'])
        self.parity.assert_not_called()

    def test_timeout_leaves_partial_diagnostics_and_independent_role_runs(self):
        self.failures['windows-legacy-capture'] = subprocess.TimeoutExpired('synthetic renderer', 900)
        report = self.run_case()
        self.assert_closed(report, 'jump-gameplay')
        rows = self.by_name(report)
        self.assertIs(report['passed'], False)
        self.assertIn('TimeoutExpired', rows['windows-legacy/capture']['error'])
        self.assertFalse(rows['windows-legacy/finite-images']['passed'])
        self.assertFalse(rows['windows-legacy/existing-validator']['passed'])
        self.assertTrue(rows['dx12/capture']['passed'])
        self.assertTrue(rows['dx12/existing-validator']['passed'])
        self.assertIn('logs/windows-legacy-capture/invocation.json', report['files'])
        self.parity.assert_not_called()

    def test_legacy_log_sidecar_adapter_disagreement_fails_before_validator(self):
        self.images.side_effect = lambda folder, role, count: {
            'frames': count, 'all_images_checked': True,
            'adapter': 'Different actual adapter' if role == 'windows-legacy' else authored.WARP}
        report = self.run_case()
        rows = self.by_name(report)
        self.assertFalse(rows['windows-legacy/finite-images']['passed'])
        self.assertIn('log and capture adapters differ', rows['windows-legacy/finite-images']['error'])
        self.assertFalse(rows['windows-legacy/existing-validator']['passed'])
        self.assertTrue(rows['dx12/existing-validator']['passed'])
        self.parity.assert_not_called()

    def test_wrong_dx12_actual_identity_fails_existing_renderer_log_gate(self):
        def corrupt(log_name):
            if log_name == 'dx12-capture':
                (self.evidence / 'logs/dx12-capture/stderr.log').write_text('renderer dx12_shader_compiler=Dxc\n')
        self.after_process = corrupt
        report = self.run_case()
        row = self.by_name(report)['dx12/capture']
        self.assertFalse(row['passed'])
        self.assertIn('Fxc', row['error'])
        self.assertFalse(report['passed'])
        self.parity.assert_not_called()

    def test_existing_validator_or_exact_parity_failure_cannot_pass(self):
        self.failures['windows-legacy-validator'] = RuntimeError('existing validator failed')
        report = self.run_case()
        self.assertFalse(report['passed'])
        self.assertTrue(self.by_name(report)['dx12/existing-validator']['passed'])
        self.parity.assert_not_called()
        self.evidence = self.base / 'strict-parity-failure'
        self.failures.clear()
        self.parity.side_effect = ValueError('0001.png.time.json exact numeric value differs')
        report = self.run_case()
        self.assert_closed(report, 'jump-gameplay')
        self.assertFalse(report['passed'])
        self.assertIn('exact numeric value differs', self.by_name(report)['same-windows-strict-parity']['error'])

    def test_manifest_binding_tamper_blocks_all_renderer_work(self):
        for field, value in [('run_attempt', '3'), ('executable_sha256', 'b' * 64),
                             ('cargo_lock_sha256', 'c' * 64)]:
            self.evidence = self.base / field
            manifest = copy.deepcopy(self.manifest)
            manifest['binding'][field] = value
            with self.subTest(field=field):
                report = self.run_case(manifest=manifest)
                self.assert_closed(report, 'jump-gameplay')
                self.assertFalse(report['passed'])
                self.assertTrue(all(row['passed'] is False for row in report['checks']))
        self.assertEqual(self.calls, [])
        self.images.assert_not_called()

    def test_full_input_schema_build_selection_and_scenario_set_are_validated(self):
        mutations = [
            ('schema', 'invented/v1'), ('platform', 'linux'),
            ('build_selection', {'default_enabled': 0, 'features': ['legacy-macroquad', 'wgpu-runtime']}),
            ('build_selection', {'default_enabled': False, 'features': ['wgpu-runtime']}),
            ('expected_scenarios', list(reversed(shared.SCENARIOS))), ('unexpected', True),
        ]
        for index, (field, value) in enumerate(mutations):
            self.evidence = self.base / f'bad-schema-{index}'
            manifest = copy.deepcopy(self.manifest)
            manifest[field] = value
            with self.subTest(field=field, value=value):
                report = self.run_case(manifest=manifest)
                self.assert_closed(report, 'jump-gameplay')
                self.assertFalse(report['passed'])
                self.assertFalse(self.by_name(report)['validated-inputs']['passed'])
        self.assertEqual(self.calls, [])

    def test_real_input_bytes_are_rechecked_before_rendering(self):
        targets = [self.executable, self.fixture, self.root / 'Cargo.toml', self.root / 'Cargo.lock',
                   self.root / 'settings.cfg', self.root / 'assets/animations.cfg']
        for number, path in enumerate(targets):
            original = path.read_bytes()
            path.write_bytes(original + b'changed')
            self.evidence = self.base / f'changed-before-{number}'
            with self.subTest(file=path.name):
                report = self.run_case()
                self.assertFalse(report['passed'])
                self.assertFalse(self.by_name(report)['validated-inputs']['passed'])
            path.write_bytes(original)
        self.assertEqual(self.calls, [])

    def test_input_mutation_after_capture_fails_final_recheck(self):
        def mutate(log_name):
            if log_name == 'dx12-capture':
                (self.root / 'settings.cfg').write_text('fov = 91\n', encoding='utf-8')
        self.after_process = mutate
        report = self.run_case()
        self.assert_closed(report, 'jump-gameplay')
        rows = self.by_name(report)
        self.assertTrue(rows['validated-inputs']['passed'])
        self.assertTrue(rows['same-windows-strict-parity']['passed'])
        self.assertFalse(rows['inputs-unchanged']['passed'])
        self.assertFalse(report['passed'])
        self.assertEqual(report['binding'], self.manifest['binding'])

    def test_existing_evidence_is_never_overwritten(self):
        self.evidence.mkdir()
        sentinel = self.evidence / 'keep.txt'
        sentinel.write_text('keep', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'existing'):
            self.run_case()
        self.assertEqual(list(self.evidence.iterdir()), [sentinel])
        self.assertEqual(self.calls, [])

    def test_existing_evidence_file_is_never_replaced(self):
        self.evidence.write_bytes(b'original evidence path')
        with self.assertRaisesRegex(ValueError, 'existing'):
            self.run_case()
        self.assertEqual(self.evidence.read_bytes(), b'original evidence path')
        self.assertEqual(self.calls, [])

    def test_dangling_evidence_symlink_is_rejected_before_resolution(self):
        target = self.base / 'missing-target'
        try:
            self.evidence.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('symlink creation is unavailable on this host')
        with self.assertRaisesRegex(ValueError, 'existing shard evidence symlink'):
            self.run_case()
        self.assertTrue(self.evidence.is_symlink())
        self.assertFalse(target.exists())
        self.assertEqual(self.calls, [])

    def test_missing_manifest_retains_failure_and_does_not_attempt_renderer(self):
        self.manifest_path.unlink()
        report = self.run_case()
        self.assert_closed(report, 'jump-gameplay')
        self.assertFalse(report['passed'])
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['binding'], {})
        self.assertTrue(all(row['passed'] is False for row in report['checks']))
        self.assertEqual(self.calls, [])

    def test_runner_identity_must_be_complete_and_actual_windows(self):
        for field, value in [('RUNNER_OS', 'Linux'), ('RUNNER_OS', ''), ('RUNNER_NAME', ''), ('RUNNER_ARCH', ' ')]:
            with self.subTest(field=field, value=value), patch.dict(os.environ, {field: value}):
                with self.assertRaisesRegex(ValueError, 'Windows runner identity'):
                    self.run_case()
            self.assertFalse(self.evidence.exists())
        self.assertEqual(self.calls, [])

    def test_invalid_timeout_or_unknown_scenario_never_renders(self):
        for value in (0, -1, True, float('nan'), float('inf'), '900'):
            for parameter in ('capture_timeout', 'run_timeout'):
                with self.subTest(parameter=parameter, value=value), self.assertRaises(ValueError):
                    self.run_case(**{parameter: value})
        with self.assertRaisesRegex(ValueError, 'scenario'):
            self.run_case('invented')
        self.assertEqual(self.calls, [])
        self.assertFalse(self.evidence.exists())

    def test_custom_capture_timeout_does_not_shorten_legacy_or_validator_allowances(self):
        report = self.run_case(capture_timeout=77, run_timeout=5000)
        self.assertTrue(report['passed'])
        self.assertEqual(report['run_timeout_seconds'], 5000)
        self.assertEqual([row['timeout'] for row in self.calls], [120, 900, 900, 77, 900])
        self.assertEqual([call.args[2] for call in self.images.call_args_list], [403, 403])

    def test_whole_shard_deadline_cannot_turn_a_partial_capture_into_a_pass(self):
        clock = [0.0]
        def expire(log_name):
            if log_name == 'windows-legacy-capture':
                clock[0] = 11.0
        self.after_process = expire
        with patch.object(shard.time, 'monotonic', side_effect=lambda: clock[0]):
            report = self.run_case(run_timeout=10)
        self.assert_closed(report, 'jump-gameplay')
        self.assertFalse(report['passed'])
        self.assertTrue(report['budget_exhausted'])
        self.assertEqual([(row['logs'].name, row['timeout']) for row in self.calls],
                         [('windows-legacy-stock-probe', 10), ('windows-legacy-capture', 10)])
        self.assertFalse(self.by_name(report)['dx12/capture']['passed'])

    def test_auxiliary_executes_exact_fixture_and_all_twelve_existing_lighting_commands(self):
        report = self.run_case('lighting-orientation')
        self.assert_closed(report, 'lighting-orientation')
        self.assertTrue(report['passed'])
        self.assertEqual(report['run_timeout_seconds'], 1800)
        self.assertEqual(len(self.calls), 13)
        self.assertEqual(self.calls[0]['command'], [str(self.fixture), '--renderer=dx12', '--force-fallback-adapter',
                                                   f'--output-dir={self.evidence / "renderer-contract"}'])
        expected = list(authored.lighting_commands(self.evidence / 'gl-runtime/vector-range.exe', self.root, self.evidence / 'captures/dx12/lighting'))
        self.assertEqual([row['command'] for row in self.calls[1:]], [command for _, command in expected])
        self.assertTrue(all(row['renderer'] and row['timeout'] == 900 for row in self.calls))
        self.stock.assert_not_called()
        self.images.assert_not_called()
        self.parity.assert_not_called()
        self.orientation.assert_called_once_with(self.evidence / 'renderer-contract')
        self.lighting.assert_called_once_with(self.evidence / 'captures/dx12/lighting')

    def test_auxiliary_failures_preserve_independent_attempts_and_fail_final_report(self):
        self.failures['renderer-contract'] = RuntimeError('orientation process failed')
        first_stem = next(authored.lighting_commands(self.executable, self.root, self.evidence))[0]
        self.failures[f'lighting-{first_stem}'] = RuntimeError('lighting process failed')
        report = self.run_case('lighting-orientation')
        self.assert_closed(report, 'lighting-orientation')
        self.assertFalse(report['passed'])
        self.assertEqual(len(self.calls), 13)
        rows = self.by_name(report)
        self.assertFalse(rows['orientation-renderer-contract']['passed'])
        self.assertFalse(rows[f'lighting/{first_stem}']['passed'])
        self.assertFalse(rows['lighting-existing-validator-and-images']['passed'])
        self.assertTrue(rows['inputs-unchanged']['passed'])
        self.orientation.assert_not_called()
        self.lighting.assert_not_called()

    def test_ordinary_helper_exception_inside_check_is_reported_and_other_role_runs(self):
        def images(folder, role, count):
            if role == 'windows-legacy':
                raise KeyError('unexpected helper error')
            return self.images_double(folder, role, count)
        self.images.side_effect = images
        report = self.run_case()
        self.assert_closed(report, 'jump-gameplay')
        self.assertFalse(report['passed'])
        self.assertIn('KeyError', self.by_name(report)['windows-legacy/finite-images']['error'])
        self.assertTrue(self.by_name(report)['dx12/existing-validator']['passed'])

    def test_fatal_helper_exception_is_rethrown_after_durable_failed_summary(self):
        with patch.object(shard, 'run_pair', side_effect=KeyError('fatal helper error')):
            with self.assertRaises(KeyError):
                self.run_case()
        report = self.saved_report()
        self.assertFalse(report['passed'])
        self.assertEqual(report['status'], 'failed')
        self.assertIn('KeyError', report['fatal_error'])
        self.assertFalse(report['acceptance_complete'])
        self.assertEqual(report['files'], shared.inventory_files(self.evidence))

    def test_interrupt_keeps_partial_logs_and_interrupted_summary(self):
        self.failures['windows-legacy-capture'] = KeyboardInterrupt('cancelled')
        with self.assertRaises(KeyboardInterrupt):
            self.run_case()
        report = self.saved_report()
        self.assertFalse(report['passed'])
        self.assertEqual(report['status'], 'interrupted')
        self.assertIn('KeyboardInterrupt', report['fatal_error'])
        self.assertIn('logs/windows-legacy-capture/stdout.log', report['files'])
        self.assertFalse(self.by_name(report)['windows-legacy/capture']['passed'])
        self.assertNotIn('dx12/capture', self.by_name(report))

    def test_inventory_seal_failure_cannot_leave_successful_report(self):
        with patch.object(shared, 'inventory_files', side_effect=ValueError('changed while hashing')):
            report = self.run_case()
        self.assertFalse(report['passed'])
        self.assertEqual(report['status'], 'failed')
        self.assertIn('inventory seal failed', report['fatal_error'])
        self.assertEqual(report, self.saved_report())

    def test_missing_or_extra_check_cannot_pass_via_all_checks_truthiness(self):
        for extra in (False, True):
            self.evidence = self.base / f'wrong-check-set-{extra}'
            def wrong_checks(journal, *args):
                if extra:
                    for name in shard.required_checks('jump-gameplay')[1:-1]:
                        journal.check(name, lambda: {'synthetic': True})
                    journal.check('unapproved-extra-gate', lambda: {'synthetic': True})
            with self.subTest(extra=extra), patch.object(shard, 'run_pair', side_effect=wrong_checks):
                with self.assertRaisesRegex(ValueError, 'check inventory differs'):
                    self.run_case()
                self.assertFalse(self.saved_report()['passed'])
                self.assertEqual(self.saved_report()['status'], 'failed')

    def test_invalid_manifest_file_retains_failed_summary_without_native_attempt(self):
        for index, raw in enumerate(('{', '{"binding":{},"binding":{}}', '[]')):
            self.evidence = self.base / f'invalid-manifest-{index}'
            self.manifest_path.write_text(raw, encoding='utf-8')
            with self.subTest(raw=raw):
                report = self.run_case()
                self.assert_closed(report, 'jump-gameplay')
                self.assertFalse(report['passed'])
                self.assertEqual(report['status'], 'failed')
                self.assertEqual(report['binding'], {})
                self.assertTrue(all(row['passed'] is False for row in report['checks']))
        self.assertEqual(self.calls, [])

    def test_nonserializable_untrusted_binding_cannot_break_initial_failure_reporting(self):
        for index, value in enumerate((float('nan'), {'non-json-set'}, object())):
            self.evidence = self.base / f'untrusted-binding-{index}'
            manifest = copy.deepcopy(self.manifest)
            manifest['binding'] = value
            with self.subTest(value_type=type(value).__name__):
                report = self.run_case(manifest=manifest)
                self.assert_closed(report, 'jump-gameplay')
                self.assertFalse(report['passed'])
                self.assertEqual(report['status'], 'failed')
                self.assertEqual(report['binding'], {})
                self.assertTrue(all(row['passed'] is False for row in report['checks']))
        self.assertEqual(self.calls, [])


class CliTests(FixtureCase):
    def args(self, command='run'):
        args = [command, '--executable', str(self.executable), '--renderer-contract', str(self.fixture),
                '--root', str(self.root), '--evidence', str(self.evidence)]
        if command == 'run':
            args += ['--input-manifest', str(self.manifest_path), '--scenario', 'ads-offset',
                     '--timeout', '123', '--run-timeout', '456']
        else:
            args += ['--legacy-linux', str(self.base / 'historical')]
        return args

    def test_run_cli_forwards_inputs_timeouts_and_returns_only_report_pass_status(self):
        for passed in (True, False):
            with self.subTest(passed=passed), patch.object(shard, 'run_shard', return_value={'passed': passed}) as run, \
                    redirect_stdout(io.StringIO()) as output:
                self.assertEqual(shard.main(self.args()), 0 if passed else 1)
                self.assertEqual(json.loads(output.getvalue()), {'passed': passed})
            run.assert_called_once_with(self.executable, self.fixture, self.root, self.evidence,
                                        self.manifest_path, 'ads-offset', capture_timeout=123.0, run_timeout=456.0)

    def test_prepare_cli_forwards_source_bound_historical_directory(self):
        with patch.object(shard, 'prepare', return_value=self.manifest) as prepare, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(shard.main(self.args('prepare')), 0)
            self.assertEqual(json.loads(output.getvalue()), self.manifest)
        prepare.assert_called_once_with(self.executable, self.fixture, self.root, self.base / 'historical', self.evidence)

    def test_expected_runtime_failures_return_nonzero_and_name_the_error(self):
        for error in (ValueError('bad inputs'), OSError('cannot write'), RuntimeError('native process failed')):
            with self.subTest(error=type(error).__name__), patch.object(shard, 'run_shard', side_effect=error), \
                    redirect_stderr(io.StringIO()) as output:
                self.assertEqual(shard.main(self.args()), 1)
                self.assertIn('Authored shard failed', output.getvalue())
                self.assertIn(str(error), output.getvalue())

    def test_cli_rejects_unknown_scenario_without_calling_runner(self):
        args = self.args()
        args[args.index('ads-offset')] = 'shortened-smoke'
        with patch.object(shard, 'run_shard') as run, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as result:
                shard.main(args)
        self.assertEqual(result.exception.code, 2)
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
