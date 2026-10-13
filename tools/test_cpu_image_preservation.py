"""Original synthetic guards; no native binary or asset execution."""
import io
import os
from pathlib import Path
import subprocess
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

import run_cpu_image_preservation as image
import test_pass_submission_benchmark as shared_tests
import test_renderer_contract as renderer_tests


class SourcePairTests(unittest.TestCase):
    def setUp(self):
        self.production = {'Cargo.toml': b'original manifest',
                           **{name: ('new ' + name).encode() for name in image.CPU_BASELINE}}
        self.old = {name: ('old ' + name).encode() for name in image.CPU_BASELINE}
        self.harness = {name: ('shared ' + name).encode() for name in image.HARNESS_PATHS}
        for item in (patch.object(image, 'PRODUCTION_MANIFEST', image.matrix.canonical_hash(image.hashes(self.production))),
                     patch.object(image, 'CPU_BASELINE', image.hashes(self.old))):
            item.start()
            self.addCleanup(item.stop)

    def test_only_four_reviewed_cpu_files_differ_and_harness_is_shared(self):
        pair = image.source_pair(self.production, self.old, self.harness)
        self.assertEqual({name for name in pair['baseline'] if pair['baseline'][name] != pair['candidate'][name]},
                         set(self.old))
        self.assertEqual(pair['baseline']['Cargo.toml'], pair['candidate']['Cargo.toml'])
        for name, raw in self.harness.items():
            self.assertEqual(pair['baseline'][name], raw)
            self.assertEqual(pair['candidate'][name], raw)

    def test_unreviewed_changed_missing_or_added_production_is_rejected(self):
        for production in ({**self.production, 'Cargo.toml': b'changed'},
                           {k: v for k, v in self.production.items() if k != 'Cargo.toml'},
                           {**self.production, 'src/unreviewed.rs': b'extra'}):
            with self.subTest(production=production), self.assertRaisesRegex(ValueError, 'compile inventory'):
                image.source_pair(production, self.old, self.harness)

    def test_old_sources_and_common_harness_cannot_be_substituted(self):
        with self.assertRaisesRegex(ValueError, 'baseline CPU'):
            image.source_pair(self.production, {**self.old, 'extra.rs': b'extra'}, self.harness)
        with self.assertRaisesRegex(ValueError, 'both common'):
            image.source_pair(self.production, self.old, {**self.harness, 'src/override.rs': b'override'})

    def test_an_unchanged_cpu_file_is_not_a_four_file_experiment(self):
        changed = dict(self.production)
        key = next(iter(self.old))
        changed[key] = self.old[key]
        with patch.object(image, 'PRODUCTION_MANIFEST', image.matrix.canonical_hash(image.hashes(changed))):
            with self.assertRaisesRegex(ValueError, 'exactly the four'):
                image.source_pair(changed, self.old, self.harness)

    def test_prepare_binds_every_materialized_byte_without_running_any_program(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, raw in {**self.production, **self.harness}.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            def sources(_, commit, paths):
                if commit == image.BASELINE_CPU_COMMIT:
                    return self.old
                return self.harness if paths == image.HARNESS_PATHS else self.production
            binding = {'source_commit': 'a' * 40}
            with patch.object(image, '__file__', str(root / 'tools/run_cpu_image_preservation.py')), \
                    patch.object(image.session, 'source_binding', return_value=binding), \
                    patch.object(image, 'read_sources', side_effect=sources), \
                    patch.object(image.subprocess, 'Popen', side_effect=AssertionError('execution forbidden')):
                actual, receipts = image.prepare(root, root / 'evidence')
                self.assertEqual(actual, binding)
                image.verify_sources(receipts)
                receipt_path = receipts['baseline']['receipt_path']
                original_receipt = receipt_path.read_bytes()
                receipt_path.write_bytes(b'changed source receipt')
                with self.assertRaisesRegex(ValueError, 'source receipt changed'):
                    image.verify_sources(receipts)
                receipt_path.write_bytes(original_receipt)
                verifier_path = receipts['baseline']['verifier_path']
                original_verifier = verifier_path.read_bytes()
                verifier_path.write_bytes(b'changed verifier receipt')
                with self.assertRaisesRegex(ValueError, 'verifier receipt changed'):
                    image.verify_sources(receipts)
                verifier_path.write_bytes(original_verifier)
                target = receipts['baseline']['source'] / 'Cargo.toml'
                target.write_bytes(b'changed after preparation')
                with self.assertRaisesRegex(ValueError, 'variant source changed'):
                    image.verify_sources(receipts)
                with self.assertRaisesRegex(ValueError, 'stale'):
                    image.prepare(root, root / 'evidence')


class GeometrySourcePairTests(unittest.TestCase):
    def setUp(self):
        self.production = {'Cargo.toml': b'manifest', 'src/untouched.rs': b'unchanged',
                           image.UPLOAD_POLICY_PATH: b'pub const REUSE_ENABLED: bool = true;\n'}
        self.pin = patch.object(image, 'PRODUCTION_MANIFEST',
                                image.matrix.canonical_hash(image.hashes(self.production)))
        self.pin.start()
        self.addCleanup(self.pin.stop)

    def test_same_instrumentation_only_one_policy_line_changes(self):
        pair = image.geometry_production_pair(self.production)
        self.assertEqual(pair['candidate'], self.production)
        self.assertEqual(pair['baseline'][image.UPLOAD_POLICY_PATH],
                         b'pub const REUSE_ENABLED: bool = false;\n')
        self.assertEqual({name for name in self.production
                          if pair['baseline'][name] != pair['candidate'][name]}, {image.UPLOAD_POLICY_PATH})
        self.assertEqual(image.experiment_metadata('geometry-reuse')['upload_policies'],
                         {'baseline': 'immutable_per_frame_v1', 'candidate': 'bounded_reuse_v1'})
        self.assertFalse(image.experiment_metadata('geometry-reuse')['baseline_is_four_file_counterfactual'])
        self.assertTrue(image.experiment_metadata('cpu-overlay')['baseline_is_four_file_counterfactual'])

    def test_closed_inventory_rejects_extra_missing_or_changed_inputs(self):
        for production in ({**self.production, 'src/extra.rs': b'extra'},
                           {k: v for k, v in self.production.items() if k != 'Cargo.toml'},
                           {**self.production, 'src/untouched.rs': b'changed'}):
            with self.subTest(production=production), self.assertRaisesRegex(ValueError, 'compile inventory'):
                image.geometry_production_pair(production)

    def test_even_rebound_manifest_cannot_enable_a_missing_or_ambiguous_policy(self):
        for raw in (b'', image.UPLOAD_POLICY_DISABLED, image.UPLOAD_POLICY_ENABLED * 2,
                    image.UPLOAD_POLICY_ENABLED + image.UPLOAD_POLICY_DISABLED):
            production = {**self.production, image.UPLOAD_POLICY_PATH: raw}
            with self.subTest(raw=raw), patch.object(image, 'PRODUCTION_MANIFEST',
                    image.matrix.canonical_hash(image.hashes(production))):
                with self.assertRaisesRegex(ValueError, 'upload policy'):
                    image.geometry_production_pair(production)

    def test_unknown_experiment_is_not_a_source_alias(self):
        for value in ('reuse', 'baseline', None, True):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'unknown'):
                image.experiment_metadata(value)


