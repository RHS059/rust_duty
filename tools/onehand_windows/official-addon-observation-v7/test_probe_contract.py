"""Execute the exact bound probe producer with inert modules, then real observer.

No installed Blender, DLL load, process, shell, network, or rendering is used.
The source directory is explicit and its PINS/probe identities are mandatory.
Run: python -I -B test_probe_contract.py --orchestration <exact-source-root>
"""
import argparse
import ast
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).absolute().parent))
import observe_official_addon as o
from test_observe_official_addon import Fixture, SENTINEL, write_json

ORCHESTRATION_ROOT = None


def execute_published_probe(fixture, raw, *, native_host=None):
    """Only external host/Blender APIs are inert; schema-producing code is exact."""
    native = native_host or {'system': 'Windows', 'release': '10',
                             'version': '10.0.20348', 'machine': 'AMD64'}
    runtime = fixture.bundle / 'python-runtime-fixture.dll'
    runtime.write_bytes(b'INERT DLL FIXTURE ' + SENTINEL.encode())
    fake_sys = types.ModuleType('sys')
    fake_sys.platform = 'win32'
    fake_sys.flags = types.SimpleNamespace(optimize=0)
    fake_sys.dllhandle = 1
    fake_sys.argv = ['inert-probe', '--', str(fixture.probe_path)]
    fake_platform = types.ModuleType('platform')
    for name, value in native.items():
        setattr(fake_platform, name, lambda value=value: value)
    fake_ctypes = types.ModuleType('ctypes')
    fake_ctypes.c_void_p = object()
    fake_ctypes.c_wchar_p = object()
    fake_ctypes.c_uint = object()
    fake_ctypes.sizeof = lambda pointer: 8
    class Buffer:
        value = ''
        def __len__(self):
            return 32768
    fake_ctypes.create_unicode_buffer = lambda size: Buffer()
    def get_name(handle, buffer, size):
        buffer.value = str(runtime)
        return len(buffer.value)
    fake_ctypes.WinDLL = lambda *args, **kwargs: types.SimpleNamespace(GetModuleFileNameW=get_name)
    fake_bpy = types.ModuleType('bpy')
    fake_bpy.app = types.SimpleNamespace(version=(4, 3, 2), background=True,
        build_hash=b'32f5fdce0a0a', binary_path=str(fixture.binary))
    fake_bpy.context = types.SimpleNamespace(preferences=types.SimpleNamespace(
        filepaths=types.SimpleNamespace(use_scripts_auto_execute=False)))
    fake_addon = types.ModuleType('io_scene_fbx')
    fake_addon.__file__ = str(fixture.addon / '__init__.py')
    fixture.probe_path.unlink()
    modules = {'sys': fake_sys, 'platform': fake_platform, 'ctypes': fake_ctypes,
               'bpy': fake_bpy, 'io_scene_fbx': fake_addon}
    with mock.patch.dict(sys.modules, modules):
        namespace = {'__name__': '__main__', '__file__': 'probe_blender.py'}
        exec(compile(raw, 'probe_blender.py', 'exec'), namespace)
    return json.loads(fixture.probe_path.read_bytes())


class ProbeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if ORCHESTRATION_ROOT is None:
            raise RuntimeError('Explicit --orchestration source root is required; no skipped composition tests')
        root = Path(ORCHESTRATION_ROOT).absolute()
        cls.source = (root / 'probe_blender.py').read_bytes()
        cls.pins = (root / 'PINS.json').read_bytes()
        if o.sha(cls.pins) != o.ORCHESTRATION_PINS_SHA:
            raise RuntimeError('Actual orchestration PINS must match the observer dependency')
        if o.sha(cls.source) != o.PROBE_SOURCE_SHA:
            raise RuntimeError('Actual probe bytes must match the observer dependency')
        if json.loads(cls.pins)['probe_blender.py'] != o.PROBE_SOURCE_SHA:
            raise RuntimeError('Actual orchestration must bind the exact producer source')

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.f = Fixture(Path(temp.name).absolute())
        (self.f.source / 'probe_blender.py').write_bytes(self.source)
        (self.f.source / 'PINS.json').write_bytes(self.pins)
        self.f.patches.pop('PROBE_SOURCE_SHA')
        self.f.patches.pop('ORCHESTRATION_PINS_SHA')
        self.probe = execute_published_probe(self.f, self.source)

    def reject_probe(self, change, code):
        value = copy.deepcopy(self.probe)
        change(value)
        write_json(self.f.probe_path, value)
        with self.assertRaisesRegex(o.ObservationError, '^' + code + '$'):
            self.f.run()
        self.assertFalse(self.f.output.exists())

    def test_exact_published_probe_main_to_real_observer(self):
        before = (self.f.evidence / 'summary.json').read_bytes()
        result = self.f.run()
        self.assertEqual(result['status'], 'observed_diagnostic_only')
        self.assertEqual(result['provenance']['probe_source_sha256'], o.PROBE_SOURCE_SHA)
        self.assertEqual(result['provenance']['observed_probe_sha256'], o.sha(self.f.probe_path.read_bytes()))
        self.assertEqual(len(result['files']), 10)
        self.assertTrue(all(row['archive_equals_installed'] and row['installed_raw_matches_expected']
                            and row['archive_raw_matches_expected'] for row in result['files']))
        for name in ('native_admission', 'animation_proof', 'normalized_hash_acceptance', 'native_outcome_modified'):
            self.assertIs(result[name], False)
        self.assertEqual(before, (self.f.evidence / 'summary.json').read_bytes())
        self.assertNotIn(SENTINEL, self.f.output.read_text())

    def test_previous_schema_is_rejected(self):
        self.reject_probe(lambda v: v.update(schema='rust-duty-official-blender-host-observation/v1'), 'probe_contract_differs')

    def test_exact_probe_fields_no_missing_or_extra(self):
        for key in self.probe:
            with self.subTest(key=key):
                self.reject_probe(lambda v: v.pop(key), 'json_fields_differ')
        self.reject_probe(lambda v: v.update(extra=SENTINEL), 'json_fields_differ')

    def test_native_platform_and_pointer_width_exact_types(self):
        for key, value in (('sys_platform', 'linux'), ('sys_platform', True), ('pointer_bits', 32),
                           ('pointer_bits', True), ('pointer_bits', 64.0), ('pointer_bits', '64')):
            with self.subTest(key=key, value=value):
                self.reject_probe(lambda v: v.update({key: value}), 'probe_native_runtime_differs')

    def test_native_tuple_fields_exact(self):
        for key in o.HOST_FIELDS:
            with self.subTest(key=key):
                self.reject_probe(lambda v: v['observed_host'].pop(key), 'probe_host_fields_differ')
        self.reject_probe(lambda v: v['observed_host'].update(extra=SENTINEL), 'probe_host_fields_differ')
        self.reject_probe(lambda v: v.update(observed_host=[]), 'probe_host_fields_differ')

    def test_native_tuple_missing_unknown_and_oversized_values_rejected(self):
        for field in o.HOST_FIELDS:
            for value in (None, True, '', 'unknown', 'UNKNOWN', 'x' * 129, 'x\0y'):
                with self.subTest(field=field, value=value):
                    self.reject_probe(lambda v: v['observed_host'].update({field: value}), 'probe_host_text_invalid')

    def test_native_tuple_grammar_and_aliases_rejected(self):
        mutations = (('system', 'windows', 'system'), ('system', 'Linux', 'system'),
                     ('release', ' 10 ', 'release'), ('release', '2022/Server', 'release'),
                     ('version', '10.0', 'version'), ('version', '10.0.20348 extra', 'version'),
                     ('machine', 'x86_64', 'machine'), ('machine', 'ARM64', 'machine'))
        for field, value, category in mutations:
            with self.subTest(field=field, value=value):
                self.reject_probe(lambda v: v['observed_host'].update({field: value}),
                                  'probe_host_' + category + '_invalid')

    def test_distinct_valid_release_labels_are_accepted(self):
        self.assertNotEqual(self.probe['observed_host']['release'],
                            self.f.terminal['host_binding']['observed_host']['release'])
        self.assertEqual(self.f.run()['status'], 'observed_diagnostic_only')

    def test_cross_role_version_mismatch_is_rejected(self):
        self.reject_probe(lambda v: v['observed_host'].update(version='10.0.20349'), 'probe_cross_role_host_differs')

    def test_supervisor_tuple_missing_or_invalid_rejected(self):
        for field in o.HOST_FIELDS:
            with self.subTest(field=field):
                original = copy.deepcopy(self.f.terminal)
                self.f.terminal['host_binding']['observed_host'].pop(field)
                self.f.write_terminal()
                with self.assertRaisesRegex(o.ObservationError, 'probe_host_fields_differ'):
                    self.f.run()
                self.f.terminal = original

    def test_supervisor_command_and_terminal_tuple_must_match_all_fields(self):
        self.f.command['host']['release'] = '10'
        write_json(self.f.command_path, self.f.command)
        self.f.terminal['host_binding']['context_sha256'] = o.sha(o.canonical(self.f.command))
        self.f.write_terminal()
        with self.assertRaisesRegex(o.ObservationError, 'probe_command_host_differs'):
            self.f.run()

    def test_supervisor_command_and_terminal_ids_and_build_must_match(self):
        for key, value in (('run_id', 'run-1-attempt-1'), ('runner_id', 'runner-' + 'c' * 24),
                           ('build_sha256', 'f' * 64)):
            with self.subTest(key=key):
                original = copy.deepcopy(self.f.command)
                self.f.command['host'][key] = value
                write_json(self.f.command_path, self.f.command)
                self.f.terminal['host_binding']['context_sha256'] = o.sha(o.canonical(self.f.command))
                self.f.write_terminal()
                with self.assertRaisesRegex(o.ObservationError, 'probe_command_host_differs'):
                    self.f.run()
                self.f.command = original

    def test_actual_source_mismatch_is_rejected(self):
        (self.f.source / 'probe_blender.py').write_bytes(self.source + b'\n')
        with self.assertRaisesRegex(o.ObservationError, 'probe_source_pin_differs'):
            self.f.run()

    def test_actual_manifest_mismatch_is_rejected(self):
        (self.f.source / 'PINS.json').write_bytes(self.pins + b' ')
        with self.assertRaisesRegex(o.ObservationError, 'input_pin_mismatch'):
            self.f.run()

    def test_stale_probe_pin_in_exact_manifest_is_rejected(self):
        pins = json.loads(self.pins)
        pins['probe_blender.py'] = '618eeef21e353a43e90855c2914c32b89d6c66e6b51a902b49825dfb958e57b1'
        write_json(self.f.source / 'PINS.json', pins)
        self.f.patches['ORCHESTRATION_PINS_SHA'] = o.sha((self.f.source / 'PINS.json').read_bytes())
        with self.assertRaisesRegex(o.ObservationError, 'probe_source_binding_differs'):
            self.f.run()

    def test_failure_projection_identifies_real_static_guard_and_source_frame(self):
        self.probe['schema'] = 'bad-' + SENTINEL
        write_json(self.f.probe_path, self.probe)
        before = (self.f.evidence / 'summary.json').read_bytes()
        args = ['--work-root', str(self.f.work), '--config', str(self.f.config_path),
                '--config-sha256', self.f.config_sha, '--run-id', '39103418788', '--run-attempt', '1']
        stdout = io.StringIO()
        with mock.patch.multiple(o, **self.f.patches), contextlib.redirect_stdout(stdout):
            self.assertEqual(o.main(args), 1)
        raw = stdout.getvalue()
        value = json.loads(raw)
        self.assertEqual(value['error_code'], 'probe_contract_differs')
        self.assertEqual(value['error_category'], 'probe_contract')
        self.assertEqual(value['error_type'], 'ObservationError')
        self.assertEqual(value['observation_error_sha256'], o.sha(b'probe_contract_differs'))
        self.assertTrue(any(frame['function'] == 'probe_observation' for frame in value['source_frames']))
        for forbidden in (SENTINEL, str(self.f.work), 'PRIVATE', 'native_environment', 'Traceback'):
            self.assertNotIn(forbidden, raw)
        self.assertLessEqual(len(raw.encode()), o.FAILURE_CAP + 1)
        self.assertEqual(before, (self.f.evidence / 'summary.json').read_bytes())
        self.assertFalse(self.f.output.exists())

    def test_failure_projection_untrusted_text_and_types_are_not_emitted(self):
        secret_type = type(SENTINEL, (RuntimeError,), {})
        for exc in (OSError(SENTINEL), o.ObservationError(SENTINEL), secret_type(SENTINEL)):
            with self.subTest(kind=type(exc).__name__):
                value = o.failure_projection(exc)
                raw = o.canonical(value)
                self.assertNotIn(SENTINEL.encode(), raw)
                self.assertEqual(value['observation_error_sha256'], o.sha(SENTINEL.encode()))
                self.assertEqual(value['error_code'], 'unclassified_observer_error')
                self.assertEqual(value['source_frames'], [])

    def test_failure_projection_exact_hash_for_long_exception_without_output_growth(self):
        message = SENTINEL * 10000
        value = o.failure_projection(OSError(message))
        self.assertEqual(value['observation_error_sha256'], o.sha(message.encode()))
        self.assertLess(len(o.canonical(value)), o.FAILURE_CAP)
        self.assertNotIn(SENTINEL.encode(), o.canonical(value))

    def test_fake_external_frame_spelling_cannot_enter_projection(self):
        scope = {}
        exec(compile('def probe_observation():\n raise ValueError("private")\n',
                     'observe_official_addon.py', 'exec'), scope)
        try:
            scope['probe_observation']()
        except ValueError as exc:
            self.assertEqual(o.failure_projection(exc)['source_frames'], [])

    def test_every_source_guard_has_static_allowlisted_error_code(self):
        tree = ast.parse(Path(o.__file__).read_text())
        codes = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ('require', 'ObservationError'):
                if node.args and isinstance(node.args[-1], ast.Constant) and isinstance(node.args[-1].value, str):
                    codes.add(node.args[-1].value)
        self.assertEqual(codes, set(o.FAILURE_CODES))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--orchestration', required=True)
    options, remaining = parser.parse_known_args()
    ORCHESTRATION_ROOT = Path(options.orchestration)
    unittest.main(argv=[sys.argv[0]] + remaining, verbosity=2)
