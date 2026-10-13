"""Synthetic release-build protocol tests; no compiler or native game executes."""
import contextlib
import copy
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import build_performance_pair as builder


class BuildPerformancePairTests(unittest.TestCase):
    def flow(self, mutation=None, *, timeout=30, platform='win32', environment=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        home = Path(temporary.name).resolve()
        roots = {label: home / label for label in ('baseline', 'candidate')}
        output = home / 'build-evidence'
        candidate = {'Cargo.toml': b'synthetic Cargo manifest', 'Cargo.lock': b'synthetic locked graph',
                     'build.rs': b'synthetic build script', 'src/common.rs': b'unchanged implementation',
                     **{name: ('candidate ' + name).encode() for name in builder.pair.CPU_BASELINE}}
        old = {name: ('baseline ' + name).encode() for name in builder.pair.CPU_BASELINE}
        files = {'candidate': candidate, 'baseline': {**candidate, **old}}
        adjacent = {'ui/theme.css': b'original public style', 'settings.cfg': b'original public settings'}
        for label, root in roots.items():
            root.mkdir()
            for name, raw in {**files[label], **adjacent}.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
        runtime_paths = (*old, 'src/common.rs')
        sources = {label: {'commit': char * 40, 'runtime_files_sha256': builder.pair.hashes(
            {name: files[label][name] for name in runtime_paths})}
            for label, char in (('baseline', 'a'), ('candidate', 'b'))}
        toolchain = {'rustc': 'rustc 1.99.0 (synthetic)\nhost: x86_64-pc-windows-msvc\nrelease: 1.99.0\n',
                     'cargo': 'cargo 1.99.0 (synthetic)\n'}
        env = {key: value for key, value in os.environ.items()
               if key not in builder.pair.FORBIDDEN_ENV and not key.startswith(builder.pair.CONFIG_ENV_PREFIXES)}
        env.update(CARGO_HOME=str(home / 'cargo-home'), GITHUB_SHA=sources['candidate']['commit'],
                   GITHUB_REPOSITORY='RHS059/rust_duty', GITHUB_RUN_NUMBER='1', GITHUB_RUN_ID='123',
                   GITHUB_RUN_ATTEMPT='2', GITHUB_REF_NAME='synthetic-test-only', GITHUB_ACTIONS='true',
                   GITHUB_WORKFLOW_REF='RHS059/rust_duty/.github/workflows/build.yml@refs/heads/synthetic-test-only')
        env.pop('RUST_DUTY_BUILD_VERSION', None)
        env.update(environment or {})
        events, metadata_calls, config_checks = [], [], []
        self.last = {'roots': roots, 'output': output, 'sources': sources,
                     'files': files, 'events': events, 'metadata_calls': metadata_calls,
                     'toolchain': toolchain, 'config_checks': config_checks}

        if mutation == 'stale_output':
            output.mkdir()
        elif mutation == 'wrong_ci_source':
            env['GITHUB_SHA'] = 'c' * 40
        elif mutation == 'invalid_ci_identity':
            env['GITHUB_RUN_ID'] = 'not-a-real-run-number'
        elif mutation == 'private_asset':
            path = roots['candidate'] / 'assets/weapons/hk416a5.vrm'
            path.parent.mkdir(parents=True)
            path.write_bytes(b'synthetic bytes, not a weapon asset')
        elif mutation == 'ignored_updater_notice':
            path = roots['candidate'] / 'updater/notices/THIRD_PARTY_UPDATER_LICENSES.txt'
            path.parent.mkdir(parents=True)
            path.write_bytes(b'synthetic untracked compile-time input')
        elif mutation == 'checkout_drift':
            (roots['candidate'] / 'Cargo.toml').write_bytes(b'changed checkout only')
        elif mutation == 'extra_compile_input':
            files['candidate']['src/extra.rs'] = b'new unreviewed input'
            (roots['candidate'] / 'src/extra.rs').write_bytes(files['candidate']['src/extra.rs'])
        elif mutation == 'baseline_cargo_drift':
            files['baseline']['Cargo.lock'] = b'changed dependency graph'
            (roots['baseline'] / 'Cargo.lock').write_bytes(files['baseline']['Cargo.lock'])
        elif mutation == 'adjacent_drift':
            (roots['baseline'] / 'ui/theme.css').write_bytes(b'different public style')
        elif mutation in ('home_config', 'ancestor_config'):
            path = (home / 'cargo-home/config.toml' if mutation == 'home_config'
                    else home / '.cargo/config')
            path.parent.mkdir(parents=True)
            path.write_bytes(b'never read or executed')

        def label_for(root):
            return next(label for label, path in roots.items() if Path(root) == path)

        def git(root, *args):
            if args == ('rev-parse', 'HEAD^{tree}'):
                return (('0' * 40 if mutation == 'wrong_baseline_tree' else builder.BASELINE_TREE) + '\n').encode()
            if args[0] == 'status':
                return b' M src/common.rs\n' if mutation == 'dirty_checkout' else b''
            if args[0] == 'ls-files':
                return b'src/untracked.rs\n' if mutation == 'untracked_compile_input' else b''
            raise AssertionError('Unexpected synthetic Git command: ' + repr(args))

        def read_sources(root, commit, paths):
            label = label_for(root)
            self.assertEqual(commit, sources[label]['commit'])
            if paths == builder.pair.PRODUCTION_PATHS:
                return copy.deepcopy(files[label])
            self.assertEqual(paths, ['ui', 'settings.cfg'])
            value = copy.deepcopy(adjacent)
            if mutation == 'adjacent_drift' and label == 'baseline':
                value['ui/theme.css'] = b'different public style'
            return value

        def compiler(root):
            value = dict(toolchain)
            if mutation == 'wrong_compiler' or (mutation == 'cwd_compiler' and label_for(root) == 'baseline'):
                value['rustc'] = value['rustc'].replace('1.99.0', '1.98.0')
            if mutation == 'compiler_changed' and events:
                value['cargo'] = 'cargo 1.99.0 (changed after build)\n'
            return value

        check_config = builder.pair.check_cargo_configuration

        def configuration(root, build_env):
            config_checks.append(Path(root))
            return check_config(root, build_env)

        def logged(command, cwd, directory, build_env, build_timeout, executable_sha256=None):
            label = label_for(cwd)
            events.append(label)
            self.assertEqual(command, builder.COMMAND)
            self.assertEqual(build_timeout, timeout)
            self.assertIsNone(executable_sha256)
            self.assertEqual({name: build_env[name] for name in builder.SETTINGS}, builder.SETTINGS)
            self.assertEqual(Path(build_env['CARGO_TARGET_DIR']), output / label / 'target')
            directory.mkdir(parents=True)
            builder.matrix.write_json(directory / 'invocation.json', {
                'command': command, 'cwd': str(cwd), 'timeout_seconds': build_timeout,
                'executable_sha256': None})
            (directory / 'stdout.log').write_bytes(b'Synthetic compiler output only\n')
            (directory / 'stderr.log').write_bytes(b'')
            builder.matrix.write_json(directory / 'result.json', {'exit_code': 7 if mutation == 'build_failure' else 0})
            if mutation == 'build_failure':
                raise ValueError('build/control process failed; inspect retained logs')
            if mutation == 'timeout':
                raise subprocess.TimeoutExpired(command, build_timeout)
            target = Path(build_env['CARGO_TARGET_DIR']) / 'release/vector-range.exe'
            target.parent.mkdir(parents=True)
            target.write_bytes(b'MZ synthetic nonexecutable ' + label.encode())
            if mutation == 'source_changed':
                (Path(cwd) / 'Cargo.toml').write_bytes(b'changed after compiler launch')
            if mutation == 'new_config':
                path = Path(cwd) / '.cargo/config.toml'
                path.parent.mkdir()
                path.write_bytes(b'never read or executed')
            if label == 'candidate':
                targets = {
                    'earlier_executable': output / 'baseline/package/vector-range.exe',
                    'earlier_ui': output / 'baseline/package/ui/theme.css',
                    'earlier_identity': output / 'baseline/package/BUILD_IDENTITY.json',
                    'earlier_receipt': output / 'baseline/build-receipt.json',
                    'earlier_log': output / 'baseline/build/stdout.log',
                    'earlier_source': roots['baseline'] / 'Cargo.toml',
                    'earlier_witness': output / 'baseline/source-witness/src/common.rs',
                    'build_inputs': output / 'BUILD_INPUTS.json',
                }
                if mutation in targets:
                    path = targets[mutation]
                    self.assertTrue(path.is_file(), str(path))
                    path.write_bytes(path.read_bytes() + b' ')

        def metadata(command, **kwargs):
            self.assertIn(command[-1], ('--build-version', '--build-label'))
            self.assertEqual(kwargs['timeout'], 30)
            metadata_calls.append(list(command))
            if mutation == 'embedded_identity' or (mutation == 'embedded_label' and command[-1] == '--build-label'):
                return 'wrong embedded metadata'
            return '0.1.11' if command[-1] == '--build-version' else '0.1.11+build.123.2'

        with contextlib.ExitStack() as stack:
            patches = (
                mock.patch.dict(os.environ, env, clear=True),
                mock.patch.object(builder.sys, 'platform', platform),
                mock.patch.object(builder, '__file__', str(roots['candidate'] / 'tools/build_performance_pair.py')),
                mock.patch.object(builder.pair, 'git', side_effect=git),
                mock.patch.object(builder.pair, 'read_sources', side_effect=read_sources),
                mock.patch.object(builder.pair, 'toolchain_at', side_effect=compiler),
                mock.patch.object(builder.pair, 'check_cargo_configuration', side_effect=configuration),
                mock.patch.object(builder.pair, 'logged', side_effect=logged),
                mock.patch.object(builder.matrix, 'AUDITED_GPU_PRODUCTION_MANIFEST', builder.matrix.canonical_hash(
                    builder.pair.hashes({name: raw for name, raw in candidate.items() if name != 'src/extra.rs'}))),
                mock.patch.object(builder.pair, 'CPU_BASELINE', builder.pair.hashes(old)),
                mock.patch.object(builder.matrix, 'source_identity', side_effect=lambda root: copy.deepcopy(sources[label_for(root)])),
                mock.patch.object(builder.matrix, 'GPU_CANDIDATE_SOURCE_PATHS', runtime_paths),
                mock.patch.object(builder.matrix, 'AUDITED_GPU_CPU_BASELINE_MANIFEST',
                                  builder.matrix.canonical_hash(sources['baseline']['runtime_files_sha256'])),
                mock.patch.object(builder.matrix, 'AUDITED_GPU_CANDIDATE_MANIFEST',
                                  builder.matrix.canonical_hash(sources['candidate']['runtime_files_sha256'])),
                mock.patch.object(builder.build_identity, 'package_version', return_value='0.1.11'),
                mock.patch.object(builder.subprocess, 'check_output', side_effect=metadata),
                mock.patch.object(builder.subprocess, 'Popen', side_effect=AssertionError('Real process forbidden')),
            )
            for patch in patches:
                stack.enter_context(patch)
            return builder.build_pair(roots['candidate'], roots['baseline'], output, timeout)

    def test_fresh_pair_binds_exact_inputs_real_metadata_contract_and_fixed_release_command(self):
        result = self.flow()
        fixture = self.last
        self.assertEqual(fixture['events'], ['baseline', 'candidate'])
        self.assertEqual(len(fixture['metadata_calls']), 4)
        for label in ('baseline', 'candidate'):
            folder = fixture['output'] / label
            receipt = builder.matrix.json_read(folder / 'build-receipt.json')
            identity = builder.matrix.json_read(folder / 'package/BUILD_IDENTITY.json')
            self.assertEqual(identity['source']['commit'], fixture['sources'][label]['commit'])
            self.assertEqual(identity['source']['workflow'], '.github/workflows/build.yml')
            self.assertEqual(identity['display_version'], '0.1.11+build.123.2')
            self.assertEqual(receipt['production_files_sha256'], builder.pair.hashes(fixture['files'][label]))
            self.assertEqual(receipt['source_commit'], fixture['sources'][label]['commit'])
            self.assertEqual(receipt['ci_run_source_commit'], fixture['sources']['candidate']['commit'])
            self.assertEqual(receipt['command'], builder.COMMAND)
            self.assertEqual(receipt['build_settings'], builder.SETTINGS)
            self.assertEqual(receipt['toolchain'], fixture['toolchain'])
            self.assertEqual(receipt['build_result'], {'exit_code': 0})
            self.assertEqual(receipt['build_evidence_files_sha256'], builder.pair.controls.source_manifest(folder / 'build'))
            self.assertEqual(receipt['executable_sha256'], builder.matrix.sha256(folder / 'package/vector-range.exe'))
            self.assertEqual(result[label]['build_receipt_sha256'], builder.matrix.sha256(folder / 'build-receipt.json'))
            self.assertEqual(receipt['baseline_is_exact_four_file_counterfactual'], label == 'baseline')
            self.assertGreaterEqual(fixture['config_checks'].count(fixture['roots'][label]), 3)
            self.assertFalse((folder / 'package/assets').exists())
        summary = builder.matrix.json_read(fixture['output'] / 'BUILD_PAIR.json')
        self.assertTrue(summary['passed'])
        self.assertFalse(summary['runtime_executed'])

    def test_non_windows_and_invalid_timeouts_stop_before_build(self):
        with self.assertRaisesRegex(ValueError, 'Windows MSVC'):
            self.flow(platform='linux')
        for timeout in (True, 0, -1, float('nan'), float('inf'), 10**400):
            with self.subTest(timeout=timeout), self.assertRaisesRegex(ValueError, 'positive and finite'):
                self.flow(timeout=timeout)
            self.assertEqual(self.last['events'], [])

    def test_inherited_compiler_and_asset_overrides_stop_before_build(self):
        for name in ('RUSTFLAGS', 'RUSTC', 'CARGO_BUILD_RUSTC', 'CARGO_BUILD_RUSTC_WRAPPER',
                     'CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUSTFLAGS', 'CARGO_PROFILE_RELEASE_OPT_LEVEL',
                     'CARGO_SOURCE_CRATES_IO_REPLACE_WITH', 'RUSTUP_TOOLCHAIN', 'VR_WEAPON_ASSET'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'unset inherited'):
                self.flow(environment={name: ''})
            self.assertEqual(self.last['events'], [])

    def test_dirty_untracked_wrong_tree_and_stale_output_stop_before_build(self):
        for mutation in ('dirty_checkout', 'untracked_compile_input', 'wrong_baseline_tree', 'stale_output'):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.flow(mutation)
            self.assertEqual(self.last['events'], [])

    def test_closed_production_and_adjacent_inputs_stop_drift_before_build(self):
        for mutation in ('checkout_drift', 'extra_compile_input', 'baseline_cargo_drift',
                         'adjacent_drift', 'private_asset', 'ignored_updater_notice'):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.flow(mutation)
            self.assertEqual(self.last['events'], [])

    def test_actual_ci_identity_is_required_before_compilation(self):
        for mutation in ('wrong_ci_source', 'invalid_ci_identity'):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.flow(mutation)
            self.assertEqual(self.last['events'], [])

    def test_actual_workflow_matches_the_packaged_identity(self):
        for environment in ({'GITHUB_ACTIONS': 'false'}, {'GITHUB_WORKFLOW_REF': ''},
                            {'GITHUB_WORKFLOW_REF': 'RHS059/rust_duty/.github/workflows/other.yml@refs/heads/main'},
                            {'GITHUB_WORKFLOW_REF': 'other/repository/.github/workflows/build.yml@refs/heads/main'}):
            with self.subTest(environment=environment), self.assertRaisesRegex(ValueError, 'real build.yml'):
                self.flow(environment=environment)
            self.assertEqual(self.last['events'], [])

    def test_wrong_and_source_directory_selected_compilers_stop_before_build(self):
        for mutation in ('wrong_compiler', 'cwd_compiler'):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.flow(mutation)
            self.assertEqual(self.last['events'], [])

    def test_external_cargo_configuration_is_rejected_without_execution(self):
        for mutation in ('home_config', 'ancestor_config'):
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'unbound Cargo configuration'):
                self.flow(mutation)
            self.assertEqual(self.last['events'], [])

    def test_changed_source_compiler_or_config_after_build_never_produces_success(self):
        for mutation in ('source_changed', 'compiler_changed', 'new_config'):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.flow(mutation)
            self.assertEqual(self.last['events'], ['baseline'])
            self.assertFalse((self.last['output'] / 'BUILD_PAIR.json').exists())
            self.assertFalse(builder.matrix.json_read(self.last['output'] / 'BUILD_FAILURE.json')['passed'])

    def test_failed_build_or_timeout_retains_failure_and_never_builds_candidate(self):
        for mutation, error in (('build_failure', ValueError), ('timeout', subprocess.TimeoutExpired)):
            with self.subTest(mutation=mutation), self.assertRaises(error):
                self.flow(mutation)
            self.assertEqual(self.last['events'], ['baseline'])
            self.assertFalse((self.last['output'] / 'BUILD_PAIR.json').exists())
            self.assertFalse(builder.matrix.json_read(self.last['output'] / 'BUILD_FAILURE.json')['passed'])

    def test_embedded_build_identity_must_match_the_actual_ci_run(self):
        for mutation in ('embedded_identity', 'embedded_label'):
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'embedded game'):
                self.flow(mutation)
            self.assertEqual(self.last['events'], ['baseline'])
            self.assertFalse((self.last['output'] / 'BUILD_PAIR.json').exists())

    def test_later_build_cannot_mutate_earlier_retained_inputs_or_evidence(self):
        for mutation in ('earlier_executable', 'earlier_ui', 'earlier_identity', 'earlier_receipt',
                         'earlier_log', 'earlier_source', 'earlier_witness', 'build_inputs'):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.flow(mutation)
            self.assertEqual(self.last['events'], ['baseline', 'candidate'])
            self.assertFalse((self.last['output'] / 'BUILD_PAIR.json').exists())
            self.assertFalse(builder.matrix.json_read(self.last['output'] / 'BUILD_FAILURE.json')['passed'])


if __name__ == '__main__':
    unittest.main()
