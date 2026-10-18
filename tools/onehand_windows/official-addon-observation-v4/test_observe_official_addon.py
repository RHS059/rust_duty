#!/usr/bin/env python3
"""Source-only synthetic regressions. Never executes Blender, Cargo or a shell.

Small ZIP fixtures use test-only monkeypatches of immutable production constants.
The production CLI has no synthetic/bypass or pin-override option.
"""
from __future__ import annotations

import ast
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
import types
import unittest
from unittest import mock
import warnings
import zipfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).absolute().parent))
import observe_official_addon as o

SENTINEL = 'PRIVATE_SENTINEL_DO_NOT_PUBLISH_7a31'
ACTUAL_NATIVE_SUMMARY = b'{"activation_authorized":false,"candidate_retention":"private runner-local until teardown","controller_config_canonical_sha256":"e229feab53475e330437b609be1aa4b261ca8cf449d25f9ef3199e1add121425","cross_platform_float64_equality_proved":false,"error_sha256":"8fbf4ddff747b03e580219fa0d2a3a80fb9b4c0664fdb437c1542514944ad737","error_type":"ContextError","game_capture_binding_reviewed":false,"game_capture_performed":false,"metadata_recipe_sha256":"24f8bb1872d2185d2ce550d701b87f10b42b55fcda15dff9f00faf6a49930906","passed":false,"private_raw_outputs_uploaded":false,"reproduction":["python","-I","-B","run_proof.py","--package-pins-sha256","<reviewed-package-sha256>","--config","<same-pinned-controller-config>","--config-sha256","<same-config-sha256>","run"],"runtime_asset_artifact_route":null,"schema":"rust-duty-onehand-windows-public-summary/v2","source_package_pins_sha256":"3b52a15fe761b9b1ae30b88caab7be132ad635f9aa2d070b6bb2f6d3133fbd71","source_projection_sha256":"4bf38952b5ff765ad65c8fab2c985303287b570b4a0d897eac28bf78e73bec1b","transport_pins_sha256":"d9ef5486cbd7d80ec8d4c9d37c556ff7d13d8dc0147cbd7e6244a4154ca79751"}\n'


def write_json(path, value):
    path.write_bytes(o.canonical(value) + b'\n')


def raw_name_zip_info(name):
    """Test-only malformed member; defeat ZipInfo's writer-side normalization.

    CPython's writer serializes filename, not orig_filename. Set both after
    construction so the actual local and central records retain hostile bytes.
    Production code and the reader's own normalization remain untouched.
    """
    info = zipfile.ZipInfo('fixture-placeholder')
    info.filename = info.orig_filename = name
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


