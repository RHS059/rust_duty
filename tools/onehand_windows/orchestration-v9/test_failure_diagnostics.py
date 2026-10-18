"""Portable adversarial failure diagnostics; synthetic receipts, no child launch."""
import ast
import contextlib
import copy
import dataclasses
import hashlib
import json
import os
import shutil
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as N
import unittest
from unittest.mock import patch

import command_contract
import failure_diagnostics as d
import orchestrate
import owned_commands
import workflow_core as w

SECRET = 'SECRET-TOKEN-private-geometry-vertices-1.2345-9.8765'


class DiagnosticFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter, _ = command_contract.load_dependencies(w.HERE.parent/'process-v2', w.HERE.parent/'native-producer-reviewed')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.python = self.root/'synthetic-python.exe'
        self.python.write_bytes(b'not executable; no child launched')
        self.python_patch = patch.object(sys, 'executable', str(self.python))
        self.python_patch.start()
        self.candidate = self.root/'session/candidates/candidate'
        self.candidate.mkdir(parents=True)
        self.host = {'runner_id': 'synthetic', 'run_id': 'test-run', 'build_sha256': 'a'*64,
                     'system': 'Windows', 'release': 'synthetic', 'version': 'synthetic', 'machine': 'AMD64'}
        self.environment = {'SystemRoot': 'C:\\Windows', 'TEST_SECRET': SECRET}
        self.argv = [sys.executable, '-I', '-B', 'known_source.py']
        self.source = self.root/'known_source.py'
        self.source.write_text('def require(value, message):\n    if not value: raise ValueError(message)\n\ndef run():\n    require(False, "source projection differs")\n')
        row = {'source_id': 'source-producer/known_source.py', **d.identity(self.source.read_bytes())}
        self.registry = {d.path_key(str(self.source)): (self.source, row)}
        self.error = self.adapter.AdapterError('child_exit_failure')
        self.state = self.prepare()
        self.write_receipts()

    def tearDown(self):
        self.python_patch.stop()
        self.temp.cleanup()

    def prepare(self, label='source-replay', native=None):
        context = {'schema': 'rust-duty-onehand-controller-command/v1', 'label': label,
                   'argv': self.argv, 'cwd': str(self.candidate), 'secret': SECRET}
        if native:
            stage, index = native
            label = stage if index is None else f'{stage}-{index:03d}'
            context = {'schema': 'synthetic-native-context', 'stage': stage, 'index': index,
                       'stage_id': label, 'secret': SECRET}
        path = self.candidate/'contexts'/(label+'.json')
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(d.canonical(context)+b'\n')
        binding = self.adapter.HostBinding(runner_id=self.host['runner_id'], run_id=self.host['run_id'],
                   build_sha256=self.host['build_sha256'], context_sha256=w.digest(context),
                   expected_host={k:self.host[k] for k in ('system','release','version','machine')},
                   environment=self.environment, owner_lock=str(self.root/'native-owner.lock'))
        return d.expected(self.adapter, self.candidate/'process'/label, self.argv, self.candidate,
                          binding, self.adapter.Limits(stdout_mode='bytes', max_stdout_bytes=4*d.MIB,
                          max_stderr_bytes=d.MIB), path, w.sha(path), w.record(sys.executable))

    def trace(self, message='source projection differs', filename=None):
        return (f'Traceback (most recent call last):\n  File "{filename or self.source}", line 5, in run\n'
                f'    require(False, "{SECRET}")\n  File "{filename or self.source}", line 2, in require\n'
                f'    if not value: raise ValueError(message)\nValueError: {message}\n').encode()

    def write_receipts(self, stdout=None, stderr=b'', completed=False, cleanup=True, started=True):
        root = self.state['target']
        root.mkdir(parents=True, exist_ok=True)
        request = self.state['request']
        base = {'schema': 'rust-duty-owned-process/v1', **copy.deepcopy(request)}
        def put(name, value):
            raw = self.adapter.canonical(value)
            (root/name).write_bytes(raw)
            return {'path': name, **d.identity(raw)}
        attempt = put('attempt.json', {**base, 'state': 'prepared'})
        before = self.adapter.file_identity(sys.executable) if started else None
        start = put('started.json', {**base, 'state': 'started', 'executable_before': before, 'attempt': attempt, 'pid': 1234}) if started else None
        streams = {}
        for key, raw in (('stdout', self.trace() if stdout is None else stdout), ('stderr', stderr), ('samples', b'')):
            name = key+('.jsonl' if key == 'samples' else '.bin')
            (root/name).write_bytes(raw)
            ident = d.identity(raw)
            streams[key] = {'path': name, **ident, 'observed_sha256': ident['sha256'], 'observed_bytes': ident['bytes'],
                            'eof_observed': True, 'truncated': False}
        self.terminal = {**base, 'state': 'completed' if completed else 'partial', 'completed': completed,
                         'started': started, 'exit_code': 0 if completed else 1 if started else None,
                         'pid': 1234 if started else None,
                         'cleanup_complete': cleanup, 'consumer_complete': completed,
                         'constructor_cleanup_complete': None, 'windows_job_empty_verified': cleanup if started else None,
                         'timed_out': False, 'resource_stop_reason': None if completed else 'child_exit_failure' if started else 'launch_failure',
                         'executable_before': before, 'executable_after': before,
                         'attempt': attempt, 'started_record': start, 'streams': streams}
        self.terminal['transport_record'] = put('transport.json', {**self.terminal, 'state': 'transport_stopped'}) if started else None
        self.reseal()

    def reseal(self):
        raw = self.adapter.canonical(self.terminal)
        (self.state['target']/'terminal.json').write_bytes(raw)
        (self.state['target']/'terminal.sha256.json').write_bytes(self.adapter.canonical({'path': 'terminal.json', **d.identity(raw)}))

    def project(self, kind='command', label='source-replay', index=None, registry=None):
        with patch.object(d, 'source_index', return_value=self.registry if registry is None else registry):
            d.capture_failure(self.error, kind=kind, label=label, index=index,
                              adapter=self.adapter, state=self.state)
        result = d.public_failure(self.error)
        self.assertIsNotNone(result)
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertFalse(result['native_proof'])
        self.assertEqual(result['original_outcome'], 'failed')
        return result

    def unavailable(self, **kwargs):
        result = self.project(**kwargs)
        self.assertEqual(result['diagnostic_status'], 'unavailable')
        self.assertFalse(result['receipt_binding_verified'])
        self.assertIsNone(result['lifecycle'])
        self.assertIsNone(result['identities'])

    def test_useful_stdout_traceback_and_static_caller_message(self):
        value = self.project()
        self.assertEqual(value['role'], 'source-replay')
        self.assertEqual(value['lifecycle']['exit_code'], 1)
        self.assertEqual(value['lifecycle']['reason'], 'child_exit_failure')
        trace = value['tracebacks']['stdout']
        self.assertEqual(trace['frames'][0]['source_id'], 'source-producer/known_source.py')
        self.assertEqual(trace['frames'][0]['line'], 5)
        self.assertEqual(trace['frames'][0]['static_error_templates'], ['source projection differs'])
        self.assertEqual(trace['exceptions'][0]['verified_static_message'], 'source projection differs')
        self.assertEqual(value['original_error_sha256'], hashlib.sha256(b'child_exit_failure').hexdigest())

    def test_sealed_failure_fixture_is_accepted_by_unchanged_adapter(self):
        self.assertFalse(self.adapter.verify_attempt(self.state['target'])['completed'])
        with self.assertRaises(self.adapter.AdapterError):
            self.adapter.verify_attempt(self.state['target'], require_completed=True)

    def test_stderr_traceback_and_nested_chains(self):
        self.write_receipts(stdout=b'', stderr=self.trace()+b'\nDuring handling of the above exception, another exception occurred:\n\n'+self.trace(SECRET))
        trace = self.project()['tracebacks']['stderr']
        self.assertEqual(len(trace['exceptions']), 2)
        self.assertEqual(trace['exceptions'][0]['verified_static_message'], 'source projection differs')
        self.assertIsNone(trace['exceptions'][1]['verified_static_message'])
        self.assertEqual([x['traceback'] for x in trace['exceptions']], [1, 2])

    def test_blender_prefixed_traceback_has_useful_static_message(self):
        self.write_receipts(stdout=b'Error: Python: '+self.trace())
        self.assertEqual(self.project()['tracebacks']['stdout']['exceptions'][0]['verified_static_message'], 'source projection differs')

    def test_native_host_field_static_failure_is_pinned_and_hash_only(self):
        from test_host_identity_collection import native_root
        root=native_root();source=root/'host_identity.py';message='native host machine invalid'
        tree=ast.parse(source.read_bytes())
        line=next(node.lineno for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='require' and len(node.args)==2 and isinstance(node.args[1],ast.Constant) and node.args[1].value==message)
        registry=d.source_index({'native_producer':str(root)})
        trace=(f'Traceback (most recent call last):\n  File "{source}", line {line}, in require_native_host\n    {SECRET}\nValueError: {message}\n').encode()
        self.write_receipts(stdout=trace);value=self.project(registry=registry)
        frame=value['tracebacks']['stdout']['frames'][0]
        self.assertEqual(frame['source_id'],'native-producer-reviewed/host_identity.py')
        self.assertEqual(frame['source_sha256'],w.sha(source));self.assertIn(message,frame['static_error_templates'])
        self.assertEqual(value['tracebacks']['stdout']['exceptions'][0]['verified_static_message'],message)

    def test_exception_group_gutters_and_nested_traceback(self):
        raw = b'  + Exception Group Traceback (most recent call last):\n'
        raw += f'  |   File "{self.source}", line 5, in run\n  | ExceptionGroup: {SECRET}\n'.encode()
        raw += b'  +-+---------------- 1 ----------------\n'
        raw += b'    | '+self.trace().replace(b'\n', b'\n    | ')
        self.write_receipts(stdout=raw)
        trace = self.project()['tracebacks']['stdout']
        self.assertEqual([e['category'] for e in trace['exceptions']], ['ExceptionGroup', 'ValueError'])
        self.assertEqual(trace['exceptions'][-1]['verified_static_message'], 'source projection differs')

    def test_unknown_frames_and_exception_text_are_hash_only(self):
        self.write_receipts(stdout=self.trace(SECRET, r'C:\private\credentials.py'))
        value = self.project()
        self.assertEqual(value['tracebacks']['stdout']['frames'], [])
        self.assertEqual(value['tracebacks']['stdout']['unknown_frames'], 2)
        self.assertNotIn('credentials.py', json.dumps(value))

    def test_forged_displayed_source_does_not_become_public(self):
        self.write_receipts(stdout=self.trace(SECRET))
        value = self.project()['tracebacks']['stdout']
        self.assertEqual(value['frames'][0]['static_error_templates'], ['source projection differs'])
        self.assertIsNone(value['exceptions'][0]['verified_static_message'])

    def test_no_traceback_does_not_invent_a_cause(self):
        self.write_receipts(stdout=(SECRET+'\n').encode(), stderr=b'error[E0308]: '+SECRET.encode()+b'\n')
        value = self.project()
        self.assertEqual(value['tracebacks']['stdout']['frames'], [])
        self.assertEqual(value['tracebacks']['stdout']['exceptions'], [])
        self.assertEqual(value['tracebacks']['stderr']['recognized_rust_error_codes'], ['E0308'])
        self.assertEqual(value['lifecycle']['exit_code'], 1)

    def test_dynamic_template_never_interpolates_private_value(self):
        self.source.write_text('assert False, f"source mismatch: {private_value}"\n')
        self.registry[d.path_key(str(self.source))] = (self.source, {'source_id': 'source-producer/known_source.py', **d.identity(self.source.read_bytes())})
        self.write_receipts(stdout=f'Traceback (most recent call last):\n  File "{self.source}", line 1, in run\nAssertionError: source mismatch: {SECRET}\n'.encode())
        value = self.project()['tracebacks']['stdout']
        self.assertEqual(value['frames'][0]['static_error_templates'], ['source mismatch: <dynamic>'])
        self.assertIsNone(value['exceptions'][0]['verified_static_message'])

    def test_static_assertion_message_is_useful(self):
        self.source.write_text('assert False, "fixed assertion failed"\n')
        self.registry[d.path_key(str(self.source))] = (self.source, {'source_id': 'source-producer/known_source.py', **d.identity(self.source.read_bytes())})
        self.write_receipts(stdout=f'Traceback (most recent call last):\n  File "{self.source}", line 1, in run\nAssertionError: fixed assertion failed\n'.encode())
        self.assertEqual(self.project()['tracebacks']['stdout']['exceptions'][0]['verified_static_message'], 'fixed assertion failed')

    def test_source_secret_literal_template_suppressed(self):
        self.source.write_text('assert False, "password=literal_secret"\n')
        self.registry[d.path_key(str(self.source))] = (self.source, {'source_id': 'source-producer/known_source.py', **d.identity(self.source.read_bytes())})
        self.write_receipts(stdout=f'Traceback (most recent call last):\n  File "{self.source}", line 1, in run\nAssertionError: password=literal_secret\n'.encode())
        value = self.project()['tracebacks']['stdout']
        self.assertEqual(value['frames'][0]['static_error_templates'], [])
        self.assertNotIn('literal_secret', json.dumps(value))

    def test_windows_absolute_case_and_separator_match_only_exact_path(self):
        windows = r'C:\Reviewed\Source\known_source.py'
        registry = {d.path_key(windows): next(iter(self.registry.values()))}
        self.write_receipts(stdout=self.trace(filename='c:/reviewed/source/KNOWN_SOURCE.PY'))
        self.assertEqual(len(self.project(registry=registry)['tracebacks']['stdout']['frames']), 2)
        self.write_receipts(stdout=self.trace(filename=r'D:\Other\known_source.py'))
        self.assertEqual(self.project(registry=registry)['tracebacks']['stdout']['frames'], [])

    def test_windows_path_alias_traversal_ads_and_unc_rejected(self):
        for filename in (r'C:\Reviewed\..\Source\known_source.py', r'C:\Reviewed\Source\known_source.py:secret',
                         r'C:\Reviewed\Source\known_source.py ', r'\\server\private\known_source.py'):
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                d.path_key(filename)

    def test_source_bytes_mutated_or_symlinked_are_not_reported(self):
        self.source.write_bytes(self.source.read_bytes()+b'# changed\n')
        self.assertEqual(self.project()['tracebacks']['stdout']['frames'], [])
        real = self.root/'real.py'
        self.source.rename(real)
        self.source.symlink_to(real)
        self.assertEqual(self.project()['tracebacks']['stdout']['frames'], [])

    def test_unrecognized_role_or_stage_never_echoes_arbitrary_label(self):
        value = self.project(label=SECRET)
        self.assertEqual(value['kind'], 'unrecognized')
        self.unavailable(kind='native-stage', label='block', index=12)

    def test_role_rebinding_rejected(self):
        self.unavailable(label='blender-host-observation')

    def test_native_stage_and_index_bound(self):
        self.state = self.prepare(native=('block', 3))
        self.write_receipts()
        value = self.project(kind='native-stage', label='block', index=3)
        self.assertEqual((value['stage'], value['index']), ('block', 3))
        self.unavailable(kind='native-stage', label='block', index=4)

    def test_each_current_request_field_must_match_terminal(self):
        original = copy.deepcopy(self.terminal)
        for key, bad in (('command', ['other.exe']), ('cwd', 'C:\\other'), ('limits', {}),
                         ('host_binding', {}), ('supervisor_python', {})):
            self.terminal = copy.deepcopy(original)
            self.terminal[key] = bad
            self.reseal()
            with self.subTest(field=key):
                self.unavailable()

    def test_host_environment_context_and_build_bindings(self):
        original = copy.deepcopy(self.terminal)
        for key in ('runner_id', 'run_id', 'build_sha256', 'context_sha256', 'environment_sha256', 'owner_lock'):
            self.terminal = copy.deepcopy(original)
            self.terminal['host_binding'][key] = 'different'
            self.reseal()
            with self.subTest(field=key):
                self.unavailable()

    def test_executable_identity_mismatch_rejected(self):
        self.terminal['executable_before']['sha256'] = '0'*64
        self.reseal()
        self.unavailable()

    def test_context_bytes_or_role_mutation_rejected(self):
        path = self.state['context_path']
        value = json.loads(path.read_bytes())
        value['label'] = 'cargo-build'
        path.write_bytes(d.canonical(value)+b'\n')
        self.unavailable()

    def test_cross_request_attempt_even_with_resealed_terminal_rejected(self):
        path = self.state['target']/'attempt.json'
        value = json.loads(path.read_bytes())
        value['command'] = ['different.exe']
        raw = self.adapter.canonical(value)
        path.write_bytes(raw)
        self.terminal['attempt'] = {'path': 'attempt.json', **d.identity(raw)}
        self.reseal()
        self.unavailable()

    def test_contradictory_transport_lifecycle_or_linkage_rejected(self):
        path = self.state['target']/'transport.json'
        original = json.loads(path.read_bytes())
        for key, bad in (('exit_code',77), ('cleanup_complete',False), ('pid',9876), ('attempt',None),
                         ('executable_before',{}), ('windows_job_empty_verified',False)):
            value = copy.deepcopy(original)
            value[key] = bad
            raw = self.adapter.canonical(value)
            path.write_bytes(raw)
            self.terminal['transport_record'] = {'path': 'transport.json', **d.identity(raw)}
            self.reseal()
            with self.subTest(field=key):
                self.unavailable()

    def test_legitimate_late_consumer_difference_is_preserved(self):
        self.write_receipts(completed=True)
        path = self.state['target']/'transport.json'
        value = json.loads(path.read_bytes())
        value['consumer_complete'] = False
        value['completed'] = False
        raw = self.adapter.canonical(value)
        path.write_bytes(raw)
        self.terminal['transport_record'] = {'path': 'transport.json', **d.identity(raw)}
        self.reseal()
        self.assertTrue(self.project()['lifecycle']['completed'])

    def test_exact_real_source_replay_static_message_is_emitted(self):
        source = w.HERE.parent/'source-producer/onehand_v6_source_native.py'
        line = next(i for i,s in enumerate(source.read_text().splitlines(),1) if '"source skeleton count differs"' in s)
        self.write_receipts(stdout=f'Error: Python: Traceback (most recent call last):\n  File "{source}", line {line}, in replay\nAssertionError: source skeleton count differs\n'.encode())
        layout = w.strict_json(w.HERE/'controller-layout.template.json')
        registry = d.source_index({k:str(w.HERE.parent/v) for k,v in layout['roots'].items()})
        value = self.project(registry=registry)['tracebacks']['stdout']
        self.assertEqual(value['frames'][0]['source_id'], 'source-producer/onehand_v6_source_native.py')
        self.assertEqual(value['frames'][0]['source_sha256'], w.sha(source))
        self.assertEqual(value['exceptions'][0]['verified_static_message'], 'source skeleton count differs')

    def test_projection_cap_retains_role_and_lifecycle(self):
        value = self.project()
        value['tracebacks'] = {'large': 'x'*(d.PUBLIC_CAP+1)}
        self.error._onehand_failure_projection = d._Projection(value)
        result = d.public_failure(self.error)
        self.assertEqual(result['role'], 'source-replay')
        self.assertEqual(result['lifecycle']['exit_code'], 1)
        self.assertIsNone(result['tracebacks'])
        self.assertEqual(result['traceback_status'], 'public-projection-cap')

    def test_stream_mutation_and_truncation_rejected(self):
        for raw in (b'changed', b''):
            (self.state['target']/'stdout.bin').write_bytes(raw)
            self.unavailable()

    def test_symlinked_stream_and_parent_rejected(self):
        path = self.state['target']/'stdout.bin'
        real = self.root/'raw.bin'
        path.rename(real)
        path.symlink_to(real)
        self.unavailable()

    def test_oversize_stream_rejected_before_read(self):
        path = self.state['target']/'stdout.bin'
        with path.open('wb') as stream:
            stream.truncate(d.STREAM_CAPS['stdout']+1)
        self.terminal['streams']['stdout']['bytes'] = d.STREAM_CAPS['stdout']+1
        self.reseal()
        self.unavailable()

    def test_unsealed_missing_or_corrupt_terminal_rejected(self):
        path = self.state['target']/'terminal.sha256.json'
        raw = path.read_bytes()
        for changed in (b'{}', b'{"path":"terminal.json","path":"other"}', b'{"bad":NaN}'):
            path.write_bytes(changed)
            self.unavailable()
        path.write_bytes(raw)
        path.unlink()
        self.unavailable()

    def test_unsafe_receipt_reference_never_read(self):
        self.terminal['streams']['stdout']['path'] = '../private.txt'
        self.reseal()
        self.unavailable()

    def test_completed_child_still_preserves_enclosing_failure(self):
        self.write_receipts(completed=True)
        value = self.project()
        self.assertTrue(value['lifecycle']['completed'])
        self.assertEqual(value['lifecycle']['exit_code'], 0)
        summary = orchestrate.summary({}, error=self.error)
        self.assertFalse(summary['passed'])
        self.assertEqual(summary['error_sha256'], value['original_error_sha256'])

    def test_incomplete_cleanup_reported_without_admission(self):
        self.write_receipts(cleanup=False)
        value = self.project()
        self.assertFalse(value['lifecycle']['cleanup_complete'])
        self.assertFalse(value['lifecycle']['windows_job_empty_verified'])
        self.assertFalse(value['lifecycle']['completed'])

    def test_inconsistent_completed_receipt_rejected(self):
        self.write_receipts(completed=True)
        self.terminal['cleanup_complete'] = False
        self.reseal()
        self.unavailable()

    def test_launch_failure_without_started_or_transport_receipt_is_honest(self):
        self.write_receipts(started=False)
        value = self.project()
        self.assertFalse(value['lifecycle']['started'])
        self.assertIsNone(value['lifecycle']['exit_code'])
        self.assertIsNone(value['identities']['started_record'])
        self.assertIsNone(value['identities']['transport_record'])

    def test_unknown_termination_reason_is_hash_only(self):
        self.terminal['resource_stop_reason'] = SECRET
        self.reseal()
        value = self.project()
        self.assertIsNone(value['lifecycle']['reason'])
        self.assertIsNotNone(value['lifecycle']['reason_sha256'])

    def test_missing_diagnostic_state_preserves_exact_error(self):
        self.state = {}
        self.unavailable()
        self.assertEqual(str(self.error), 'child_exit_failure')

    def test_diagnostic_internal_failure_preserves_original(self):
        with patch.object(d, 'sealed', side_effect=RuntimeError(SECRET)):
            self.unavailable()
        self.assertEqual(str(self.error), 'child_exit_failure')

    def test_read_mutation_is_rejected(self):
        original = d.snapshot
        def mutate(path, cap):
            raw = original(path, cap)
            if Path(path).name == 'terminal.json':
                Path(path).write_bytes(raw+b' ')
            return raw
        with patch.object(d, 'snapshot', side_effect=mutate):
            self.unavailable()

    def test_traceback_frame_and_output_caps(self):
        raw = b'Traceback (most recent call last):\n'
        raw += (f'  File "{self.source}", line 5, in run\n'.encode())*(d.MAX_FRAMES+10)
        raw += b'ValueError: source projection differs\n'
        self.write_receipts(stdout=raw)
        value = self.project()
        self.assertEqual(len(value['tracebacks']['stdout']['frames']), d.MAX_FRAMES)
        self.assertTrue(value['tracebacks']['stdout']['truncated'])
        self.assertLessEqual(len(d.canonical(value)), d.PUBLIC_CAP)

    def test_long_invalid_utf8_and_geometry_lines_ignored(self):
        self.write_receipts(stdout=(SECRET+' ').encode()*1000+b'\n\xff\xfe\n'+self.trace())
        self.assertEqual(self.project()['tracebacks']['stdout']['exceptions'][0]['verified_static_message'], 'source projection differs')

    def test_summary_without_diagnostics_remains_exact_shape(self):
        value = orchestrate.summary({}, error=ValueError(SECRET))
        self.assertNotIn('owned_failure', value)
        self.assertNotIn(SECRET, json.dumps(value))
        self.assertEqual(value['schema'], 'rust-duty-onehand-windows-public-summary/v2')

    def test_fake_projection_attribute_is_not_accepted(self):
        self.error._onehand_failure_projection = {'text': SECRET}
        self.assertIsNone(d.public_failure(self.error))

    def test_actual_frozen_public_source_manifest_matches_source_files(self):
        layout = w.strict_json(w.HERE/'controller-layout.template.json')
        registry = d.source_index({k:str(w.HERE.parent/v) for k,v in layout['roots'].items()})
        self.assertGreater(len(registry), 50)
        for path, row in registry.values():
            self.assertEqual(d.identity(d.snapshot(path, d.SOURCE_CAP)), {'sha256':row['sha256'], 'bytes':row['bytes']}, row['source_id'])


    def test_commands_capture_after_owned_context_exit_and_preserve_identical_exception(self):
        shutil.rmtree(self.state['target'])
        events = []
        @contextlib.contextmanager
        def run(argv, cwd, limits, target, binding):
            self.state = d.expected(self.adapter, target, argv, cwd, binding, limits,
                        self.candidate/'contexts/source-replay-command.json',
                        w.sha(self.candidate/'contexts/source-replay-command.json'), w.record(argv[0]))
            try:
                yield N(wait=lambda: (_ for _ in ()).throw(self.error))
            finally:
                self.write_receipts()
                events.append('sealed')
        original = d.capture_failure
        def capture(*args, **kwargs):
            self.assertEqual(events, ['sealed'])
            return original(*args, **kwargs)
        with patch.object(self.adapter.OwnedProcess, 'run', side_effect=run), patch.object(d, 'capture_failure', side_effect=capture), patch.object(d, 'source_index', return_value=self.registry):
            with self.assertRaises(self.adapter.AdapterError) as caught:
                owned_commands.Commands(self.adapter, self.host, self.candidate, self.environment, lambda *args:None).run('source-replay', self.argv, self.candidate)
        self.assertIs(caught.exception, self.error)
        value = d.public_failure(caught.exception)
        self.assertEqual(value['lifecycle']['exit_code'], 1)
        self.assertEqual(value['tracebacks']['stdout']['exceptions'][0]['verified_static_message'], 'source projection differs')


    def test_commands_early_validation_has_role_but_no_fabricated_receipt(self):
        with self.assertRaises(ValueError) as caught:
            owned_commands.Commands(self.adapter, self.host, self.candidate, self.environment, None).run('source-replay', [], self.candidate)
        value = d.public_failure(caught.exception)
        self.assertEqual(str(caught.exception), 'explicit argv list')
        self.assertEqual(value['role'], 'source-replay')
        self.assertIsNone(value['lifecycle'])


    def test_native_early_exception_preserved_even_when_capture_breaks(self):
        pipeline = orchestrate.Pipeline({'roots': {}}, {}, N(adapter=self.adapter), self.candidate, None, {}, {}, None)
        with patch.object(pipeline, '_native', side_effect=self.error), patch.object(d, 'capture_failure', side_effect=RuntimeError(SECRET)):
            with self.assertRaises(self.adapter.AdapterError) as caught:
                pipeline.native('control-export')
        self.assertIs(caught.exception, self.error)


    def test_native_wrapper_binds_stage_and_preserves_identical_exception(self):
        self.state = self.prepare(native=('control-export', None))
        self.write_receipts()
        pipeline = orchestrate.Pipeline({'roots': {}}, {}, N(adapter=self.adapter), self.candidate, None, {}, {}, None)
        def failed(stage, index, extra, state):
            state.update(self.state)
            raise self.error
        with patch.object(pipeline, '_native', side_effect=failed), patch.object(d, 'source_index', return_value=self.registry):
            with self.assertRaises(self.adapter.AdapterError) as caught:
                pipeline.native('control-export')
        self.assertIs(caught.exception, self.error)
        self.assertEqual(d.public_failure(caught.exception)['stage'], 'control-export')
        self.assertEqual(d.public_failure(caught.exception)['lifecycle']['exit_code'], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
