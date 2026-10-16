"""Mandatory future Windows smoke; skipped on non-Windows, never a proof pass.

Only short original Python children are launched. No Blender, game, source rig,
FBX, VRA, private assets, graphics, downloads, installation or native builds.
Set OWNED_ADAPTER_EVIDENCE_ROOT to retain the synthetic process receipts.
"""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from owned_process import AdapterError, HostBinding, OwnedProcess, observed_host
from test_owned_process import environment, small_limits


@unittest.skipUnless(os.name=='nt', 'actual Windows execution required; not validated on Linux')
class NativeWindowsSmoke(unittest.TestCase):
    def setUp(self):
        target=os.environ.get('OWNED_ADAPTER_EVIDENCE_ROOT')
        self.temporary=None
        if target:
            base=Path(target).absolute(); base.mkdir(parents=True,exist_ok=True)
            self.root=base/self._testMethodName; self.root.mkdir(exist_ok=False)
        else:
            self.temporary=tempfile.TemporaryDirectory(prefix='owned-windows-smoke-')
            self.root=Path(self.temporary.name)
        here=Path(__file__).resolve().parent
        source=hashlib.sha256()
        for name in ('owned_process.py','windows_job.py'):
            source.update(name.encode()); source.update((here/name).read_bytes())
        self.binding=HostBinding('windows-python-smoke',self._testMethodName,source.hexdigest(),
                                 observed_host(),environment(),str(self.root/'owner.lock'),hashlib.sha256(b'synthetic-windows-transport-only').hexdigest())

    def tearDown(self):
        if self.temporary: self.temporary.cleanup()

    def run_child(self, code, *extra, **changes):
        return OwnedProcess.run([sys.executable,'-c',code,*extra],self.root,
            small_limits(deadline_seconds=10,**changes),self.root/'attempt',self.binding)

    def verify_receipt(self, run, completed):
        root=self.root/'attempt'; receipt=json.loads((root/'terminal.json').read_text())
        self.assertEqual(receipt['completed'],completed)
        self.assertEqual(receipt['host_binding']['observed_host']['system'],'Windows')
        self.assertEqual(receipt['executable_before'],receipt['executable_after'])
        self.assertTrue(receipt['windows_job_empty_verified']); self.assertTrue(receipt['cleanup_complete'])
        self.assertIsNone(receipt['signal'])
        for record in receipt['streams'].values():
            data=(root/record['path']).read_bytes()
            self.assertEqual(record['bytes'],len(data)); self.assertEqual(record['sha256'],hashlib.sha256(data).hexdigest())
        seal=json.loads((root/'terminal.sha256.json').read_text())
        self.assertEqual(seal['sha256'],hashlib.sha256((root/'terminal.json').read_bytes()).hexdigest())
        self.assertFalse((self.root/'owner.lock').exists())
        return receipt

    def test_windows_normal_bytes_and_argument_roundtrip(self):
        arguments=['space separated', 'embedded"quote', 'tail\\', 'snowman-\u2603']
        run=self.run_child("import sys,json; print(json.dumps({'argv':sys.argv[1:]})); sys.stderr.write('diagnostic\\n')",*arguments)
        with run: self.assertEqual(list(run.jsonl()),[{'argv':arguments}])
        receipt=self.verify_receipt(run,True)
        self.assertEqual(receipt['exit_code'],0); self.assertEqual(receipt['rows'],1)

    def test_windows_failure_receipt(self):
        run=self.run_child("import os; os.write(1,b'{}\\n'); raise SystemExit(7)")
        with self.assertRaises(AdapterError):
            with run: list(run.jsonl())
        receipt=self.verify_receipt(run,False); self.assertEqual(receipt['exit_code'],7)
        self.assertEqual(receipt['resource_stop_reason'],'child_exit_failure')

    def test_windows_owned_job_descendants_only(self):
        from windows_job import WinAPI, HANDLE, U32, BOOL
        api=WinAPI(); api.k.OpenProcess.restype=HANDLE; api.k.OpenProcess.argtypes=[U32,BOOL,U32]
        foreign=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)'])
        descendant_handle=None
        try:
            code="import subprocess,sys,json,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)']); print(json.dumps({'descendant_pid':p.pid}),flush=True); time.sleep(20)"
            run=OwnedProcess.run([sys.executable,'-c',code],self.root,
                small_limits(deadline_seconds=1.5),self.root/'attempt',self.binding)
            with self.assertRaises(AdapterError):
                with run:
                    for row in run.jsonl():
                        descendant_handle=api.k.OpenProcess(0x100000,False,row['descendant_pid'])
                        self.assertTrue(descendant_handle)
            self.assertIsNotNone(descendant_handle)
            self.assertEqual(api.k.WaitForSingleObject(descendant_handle,5000),0)
            self.assertIsNone(foreign.poll(), 'foreign Python process must survive owned-job cleanup')
            receipt=self.verify_receipt(run,False); self.assertTrue(receipt['timed_out'])
        finally:
            if descendant_handle: api.close(descendant_handle)
            foreign.terminate(); foreign.wait(timeout=5)

    def test_windows_oversize_row_and_bounded_queue(self):
        run=self.run_child("import os; os.write(1,b'x'*256+b'\\n')",max_row_bytes=64)
        with self.assertRaises(AdapterError):
            with run: list(run.jsonl())
        receipt=self.verify_receipt(run,False)
        self.assertEqual(receipt['resource_stop_reason'],'stdout_row_limit')
        self.assertLessEqual(receipt['queue_peak_bytes'],receipt['limits']['queue_bytes'])
        self.assertLessEqual(receipt['queue_peak_rows'],receipt['limits']['queue_rows'])


if __name__=='__main__': unittest.main(verbosity=2)