class Fixture:
    def __init__(self, root):
        self.work = root / SENTINEL
        self.bundle = self.work / 'blender-official' / o.BUNDLE_NAME
        self.addon = self.bundle / '4.3' / 'scripts' / 'addons_core' / 'io_scene_fbx'
        self.context = self.work / 'admission' / 'full-materialized' / 'context-v3'
        self.source = self.context.parent / 'orchestration'
        self.evidence = self.work / 'proof' / 'public-evidence'
        self.candidate = self.work / 'proof' / 'private' / 'run-39103418788-attempt-1' / 'candidates' / 'onehand-v6-windows'
        self.process = self.candidate / 'process' / 'blender-host-observation'
        for path in (self.addon, self.context, self.source, self.evidence,
                     self.candidate / 'contexts', self.process):
            path.mkdir(parents=True)
        self.binary = self.bundle / 'blender.exe'
        self.binary.write_bytes(b'FAKE_NOT_EXECUTABLE_' + SENTINEL.encode())
        self.expected = {name: (name + '\n# synthetic\n').encode() for name in o.NAMES}
        self.members = {name: raw.replace(b'\n', b'\r\n') for name, raw in self.expected.items()}
        for name, raw in self.members.items():
            (self.addon / name).write_bytes(raw)
        addon_pins = {'schema': 'rust-duty-windows-official-fbx-pins/v2',
                      'profile_id': o.PROFILE_ID, 'blender_version': [4, 3, 2],
                      'distribution': copy.deepcopy(o.PROFILE_DISTRIBUTION),
                      'observation': copy.deepcopy(o.PROFILE_OBSERVATION),
                      'hash_domains': copy.deepcopy(o.PROFILE_HASH_DOMAINS),
                      'files': {name: o.sha(raw) for name, raw in self.members.items()},
                      'file_metadata': {name: {key: o.newline_stats(raw)[key] for key in
                          ('bytes', 'crlf_count', 'bare_lf_count', 'bare_cr_count')}
                          for name, raw in self.members.items()},
                      'raw_functions_sha256': {'import_fbx.py': {
                          'blen_read_animations': 'a' * 64, 'blen_store_keyframes_multi': 'b' * 64}},
                      'loaded_functions_sha256': {'import_fbx.py': {
                          'blen_read_animations': 'c' * 64, 'blen_store_keyframes_multi': 'd' * 64}}}
        write_json(self.context / 'OFFICIAL_ADDON_PINS.json', addon_pins)
        addon_sha = o.sha((self.context / 'OFFICIAL_ADDON_PINS.json').read_bytes())
        write_json(self.context / 'PINS.json', {'OFFICIAL_ADDON_PINS.json': addon_sha})
        (self.source / 'probe_blender.py').write_bytes(b'# synthetic probe source, never executed\n')
        probe_source_sha = o.sha((self.source / 'probe_blender.py').read_bytes())
        write_json(self.source / 'PINS.json', {'probe_blender.py': probe_source_sha})
        self.patches = {'ADDON_PINS_SHA': addon_sha,
                        'CONTEXT_PINS_SHA': o.sha((self.context / 'PINS.json').read_bytes()),
                        'PROBE_SOURCE_SHA': probe_source_sha,
                        'ORCHESTRATION_PINS_SHA': o.sha((self.source / 'PINS.json').read_bytes())}
        self.archive = self.work / 'blender-official.zip'
        self.receipt = self.work / 'blender-install.json'
        self.checksum = self.work / 'blender-official.vendor.sha256'
        self.write_archive()
        self.config = {'byte_checkout': {'path': SENTINEL, 'sha256': '0' * 64},
                       'candidate_id': 'onehand-v6-windows',
                       'session_id': 'run-39103418788-attempt-1',
                       'runner_id': 'runner-' + 'a' * 24,
                       'run_id': 'run-39103418788-attempt-1',
                       'private_root': str(self.work / 'proof' / 'private'),
                       'evidence_root': str(self.evidence),
                       'roots': {'blender_bundle': str(self.bundle), 'context_package': str(self.context)},
                       'inputs': {'private': SENTINEL}, 'authored_bridge': SENTINEL,
                       'blender_install_receipt': str(self.receipt),
                       'native_environment': {'PRIVATE': SENTINEL},
                       'runtime_environment': {'PRIVATE': SENTINEL}, 'rust': {'private': SENTINEL}}
        self.config_path = self.work / 'controller.json'
        self.write_config()
        self.probe = {'schema': 'rust-duty-official-blender-host-observation/v1',
                      'blender_version': [4, 3, 2], 'blender_build_hash': '32f5fdce0a0a',
                      'blender_binary': str(self.binary), 'blender_binary_sha256': o.sha(self.binary.read_bytes()),
                      'python_runtime': str(self.bundle / SENTINEL), 'python_runtime_sha256': 'a' * 64,
                      'fbx_addon_file': str(self.addon / '__init__.py'), 'background': True,
                      'autoexec_disabled': True, 'source_saved': False, 'rendered': False}
        self.probe_path = self.candidate / 'blender-observed.json'
        write_json(self.probe_path, self.probe)
        argv = [str(self.binary), '--background', '--factory-startup', '--disable-autoexec',
                '--threads', '1', '--python-exit-code', '1', '--python',
                str(self.source / 'probe_blender.py'), '--', str(self.probe_path)]
        self.command = {'schema': 'rust-duty-onehand-controller-command/v1',
                        'label': 'blender-host-observation', 'argv': argv,
                        'cwd': str(self.candidate), 'executable': {'path': str(self.binary),
                         'sha256': self.probe['blender_binary_sha256']},
                        'environment_sha256': o.sha(o.canonical(self.config['native_environment'])),
                        'host': {'private': SENTINEL}}
        self.command_path = self.candidate / 'contexts' / 'blender-host-observation-command.json'
        write_json(self.command_path, self.command)
        self.terminal = {'schema': 'rust-duty-owned-process/v1', 'command': argv,
                         'cwd': str(self.candidate), 'state': 'completed', 'completed': True,
                         'exit_code': 0, 'windows_job_empty_verified': True,
                         'cleanup_complete': True, 'consumer_complete': True,
                         'timed_out': False, 'resource_stop_reason': None,
                         'host_binding': {'context_sha256': o.sha(o.canonical(self.command)),
                           'run_id': self.config['run_id'], 'runner_id': self.config['runner_id'],
                           'owner_lock': str(self.candidate.parent.parent / 'native-owner.lock'),
                           'environment_sha256': o.sha(o.canonical(self.config['native_environment']) + b'\n'),
                           'environment_keys': sorted(self.config['native_environment']),
                           'observed_host': {'system': 'Windows'}, 'private': SENTINEL}}
        self.write_terminal()
        (self.evidence / 'summary.json').write_bytes(ACTUAL_NATIVE_SUMMARY)
        self.output = self.evidence / 'official-addon-observation.json'

    def write_archive(self, extras=()):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(self.archive, 'w', zipfile.ZIP_DEFLATED) as zf:
                prefix = o.BUNDLE_NAME + '/' + self.addon.relative_to(self.bundle).as_posix() + '/'
                for name, raw in self.members.items():
                    zf.writestr(prefix + name, raw)
                for name, raw in extras:
                    zf.writestr(name, raw)
        archive_raw = self.archive.read_bytes()
        self.patches.update(ARCHIVE_SHA=o.sha(archive_raw), ARCHIVE_BYTES=len(archive_raw))
        self.checksum.write_bytes((o.sha(archive_raw) + '  ' + o.ARCHIVE_NAME + '\r\n').encode())
        write_json(self.receipt, {'schema': 'rust-duty-onehand-official-blender-install/v1',
                    'version': '4.3.2', 'vendor_checksum_url': o.VENDOR + 'blender-4.3.2.sha256',
                    'archive_url': o.VENDOR + o.ARCHIVE_NAME, 'vendor_sha256': o.sha(archive_raw),
                    'archive_sha256': o.sha(archive_raw), 'archive_bytes': len(archive_raw),
                    'archive_path': str(self.archive), 'bundle_root': str(self.bundle),
                    'executable_sha256': o.sha(self.binary.read_bytes()), 'vendor_checksum_verified': True,
                    'vendor_checksum_file': {'path': str(self.checksum), 'sha256': o.sha(self.checksum.read_bytes())}})

    def write_config(self):
        write_json(self.config_path, self.config)
        self.config_sha = o.sha(self.config_path.read_bytes())

    def write_terminal(self):
        write_json(self.process / 'terminal.json', self.terminal)
        raw = (self.process / 'terminal.json').read_bytes()
        write_json(self.process / 'terminal.sha256.json',
                   {'path': 'terminal.json', 'sha256': o.sha(raw), 'bytes': len(raw)})

    def run(self):
        with mock.patch.multiple(o, **self.patches):
            return o.observe(self.work, self.config_path, self.config_sha, '39103418788', '1')


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = Fixture(Path(self.temp.name).absolute())

    def assert_rejected(self, code=None):
        if code:
            with self.assertRaisesRegex(o.ObservationError, code):
                self.f.run()
        else:
            with self.assertRaises(Exception):
                self.f.run()
        self.assertFalse(self.f.output.exists())

    def assert_stored_zip_spelling(self, raw, expected):
        """Assert actual central/local header bytes before production reads them."""
        end = raw.rfind(b'PK\x05\x06')
        self.assertGreaterEqual(end, 0)
        entries = struct.unpack_from('<H', raw, end + 10)[0]
        cursor = struct.unpack_from('<L', raw, end + 16)[0]
        names = []
        for _ in range(entries):
            self.assertEqual(raw[cursor:cursor + 4], b'PK\x01\x02')
            name_size, extra_size, comment_size = struct.unpack_from('<3H', raw, cursor + 28)
            name = raw[cursor + 46:cursor + 46 + name_size]
            local = struct.unpack_from('<L', raw, cursor + 42)[0]
            self.assertEqual(raw[local:local + 4], b'PK\x03\x04')
            local_name_size = struct.unpack_from('<H', raw, local + 26)[0]
            self.assertEqual(raw[local + 30:local + 30 + local_name_size], name)
            names.append(name)
            cursor += 46 + name_size + extra_size + comment_size
        self.assertEqual(cursor, end)
        self.assertEqual(names.count(expected.encode('ascii')), 1)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            self.assertEqual([info.orig_filename.encode('ascii') for info in zf.infolist()], names)

    @contextlib.contextmanager
    def windows_stat_domains(self, path, *, handle_change=None, path_change=None):
        """Model exact CPython 3.12 timestamp semantics around a real file.

        This is source-only simulation, never a claim of Windows execution.
        No path/file checks are bypassed: real lstat/fstat still happen first.
        """
        path = Path(path)
        real_lstat, real_fstat = Path.lstat, os.fstat
        base = real_lstat(path)
        birthtime = getattr(base, 'st_birthtime_ns', base.st_ctime_ns)
        handle_calls = 0

        def shape(value, is_handle):
            values = {name: getattr(value, name) for name in (
                'st_mode', 'st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_nlink')}
            values.update(st_birthtime_ns=birthtime,
                          st_file_attributes=getattr(value, 'st_file_attributes', 0))
            values['st_ctime_ns'] = birthtime + 100 if is_handle else birthtime
            return values

        def lstat(current, *args, **kwargs):
            value = real_lstat(current, *args, **kwargs)
            if current != path:
                return value
            values = shape(value, False)
            if path_change:
                path_change(values)
            return types.SimpleNamespace(**values)

        def fstat(fd):
            nonlocal handle_calls
            value = real_fstat(fd)
            if (value.st_dev, value.st_ino) != (base.st_dev, base.st_ino):
                return value
            handle_calls += 1
            values = shape(value, True)
            if handle_change:
                handle_change(values, handle_calls)
            return types.SimpleNamespace(**values)

        with mock.patch.object(Path, 'lstat', lstat), mock.patch.object(os, 'fstat', fstat), \
                mock.patch.object(o.sys, 'platform', 'win32'):
            yield

    def test_windows_ctime_domain_reproduction_and_correction(self):
        path = self.f.config_path
        raw = path.read_bytes()
        before = path.lstat()
        fields = {name: getattr(before, name) for name in (
            'st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_nlink')}
        path_stat = types.SimpleNamespace(**fields, st_birthtime_ns=before.st_ctime_ns)
        fields['st_ctime_ns'] += 100
        handle_stat = types.SimpleNamespace(**fields, st_birthtime_ns=before.st_ctime_ns)
        # identity() is byte-identical to v1: the old cross-API comparison fails.
        self.assertNotEqual(o.identity(path_stat), o.identity(handle_stat))
        with mock.patch.object(o.sys, 'platform', 'win32'):
            self.assertEqual(o.path_handle_identity(path_stat), o.path_handle_identity(handle_stat))
        with self.windows_stat_domains(path):
            self.assertEqual(o.read_bytes(path, o.MIB), raw)

    def test_windows_cross_domain_file_replacement_and_changes_rejected(self):
        for field in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_birthtime_ns', 'st_nlink'):
            with self.subTest(field=field):
                def change(values, _):
                    values[field] += 1
                with self.windows_stat_domains(self.f.config_path, handle_change=change):
                    with self.assertRaisesRegex(o.ObservationError, 'input_changed_before_read'):
                        o.read_bytes(self.f.config_path, o.MIB)

    def test_windows_handle_change_time_mutation_still_rejected(self):
        def change(values, call):
            if call >= 2:
                values['st_ctime_ns'] += 1
        with self.windows_stat_domains(self.f.config_path, handle_change=change):
            with self.assertRaisesRegex(o.ObservationError, 'input_changed_during_read'):
                o.read_bytes(self.f.config_path, o.MIB)

    def test_windows_handle_identity_mutations_still_rejected(self):
        for field in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_nlink'):
            with self.subTest(field=field):
                def change(values, call):
                    if call >= 2:
                        values[field] += 1
                with self.windows_stat_domains(self.f.config_path, handle_change=change):
                    with self.assertRaisesRegex(o.ObservationError, 'input_changed_during_read'):
                        o.read_bytes(self.f.config_path, o.MIB)

    def test_windows_path_snapshot_mutations_still_rejected(self):
        for field in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'):
            with self.subTest(field=field):
                changed = False
                def change(values):
                    if changed:
                        values[field] += 1
                with self.windows_stat_domains(self.f.config_path, path_change=change):
                    with self.assertRaisesRegex(o.ObservationError, 'input_changed_after_read'):
                        with o.open_read(self.f.config_path, o.MIB) as stream:
                            stream.read()
                            changed = True

    def test_windows_missing_birthtime_or_file_identity_rejected(self):
        info = self.f.config_path.lstat()
        fields = {name: getattr(info, name) for name in (
            'st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_nlink')}
        with mock.patch.object(o.sys, 'platform', 'win32'):
            with self.assertRaisesRegex(o.ObservationError, 'windows_file_identity_unavailable'):
                o.path_handle_identity(types.SimpleNamespace(**fields))
            fields.update(st_ino=0, st_birthtime_ns=1)
            with self.assertRaisesRegex(o.ObservationError, 'windows_file_identity_unavailable'):
                o.path_handle_identity(types.SimpleNamespace(**fields))

    def test_linux_cross_domain_identity_keeps_full_ctime(self):
        info = self.f.config_path.lstat()
        with mock.patch.object(o.sys, 'platform', 'linux'):
            self.assertEqual(o.path_handle_identity(info), o.identity(info))
            changed = types.SimpleNamespace(**{name: getattr(info, name) for name in (
                'st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_nlink')})
            changed.st_ctime_ns += 1
            self.assertNotEqual(o.path_handle_identity(info), o.path_handle_identity(changed))

    def test_real_file_path_handle_binding_on_current_platform(self):
        path = self.f.work / 'real-file-domain-check.bin'
        path.write_bytes(b'original bytes\n')
        initial = path.stat()
        os.utime(path, ns=(initial.st_atime_ns, initial.st_mtime_ns + 2000000000))
        with o.open_read(path, 1024) as stream:
            self.assertEqual(o.path_handle_identity(path.lstat()), o.path_handle_identity(os.fstat(stream.fileno())))
            self.assertEqual(stream.read(), b'original bytes\n')

    def test_real_file_in_place_mutation_rejected(self):
        path = self.f.work / 'in-place-change.bin'
        path.write_bytes(b'original')
        with self.assertRaisesRegex(o.ObservationError, 'input_changed_during_read'):
            with o.open_read(path, 1024) as stream:
                stream.read()
                path.write_bytes(b'modified bytes with different size')

    def test_real_production_identity_constants(self):
        self.assertEqual(o.ARCHIVE_BYTES, 405138423)
        self.assertEqual(o.ARCHIVE_SHA, '933a62a770c941e316535f893629ff106ddd2aa5a956f0081ec557439073d4f6')
        self.assertEqual(o.ADDON_PINS_SHA, '710ac9f97ba798dda2b4091232215bf0d973a03a07703448d184b420f5addb4f')
        self.assertEqual(o.CONTEXT_PINS_SHA, '8702d486bc36a649924c3d844ea5eab445600f93995ec8367ea02d94e250c48a')
        self.assertEqual(len(o.NAMES), 10)

    def test_newline_counts_and_diagnostic_normalization(self):
        row = o.newline_stats(b'a\r\nb\nc\rd\r\n')
        self.assertEqual((row['crlf_count'], row['bare_lf_count'], row['bare_cr_count']), (2, 1, 1))
        self.assertEqual(row['diagnostic_crlf_to_lf_sha256'], o.sha(b'a\nb\nc\rd\n'))
        self.assertNotEqual(row['raw_sha256'], row['diagnostic_crlf_to_lf_sha256'])

    def test_crlf_only_difference_is_recorded_never_admitted(self):
        for name, raw in self.f.expected.items():
            (self.f.addon / name).write_bytes(raw)
        before = (self.f.evidence / 'summary.json').read_bytes()
        result = self.f.run()
        self.assertEqual(result['status'], 'observed_diagnostic_only')
        self.assertEqual(len(result['files']), 10)
        for row in result['files']:
            self.assertFalse(row['archive_equals_installed'])
            self.assertFalse(row['installed_raw_matches_expected'])
            self.assertTrue(row['archive_raw_matches_expected'])
            self.assertEqual(row['expected_raw_sha256'], row['archive']['raw_sha256'])
            self.assertEqual(row['installed']['raw_sha256'], row['archive']['diagnostic_crlf_to_lf_sha256'])
        self.assertFalse(result['normalized_hash_acceptance'])
        self.assertFalse(result['native_admission'])
        self.assertFalse(result['animation_proof'])
        self.assertFalse(result['original_native_outcome']['passed'])
        self.assertEqual(result['original_native_outcome']['error_type'], 'ContextError')
        self.assertEqual(result['original_native_outcome']['error_sha256'], o.KNOWN_FAILURE_SHA)
        self.assertEqual(before, (self.f.evidence / 'summary.json').read_bytes())
        self.assertEqual(result['original_native_outcome']['summary_sha256'], o.sha(ACTUAL_NATIVE_SUMMARY))

    def test_archive_vs_installed_difference_is_measured(self):
        (self.f.addon / 'data_types.py').write_bytes(b'changed\n')
        rows = self.f.run()['files']
        row = next(x for x in rows if x['relative_filename'] == 'data_types.py')
        self.assertFalse(row['archive_equals_installed'])
        self.assertNotEqual(row['archive']['raw_sha256'], row['installed']['raw_sha256'])

    def test_raw_expected_match_still_does_not_admit(self):
        for name, raw in self.f.members.items():
            (self.f.addon / name).write_bytes(raw)
        result = self.f.run()
        self.assertTrue(all(r['installed_raw_matches_expected'] for r in result['files']))
        self.assertFalse(result['native_admission'])
        self.assertFalse(result['original_native_outcome']['passed'])

    def test_original_nonaddon_failure_preserved(self):
        value = json.loads(ACTUAL_NATIVE_SUMMARY)
        value.update(error_type='ValueError', error_sha256=o.sha(b'different original failure'))
        write_json(self.f.evidence / 'summary.json', value)
        result = self.f.run()
        self.assertEqual(result['original_native_outcome']['error_sha256'], value['error_sha256'])
        self.assertEqual(result['original_native_outcome']['error_type'], 'ValueError')

    def test_missing_probe_reports_unavailable(self):
        self.f.probe_path.unlink()
        result = self.f.run()
        self.assertEqual(result['status'], 'observation_unavailable')
        self.assertEqual(result['reason'], 'original_probe_missing')
        self.assertEqual(result['files'], [])
        self.assertFalse(result['native_admission'])

    def test_missing_terminal_reports_unavailable(self):
        (self.f.process / 'terminal.json').unlink()
        result = self.f.run()
        self.assertEqual(result['status'], 'observation_unavailable')
        self.assertEqual(result['reason'], 'retained_process_context_missing')

    def test_missing_installed_member_rejected(self):
        (self.f.addon / 'data_types.py').unlink()
        self.assert_rejected('required_path_missing')

    def test_missing_zip_member_rejected(self):
        del self.f.members['data_types.py']
        self.f.write_archive()
        self.assert_rejected('archive_member_missing')

    def test_candidate_identity_cannot_escape(self):
        self.f.config['session_id'] = '../escape'
        self.f.write_config()
        self.assert_rejected('candidate_identity_differs')

    def test_config_raw_sha_required(self):
        self.f.config_path.write_bytes(self.f.config_path.read_bytes() + b' ')
        self.assert_rejected('input_pin_mismatch')

    def test_context_manifest_raw_pin_required(self):
        path = self.f.context / 'OFFICIAL_ADDON_PINS.json'
        path.write_bytes(path.read_bytes() + b' ')
        self.assert_rejected('input_pin_mismatch')

    def test_evidence_root_cannot_escape(self):
        self.f.config['evidence_root'] = str(self.f.work)
        self.f.write_config()
        self.assert_rejected('path_binding_differs')

    def test_observed_addon_cannot_escape_bundle(self):
        foreign = self.f.work / '__init__.py'
        foreign.write_bytes(b'foreign')
        self.f.probe['fbx_addon_file'] = str(foreign)
        write_json(self.f.probe_path, self.f.probe)
        self.assert_rejected('probe_addon_escape')

    def test_archive_path_cannot_escape(self):
        value = json.loads(self.f.receipt.read_bytes())
        foreign = self.f.work / 'foreign.zip'
        foreign.write_bytes(self.f.archive.read_bytes())
        value['archive_path'] = str(foreign)
        write_json(self.f.receipt, value)
        self.assert_rejected('path_binding_differs')

    def test_archive_raw_pin_required(self):
        raw = self.f.archive.read_bytes()
        self.f.archive.write_bytes(b'X' + raw[1:])
        self.assert_rejected('official_archive_pin_differs')

    def test_vendor_checksum_required(self):
        self.f.checksum.write_bytes(b'wrong')
        self.assert_rejected('vendor_checksum_pin_differs')

    def test_binary_raw_hash_required(self):
        self.f.binary.write_bytes(b'changed')
        self.assert_rejected('installed_binary_pin_differs')

    def test_probe_version_and_action_contract(self):
        for key, value in (('blender_version', [4, 3, 3]), ('rendered', True),
                           ('source_saved', True), ('background', False), ('autoexec_disabled', False)):
            with self.subTest(key=key):
                altered = {**self.f.probe, key: value}
                write_json(self.f.probe_path, altered)
                self.assert_rejected('probe_contract_differs')

    def test_probe_process_finished_and_same_run(self):
        for key, value in (('completed', False), ('windows_job_empty_verified', False),
                           ('exit_code', 1), ('cwd', str(self.f.work))):
            with self.subTest(key=key):
                old = self.f.terminal[key]
                self.f.terminal[key] = value
                self.f.write_terminal()
                self.assert_rejected('probe_terminal_not_complete')
                self.f.terminal[key] = old
        self.f.terminal['host_binding']['run_id'] = 'run-1-attempt-1'
        self.f.write_terminal()
        self.assert_rejected('probe_terminal_binding_differs')

    def test_owner_lock_rejects_live_process(self):
        (self.f.candidate.parent.parent / 'native-owner.lock').write_bytes(b'owner')
        self.assert_rejected('native_owner_still_present')

    def test_process_context_digest_has_no_newline(self):
        self.f.terminal['host_binding']['context_sha256'] = o.sha(o.canonical(self.f.command) + b'\n')
        self.f.write_terminal()
        self.assert_rejected('probe_terminal_binding_differs')

    def test_transport_environment_digest_requires_newline(self):
        self.f.terminal['host_binding']['environment_sha256'] = o.sha(o.canonical(self.f.config['native_environment']))
        self.f.write_terminal()
        self.assert_rejected('probe_terminal_binding_differs')

    def test_command_environment_digest_uses_controller_domain(self):
        self.f.command['environment_sha256'] = o.sha(o.canonical(self.f.config['native_environment']) + b'\n')
        write_json(self.f.command_path, self.f.command)
        self.assert_rejected('command_environment_binding_differs')

    def test_terminal_seal_raw_identity(self):
        (self.f.process / 'terminal.json').write_bytes((self.f.process / 'terminal.json').read_bytes() + b' ')
        self.assert_rejected('process_terminal_seal_differs')

    def test_duplicate_zip_exact_and_casefold(self):
        prefix = o.BUNDLE_NAME + '/' + self.f.addon.relative_to(self.f.bundle).as_posix() + '/'
        for name in ('data_types.py', 'DATA_TYPES.PY'):
            with self.subTest(name=name):
                self.f.write_archive([(prefix + name, b'duplicate')])
                self.assert_rejected('duplicate_zip_name')

    def test_zip_escape_and_windows_ambiguities(self):
        # Each case owns a fresh archive/output tree, even if another case fails.
        # Run native separator semantics plus an explicit Windows zipfile model.
        for separator in (None, '\\'):
            for name in ('../evil', '/evil', 'x/../evil', 'x\\evil', 'x:ads',
                         'x/CON.py', 'x/trailing. ', 'x//empty'):
                with self.subTest(name=name, separator=separator), tempfile.TemporaryDirectory() as temp:
                    fixture = Fixture(Path(temp).absolute())
                    semantics = (contextlib.nullcontext() if separator is None else
                                 mock.patch.object(zipfile.os, 'sep', separator))
                    with semantics:
                        fixture.write_archive([(raw_name_zip_info(name), b'bad')])
                        self.assert_stored_zip_spelling(fixture.archive.read_bytes(), name)
                        self.assertFalse(fixture.output.exists())
                        code = 'unsafe_zip_name' if '\\' in name else 'ambiguous_path_component'
                        with self.assertRaisesRegex(o.ObservationError, '^' + code + '$'):
                            fixture.run()
                        self.assertFalse(fixture.output.exists())

    def test_windows_zip_writer_normalization_reproduction_and_raw_fixture(self):
        # Source-only CPython Windows separator model; no Windows run is claimed.
        for raw_fixture in (False, True):
            with self.subTest(raw_fixture=raw_fixture), mock.patch.object(zipfile.os, 'sep', '\\'):
                stream = io.BytesIO()
                name = 'x\\evil'
                with zipfile.ZipFile(stream, 'w') as zf:
                    zf.writestr(raw_name_zip_info(name) if raw_fixture else name, b'bad')
                expected = name if raw_fixture else 'x/evil'
                self.assert_stored_zip_spelling(stream.getvalue(), expected)
                with zipfile.ZipFile(io.BytesIO(stream.getvalue())) as zf:
                    info = zf.infolist()[0]
                    self.assertEqual(info.orig_filename, expected)
                    self.assertEqual(info.filename, 'x/evil')
                    if raw_fixture:
                        self.assertNotEqual(info.orig_filename, info.filename)
                    else:
                        self.assertEqual(info.orig_filename, info.filename)

    def test_zip_symlink_member_rejected(self):
        prefix = o.BUNDLE_NAME + '/' + self.f.addon.relative_to(self.f.bundle).as_posix() + '/'
        del self.f.members['data_types.py']
        info = zipfile.ZipInfo(prefix + 'data_types.py')
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.f.write_archive([(info, b'elsewhere')])
        self.assert_rejected('nonordinary_archive_member')

    def test_member_oversize_before_read(self):
        self.f.members['data_types.py'] = b'x' * (o.MEMBER_CAP + 1)
        self.f.write_archive()
        self.assert_rejected('member_size_bound')

    def test_installed_oversize_before_read(self):
        (self.f.addon / 'data_types.py').write_bytes(b'x' * (o.MEMBER_CAP + 1))
        self.assert_rejected('member_size_bound')

    def test_combined_payload_bound(self):
        for name in list(self.f.members)[:5]:
            self.f.members[name] = b'x' * o.MEMBER_CAP
        self.f.write_archive()
        self.assert_rejected('addon_total_size_bound')

    def test_central_directory_bound_before_zipfile(self):
        raw = bytearray(self.f.archive.read_bytes())
        end = raw.rfind(b'PK\x05\x06')
        struct.pack_into('<L', raw, end + 12, 17 * o.MIB)
        with self.assertRaisesRegex(o.ObservationError, 'zip_directory_bounds'):
            o.bounded_zip_directory(io.BytesIO(raw))

    def test_json_duplicate_keys_and_nonfinite(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'):
            path = self.f.work / 'malformed.json'
            path.write_bytes(raw)
            with self.assertRaises(o.ObservationError):
                o.strict_json(path)

    def test_json_read_cap(self):
        path = self.f.work / 'big.json'
        path.write_bytes(b' ' * (o.JSON_CAP + 1))
        with self.assertRaisesRegex(o.ObservationError, 'file_size_bound'):
            o.strict_json(path)

    def test_windows_ambiguous_components_rejected(self):
        for value in ('..', 'CON', 'NUL.py', 'LPT1.txt', 'file:ads', 'file.', 'file ', 'x\\y', 'x\x00y'):
            with self.subTest(value=value), self.assertRaises(o.ObservationError):
                o.component(value)

    def test_reparse_attribute_rejected(self):
        target = self.f.addon / 'data_types.py'
        original = Path.lstat
        def fake(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if path == target:
                return types.SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x400)
            return result
        with mock.patch.object(Path, 'lstat', fake):
            self.assert_rejected('redirected_path')

    def test_symlink_member_rejected(self):
        target = self.f.addon / 'data_types.py'
        foreign = self.f.work / 'foreign.py'
        foreign.write_bytes(b'foreign')
        target.unlink()
        try:
            target.symlink_to(foreign)
        except OSError:
            self.skipTest('OS does not allow synthetic symlink creation; reparse rejection tested separately')
        self.assert_rejected('redirected_path')

    def test_hardlink_member_rejected(self):
        target = self.f.addon / 'data_types.py'
        foreign = self.f.work / 'foreign.py'
        foreign.write_bytes(b'foreign')
        target.unlink()
        os.link(foreign, target)
        self.assert_rejected('ordinary_single_link_file_required')

    def test_non_overwrite(self):
        self.f.output.write_bytes(b'preserve original')
        with self.assertRaisesRegex(o.ObservationError, 'report_already_exists'):
            self.f.run()
        self.assertEqual(self.f.output.read_bytes(), b'preserve original')

    def test_report_cap(self):
        with self.assertRaisesRegex(o.ObservationError, 'report_size_bound'):
            o.write_report(self.f.output, {'x': 'x' * o.REPORT_CAP})
        self.assertFalse(self.f.output.exists())

    def test_sensitive_sentinel_and_source_content_not_emitted(self):
        (self.f.addon / 'data_types.py').write_bytes((SENTINEL + '\r\n').encode())
        self.f.run()
        raw = self.f.output.read_bytes()
        for text in (SENTINEL, str(self.f.work), o.VENDOR, 'native_environment', 'PRIVATE'):
            self.assertNotIn(text.encode(), raw)
        self.assertLessEqual(len(raw), o.REPORT_CAP)

    def test_exception_output_is_redacted_and_nonzero(self):
        args = ['--work-root', str(self.f.work), '--config', str(self.f.config_path),
                '--config-sha256', self.f.config_sha, '--run-id', '39103418788', '--run-attempt', '1']
        captured = io.StringIO()
        with mock.patch.object(o, 'observe', side_effect=OSError(SENTINEL)), contextlib.redirect_stdout(captured):
            self.assertEqual(o.main(args), 1)
        self.assertNotIn(SENTINEL, captured.getvalue())
        self.assertIn(o.sha(SENTINEL.encode()), captured.getvalue())

    def test_runtime_has_no_process_network_import_or_write_escape(self):
        source = Path(o.__file__).read_text()
        tree = ast.parse(source)
        imports = {alias.name.split('.')[0] for node in ast.walk(tree)
                   if isinstance(node, (ast.Import, ast.ImportFrom))
                   for alias in (node.names if isinstance(node, ast.Import) else [])}
        self.assertFalse(imports & {'subprocess', 'socket', 'urllib', 'requests', 'bpy'})
        self.assertNotIn('os.environ', source)
        self.assertNotIn('os.system', source)
        self.assertNotIn('extractall', source)
        self.assertNotIn('write_bytes(', source)
        self.assertNotIn('write_text(', source)


if __name__ == '__main__':
    unittest.main(verbosity=2)
