"""Current-build producer guards and orchestration; no native Windows pass claimed."""
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path, PureWindowsPath
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import current_ads_source_oracle as current
import current_ads_build_context as build_context


CONTEXT = {'source_commit': '1' * 40, 'run_id': '1234', 'run_attempt': '2'}
ENVIRONMENT = {'GITHUB_SHA': CONTEXT['source_commit'], 'GITHUB_RUN_ID': '1234', 'GITHUB_RUN_ATTEMPT': '2',
               'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': current.REPOSITORY, 'GITHUB_REPOSITORY_ID': '7654321',
               'GITHUB_REF': 'refs/heads/main',
               'GITHUB_WORKFLOW_REF': current.REPOSITORY + '/.github/workflows/build.yml@refs/heads/main',
               'GITHUB_WORKFLOW_SHA': CONTEXT['source_commit'], 'GITHUB_EVENT_NAME': 'push',
               'RUNNER_OS': 'Windows', 'RUNNER_ARCH': 'X64'}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, default=float) + '\n', encoding='utf-8')


class CurrentContextTests(unittest.TestCase):
    def event(self, name='push'):
        repository = {'full_name': current.REPOSITORY, 'id': 7654321, 'fork': False}
        if name == 'pull_request':
            return {'repository': repository, 'action': 'synchronize', 'number': 401,
                    'pull_request': {'number': 401, 'state': 'open', 'merged': False,
                        'merge_commit_sha': CONTEXT['source_commit'],
                        'head': {'ref': 'halcyon/current-frame-ads-certificate', 'sha': '2' * 40, 'repo': repository.copy()},
                        'base': {'ref': 'main', 'sha': '3' * 40, 'repo': repository.copy()}}}
        if name == 'workflow_dispatch':
            return {'repository': repository, 'ref': 'main', 'inputs': {}}
        return {'repository': repository, 'ref': 'refs/heads/main', 'after': CONTEXT['source_commit'], 'deleted': False}

    def pr_environment(self):
        ref = 'refs/pull/401/merge'
        return {**ENVIRONMENT, 'GITHUB_EVENT_NAME': 'pull_request', 'GITHUB_REF': ref,
                'GITHUB_WORKFLOW_REF': current.REPOSITORY + '/.github/workflows/build.yml@' + ref,
                'GITHUB_HEAD_REF': 'halcyon/current-frame-ads-certificate', 'GITHUB_BASE_REF': 'main'}

    def context(self, environment, platform='win32', machine='AMD64', *, event=None, identity=False, root=None):
        if event is None:
            event = self.event(environment.get('GITHUB_EVENT_NAME'))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'event.json'
            path.write_text(event if type(event) is str else json.dumps(event), encoding='utf-8')
            with patch.dict(os.environ, {**environment, 'GITHUB_EVENT_PATH': str(path)}, clear=True), \
                    patch.object(current.sys, 'platform', platform), \
                    patch.object(current.platform, 'machine', return_value=machine):
                result = current.current_build_identity() if identity else current.current_main_context()
                if root is not None:
                    current.check_build_checkout(root, result if identity else current.current_build_identity())
                return result

    def test_actual_main_push_and_dispatch_work_without_completed_history(self):
        self.assertEqual(self.context(ENVIRONMENT), CONTEXT)
        self.assertEqual(self.context({**ENVIRONMENT, 'GITHUB_EVENT_NAME': 'workflow_dispatch'}), CONTEXT)
        dispatch = self.event('workflow_dispatch')
        dispatch['ref'] = 'refs/heads/main'
        self.assertEqual(self.context({**ENVIRONMENT, 'GITHUB_EVENT_NAME': 'workflow_dispatch'}, event=dispatch), CONTEXT)

    def test_same_repository_pr_binds_actual_merge_workflow_event_head_and_base(self):
        event = self.event('pull_request')
        result = self.context(self.pr_environment(), event=event, identity=True)
        self.assertEqual(result['capture_context'], CONTEXT)
        self.assertEqual(result['workflow_sha'], CONTEXT['source_commit'])
        self.assertEqual(result['ref'], 'refs/pull/401/merge')
        self.assertEqual(result['repository_id'], '7654321')
        self.assertEqual(result['pull_request']['number'], 401)
        self.assertEqual(result['pull_request']['head']['sha'], '2' * 40)
        self.assertEqual(result['pull_request']['base']['sha'], '3' * 40)
        self.assertEqual(result['event_payload_sha256'], hashlib.sha256(json.dumps(event).encode()).hexdigest())
        self.assertEqual(self.context(self.pr_environment()), CONTEXT)
        for action in ('opened', 'reopened'):
            with self.subTest(action=action):
                self.assertEqual(self.context(self.pr_environment(), event={**event, 'action': action}), CONTEXT)

    def test_other_repository_branch_workflow_commit_runner_and_event_rejected(self):
        replacements = {'GITHUB_ACTIONS': 'false', 'GITHUB_REPOSITORY': 'other/rust_duty',
                        'GITHUB_REPOSITORY_ID': '7654322',
                        'GITHUB_REF': 'refs/heads/aella/wgpu-renderer-port',
                        'GITHUB_WORKFLOW_REF': current.REPOSITORY + '/.github/workflows/recovery.yml@refs/heads/main',
                        'GITHUB_WORKFLOW_SHA': '2' * 40, 'RUNNER_OS': 'Linux', 'RUNNER_ARCH': 'ARM64',
                        'GITHUB_EVENT_NAME': 'pull_request_target', 'GITHUB_SHA': '', 'GITHUB_RUN_ID': '0',
                        'GITHUB_RUN_ATTEMPT': '0', 'GITHUB_HEAD_REF': 'other', 'GITHUB_BASE_REF': 'main'}
        for name, value in replacements.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.context({**ENVIRONMENT, name: value})
        for platform, machine in [('linux', 'x86_64'), ('win32', 'ARM64')]:
            with self.subTest(platform=platform, machine=machine), self.assertRaises(ValueError):
                self.context(ENVIRONMENT, platform, machine)

    def test_pr_environment_must_identify_the_exact_merge_workflow_and_refs(self):
        environment = self.pr_environment()
        replacements = {'GITHUB_REF': 'refs/pull/402/merge',
                        'GITHUB_HEAD_REF': 'other', 'GITHUB_BASE_REF': 'develop',
                        'GITHUB_SHA': '2' * 40, 'GITHUB_WORKFLOW_SHA': '2' * 40,
                        'GITHUB_EVENT_NAME': 'pull_request_target',
                        'GITHUB_WORKFLOW_REF': current.REPOSITORY + '/.github/workflows/build.yml@refs/heads/main'}
        for name, value in replacements.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.context({**environment, name: value}, event=self.event('pull_request'))
        for ref in ('refs/pull/401/head', 'refs/pull/0401/merge', 'refs/heads/main'):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                self.context({**environment, 'GITHUB_REF': ref,
                              'GITHUB_WORKFLOW_REF': current.REPOSITORY + '/.github/workflows/build.yml@' + ref},
                             event=self.event('pull_request'))

    def test_fork_mismatched_and_untrusted_pr_payloads_are_rejected(self):
        mutations = [
            lambda e: e.update(action='closed'),
            lambda e: e.update(number=True),
            lambda e: e.update(number=402),
            lambda e: e.update(pull_request=None),
            lambda e: e['pull_request'].update(number=402),
            lambda e: e['pull_request'].update(state='closed'),
            lambda e: e['pull_request'].update(merged=True),
            lambda e: e['pull_request'].update(merged=0),
            lambda e: e['pull_request'].update(merge_commit_sha='invalid'),
            lambda e: e['pull_request'].update(merge_commit_sha=False),
            lambda e: e['pull_request'].pop('merge_commit_sha'),
            lambda e: e['pull_request']['head'].update(ref='other'),
            lambda e: e['pull_request']['base'].update(ref='develop'),
            lambda e: e['pull_request']['head'].update(sha='bad'),
            lambda e: e['pull_request']['base'].update(sha='A' * 40),
            lambda e: e['pull_request']['head'].update(repo=None),
        ]
        for side in ('repository', 'head', 'base'):
            def repo(event, side=side):
                return event['repository'] if side == 'repository' else event['pull_request'][side]['repo']
            mutations.extend([
                lambda e, repo=repo: repo(e).update(full_name='attacker/rust_duty'),
                lambda e, repo=repo: repo(e).update(id=123),
                lambda e, repo=repo: repo(e).update(id='7654321'),
                lambda e, repo=repo: repo(e).update(fork=True),
                lambda e, repo=repo: repo(e).update(fork=0),
            ])
        for index, mutation in enumerate(mutations):
            event = deepcopy(self.event('pull_request'))
            mutation(event)
            with self.subTest(mutation=index), self.assertRaises(ValueError):
                self.context(self.pr_environment(), event=event)

    def test_main_event_payload_must_match_the_actual_environment(self):
        for mutation in (lambda e: e.update(after='2' * 40), lambda e: e.update(ref='refs/heads/other'),
                         lambda e: e.update(deleted=True), lambda e: e.update(deleted=0),
                         lambda e: e.update(pull_request={}), lambda e: e['repository'].update(id=1)):
            event = self.event()
            mutation(event)
            with self.subTest(event=event), self.assertRaises(ValueError):
                self.context(ENVIRONMENT, event=event)
        with self.assertRaises(ValueError):
            self.context({**ENVIRONMENT, 'GITHUB_EVENT_NAME': 'workflow_dispatch'},
                         event={**self.event('workflow_dispatch'), 'ref': 'other'})
        for event in ('{}', '[]', '{"repository":{},"repository":{}}', '{"repository":NaN}'):
            with self.subTest(event=event), self.assertRaises(ValueError):
                self.context(ENVIRONMENT, event=event)
        with patch.dict(os.environ, ENVIRONMENT, clear=True), patch.object(current.sys, 'platform', 'win32'), \
                patch.object(current.platform, 'machine', return_value='AMD64'), self.assertRaisesRegex(ValueError, 'event payload'):
            current.current_main_context()

    def test_identity_preserves_run_attempt_and_detects_event_byte_changes(self):
        first = self.context(self.pr_environment(), identity=True)
        second = self.context({**self.pr_environment(), 'GITHUB_RUN_ID': '5678', 'GITHUB_RUN_ATTEMPT': '3'}, identity=True)
        self.assertNotEqual(first['capture_context'], second['capture_context'])
        self.assertEqual(second['capture_context'], {**CONTEXT, 'run_id': '5678', 'run_attempt': '3'})
        changed = self.event('pull_request')
        changed['pull_request']['head']['sha'] = '4' * 40
        third = self.context(self.pr_environment(), event=changed, identity=True)
        self.assertNotEqual(first['event_payload_sha256'], third['event_payload_sha256'])
        self.assertNotEqual(first['pull_request'], third['pull_request'])

    def merge_fixture(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        def git(*args):
            return subprocess.check_output(['git', '-C', str(root), '-c', 'user.name=Synthetic test',
                '-c', 'user.email=synthetic@example.invalid', *args], stderr=subprocess.PIPE).decode().strip()
        git('init', '-q', '-b', 'main')
        (root / 'base').write_text('base')
        git('add', '.'); git('commit', '-qm', 'base')
        base = git('rev-parse', 'HEAD')
        git('checkout', '-qb', 'topic')
        (root / 'head').write_text('head')
        git('add', '.'); git('commit', '-qm', 'head')
        head = git('rev-parse', 'HEAD')
        git('checkout', '-q', 'main'); git('merge', '--no-ff', '-m', 'merge', 'topic')
        merge = git('rev-parse', 'HEAD')
        (root / '.git/shallow').write_text(merge + '\n', newline='\n')
        event = self.event('pull_request')
        event['pull_request'].update(merge_commit_sha=merge)
        event['pull_request']['head']['sha'] = head
        event['pull_request']['base']['sha'] = base
        environment = {**self.pr_environment(), 'GITHUB_SHA': merge, 'GITHUB_WORKFLOW_SHA': merge}
        return root, environment, event

    def command(self, root, environment, event, *arguments):
        event_path = root / 'event.json'
        write(event_path, event)
        output = root / 'github-output'
        output.write_text('')
        capture = io.StringIO()
        with patch.dict(os.environ, {**environment, 'GITHUB_EVENT_PATH': str(event_path),
                                     'GITHUB_OUTPUT': str(output), 'GITHUB_TOKEN': 'secret-do-not-print'}, clear=True), \
                patch.object(current.sys, 'platform', 'win32'), \
                patch.object(current.platform, 'machine', return_value='AMD64'), redirect_stdout(capture):
            result = build_context.main(['--root', str(root), *arguments])
        return result, capture.getvalue(), output.read_text()

    def test_merge_checkout_binds_ordered_base_and_head_even_when_shallow(self):
        root, environment, event = self.merge_fixture()
        identity = self.context(environment, event=event, identity=True, root=root)
        head, base = event['pull_request']['head']['sha'], event['pull_request']['base']['sha']
        for side, replacement in [('base', head), ('head', base), ('base', '9' * 40), ('head', '8' * 40)]:
            changed = deepcopy(identity)
            changed['pull_request'][side]['sha'] = replacement
            with self.subTest(side=side, replacement=replacement), self.assertRaisesRegex(ValueError, 'merge parents'):
                current.check_build_checkout(root, changed)
        swapped = deepcopy(identity)
        swapped['pull_request']['head']['sha'], swapped['pull_request']['base']['sha'] = base, head
        with self.assertRaisesRegex(ValueError, 'merge parents'):
            current.check_build_checkout(root, swapped)
        changed = deepcopy(identity)
        changed['capture_context']['source_commit'] = head
        with self.assertRaisesRegex(ValueError, 'actual GitHub commit'):
            current.check_build_checkout(root, changed)

    def test_nullable_and_stale_event_merge_hints_require_actual_sha_and_ordered_parents(self):
        root, environment, event = self.merge_fixture()
        for hint in (None, '4' * 40, environment['GITHUB_SHA']):
            with self.subTest(hint=hint):
                event['pull_request']['merge_commit_sha'] = hint
                identity = self.context(environment, event=event, identity=True, root=root)
                self.assertEqual(identity['pull_request']['merge_commit_sha'], environment['GITHUB_SHA'])
                self.assertEqual(identity['pull_request']['event_merge_commit_sha'], hint)
                result, _, output = self.command(root, environment, event, '--emit-admission-output')
                self.assertEqual(result, 0)
                self.assertEqual(output, 'admitted=true\n')
                head = event['pull_request']['head']['sha']
                with self.assertRaisesRegex(ValueError, 'actual GitHub commit'):
                    self.command(root, {**environment, 'GITHUB_SHA': head, 'GITHUB_WORKFLOW_SHA': head},
                                 event, '--emit-admission-output')
                self.assertEqual((root / 'github-output').read_text(), '')
                swapped = deepcopy(event)
                swapped['pull_request']['head']['sha'], swapped['pull_request']['base']['sha'] = (
                    swapped['pull_request']['base']['sha'], swapped['pull_request']['head']['sha'])
                with self.assertRaisesRegex(ValueError, 'merge parents'):
                    self.command(root, environment, swapped, '--emit-admission-output')
                self.assertEqual((root / 'github-output').read_text(), '')

    def test_diagnostics_are_allowlisted_and_cannot_emit_admission(self):
        root, environment, event = self.merge_fixture()
        event['pull_request']['merge_commit_sha'] = None
        event['pull_request']['body'] = 'private-body-do-not-print'
        event['sender'] = {'login': 'private-sender-do-not-print'}
        result, output, step_output = self.command(root, environment, event, '--diagnostics-only')
        self.assertEqual(result, 0)
        self.assertEqual(step_output, '')
        report = json.loads(output)
        self.assertTrue(report['admitted'])
        self.assertEqual(report['event']['pull_request.merge_commit_sha'], None)
        self.assertEqual(report['checkout']['head'], environment['GITHUB_SHA'])
        self.assertEqual(report['checkout']['parents'], [event['pull_request']['base']['sha'], event['pull_request']['head']['sha']])
        for secret in ('secret-do-not-print', 'private-body-do-not-print', 'private-sender-do-not-print', 'GITHUB_TOKEN'):
            self.assertNotIn(secret, output)
        with self.assertRaisesRegex(ValueError, 'cannot emit an admission'):
            self.command(root, environment, event, '--diagnostics-only', '--emit-admission-output')
        self.assertEqual((root / 'github-output').read_text(), '')

    def test_diagnostics_expose_rejection_without_turning_it_into_admission(self):
        root, environment, event = self.merge_fixture()
        event['pull_request']['head']['repo']['fork'] = True
        result, output, step_output = self.command(root, environment, event, '--diagnostics-only')
        self.assertEqual(result, 0)
        self.assertEqual(step_output, '')
        report = json.loads(output)
        self.assertFalse(report['admitted'])
        self.assertTrue(report['event']['pull_request.head.repo.fork'])
        self.assertIn('fork', report['rejection'])
        with self.assertRaisesRegex(ValueError, 'fork'):
            self.command(root, environment, event, '--diagnostics', '--emit-admission-output')
        self.assertEqual((root / 'github-output').read_text(), '')

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
            (tool.parent / 'current_ads_build_context.py').write_text('original committed identity\n')
            (tool.parent / 'finite_ads_profile_binding.py').write_text('original committed finite binder\n')
            profile_tools = ('current_ads_native_binding.py', 'current_ads_profile_proof.py',
                             'current_ads_profile_binding.py', 'prepare_current_ads_profile.py',
                             'run_current_ads_profile.py')
            for name in profile_tools:
                (tool.parent / name).write_text('original committed profile tool\n')
            def git(*args):
                return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE)
            git('init', '-q')
            git('add', 'tools')
            git('-c', 'user.name=Synthetic test', '-c', 'user.email=synthetic@example.invalid', 'commit', '-qm', 'synthetic source')
            context = {**CONTEXT, 'source_commit': git('rev-parse', 'HEAD').decode().strip()}
            with patch.object(current.prepared, 'implementation_paths', return_value={}):
                self.assertEqual(set(current.check_checkout(root, context)),
                                 {'tools/current_ads_source_oracle.py', 'tools/current_ads_build_context.py',
                                  'tools/collect_ads_offset_evidence.py', 'tools/finite_ads_profile_binding.py'}
                                 | {'tools/' + name for name in profile_tools})
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
        self.collection = {'needs_supplement': True, 'original_passed': False, 'original_status': 'failed',
                           'images': {role: {'typed_structure_failures': [{'frame': 3}, {'frame': 17}]}
                                      for role in current.binding.ROLES}}
        self.profile_identity = {'bounded_ads_profile_established': True, 'class_id': 'synthetic-orchestration-only'}
        self.fake_leaf_result = {'passed': True, 'bounded_ads_profile_established': True,
                                 'conditional_diagnostic': False, 'bounded_ads_profile': self.profile_identity}
        self.packet = Mock()
        self.profile = Mock()
        self.profile_failure = None
        self.replay_mutation = None
        self.collection_mutation = None
        self.copy_mutation = None
        self.build_identity = {'capture_context': deepcopy(CONTEXT), 'event_payload_sha256': 'b' * 64,
                               'pull_request': None}
        self.profile_oracle = self.root / 'evidence/precompiled-current-profile'
        self.profile_oracle.mkdir()
        self.profile_build_anchor = 'e' * 64
        self.current_profile_manifest = self.evidence / 'current-profile/current-profile.json'
        self.current_profile_sha256 = 'f' * 64
        self.current_profile_calls = []
        self.current_profile_failure = None
        self.checkout_failure = None
        self.leaf_mutation = None

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
        if self.leaf_mutation:
            self.leaf_mutation()
        return self.fake_leaf_result

    def enable_current_profile(self):
        self.args.update(current_profile_oracle=self.profile_oracle,
                         current_profile_receipt_sha256=self.profile_build_anchor)
        self.args.pop('reviewed_class')
        self.args.pop('expected_class_sha256')

    def run_current_profile(self, **kwargs):
        self.current_profile_calls.append(kwargs)
        self.assertEqual(kwargs['bound_source'], self.packet)
        self.assertTrue(kwargs['source_packet'].is_file())
        self.assertEqual(self.anchor.read_text().strip(), kwargs['source_receipt_sha256'])
        self.assertFalse(self.leaf_calls)
        if self.current_profile_failure:
            raise self.current_profile_failure
        write(self.current_profile_manifest, {'schema': 'synthetic current-profile orchestration'})
        return {'path': self.current_profile_manifest, 'sha256': self.current_profile_sha256}

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
            self.identity_check = stack.enter_context(patch.object(current, 'current_build_identity',
                side_effect=lambda: deepcopy(self.build_identity)))
            self.checkout_check = stack.enter_context(patch.object(current, 'check_build_checkout',
                side_effect=self.checkout_failure))
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
            stack.enter_context(patch.object(current.current_profile, 'run', side_effect=self.run_current_profile))
            stack.enter_context(patch.object(current.binding, 'bind_source_packet', return_value=self.packet))
            self.profile_bind = stack.enter_context(patch.object(current.leaf, 'bind_bounded_profile',
                return_value=self.profile, side_effect=self.profile_failure))
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
        self.assertFalse(self.current_profile_calls)
        self.assertEqual(self.identity_check.call_count, 3)
        self.assertEqual(self.checkout_check.call_count, 3)
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

    def test_current_profile_runs_after_source_binding_and_supplies_fresh_manifest_to_leaf(self):
        self.enable_current_profile()
        self.collection['images']['dx12']['typed_structure_failures'] = []
        result = self.call()
        self.assertTrue(result['passed'])
        self.assertEqual(result['build_identity'], self.build_identity)
        self.assertEqual(len(self.current_profile_calls), 1)
        call = self.current_profile_calls[0]
        self.assertEqual(call['profile_oracle'], self.profile_oracle)
        self.assertEqual(call['profile_oracle_receipt_sha256'], self.profile_build_anchor)
        self.assertEqual(call['capture_rustc_sha256'], self.compiler_anchor)
        self.assertEqual(call['build_identity'], self.build_identity)
        self.assertEqual(call['input_manifest'], self.input_manifest)
        self.assertEqual(call['root'], self.root)
        self.assertEqual(call['evidence'], self.evidence / 'current-profile')
        self.assertEqual(call['fallback_frames'], {'windows-legacy': [3, 17], 'dx12': []})
        self.assertEqual(self.profile_bind.call_args.args[2:4],
                         (self.current_profile_manifest, self.current_profile_sha256))
        self.assertEqual(self.leaf_calls[0]['reviewed_class'], self.current_profile_manifest)
        self.assertEqual(self.leaf_calls[0]['expected_class_sha256'], self.current_profile_sha256)
        request = json.loads((self.evidence / 'aggregate-supplement.json').read_text())
        self.assertEqual(request['reviewed_class'], str(self.current_profile_manifest))
        self.assertEqual(request['expected_class_sha256'], self.current_profile_sha256)
        for path, raw in self.originals.items():
            self.assertEqual(path.read_bytes(), raw)

    def test_current_profile_options_must_be_paired_and_not_mixed_with_history(self):
        original = self.args.copy()
        for options in ({'current_profile_oracle': self.profile_oracle},
                        {'current_profile_receipt_sha256': self.profile_build_anchor}):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, 'both required'):
                self.args = {**original, **options}
                self.call()
        self.args = {**original, 'current_profile_oracle': self.profile_oracle,
                     'current_profile_receipt_sha256': self.profile_build_anchor}
        with self.assertRaisesRegex(ValueError, 'cannot be combined'):
            self.call()
        self.assertFalse(self.evidence.exists())
        self.assertFalse(self.current_profile_calls)
        self.assertFalse(self.calls)

    def test_current_profile_failure_cannot_reach_leaf_or_supplement(self):
        self.enable_current_profile()
        self.current_profile_failure = ValueError('fresh profile remains unresolved')
        with self.assertRaisesRegex(ValueError, 'profile remains unresolved'):
            self.call()
        self.assertFalse(self.leaf_calls)
        self.assertFalse(self.profile_bind.called)
        self.assertTrue(self.anchor.is_file())
        self.assertFalse((self.evidence / 'aggregate-supplement.json').exists())
        report = json.loads((self.evidence / 'producer-summary.json').read_text())
        self.assertEqual(report['phase'], 'establish-current-finite-ads-profile')
        self.assertFalse(report['bounded_ads_profile_established'])

    def test_current_profile_is_not_run_for_an_original_pass(self):
        self.enable_current_profile()
        self.collection = None
        self.assertTrue(self.call()['passed'])
        self.assertFalse(self.current_profile_calls)
        self.assertFalse(self.calls)
        self.assertFalse(self.leaf_calls)
        self.assertEqual(self.identity_check.call_count, 2)
        self.assertEqual(self.checkout_check.call_count, 2)

    def test_same_commit_with_changed_event_identity_cannot_publish_source_packet(self):
        self.collection_mutation = lambda: self.build_identity.update(event_payload_sha256='9' * 64)
        with self.assertRaisesRegex(ValueError, 'execution identity changed'):
            self.call()
        self.assertFalse(self.anchor.exists())
        self.assertFalse(self.leaf_calls)
        self.assertFalse((self.evidence / 'aggregate-supplement.json').exists())

    def test_changed_identity_cannot_hide_behind_an_original_native_pass(self):
        self.collection = None
        self.collection_mutation = lambda: self.build_identity.update(event_payload_sha256='9' * 64)
        with self.assertRaisesRegex(ValueError, 'execution identity changed'):
            self.call()
        self.assertFalse(self.calls)
        self.assertFalse(self.current_profile_calls)
        self.assertFalse(json.loads((self.evidence / 'producer-summary.json').read_text())['passed'])

    def test_changed_event_identity_after_leaf_cannot_publish_supplement(self):
        self.leaf_mutation = lambda: self.build_identity.update(event_payload_sha256='9' * 64)
        with self.assertRaisesRegex(ValueError, 'execution identity changed'):
            self.call()
        self.assertEqual(len(self.leaf_calls), 1)
        self.assertFalse((self.evidence / 'aggregate-supplement.json').exists())

    def test_checkout_admission_failure_never_runs_replay_or_leaf(self):
        self.checkout_failure = ValueError('actual pull request merge parents differ')
        with self.assertRaisesRegex(ValueError, 'merge parents differ'):
            self.call()
        self.assertFalse(self.calls)
        self.assertFalse(self.current_profile_calls)
        self.assertFalse(self.leaf_calls)

    def test_cli_preserves_the_current_profile_package_and_external_anchor(self):
        args = ['--root', str(self.root), '--input-manifest', str(self.input_manifest),
                '--shards', str(self.shards), '--oracle', str(self.oracle),
                '--evidence', str(self.evidence), '--receipt-anchor', str(self.anchor),
                '--capture-rustc-sha256', self.compiler_anchor,
                '--expected-oracle-receipt-sha256', self.source_receipt_anchor,
                '--current-profile-oracle', str(self.profile_oracle),
                '--current-profile-receipt-sha256', self.profile_build_anchor]
        with patch.object(current, 'assemble', return_value={'passed': False}) as assemble:
            self.assertEqual(current.main(args), 0)
        self.assertEqual(assemble.call_args.kwargs['current_profile_oracle'], self.profile_oracle)
        self.assertEqual(assemble.call_args.kwargs['current_profile_receipt_sha256'], self.profile_build_anchor)
        self.assertIsNone(assemble.call_args.kwargs['reviewed_class'])
        self.assertIsNone(assemble.call_args.kwargs['expected_class_sha256'])

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