class ArchiveTests(unittest.TestCase):
    def archive(self, name, kind=tarfile.REGTYPE):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w') as archive:
            item = tarfile.TarInfo(name)
            item.type = kind
            item.linkname = 'outside' if kind == tarfile.SYMTYPE else ''
            item.size = 0
            archive.addfile(item)
        return stream.getvalue()

    def test_safe_closed_source_archive(self):
        with patch.object(image, 'git', side_effect=[b'src/a.rs\0', self.archive('src/a.rs')]):
            self.assertEqual(image.read_sources(Path('.'), 'commit', ['src']), {'src/a.rs': b''})

    def test_symlinks_traversal_and_inventory_mismatch_fail(self):
        for name, kind in [('src/a.rs', tarfile.SYMTYPE), ('../escape.rs', tarfile.REGTYPE),
                           ('/absolute.rs', tarfile.REGTYPE), ('different.rs', tarfile.REGTYPE)]:
            with self.subTest(name=name), patch.object(image, 'git', side_effect=[b'src/a.rs\0', self.archive(name, kind)]):
                with self.assertRaises(ValueError):
                    image.read_sources(Path('.'), 'commit', ['src'])


class ControlArchiveTests(unittest.TestCase):
    def test_file_only_transport_preserves_empty_directory_and_strict_renderer_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / 'native'
            control = output / 'baseline-renderer_contract'
            renderer_tests.build_fixture(control)
            outputs = {control: image.controls.source_manifest(control)}
            directories = {control: image.directory_manifest(control)}
            self.assertIn('capture-is-directory.png', directories[control])
            self.assertTrue(image.renderer.validate_outputs(control)['passed'])
            receipt = image.archive_control_outputs(output, outputs, directories)
            download = root / 'file-only-download'
            download.mkdir()
            archive = download / receipt['file']
            shutil.copyfile(output / receipt['file'], archive)
            self.assertEqual(image.matrix.sha256(archive), receipt['sha256'])
            with image.zipfile.ZipFile(archive) as stored:
                self.assertIn('baseline-renderer_contract/capture-is-directory.png/', stored.namelist())
                stored.extractall(download / 'replay')  # Only this test's freshly authored fixture.
            replay = download / 'replay/baseline-renderer_contract'
            self.assertEqual(image.controls.source_manifest(replay), outputs[control])
            self.assertEqual(image.directory_manifest(replay), directories[control])
            self.assertTrue(image.renderer.validate_outputs(replay)['passed'])
            with self.assertRaises(FileExistsError):
                image.archive_control_outputs(output, outputs, directories)

    def test_missing_or_added_empty_directory_fails_even_when_file_bytes_match(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            control = root / 'control'
            control.mkdir()
            empty = control / 'capture-is-directory.png'
            empty.mkdir()
            outputs = {control: image.controls.source_manifest(control)}
            directories = {control: image.directory_manifest(control)}
            empty.rmdir()
            with self.assertRaisesRegex(ValueError, 'directories changed'):
                image.archive_control_outputs(root, outputs, directories)
            empty.mkdir()
            (control / 'unexpected-empty').mkdir()
            with self.assertRaisesRegex(ValueError, 'directories changed'):
                image.verify_retained_outputs(outputs, {}, directories)


class CompilerConfigurationTests(unittest.TestCase):
    def test_cargo_aliases_target_flags_and_profile_overrides_are_rejected(self):
        for key in ('RUSTC', 'RUSTC_WRAPPER', 'CARGO_BUILD_RUSTC', 'CARGO_BUILD_RUSTC_WRAPPER',
                    'CARGO_BUILD_RUSTC_WORKSPACE_WRAPPER', 'CARGO_BUILD_RUSTFLAGS',
                    'CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUSTFLAGS',
                    'CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER', 'CARGO_PROFILE_DEV_OPT_LEVEL',
                    'CARGO_SOURCE_CRATES_IO_REPLACE_WITH', 'VR_WEAPON_ASSET'):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'overrides'):
                image.check_environment({key: ''})
        image.check_environment({'PATH': 'normal path', 'CARGO_TARGET_DIR': 'replaced by isolated target'})

    def test_source_ancestors_and_cargo_home_both_config_spellings_are_probed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            source = root / 'nested/source'
            paths = image.cargo_config_paths(source, {'CARGO_HOME': str(root / 'cargo-home')})
            for directory in (source, source.parent, root):
                for name in ('config', 'config.toml'):
                    self.assertIn(directory / '.cargo' / name, paths)
            self.assertIn(root / 'cargo-home/config', paths)
            self.assertIn(root / 'cargo-home/config.toml', paths)
            relative = image.cargo_config_paths(source, {'CARGO_HOME': 'relative-home'})
            self.assertIn(source / 'relative-home/config.toml', relative)

    def test_unbound_config_is_rejected_without_reading_its_contents(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'config.toml'
            with patch.object(image, 'cargo_config_paths', return_value={config}):
                image.check_cargo_configuration(Path(folder), {})
                config.write_bytes(b'[build]\nrustc = "unreviewed-compiler"\n')
                with patch.object(Path, 'read_bytes', side_effect=AssertionError('must not read private config')):
                    with self.assertRaisesRegex(ValueError, 'unbound Cargo configuration'):
                        image.check_cargo_configuration(Path(folder), {})


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.exe = self.root / 'original-fixture.exe'
        self.exe.write_bytes(b'original synthetic nonexecutable bytes')
        self.sha = image.matrix.sha256(self.exe)
        self.child = Mock()
        self.child.wait.return_value = 0
        for item in (patch.object(image.subprocess, 'Popen', return_value=self.child),
                     patch.object(image.subprocess, 'CREATE_NEW_PROCESS_GROUP', 512, create=True)):
            self.mock = item.start()
            self.addCleanup(item.stop)

    def run_control(self, digest=None):
        image.logged([str(self.exe), '--output-dir', str(self.root / 'output')], self.root,
                     self.root / 'process', dict(os.environ), 1, self.sha if digest is None else digest)

    def test_success_retains_exact_command_exit_and_executable_identity(self):
        self.run_control()
        value = image.matrix.json_read(self.root / 'process/invocation.json')
        self.assertEqual(value['executable_sha256'], self.sha)
        self.assertEqual(value['command'][0], str(self.exe))
        self.assertEqual(image.matrix.json_read(self.root / 'process/result.json')['exit_code'], 0)

    def test_changed_executable_before_run_fails_without_execution(self):
        self.exe.write_bytes(b'replaced executable')
        with self.assertRaisesRegex(ValueError, 'before execution'):
            self.run_control()
        self.child.wait.assert_not_called()

    def test_changed_executable_during_run_fails(self):
        self.child.wait.side_effect = lambda **_: self.exe.write_bytes(b'replaced') and 0
        with self.assertRaisesRegex(ValueError, 'during execution'):
            self.run_control()
        self.assertTrue((self.root / 'process/failure.json').is_file())

    def test_timeout_uses_bounded_tree_cleanup_and_keeps_failure(self):
        self.child.wait.side_effect = subprocess.TimeoutExpired(['original'], 1)
        with patch.object(image.process, '_terminate_process_tree', return_value={'succeeded': True}) as cleanup:
            with self.assertRaises(subprocess.TimeoutExpired):
                self.run_control()
            cleanup.assert_called_once_with(self.child)
        self.assertTrue((self.root / 'process/cleanup.json').is_file())
        self.assertTrue((self.root / 'process/failure.json').is_file())

    def test_nonzero_exit_and_invalid_timeouts_fail(self):
        self.child.wait.return_value = 7
        with self.assertRaisesRegex(ValueError, 'process failed'):
            self.run_control()
        for timeout in (True, 0, -1, float('nan'), float('inf'), 10**400):
            with self.subTest(timeout=timeout), self.assertRaisesRegex(ValueError, 'finite and positive'):
                image.logged(['never'], self.root, self.root / 'unused', {}, timeout)

    def test_native_execution_is_rejected_on_non_windows_before_any_build(self):
        with patch.object(image.sys, 'platform', 'linux'), patch.object(image, 'prepare') as prepare:
            with self.assertRaisesRegex(ValueError, 'Windows DX12/WARP'):
                image.run(self.root, self.root / 'evidence')
            prepare.assert_not_called()

    def test_retained_output_and_binary_mutations_fail_before_acceptance(self):
        output = self.root / 'control'
        output.mkdir()
        capture = output / 'synthetic.png'
        capture.write_bytes(b'original output bytes')
        outputs = {output: image.controls.source_manifest(output)}
        binaries = {'baseline': {'control': {'path': self.exe, 'sha256': self.sha}}}
        image.verify_retained_outputs(outputs, binaries)
        capture.write_bytes(b'changed output bytes')
        with self.assertRaisesRegex(ValueError, 'control output changed'):
            image.verify_retained_outputs(outputs, binaries)
        capture.write_bytes(b'original output bytes')
        self.exe.write_bytes(b'changed retained executable')
        with self.assertRaisesRegex(ValueError, 'retained executable changed'):
            image.verify_retained_outputs(outputs, binaries)


class RunnerFlowTests(unittest.TestCase):
    """Simulate process results, never execute Windows code on the test host."""

    def run_flow(self, mutation=None):
        from PIL import Image
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        output = root / 'evidence'
        output.mkdir()
        receipts = {}
        verifier = output / 'verifier-source.json'
        verifier.write_bytes(b'original synthetic verifier receipt')
        for label in ('baseline', 'candidate'):
            source = root / (label + '-source')
            source.mkdir()
            (source / 'original.rs').write_bytes(label.encode())
            receipt_path = output / (label + '-source.json')
            receipt_path.write_bytes(('original ' + label + ' receipt').encode())
            receipts[label] = {'source': source, 'files': image.controls.source_manifest(source),
                               'receipt_path': receipt_path, 'receipt_sha256': image.matrix.sha256(receipt_path),
                               'verifier_path': verifier, 'verifier_sha256': image.matrix.sha256(verifier)}
        binding = {'source_commit': 'a' * 40}
        events = []

        def logged(command, cwd, directory, env, timeout, executable_sha256=None):
            directory.mkdir()
            label = 'baseline' if Path(cwd) == receipts['baseline']['source'] else 'candidate'
            if command[0] == 'cargo':
                events.append((label, 'build'))
                for name in image.EXAMPLES:
                    binary = Path(env['CARGO_TARGET_DIR']) / 'debug/examples' / (name + '.exe')
                    binary.parent.mkdir(parents=True, exist_ok=True)
                    binary.write_bytes((label + name).encode())
                if mutation == 'source-after-build' and label == 'baseline':
                    (Path(cwd) / 'original.rs').write_bytes(b'changed')
                return
            name = Path(command[0]).stem
            events.append((label, name))
            self.assertEqual(image.matrix.sha256(command[0]), executable_sha256)
            device = {'device_type': 'Cpu', 'vendor_id': 5140, 'device_id': 140,
                      'driver': 'synthetic', 'driver_info': '', 'present_mode': None,
                      'force_fallback_requested': True}
            (directory / 'stderr.log').write_text(
                'renderer requested=dx12 backend=Dx12 adapter=Microsoft Basic Render Driver\n'
                'renderer dx12_shader_compiler=Fxc\nrenderer device_evidence=' +
                image.json.dumps(device) + '\n')
            (directory / 'stdout.log').write_text('')
            captures = Path(command[command.index('--output-dir') + 1])
            captures.mkdir()
            if name == 'renderer_contract':
                # The fixed 21-image validator/comparator have their own real
                # PNG controls. Here their calls are verified, not reimplemented.
                (captures / 'synthetic.png').write_bytes(b'bound control')
                (captures / 'capture-is-directory.png').mkdir()
            else:
                control = Image.new('RGBA', (320, 180), (1, 2, 3, 255))
                control.putpixel((2, 3), (8, 9, 10, 255))
                control.save(captures / 'before.png')
                control.save(captures / 'after.png')
                report = shared_tests.Guards().report()
                report['source_receipt_sha256'] = env['PASS_SUBMISSION_SOURCE_SHA256']
                if mutation == 'wrong-compiled-receipt':
                    report['source_receipt_sha256'] = 'unbound'
                image.matrix.write_json(captures / 'report.json', report)
            if mutation == 'earlier-directory' and label == 'candidate' and name == 'renderer_contract':
                (output / 'baseline-renderer_contract/capture-is-directory.png').rmdir()
            if mutation == 'earlier-output' and label == 'candidate':
                (output / 'baseline-renderer_contract/synthetic.png').write_bytes(b'changed')

        def version(command, **kwargs):
            if mutation == 'different-cwd-toolchain' and Path(kwargs['cwd']) == receipts['baseline']['source']:
                return 'unreviewed directory-selected toolchain\n'
            return ('rustc 1.99.0\nhost: x86_64-pc-windows-msvc\nrelease: 1.99.0\n'
                    if command[0] == 'rustc' else 'cargo 1.99.0\n')

        with patch.dict(os.environ), patch.object(image.sys, 'platform', 'win32'), \
                patch.object(image, 'prepare', return_value=(binding, receipts)), \
                patch.object(image.session, 'source_binding', return_value=binding), \
                patch.object(image.subprocess, 'check_output', side_effect=version), \
                patch.object(image, 'check_cargo_configuration') as config, \
                patch.object(image, 'logged', side_effect=logged), \
                patch.object(image.renderer, 'validate_outputs', return_value={'passed': True, 'captures': 21}) as validate, \
                patch.object(image.controls, 'contract_pixels', return_value={'21': 'exact-pairs'}) as compare:
            for key in list(os.environ):
                if key in image.FORBIDDEN_ENV or key.startswith(image.CONFIG_ENV_PREFIXES):
                    os.environ.pop(key, None)
            result = image.run(root, output)
            self.assertEqual(validate.call_count, 2)
            self.assertEqual(config.call_count, 6)
            compare.assert_called_once()
        self.assertEqual(len(events), 6)
        return result

    def test_complete_flow_builds_both_and_requires_all_image_controls(self):
        result = self.run_flow()
        self.assertTrue(result['passed'])
        self.assertFalse(result['authored_acceptance'])
        self.assertFalse(result['gpu_lifecycle_verified'])
        self.assertIsNone(result['performance_improvement'])
        self.assertEqual(len(result['exact_mixed_pixels']), 4)
        self.assertEqual(len(result['control_output_files_sha256']), 4)
        self.assertEqual(result['control_outputs_archive']['file'], 'control-outputs.zip')
        self.assertIn('baseline-renderer_contract/capture-is-directory.png',
                      result['control_outputs_archive']['directories'])

    def test_changed_build_source_cannot_reach_a_pass(self):
        with self.assertRaisesRegex(ValueError, 'variant source changed'):
            self.run_flow('source-after-build')

    def test_wrong_compiled_source_receipt_cannot_reach_a_pass(self):
        with self.assertRaisesRegex(ValueError, 'source_receipt_sha256'):
            self.run_flow('wrong-compiled-receipt')

    def test_later_control_cannot_change_earlier_output(self):
        with self.assertRaisesRegex(ValueError, 'control output changed'):
            self.run_flow('earlier-output')

    def test_later_control_cannot_remove_earlier_empty_directory(self):
        with self.assertRaisesRegex(ValueError, 'directories changed'):
            self.run_flow('earlier-directory')

    def test_materialized_directory_toolchain_must_match_the_recorded_one(self):
        with self.assertRaisesRegex(ValueError, 'materialized source directory'):
            self.run_flow('different-cwd-toolchain')


if __name__ == '__main__':
    unittest.main()
