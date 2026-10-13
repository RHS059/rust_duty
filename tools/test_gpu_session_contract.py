"""Synthetic evidence guards, not GPU execution or performance measurements."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import run_gpu_session_contract as contract
from test_summarize_cpu_substages import fixture as cpu_fixture
from test_summarize_gpu_timing import fixture as gpu_fixture
from test_summarize_frame_performance import present
from test_summarize_cpu_encode_detail import fixture as encode_fixture


def write(path, value):
    data = json.dumps(value).encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def fixture(root, enabled=True, opt_in=True):
    enabled = enabled and opt_in
    binding = {'source_commit': 'a' * 40, 'source_sha256': 'b' * 64}
    adapter = {'backend': 'Dx12', 'name': 'Microsoft Basic Render Driver', 'device_type': 'Cpu',
               'force_fallback_requested': True, 'gpu_timestamps_requested': opt_in, 'present_mode': 'Fifo',
               'gpu_timestamp_features_enabled': enabled,
               'instance_descriptor': encode_fixture()[0]['identity']['runtime_observed']['actual_adapter']['instance_descriptor']}
    completions = []
    for ordinal in range(2):
        report, sidecar, _, _ = gpu_fixture()
        _, cpu, _, _ = cpu_fixture()
        _, _, encode, _, _ = encode_fixture()
        runtime = report['identity']['runtime_observed']
        runtime.update(actual_backend='Dx12', actual_adapter=copy.deepcopy(adapter), build=dict(binding),
                       scene={'fixture': 'gpu-session-contract', 'ordinal': ordinal, 'gameplay': False})
        runtime['initial_window'].update(physical_width=1920, physical_height=1080)
        report['records'] = [present(100 * (i + 1), 100 if i else None) for i in range(contract.FRAMES)]
        end = contract.FRAMES * 100
        report.update(successful_present_count=contract.FRAMES, stop_requested_ns=end - 50,
                      stopped_at_ns=end, last_observed_ns=end)
        report['summary'].update(interval_count=contract.FRAMES - 1, total_interval_ns=end - 100)
        template = report['cpu_frame_stages']['samples'][0]
        cpu_template = cpu['samples'][0]
        encode_template = encode['samples'][0]
        gpu_template = sidecar['samples'][0]
        report['cpu_frame_stages']['samples'] = []
        cpu['samples'], sidecar['samples'], encode['samples'] = [], [], []
        for index in range(1, contract.FRAMES):
            offset = 100 * (index - 1)
            parent = copy.deepcopy(template)
            parent.update(record_index=index, started_at_ns=105 + offset, finished_at_ns=200 + offset,
                          physical_width=1920, physical_height=1080)
            for span in parent['spans'].values():
                span['started_at_ns'] += offset
                span['ended_at_ns'] += offset
            report['cpu_frame_stages']['samples'].append(parent)
            row = copy.deepcopy(cpu_template)
            row['record_index'] = index
            for span in row['details']['spans']:
                span['started_at_ns'] += offset
                span['ended_at_ns'] += offset
            cpu['samples'].append(row)
            row = copy.deepcopy(encode_template)
            row['record_index'] = index
            for span in row['details']['spans']:
                span['started_at_ns'] += offset
                span['ended_at_ns'] += offset
            encode['samples'].append(row)
            row = dict(gpu_template, session=ordinal + 1, attempt=index - 1, record_index=index)
            if not enabled or index == contract.FRAMES - 1:
                row.update(status='pending_at_stop' if enabled else 'device_features_not_enabled',
                           **dict.fromkeys(contract.gpu.NUMERIC))
            sidecar['samples'].append(row)
        sidecar['session'] = ordinal + 1
        sidecar['feature_negotiation'] = {'adapter_supports_required_features': enabled, 'device_features_enabled': enabled}
        if not enabled:
            sidecar['availability'] = {'state': 'device_features_not_enabled'}
        digest = write(root / f'session-{ordinal}.json', report)
        cpu['frame_report_sha256'] = sidecar['frame_report_sha256'] = encode['frame_report_sha256'] = digest
        if opt_in:
            write(root / f'session-{ordinal}.gpu-timing.json', sidecar)
        else:
            (root / f'session-{ordinal}.gpu-timing.json').unlink(missing_ok=True)
        write(root / f'session-{ordinal}.cpu-substages.json', cpu)
        write(root / f'session-{ordinal}.cpu-encode-detail.json', encode)
        start = contract.IDLE + ordinal * (contract.FRAMES + contract.IDLE)
        completions.append({'ordinal': ordinal, 'started_after_present': start,
                            'completed_after_present': start + contract.FRAMES,
                            'stop_before_final_present': True, 'completion_consumed_once': True})
    write(root / contract.REPORT, dict(binding, schema=contract.SCHEMA, status='passed', error=None,
        platform='windows', mode='enabled' if opt_in else 'default-off',
        gpu_timestamps_requested=opt_in, backend_evidence=adapter,
        frames_per_session=contract.FRAMES, idle_frames_before_each=contract.IDLE,
        successful_end_frames=137, attempts=137, sessions=completions))
    return binding


class GpuSessionContractTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.binding = fixture(self.root)

    def change(self, name, mutate):
        path = self.root / name
        value = json.loads(path.read_text())
        mutate(value)
        write(path, value)

    def validate(self):
        return contract.validate_outputs(self.root, self.binding)

    def test_two_realistic_sessions_allow_explicit_pending_tail(self):
        result = self.validate()
        self.assertTrue(result['passed'])
        self.assertTrue(result['measurement_path_verified'])
        self.assertEqual(result['session_ids'], [1, 2])
        self.assertEqual(result['sessions'][1]['status_counts']['pending_at_stop'], 1)
        self.assertNotIn('fps', result)

    def test_honestly_rehashed_wrong_physical_extent_fails(self):
        for width, height in ((1440, 900), (2880, 1620), (1920, 1040)):
            with self.subTest(extent=(width, height)):
                fixture(self.root)
                path = self.root / 'session-1.json'
                primary = json.loads(path.read_text())
                primary['identity']['runtime_observed']['initial_window'].update(
                    physical_width=width, physical_height=height)
                for sample in primary['cpu_frame_stages']['samples']:
                    sample.update(physical_width=width, physical_height=height)
                digest = write(path, primary)
                for suffix in ('cpu-substages', 'gpu-timing', 'cpu-encode-detail'):
                    self.change(f'session-1.{suffix}.json', lambda v: v.update(frame_report_sha256=digest))
                with self.assertRaisesRegex(ValueError, 'initial physical extent'):
                    self.validate()

    def test_honestly_rehashed_per_frame_extent_drift_fails(self):
        path = self.root / 'session-0.json'
        primary = json.loads(path.read_text())
        primary['cpu_frame_stages']['samples'][-1]['physical_width'] = 1919
        digest = write(path, primary)
        for suffix in ('cpu-substages', 'gpu-timing', 'cpu-encode-detail'):
            self.change(f'session-0.{suffix}.json', lambda v: v.update(frame_report_sha256=digest))
        with self.assertRaisesRegex(ValueError, 'CPU frame physical extent'):
            self.validate()

    def test_cpu_encode_details_are_required_in_both_gpu_modes(self):
        for opt_in in (True, False):
            with self.subTest(opt_in=opt_in):
                fixture(self.root, opt_in=opt_in)
                result = contract.validate_outputs(self.root, self.binding, opt_in=opt_in)
                self.assertEqual([s['summarized_attempts'] for s in result['cpu_encode_sessions']], [63, 63])
                (self.root / 'session-1.cpu-encode-detail.json').unlink()
                with self.assertRaisesRegex(ValueError, 'missing or unexpected'):
                    contract.validate_outputs(self.root, self.binding, opt_in=opt_in)

    def test_encode_sidecar_primary_binding_is_strict(self):
        self.change('session-0.cpu-encode-detail.json',
                    lambda v: v.update(frame_report_sha256='0' * 64))
        with self.assertRaisesRegex(ValueError, 'binding differs'):
            self.validate()

    def test_incomplete_encode_row_is_not_a_native_phase_pass(self):
        self.change('session-0.cpu-encode-detail.json',
                    lambda v: v['samples'][0]['details'].update(state='incomplete', error='synthetic'))
        with self.assertRaisesRegex(ValueError, 'CPU encode-detail accounting'):
            self.validate()

    def test_encode_child_must_fit_exact_retained_substage_parent(self):
        self.change('session-0.cpu-encode-detail.json',
                    lambda v: v['samples'][0]['details']['spans'][-1].update(ended_at_ns=171, duration_ns=11))
        with self.assertRaisesRegex(ValueError, 'outside its frame or parent span'):
            self.validate()

    def test_unsupported_device_is_unavailable_coverage_not_measured_pass(self):
        fixture(self.root, enabled=False)
        result = self.validate()
        self.assertFalse(result['measurement_path_verified'])
        self.assertEqual(result['measurement_path'], 'unavailable_device_features')
        self.assertTrue(all(s['measured_eligible_count'] == 0 for s in result['sessions']))

    def test_default_off_control_requires_no_gpu_sidecars(self):
        fixture(self.root, opt_in=False)
        result = contract.validate_outputs(self.root, self.binding, opt_in=False)
        self.assertTrue(result['passed'])
        self.assertEqual(result['measurement_path'], 'disabled_control')
        (self.root / 'session-0.gpu-timing.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            contract.validate_outputs(self.root, self.binding, opt_in=False)

    def test_native_default_off_only_forbids_gpu_output_after_completion(self):
        source = (Path(__file__).resolve().parents[1] / 'examples/gpu_session_contract.rs').read_text()
        completion = source.split('fn completed(', 1)[1].split('pub fn run()', 1)[0]
        absence = completion.split('} else {', 1)[1].split('let cpu =', 1)[0]
        self.assertIn('!path.with_extension("gpu-timing.json").exists()', absence)
        self.assertNotIn('cpu-substages.json', absence)
        self.assertNotIn('cpu-encode-detail.json', absence)
        for notice in ('take_cpu_substage_export_notice', 'take_cpu_encode_detail_export_notice'):
            self.assertGreaterEqual(completion.count(notice), 2)

    def test_default_off_rejects_enabled_device_features(self):
        fixture(self.root, opt_in=False)
        self.change(contract.REPORT, lambda v: v['backend_evidence'].update(gpu_timestamp_features_enabled=True))
        with self.assertRaisesRegex(ValueError, 'default-off constructor'):
            contract.validate_outputs(self.root, self.binding, opt_in=False)

    def test_present_mode_must_be_observed_fifo(self):
        self.change(contract.REPORT, lambda v: v['backend_evidence'].update(present_mode='AutoVsync'))
        with self.assertRaisesRegex(ValueError, 'Fifo'):
            self.validate()

    def test_enabled_but_zero_measured_fails_even_with_complete_accounting(self):
        def mutate(sidecar):
            for sample in sidecar['samples']:
                sample.update(status='pending_at_stop', **dict.fromkeys(contract.gpu.NUMERIC))
        self.change('session-1.gpu-timing.json', mutate)
        with self.assertRaisesRegex(ValueError, 'real measured'):
            self.validate()

    def test_reused_session_rejected_even_when_each_sidecar_is_internally_valid(self):
        def mutate(sidecar):
            sidecar['session'] = 1
            for sample in sidecar['samples']:
                sample['session'] = 1
        self.change('session-1.gpu-timing.json', mutate)
        with self.assertRaisesRegex(ValueError, 'reused'):
            self.validate()

    def test_stale_callback_cannot_claim_new_session(self):
        self.change('session-1.gpu-timing.json', lambda v: v['samples'][0].update(session=1))
        with self.assertRaisesRegex(ValueError, 'session/attempt'):
            self.validate()

    def test_unsupported_claim_cannot_hide_supported_but_disabled_features(self):
        fixture(self.root, enabled=False)
        self.change('session-0.gpu-timing.json', lambda v: v['feature_negotiation'].update(adapter_supports_required_features=True))
        with self.assertRaisesRegex(ValueError, 'supported timestamp'):
            self.validate()

    def test_successful_fixture_rejects_submission_failure_status(self):
        self.change('session-0.gpu-timing.json', lambda v: v['samples'][0].update(
            status='submission_rejected', **dict.fromkeys(contract.gpu.NUMERIC)))
        with self.assertRaisesRegex(ValueError, 'error/rejection'):
            self.validate()

    def test_honestly_rehashed_swapped_primary_still_fails_session_identity(self):
        path = self.root / 'session-1.json'
        value = json.loads(path.read_text())
        value['identity']['runtime_observed']['scene']['ordinal'] = 0
        digest = write(path, value)
        for suffix in ('gpu-timing', 'cpu-substages', 'cpu-encode-detail'):
            self.change(f'session-1.{suffix}.json', lambda v: v.update(frame_report_sha256=digest))
        with self.assertRaisesRegex(ValueError, 'primary identity'):
            self.validate()

    def test_primary_byte_mutation_invalidates_both_sidecars(self):
        path = self.root / 'session-1.json'
        path.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'binding'):
            self.validate()

    def test_wrong_build_identity_fails(self):
        self.change(contract.REPORT, lambda v: v.update(source_sha256='c' * 64))
        with self.assertRaisesRegex(ValueError, 'compiled fixture'):
            self.validate()

    def test_stop_completion_boolean_cannot_be_integer(self):
        self.change(contract.REPORT, lambda v: v['sessions'][0].update(stop_before_final_present=1))
        with self.assertRaisesRegex(ValueError, 'completion differs'):
            self.validate()

    def test_early_window_close_fails(self):
        self.change(contract.REPORT, lambda v: v.update(successful_end_frames=136))
        with self.assertRaisesRegex(ValueError, 'closed early'):
            self.validate()

    def test_missing_and_extra_evidence_rejected(self):
        (self.root / 'extra.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            self.validate()
        (self.root / 'extra.json').unlink()
        (self.root / 'session-1.gpu-timing.json').unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.validate()

    def test_nonwindows_runner_refuses_without_creating_evidence(self):
        output = self.root / 'not-created'
        with mock.patch.object(contract.sys, 'platform', 'linux'), self.assertRaisesRegex(ValueError, 'requires Windows'):
            contract.run(self.root, output)
        self.assertFalse(output.exists())

    def test_unbounded_timeout_refused_before_source_or_build(self):
        with mock.patch.object(contract.sys, 'platform', 'win32'):
            for value in (0, -1, float('nan'), float('inf'), True, 10 ** 400):
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'finite and positive'):
                    contract.run(self.root, self.root / 'new', build_timeout=value)


class BuildIdentityTests(unittest.TestCase):
    def test_process_receipt_must_match_the_freshly_built_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / 'evidence'
            binding = {'source_commit': '1' * 40, 'source_sha256': '2' * 64}
            build = mock.Mock()
            build.wait.return_value = 0
            def compiled(*args, **kwargs):
                executable = Path(kwargs['env']['CARGO_TARGET_DIR']) / 'debug/examples/gpu_session_contract.exe'
                executable.parent.mkdir(parents=True)
                executable.write_bytes(b'synthetic built executable; never run')
                return build
            with mock.patch.object(contract.sys, 'platform', 'win32'), \
                    mock.patch.object(contract, '__file__', str(root / 'tools/runner.py')), \
                    mock.patch.object(contract, 'source_binding', return_value=binding), \
                    mock.patch.object(contract.subprocess, 'check_output', return_value='synthetic rustc'), \
                    mock.patch.object(contract.subprocess, 'CREATE_NEW_PROCESS_GROUP', 0, create=True), \
                    mock.patch.object(contract.subprocess, 'Popen', side_effect=compiled), \
                    mock.patch.object(contract.process, 'run', return_value={'executable_sha256': '0' * 64}) as run:
                with self.assertRaisesRegex(ValueError, 'freshly built fixture'):
                    contract.run(root, evidence)
                self.assertEqual(run.call_count, 1)
            self.assertTrue((evidence / 'built-executable.json').exists())
            self.assertTrue((evidence / 'failure.json').exists())


class SourceBindingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        contract.git(self.root, 'init', '-q')
        (self.root / 'examples').mkdir()
        (self.root / 'examples/gpu_session_contract.rs').write_text('fn main() {}\n')
        (self.root / 'Cargo.toml').write_text('# synthetic public binding input\n')
        self.commit()
        # Preserve PATH/SystemRoot so temporary Git fixtures also work on Windows.
        # Only the source-binding inputs under test should be absent here.
        self.env = mock.patch.dict(contract.os.environ, {})
        self.env.start()
        self.addCleanup(self.env.stop)
        contract.os.environ.pop('VR_WEAPON_ASSET', None)
        contract.os.environ.pop('GITHUB_SHA', None)
        self.identity = mock.patch.object(contract.matrix, 'source_identity', side_effect=lambda root: {
            'commit': contract.git(root, 'rev-parse', 'HEAD').decode().strip(), 'runtime_files_sha256': {}})
        self.identity.start()
        self.addCleanup(self.identity.stop)

    def commit(self):
        contract.git(self.root, 'add', '.')
        contract.git(self.root, '-c', 'user.name=Synthetic fixture', '-c', 'user.email=fixture@example.invalid',
                     'commit', '-qm', 'Synthetic source binding test')

    def test_clean_committed_bytes_are_hashed_and_new_revision_changes_binding(self):
        before = contract.source_binding(self.root)
        self.assertIn('examples/gpu_session_contract.rs', before['files_sha256'])
        (self.root / 'Cargo.toml').write_text('# changed synthetic public input\n')
        self.commit()
        after = contract.source_binding(self.root)
        self.assertNotEqual(before['source_sha256'], after['source_sha256'])
        self.assertNotEqual(before['source_commit'], after['source_commit'])

    def test_dirty_tracked_source_rejected(self):
        (self.root / 'Cargo.toml').write_text('# dirty\n')
        with self.assertRaisesRegex(ValueError, 'tracked changes'):
            contract.source_binding(self.root)

    def test_untracked_compile_input_rejected(self):
        (self.root / 'src').mkdir()
        (self.root / 'src/new.rs').write_text('// original synthetic fixture\n')
        with self.assertRaisesRegex(ValueError, 'untracked compile'):
            contract.source_binding(self.root)

    def test_optional_weapon_is_rejected_without_reading_it(self):
        path = self.root / 'assets/weapons/hk416a5.vrm'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'original synthetic placeholder, not an asset')
        with self.assertRaisesRegex(ValueError, 'optional embedded weapon'):
            contract.source_binding(self.root)

    def test_ci_commit_mismatch_rejected(self):
        with mock.patch.dict(contract.os.environ, {'GITHUB_SHA': '0' * 40}), self.assertRaisesRegex(ValueError, 'GITHUB_SHA'):
            contract.source_binding(self.root)

    def test_ignored_cargo_configuration_is_not_silently_omitted(self):
        (self.root / '.git/info/exclude').write_text('.cargo/\n')
        (self.root / '.cargo').mkdir()
        (self.root / '.cargo/config.toml').write_text('# original synthetic config\n')
        with self.assertRaisesRegex(ValueError, 'untracked Cargo configuration'):
            contract.source_binding(self.root)

    def test_override_asset_path_rejected_without_access(self):
        for value in ('', '/never/read/asset.vrm'):
            with self.subTest(value=value), mock.patch.dict(contract.os.environ, {'VR_WEAPON_ASSET': value}), self.assertRaisesRegex(ValueError, 'must be unset'):
                contract.source_binding(self.root)


if __name__ == '__main__':
    unittest.main()
