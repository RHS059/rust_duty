"""Current-main producer guards and orchestration; no native Windows pass claimed."""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import current_ads_source_oracle as current


CONTEXT = {'source_commit': '1' * 40, 'run_id': '1234', 'run_attempt': '2'}
ENVIRONMENT = {'GITHUB_SHA': CONTEXT['source_commit'], 'GITHUB_RUN_ID': '1234', 'GITHUB_RUN_ATTEMPT': '2',
               'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': current.REPOSITORY, 'GITHUB_REF': 'refs/heads/main',
               'GITHUB_WORKFLOW_REF': current.REPOSITORY + '/.github/workflows/build.yml@refs/heads/main',
               'GITHUB_WORKFLOW_SHA': CONTEXT['source_commit'], 'GITHUB_EVENT_NAME': 'push',
               'RUNNER_OS': 'Windows', 'RUNNER_ARCH': 'X64'}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, default=float) + '\n', encoding='utf-8')


class CurrentContextTests(unittest.TestCase):
    def context(self, environment, platform='win32', machine='AMD64'):
        with patch.dict(os.environ, environment, clear=True), patch.object(current.sys, 'platform', platform), \
                patch.object(current.platform, 'machine', return_value=machine):
            return current.current_main_context()

    def test_actual_main_push_and_dispatch_work_without_completed_history(self):
        self.assertEqual(self.context(ENVIRONMENT), CONTEXT)
        self.assertEqual(self.context({**ENVIRONMENT, 'GITHUB_EVENT_NAME': 'workflow_dispatch'}), CONTEXT)

    def test_other_repository_branch_workflow_commit_runner_and_event_rejected(self):
        replacements = {'GITHUB_ACTIONS': 'false', 'GITHUB_REPOSITORY': 'other/rust_duty',
                        'GITHUB_REF': 'refs/heads/aella/wgpu-renderer-port',
                        'GITHUB_WORKFLOW_REF': current.REPOSITORY + '/.github/workflows/recovery.yml@refs/heads/main',
                        'GITHUB_WORKFLOW_SHA': '2' * 40, 'RUNNER_OS': 'Linux', 'RUNNER_ARCH': 'ARM64',
                        'GITHUB_EVENT_NAME': 'pull_request', 'GITHUB_SHA': '', 'GITHUB_RUN_ID': '0',
                        'GITHUB_RUN_ATTEMPT': '0'}
        for name, value in replacements.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.context({**ENVIRONMENT, name: value})
        for platform, machine in [('linux', 'x86_64'), ('win32', 'ARM64')]:
            with self.subTest(platform=platform, machine=machine), self.assertRaises(ValueError):
                self.context(ENVIRONMENT, platform, machine)

    def test_prebuild_and_real_replay_paths_must_match_without_receipt_rewriting(self):
        current.check_replay_root(PureWindowsPath('D:/a/rust_duty/rust_duty'),
                                  {'recorded_root': 'd:\\a\\RUST_DUTY\\rust_duty'})
        for recorded in ('D:/different/root', 'C:/a/rust_duty/rust_duty', '../source'):
            with self.subTest(recorded=recorded), self.assertRaises(ValueError):
                current.check_replay_root(PureWindowsPath('D:/a/rust_duty/rust_duty'), {'recorded_root': recorded})

    def test_current_source_requires_tracked_unchanged_exact_head_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tool = root / 'tools/current_ads_source_oracle.py'
            tool.parent.mkdir()
            tool.write_text('original committed tool\n')
            (tool.parent / 'collect_ads_offset_evidence.py').write_text('original committed collector\n')
            (tool.parent / 'finite_ads_profile_binding.py').write_text('original committed finite binder\n')
            def git(*args):
                return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE)
            git('init', '-q')
            git('add', 'tools')
            git('-c', 'user.name=Synthetic test', '-c', 'user.email=synthetic@example.invalid', 'commit', '-qm', 'synthetic source')
            context = {**CONTEXT, 'source_commit': git('rev-parse', 'HEAD').decode().strip()}
            with patch.object(current.prepared, 'implementation_paths', return_value={}):
                self.assertEqual(set(current.check_checkout(root, context)),
                                 {'tools/current_ads_source_oracle.py', 'tools/collect_ads_offset_evidence.py',
                                  'tools/finite_ads_profile_binding.py'})
                with self.assertRaisesRegex(ValueError, 'differs from actual GitHub commit'):
                    current.check_checkout(root, CONTEXT)
                tool.write_text('changed tool\n')
                with self.assertRaisesRegex(ValueError, 'tracked changes'):
                    current.check_checkout(root, context)
                tool.write_text('original committed tool\n')
            extra = root / 'untracked-example.rs'
            extra.write_text('untracked replacement source\n')
            with patch.object(current.prepared, 'implementation_paths', return_value={'untracked-example.rs': extra}):
                with self.assertRaises(subprocess.CalledProcessError):
                    current.check_checkout(root, context)


