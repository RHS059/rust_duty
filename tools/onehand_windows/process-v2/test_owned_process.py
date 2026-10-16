"""Tiny synthetic Python children only. No Blender, game, native builds or assets."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from owned_process import (AdapterError, ByteQueue, GIB, HostBinding, Limits,
    OwnedProcess, Resources, Running, SERIAL, observed_host, canonical, validate_json)

HERE = Path(__file__).resolve().parent
FLOOR = (6*GIB+4)//5  # At least 1.2 GiB retained during this source-only work.


def environment():
    result = {'PYTHONIOENCODING':'utf-8', 'PYTHONUNBUFFERED':'1', 'PYTHONDONTWRITEBYTECODE':'1'}
    for key in ('SystemRoot', 'WINDIR'):
        if key in os.environ: result[key] = os.environ[key]
    return result


def binding(parent):
    return HostBinding('synthetic-local-runner', 'test', 'a'*64, observed_host(),
                       environment(), str(parent/'owner.lock'), 'b'*64)


def small_limits(**changes):
    return replace(Limits(deadline_seconds=3, sample_seconds=.02, max_stdout_bytes=32768,
        max_stderr_bytes=1024, max_row_bytes=1024, queue_bytes=2048, queue_rows=2,
        queue_wait_seconds=.3, max_receipt_bytes=32768, max_samples_bytes=32768,
        disk_floor_bytes=FLOOR, drain_seconds=1), **changes)


class SyntheticResources:
    def __init__(self, available=8*GIB, disk=8*GIB, fail_after=None):
        self.memory, self.free, self.calls, self.fail_after = available, disk, 0, fail_after
    def available(self): return self.memory
    def disk(self, root):
        self.calls += 1
        return self.free if self.fail_after is None or self.calls <= self.fail_after else GIB-1


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='owned-adapter-test-')
        self.root = Path(self.temp.name)
        if __import__('shutil').disk_usage(self.root).free < FLOOR + 2*1024**2:
            self.skipTest('source-only 1.2 GiB retained-space gate')
    def tearDown(self): self.temp.cleanup()

    def make(self, code, limits=None, resources=None, launcher=None):
        return Running([sys.executable, '-c', code], self.root, limits or small_limits(),
                       self.root/'attempt', binding(self.root),
                       resources=resources or SyntheticResources(), launcher=launcher)

    def load(self): return json.loads((self.root/'attempt'/'terminal.json').read_text())

    def check_integrity(self, receipt):
        output = self.root/'attempt'
        sidecar = json.loads((output/'terminal.sha256.json').read_text())
        data = (output/'terminal.json').read_bytes()
        self.assertEqual(sidecar['bytes'],len(data)); self.assertEqual(sidecar['sha256'],hashlib.sha256(data).hexdigest())
        for value in receipt['streams'].values():
            data=(output/value['path']).read_bytes()
            self.assertEqual(value['bytes'],len(data)); self.assertEqual(value['sha256'],hashlib.sha256(data).hexdigest())
        for key in ('attempt', 'started_record', 'transport_record'):
            if receipt[key]:
                record=receipt[key]; data=(output/record['path']).read_bytes()
                self.assertEqual(record['bytes'],len(data)); self.assertEqual(record['sha256'],hashlib.sha256(data).hexdigest())
        self.assertLessEqual(len((output/'terminal.json').read_bytes()), receipt['limits']['max_receipt_bytes'])
        self.assertGreaterEqual(receipt['duration_seconds'], 0)
        self.assertFalse((self.root/'owner.lock').exists())

    def test_normal_jsonl_exact_argv_and_hashes(self):
        code="import os; os.write(1,b'{\"a\":1}\\n{\"b\":2}\\n'); os.write(2,b'note\\n')"
        run=self.make(code)
        with run:
            self.assertEqual(list(run.jsonl()), [{'a':1},{'b':2}])
        receipt=self.load(); self.assertTrue(receipt['completed']); self.assertEqual(receipt['rows'],2)
        self.assertEqual(receipt['command'],[sys.executable,'-c',code])
        self.assertEqual(receipt['host_binding']['build_sha256'],'a'*64)
        self.assertEqual(receipt['executable_before'],receipt['executable_after'])
        self.assertTrue(receipt['streams']['stdout']['eof_observed'])
        self.check_integrity(receipt)

    def test_public_interface_bytes_stage(self):
        with OwnedProcess.run([sys.executable,'-c',"print('ordinary native log')"], self.root,
                small_limits(stdout_mode='bytes'), self.root/'attempt', binding(self.root)) as run:
            self.assertEqual(run.wait(),0)
        self.assertTrue(run.receipt['completed']); self.check_integrity(run.receipt)

    def test_launch_failure_retained(self):
        run=self.make('pass'); run.argv[0]=str(self.root/'absent.exe')
        with self.assertRaises(FileNotFoundError):
            with run: pass
        receipt=self.load(); self.assertFalse(receipt['started']); self.assertEqual(receipt['state'],'failed')
        self.assertEqual(receipt['resource_stop_reason'],'launch_failure'); self.check_integrity(receipt)

    def test_launch_api_failure_retained(self):
        def broken(*args): raise OSError('synthetic CreateProcess/Popen failure')
        run=self.make('pass',launcher=broken)
        with self.assertRaises(OSError):
            with run: pass
        self.assertEqual(self.load()['resource_stop_reason'],'launch_failure'); self.check_integrity(self.load())

    def test_initial_memory_guard(self):
        run=self.make('pass',resources=SyntheticResources(available=3*GIB))
        with self.assertRaisesRegex(AdapterError,'initial_available'):
            with run: pass
        self.assertFalse(self.load()['started']); self.check_integrity(self.load())

    def test_initial_retention_disk_guard(self):
        run=self.make('pass',resources=SyntheticResources(disk=FLOOR))
        with self.assertRaisesRegex(AdapterError,'initial_disk'):
            with run: pass
        self.assertFalse(self.load()['started']); self.check_integrity(self.load())

    def test_timeout(self):
        run=self.make('import time; time.sleep(5)',small_limits(deadline_seconds=.15))
        with self.assertRaises(AdapterError):
            with run: list(run.jsonl())
        self.assertTrue(self.load()['timed_out']); self.assertTrue(self.load()['cleanup_complete'])
        self.assertLess(self.load()['duration_seconds'],2); self.check_integrity(self.load())

    def test_sampled_rss_guard(self):
        from owned_process import launch
        def high_rss(*args):
            child=launch(*args); child.rss=lambda:3*GIB+1; return child
        run=self.make('import time; time.sleep(5)',launcher=high_rss)
        with self.assertRaises(AdapterError):
            with run: list(run.jsonl())
        self.assertEqual(self.load()['resource_stop_reason'],'own_child_rss_ceiling'); self.check_integrity(self.load())

    def test_running_disk_guard(self):
        run=self.make('import time; time.sleep(5)',resources=SyntheticResources(fail_after=1))
        with self.assertRaises(AdapterError):
            with run: list(run.jsonl())
        self.assertEqual(self.load()['resource_stop_reason'],'own_child_disk_reserve_guard'); self.check_integrity(self.load())

    def test_missing_resource_fails_closed(self):
        resource=SyntheticResources()
        def missing(): raise OSError('resource API unavailable')
        resource.available=missing
        run=self.make('pass',resources=resource)
        with self.assertRaises(OSError):
            with run: pass
        self.assertFalse(self.load()['completed']); self.check_integrity(self.load())

    def test_partial_row(self):
        run=self.make("import os; os.write(1,b'{\"a\":1}')")
        with self.assertRaises(AdapterError):
            with run: list(run.jsonl())
        self.assertEqual(self.load()['resource_stop_reason'],'stdout_partial_row'); self.check_integrity(self.load())

    def test_row_limit(self):
        run=self.make("import os; os.write(1,b'x'*300+b'\\n')",small_limits(max_row_bytes=64))
        with self.assertRaises(AdapterError):
            with run: list(run.jsonl())
        self.assertEqual(self.load()['resource_stop_reason'],'stdout_row_limit'); self.check_integrity(self.load())

    def test_no_newline_row_limit(self):
        run=self.make("import os; os.write(1,b'x'*300)",small_limits(max_row_bytes=64))
        with self.assertRaises(AdapterError):
            with run: list(run.jsonl())
        self.assertEqual(self.load()['resource_stop_reason'],'stdout_row_limit')

    def test_stdout_total_limit(self):
        run=self.make("import os; os.write(1,b'x'*300)",small_limits(stdout_mode='bytes',max_stdout_bytes=64))
        with self.assertRaises(AdapterError):
            with run: run.wait()
        receipt=self.load(); self.assertEqual(receipt['resource_stop_reason'],'stdout_bytes_limit')
        self.assertEqual(receipt['streams']['stdout']['bytes'],64)
        self.assertEqual(receipt['streams']['stdout']['observed_bytes'],300)
        self.assertEqual(receipt['streams']['stdout']['observed_sha256'],hashlib.sha256(b'x'*300).hexdigest())
        self.check_integrity(receipt)

    def test_stderr_limit(self):
        run=self.make("import os; os.write(2,b'e'*300)",small_limits(max_stderr_bytes=64))
        with self.assertRaises(AdapterError):
            with run: list(run.jsonl())
        self.assertEqual(self.load()['resource_stop_reason'],'stderr_bytes_limit')
        self.assertEqual(self.load()['streams']['stderr']['bytes'],64); self.check_integrity(self.load())

    def test_no_consumer_bounded_backpressure(self):
        run=self.make("import os,time; os.write(1,b'{}\\n'*100); time.sleep(5)",small_limits(queue_wait_seconds=.1))
        with self.assertRaises(AdapterError):
            with run:
                self.assertTrue(run.done.wait(2))
        receipt=self.load(); self.assertEqual(receipt['resource_stop_reason'],'stdout_queue_backpressure')
        self.assertLessEqual(receipt['queue_peak_rows'],2); self.assertLessEqual(receipt['queue_peak_bytes'],2048)
        self.check_integrity(receipt)

    def test_malformed_nonfinite_duplicate_and_bad_utf8(self):
        for index,data in enumerate([b'nope\n', b'{"a":NaN}\n', b'{"a":Infinity}\n',
                                     b'{"a":1e999}\n', b'{"a":1,"a":2}\n',b'[]\n',b'{"a":"\xff"}\n']):
            with self.subTest(data=data):
                run=self.make('import os; os.write(1,'+repr(data)+')')
                run.output_root=self.root/('bad-'+str(index))
                with self.assertRaises(AdapterError):
                    with run: list(run.jsonl())
                self.assertEqual(run.receipt['resource_stop_reason'],'malformed_jsonl')
                self.assertFalse(run.receipt['completed'])

    def test_consumer_exception_stops_child(self):
        run=self.make("import os,time; os.write(1,b'{}\\n'); time.sleep(5)")
        with self.assertRaisesRegex(ValueError,'consumer failed'):
            with run:
                for _ in run.jsonl(): raise ValueError('consumer failed')
        self.assertFalse(self.load()['completed']); self.assertTrue(self.load()['cleanup_complete'])
        self.assertIn(self.load()['resource_stop_reason'],('consumer_incomplete','consumer_failure'))
        self.check_integrity(self.load())

    def test_early_break_is_not_completion(self):
        run=self.make("import os,time; os.write(1,b'{}\\n'); time.sleep(5)")
        with self.assertRaises(AdapterError):
            with run:
                for _ in run.jsonl(): break
        self.assertFalse(self.load()['completed']); self.check_integrity(self.load())

    def test_nonzero_exit(self):
        run=self.make('raise SystemExit(7)')
        with self.assertRaises(AdapterError):
            with run: list(run.jsonl())
        self.assertEqual(self.load()['exit_code'],7)
        self.assertEqual(self.load()['resource_stop_reason'],'child_exit_failure'); self.check_integrity(self.load())

    @unittest.skipUnless(sys.platform.startswith('linux'),'POSIX signal exit test')
    def test_signal_exit(self):
        run=self.make('import os,signal; os.kill(os.getpid(),signal.SIGTERM)')
        with self.assertRaises(AdapterError):
            with run: list(run.jsonl())
        self.assertEqual(self.load()['exit_code'],-signal.SIGTERM); self.assertEqual(self.load()['signal'],signal.SIGTERM)
        self.check_integrity(self.load())

    def test_foreign_output_preserved(self):
        (self.root/'attempt').mkdir(); marker=self.root/'attempt'/'foreign'; marker.write_bytes(b'untouched')
        with self.assertRaises(FileExistsError):
            with self.make('pass'): pass
        self.assertEqual(marker.read_bytes(),b'untouched'); self.assertFalse((self.root/'owner.lock').exists())

    def test_foreign_lock_preserved(self):
        lock=self.root/'owner.lock'; lock.write_bytes(b'foreign owner')
        with self.assertRaises(FileExistsError):
            with self.make('pass'): pass
        self.assertEqual(lock.read_bytes(),b'foreign owner'); self.assertFalse((self.root/'attempt').exists())

    def test_replaced_lock_preserved(self):
        run=self.make('pass',small_limits(stdout_mode='bytes'))
        with self.assertRaisesRegex(AdapterError,'foreign replacement'):
            with run:
                run.wait(); (self.root/'owner.lock').unlink(); (self.root/'owner.lock').write_bytes(b'new owner')
        self.assertEqual((self.root/'owner.lock').read_bytes(),b'new owner')
        self.assertFalse(self.load()['completed']); self.assertEqual(self.load()['resource_stop_reason'],'owner_lock_changed')
        self.assertFalse(SERIAL.locked())

    def test_repeated_attempt_never_overwrites(self):
        run=self.make('pass')
        with run: list(run.jsonl())
        original=(self.root/'attempt'/'terminal.json').read_bytes()
        with self.assertRaises(FileExistsError):
            with self.make('pass'): pass
        self.assertEqual((self.root/'attempt'/'terminal.json').read_bytes(),original)

    def test_global_serial_guard(self):
        first=self.make('import time; time.sleep(.2)',small_limits(stdout_mode='bytes'))
        with first:
            second=self.make('pass'); second.output_root=self.root/'other'
            with self.assertRaisesRegex(AdapterError,'another adapter'):
                with second: pass
            first.wait()
        self.check_integrity(first.receipt)

    def test_host_binding_rejects_mismatch(self):
        run=self.make('pass'); run.binding=replace(run.binding, expected_host={'system':'unverified'})
        with self.assertRaisesRegex(AdapterError,'host binding'):
            with run: pass
        self.assertFalse((self.root/'attempt').exists())

    def test_limit_relaxation_and_unbounded_input_rejected(self):
        for limits in (replace(small_limits(),rss_bytes=3*GIB+1),replace(small_limits(),deadline_seconds=1801),
                       replace(small_limits(),disk_floor_bytes=GIB-1),replace(small_limits(),sample_seconds=.3),
                       replace(small_limits(),max_row_bytes=17*1024**2),replace(small_limits(),deadline_seconds=float('nan'))):
            with self.subTest(limits=limits),self.assertRaises(AdapterError): limits.validate()

    def test_unsupported_os_fails_closed(self):
        with mock.patch('platform.system',return_value='Darwin'):
            with self.assertRaisesRegex(AdapterError,'unsupported'): Resources()

    def test_row_count_limit(self):
        run=self.make("print('{}'); print('{}')",small_limits(max_rows=1))
        with self.assertRaises(AdapterError):
            with run: list(run.jsonl())
        self.assertEqual(self.load()['resource_stop_reason'],'stdout_row_count_limit')

    def test_receipt_tampering_is_detectable(self):
        run=self.make('pass')
        with run: list(run.jsonl())
        path=self.root/'attempt'/'stdout.bin'; path.write_bytes(b'tampered')
        receipt=self.load()
        self.assertNotEqual(hashlib.sha256(path.read_bytes()).hexdigest(), receipt['streams']['stdout']['sha256'])

    def test_verify_attempt_accepts_intact_and_rejects_tampering(self):
        from owned_process import verify_attempt
        run=self.make('print("{}")')
        with run: list(run.jsonl())
        self.assertTrue(verify_attempt(self.root/'attempt',require_completed=True)['completed'])
        (self.root/'attempt'/'stdout.bin').write_bytes(b'{ }\n')
        with self.assertRaises(AdapterError): verify_attempt(self.root/'attempt',require_completed=True)

    def test_live_resource_api_failure(self):
        resources=SyntheticResources(); calls=[0]
        def available():
            calls[0]+=1
            if calls[0]>1: raise OSError('synthetic resource API failure')
            return 8*GIB
        resources.available=available
        run=self.make('import time; time.sleep(5)',resources=resources)
        with self.assertRaises(AdapterError):
            with run: list(run.jsonl())
        self.assertEqual(self.load()['resource_stop_reason'],'resource_observation_failure')
        self.check_integrity(self.load())

    def test_executable_identity_change_fails(self):
        from owned_process import file_identity
        calls=[0]
        def identity(path):
            value=file_identity(path); calls[0]+=1
            if calls[0]==3: value['sha256']='c'*64
            return value
        run=self.make('pass')
        with mock.patch('owned_process.file_identity',side_effect=identity),self.assertRaises(AdapterError):
            with run: list(run.jsonl())
        self.assertEqual(self.load()['resource_stop_reason'],'executable_changed')
        self.check_integrity(self.load())

    def test_slow_consumer_within_bounded_queue(self):
        run=self.make("import time; [print('{}',flush=True) or time.sleep(.03) for i in range(6)]")
        with run:
            for row in run.jsonl(): time.sleep(.04)
        self.assertEqual(run.receipt['rows'],6); self.assertGreater(run.receipt['sample_count'],1)
        self.check_integrity(run.receipt)

    def test_context_digest_is_required(self):
        run=self.make('pass'); run.binding=replace(run.binding,context_sha256='')
        with self.assertRaises(AdapterError):
            with run: pass
        self.assertFalse((self.root/'attempt').exists())

    def test_json_depth_limit(self):
        with self.assertRaises(ValueError): validate_json(json.loads('['*65+'0'+']'*65))

    @unittest.skipUnless(sys.platform.startswith('linux'),'Linux process-group cleanup test')
    def test_own_descendant_cleanup_foreign_process_survives(self):
        import subprocess
        foreign=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)'])
        try:
            code="import subprocess,sys,json,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)']); print(json.dumps({'pid':p.pid}),flush=True); time.sleep(20)"
            run=self.make(code,small_limits(deadline_seconds=.2)); descendants=[]
            with self.assertRaises(AdapterError):
                with run:
                    for row in run.jsonl(): descendants.append(row['pid'])
            self.assertEqual(len(descendants),1); self.assertIsNone(foreign.poll())
            path=Path('/proc')/str(descendants[0])/'status'
            if path.exists(): self.assertIn('State:\tZ',path.read_text())
        finally:
            foreign.terminate(); foreign.wait(timeout=3)


class QueueTests(unittest.TestCase):
    def test_byte_bound_and_put_timeout(self):
        queue=ByteQueue(8,100); stop=threading.Event()
        self.assertTrue(queue.put(b'12345678',stop,.1))
        self.assertFalse(queue.put(b'x',stop,.03)); self.assertEqual(queue.peak_bytes,8)
        self.assertEqual(queue.get(threading.Event(),stop),b'12345678')
        self.assertTrue(queue.put(b'x',stop,.1))

    def test_record_size_rejected_before_creation(self):
        from owned_process import durable
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'too-large.json'
            with self.assertRaises(AdapterError): durable(path,{'x':'a'*100},16)
            self.assertFalse(path.exists())


if __name__=='__main__': unittest.main(verbosity=2)