class AssembleTests(unittest.TestCase):
    """Exercise real packet/anchor writes around mocked native subprocesses.

    Precompiled artifact, closed native collection and source/native math binding
    have separate real contract suites. These tests do not make synthetic bytes
    executable or claim a passing Windows capture.
    """
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'checkout'
        self.root.mkdir()
        self.evidence = self.root / 'evidence/current-source'
        self.anchor = self.root / 'evidence/independent-source.sha256'
        self.shards = self.root / 'evidence/shards'
        self.oracle = self.root / 'evidence/prebuilt'
        self.oracle.mkdir(parents=True)
        self.input_manifest = self.root / 'evidence/input-manifest.json'
        self.native = {**CONTEXT, **{key: 'a' * 64 for key in current.shared._HASH_FIELDS},
                       'runtime_and_manifest_sha256': {}}
        for name in current.binding.INPUTS - {'ads-offset.cfg'}:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'base setting = 1\n' if name == 'settings.cfg' else ('synthetic ' + name).encode())
            self.native['runtime_and_manifest_sha256'][name] = current.shared._read_regular(path)
        self.manifest = {'binding': self.native}
        write(self.input_manifest, self.manifest)
        self.implementation = {}
        for name in ('Cargo.toml', 'Cargo.lock', 'src/authored_viewmodel.rs', 'src/weapon_model.rs',
                     'examples/source_visibility_certificate.rs', 'tools/build_ads_source_packet.py',
                     'tools/current_ads_source_oracle.py', 'tools/collect_ads_offset_evidence.py'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('synthetic original ' + name, encoding='utf-8')
            self.implementation[name] = path
        self.originals = {}
        self.reports = {}
        for scenario in ('ads-gameplay', 'ads-offset'):
            folder = self.shards / scenario
            folder.mkdir(parents=True)
            if scenario == 'ads-offset':
                (folder / 'ads-offset.cfg').write_text('base setting = 1\n' + current.binding.OFFSET_SUFFIX, encoding='utf-8')
            value = {'passed': scenario == 'ads-gameplay', 'status': 'passed' if scenario == 'ads-gameplay' else 'failed',
                     'files': current.shared.inventory_files(folder),
                     'capture_paths': {role: 'captures/' + role for role in current.binding.ROLES}}
            write(folder / 'summary.json', value)
            self.originals[folder / 'summary.json'] = (folder / 'summary.json').read_bytes()
            self.reports[scenario] = value
        self.prepared = {'recorded_root': 'D:/a/rust_duty/rust_duty', 'active_toolchain_alias': 'stable-x86_64-pc-windows-msvc',
                         'toolchain': '1.90.0-x86_64-pc-windows-msvc'}
        self.prebuilt = {'receipt': self.prepared}
        for key, filename in [('executable', 'source_visibility_certificate.exe'), ('rustc_vv', 'rustc-Vv.txt'),
                              ('build_receipt', 'build-receipt.json'), ('input_manifest', 'input-manifest.json'),
                              ('receipt_path', 'receipt.json')]:
            path = self.oracle / filename
            path.write_bytes(b'MZ synthetic' if key == 'executable' else ('synthetic ' + filename).encode())
            self.prebuilt[key] = path
        self.build_raw = self.prebuilt['build_receipt'].read_bytes()
        self.prebuilt['input_manifest'].write_bytes(self.input_manifest.read_bytes())
        self.prepared['files'] = {name: current.producer.digest(self.oracle / name) for name in current.prepared.FILES}
        self.source_receipt_anchor = current.shared._read_regular(self.prebuilt['receipt_path'])
        self.compiler_anchor = 'c' * 64
        self.args = dict(root=self.root, input_manifest=self.input_manifest, shards=self.shards, oracle=self.oracle,
                         expected_oracle_receipt_sha256=self.source_receipt_anchor,
                         capture_rustc_sha256=self.compiler_anchor, evidence=self.evidence, receipt_anchor=self.anchor,
                         reviewed_class=self.root / 'reviewed/class.json', expected_class_sha256='d' * 64)
        self.calls = []
        self.leaf_calls = []
        self.collection = {'needs_supplement': True, 'original_passed': False, 'original_status': 'failed'}
        self.profile_identity = {'bounded_ads_profile_established': True, 'class_id': 'synthetic-orchestration-only'}
        self.fake_leaf_result = {'passed': True, 'bounded_ads_profile_established': True,
                                 'conditional_diagnostic': False, 'bounded_ads_profile': self.profile_identity}
        self.packet = Mock()
        self.profile = Mock()
        self.profile_failure = None
        self.replay_mutation = None
        self.collection_mutation = None
        self.copy_mutation = None

    def replay(self, command, root, env, logs, timeout):
        self.calls.append(list(command))
        self.assertEqual(len(command), 5)
        self.assertEqual(Path(command[0]).name, 'source_visibility_certificate.exe')
        self.assertEqual(Path(command[1]), self.root / 'assets/animations.cfg')
        self.assertEqual(Path(command[2]).read_bytes(), (self.shards / 'ads-offset/ads-offset.cfg').read_bytes())
        rows = [{'schema': 'synthetic mock CPU header'}, *({'frame': index} for index in range(553))]
        if self.replay_mutation:
            self.replay_mutation(command, rows)
        Path(command[4]).write_text(''.join(json.dumps(row) + '\n' for row in rows))
        return {'command': list(command), 'cwd': root.as_posix(), 'exit_code': 0,
                'environment': deepcopy(current.binding.ORACLE_ENVIRONMENT)}

    def leaf(self, **kwargs):
        self.leaf_calls.append(kwargs)
        self.assertTrue(self.anchor.is_file(), 'independent anchor must precede leaf revalidation')
        self.assertEqual(self.anchor.read_text().strip(), kwargs['source_receipt_sha256'])
        self.assertFalse((self.evidence / 'aggregate-supplement.json').exists())
        write(kwargs['evidence'] / 'summary.json', self.fake_leaf_result)
        return self.fake_leaf_result

    def call(self, *, failed_prebuild=False):
        def inspect(*args):
            if self.collection_mutation:
                self.collection_mutation()
            return (deepcopy(self.reports), {role: {'command': ['original game']} for role in current.binding.ROLES},
                    self.collection)
        original_copy = current.producer.copy_packet_file
        def copy(source, destination, expected):
            original_copy(source, destination, expected)
            if self.copy_mutation and destination == self.evidence / 'oracle-output/precompiled-receipt.json':
                self.copy_mutation()
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {'CARGO_HOME': str(self.root / 'cargo-home')}, clear=True))
            stack.enter_context(patch.object(current, 'current_main_context', return_value=CONTEXT))
            stack.enter_context(patch.object(current, 'check_checkout', return_value=dict(self.implementation)))
            stack.enter_context(patch.object(current, 'check_replay_root'))
            stack.enter_context(patch.object(current.leaf, 'manifest_binding', return_value=self.manifest))
            stack.enter_context(patch.object(current.shared, 'verify_input_manifest', return_value=self.native))
            verified = stack.enter_context(patch.object(current.prepared, 'verify_precompiled',
                side_effect=ValueError('independent prebuild anchor mismatch') if failed_prebuild else None,
                return_value=self.prebuilt))
            stack.enter_context(patch.object(current, 'verify_native_pair', side_effect=inspect))
            stack.enter_context(patch.object(current.producer, 'copy_packet_file', side_effect=copy))
            stack.enter_context(patch.object(current.producer, 'process', side_effect=self.replay))
            stack.enter_context(patch.object(current.leaf, 'run', side_effect=self.leaf))
            stack.enter_context(patch.object(current.binding, 'bind_source_packet', return_value=self.packet))
            stack.enter_context(patch.object(current.leaf, 'bind_bounded_profile', return_value=self.profile,
                                            side_effect=self.profile_failure))
            stack.enter_context(patch.object(current.leaf, 'bounded_profile_summary', return_value=self.profile_identity))
            result = current.assemble(**self.args)
            self.assertEqual(verified.call_args.args[-2:], (self.source_receipt_anchor, self.compiler_anchor))
            return result

    def test_two_cpu_replays_one_leaf_and_independent_anchor_produce_exact_supplement(self):
        result = self.call()
        self.assertTrue(result['passed'])
        self.assertFalse(result['acceptance_complete'])
        self.assertEqual([command[3] for command in self.calls], ['opengl', 'dx12'])
        self.assertEqual(len(self.leaf_calls), 1)
        request = json.loads((self.evidence / 'aggregate-supplement.json').read_text())
        self.assertEqual(set(request), {'leaf_summary', 'source_packet', 'source_receipt_sha256', 'capture_rustc_sha256',
                                        'capture_context', 'leaf_verifier_context', 'verifier_context',
                                        'reviewed_class', 'expected_class_sha256'})
        for key in ('capture_context', 'leaf_verifier_context', 'verifier_context'):
            self.assertEqual(request[key], CONTEXT)
        packet = json.loads(Path(request['source_packet']).read_text())
        self.assertEqual(set(packet['input_files']), current.binding.INPUTS)
        self.assertEqual(len(packet['input_files']), 21)
        receipt = json.loads((Path(request['source_packet']).parent / packet['receipt']).read_text())
        self.assertEqual(receipt['inputs_and_implementation_before'], receipt['inputs_and_implementation_after'])
        build_key = receipt['oracle_execution']['build_receipt']
        self.assertEqual((Path(request['source_packet']).parent / packet['files'][build_key]).read_bytes(), self.build_raw)
        self.assertEqual(hashlib.sha256((self.evidence / 'packet/source-receipt.json').read_bytes()).hexdigest(),
                         self.anchor.read_text().strip())
        for path, raw in self.originals.items():
            self.assertEqual(path.read_bytes(), raw)

    def test_missing_or_unestablished_profile_cannot_reach_leaf_or_supplement(self):
        self.args['reviewed_class'] = None
        with self.assertRaisesRegex(ValueError, 'independently bound finite ADS profile'):
            self.call()
        self.assertFalse(self.leaf_calls)
        self.assertFalse((self.evidence / 'aggregate-supplement.json').exists())
        self.assertFalse(json.loads((self.evidence / 'producer-summary.json').read_text())['bounded_ads_profile_established'])

    def test_pending_profile_cannot_reach_leaf_or_supplement(self):
        self.profile_failure = ValueError('reviewed finite ADS profile remains pending')
        with self.assertRaisesRegex(ValueError, 'profile remains pending'):
            self.call()
        self.assertFalse(self.leaf_calls)
        self.assertFalse((self.evidence / 'aggregate-supplement.json').exists())

    def test_late_profile_mutation_blocks_successful_leaf_publication(self):
        self.profile.verify_unchanged.side_effect = ValueError('late profile mutation')
        with self.assertRaisesRegex(ValueError, 'late profile mutation'):
            self.call()
        self.assertEqual(len(self.leaf_calls), 1)
        self.assertFalse((self.evidence / 'aggregate-supplement.json').exists())

    def test_conditional_leaf_boolean_cannot_authorize_supplement(self):
        self.fake_leaf_result['conditional_diagnostic'] = True
        with self.assertRaisesRegex(ValueError, 'established finite profile'):
            self.call()
        self.assertFalse((self.evidence / 'aggregate-supplement.json').exists())

    def test_original_pass_does_not_run_cpu_leaf_or_create_supplement(self):
        self.collection = None
        result = self.call()
        self.assertTrue(result['passed'])
        self.assertFalse(result['needs_supplement'])
        self.assertFalse(self.calls)
        self.assertFalse(self.leaf_calls)
        self.assertFalse(self.anchor.exists())
        self.assertFalse((self.evidence / 'aggregate-supplement.json').exists())

    def test_failed_leaf_retains_originals_packet_anchor_and_failure_without_supplement(self):
        self.fake_leaf_result = {'passed': False, 'failure': 'source required visible sample missing'}
        with self.assertRaisesRegex(ValueError, 'reviewed ADS leaf did not pass'):
            self.call()
        self.assertEqual(len(self.leaf_calls), 1)
        self.assertTrue(self.anchor.exists())
        self.assertFalse((self.evidence / 'aggregate-supplement.json').exists())
        self.assertFalse(json.loads((self.evidence / 'producer-summary.json').read_text())['passed'])
        for path, raw in self.originals.items():
            self.assertEqual(path.read_bytes(), raw)

    def test_wrong_prebuild_anchor_stops_before_cpu_or_leaf(self):
        with self.assertRaisesRegex(ValueError, 'independent prebuild anchor mismatch'):
            self.call(failed_prebuild=True)
        self.assertFalse(self.calls)
        self.assertFalse(self.leaf_calls)

    def test_changed_input_or_missing_last_source_frame_cannot_reach_leaf(self):
        self.replay_mutation = lambda command, rows: rows.pop()
        with self.assertRaisesRegex(ValueError, 'all 553 frames'):
            self.call()
        self.assertFalse(self.leaf_calls)
        self.assertFalse(self.anchor.exists())

    def test_input_mutation_during_replay_is_rejected_before_packet_and_leaf(self):
        def mutate(command, rows):
            (self.root / 'assets/reload/asset.vrs').write_bytes(b'changed runtime companion')
        self.replay_mutation = mutate
        with self.assertRaisesRegex(ValueError, 'changed before CPU execution'):
            self.call()
        self.assertFalse(self.leaf_calls)

    def test_precompiled_executable_swap_during_native_inspection_never_executes(self):
        self.collection_mutation = lambda: self.prebuilt['executable'].write_bytes(b'MZ different executable')
        with self.assertRaisesRegex(ValueError, 'changed before portable copy'):
            self.call()
        self.assertFalse(self.calls)
        self.assertFalse(self.leaf_calls)

    def test_precompiled_compiler_swap_during_native_inspection_never_executes(self):
        self.collection_mutation = lambda: self.prebuilt['rustc_vv'].write_bytes(b'different compiler')
        with self.assertRaisesRegex(ValueError, 'changed before portable copy'):
            self.call()
        self.assertFalse(self.calls)

    def test_precompiled_build_receipt_swap_during_native_inspection_never_executes(self):
        self.collection_mutation = lambda: self.prebuilt['build_receipt'].write_bytes(b'different recorded build')
        with self.assertRaisesRegex(ValueError, 'changed before portable copy'):
            self.call()
        self.assertFalse(self.calls)

    def test_staged_executable_swap_after_copy_never_executes(self):
        self.copy_mutation = lambda: (self.evidence / 'oracle-output/source_visibility_certificate.exe').write_bytes(b'MZ replaced staged executable')
        with self.assertRaisesRegex(ValueError, 'staged bytes changed before CPU execution'):
            self.call()
        self.assertFalse(self.calls)

    def test_original_executable_swap_after_copy_never_executes(self):
        self.copy_mutation = lambda: self.prebuilt['executable'].write_bytes(b'MZ replaced original executable')
        with self.assertRaisesRegex(ValueError, 'original bytes changed before CPU execution'):
            self.call()
        self.assertFalse(self.calls)
        self.assertFalse(self.anchor.exists())

    def test_stale_native_input_is_rejected_before_cpu(self):
        (self.root / 'assets/ads/asset.vra').write_bytes(b'different run')
        with self.assertRaisesRegex(ValueError, 'consumed native input differs'):
            self.call()
        self.assertFalse(self.calls)

    def test_original_summary_mutation_during_inspection_is_rejected_before_cpu(self):
        path = self.shards / 'ads-offset/summary.json'
        self.collection_mutation = lambda: path.write_text('{"passed":true}\n')
        with self.assertRaisesRegex(ValueError, 'changed during collection inspection'):
            self.call()
        self.assertFalse(self.calls)
        self.assertFalse(self.leaf_calls)

    def test_output_paths_cannot_replace_inputs_or_self_supply_the_anchor(self):
        variants = [dict(evidence=self.oracle / 'new'), dict(evidence=self.shards / 'new'),
                    dict(evidence=self.root.parent / 'outside'), dict(receipt_anchor=self.evidence / 'anchor'),
                    dict(receipt_anchor=self.oracle / 'anchor'), dict(receipt_anchor=self.input_manifest)]
        for variation in variants:
            with self.subTest(variation=variation), self.assertRaises(ValueError):
                current.check_paths(**{key: value for key, value in {**self.args, **variation}.items()
                                       if key in ('root', 'input_manifest', 'shards', 'oracle', 'evidence', 'receipt_anchor')})
        self.assertFalse(self.evidence.exists())


class NativePairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_collect_ads_offset_evidence as fixtures
        fixtures.CollectionTests.setUpClass()
        cls.addClassCleanup(fixtures.CollectionTests.doClassCleanups)
        cls.fixture = fixtures.CollectionTests
        cls.shards = cls.fixture.folder.parent

    def verify(self):
        return current.verify_native_pair(self.shards, self.fixture.binding, self.fixture.context)

    def test_real_closed_native_pair_and_typed_offset_collection_are_required(self):
        paths = [self.shards / scenario / 'summary.json' for scenario in ('ads-gameplay', 'ads-offset')]
        original = {path: path.read_bytes() for path in paths}
        reports, invocations, collection = self.verify()
        self.assertEqual(set(reports), {'ads-gameplay', 'ads-offset'})
        self.assertEqual(set(invocations), {'windows-legacy', 'dx12'})
        self.assertTrue(reports['ads-gameplay']['passed'])
        self.assertFalse(reports['ads-offset']['passed'])
        self.assertTrue(collection['needs_supplement'])
        self.assertFalse(collection['acceptance_complete'])
        for role in current.binding.ROLES:
            self.assertEqual(collection['images'][role]['frames'], 553)
        self.assertEqual({path: path.read_bytes() for path in paths}, original)

    def test_unrelated_gameplay_failure_cannot_be_hidden_by_eligible_offset(self):
        path = self.shards / 'ads-gameplay/summary.json'
        raw = path.read_bytes()
        self.addCleanup(path.write_bytes, raw)
        report = json.loads(raw)
        report.update(passed=False, status='failed')
        row = next(row for row in report['checks'] if row['name'] == 'dx12/existing-validator')
        row.pop('result')
        row.update(passed=False, error='ValueError: real unrelated gameplay failure')
        write(path, report)
        with self.assertRaises(ValueError):
            self.verify()


if __name__ == '__main__':
    unittest.main()
